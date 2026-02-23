import requests
import pandas as pd
import time
import re
import logging
import smtplib
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuración GeoVictoria - Captura desde Variables de Entorno (Secrets)
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://customerapi.geovictoria.com"

# Rutas Relativas para GitHub
PATH_BASE_PERSONAL = "BASE_PERSONAL_SEH.xlsx"
RUTA_SALIDA = "REPORTE_RECONSTRUIDO_OFICIAL_V2.xlsx"
TAMANO_LOTE = 20

# Configuración Email
REMITENTE = "notificacionesseh@gmail.com"
CLAVE_APP = os.getenv("CLAVE_APP")
DESTINATARIOS = ["mcampos@seguraehijos.cl"]
CC = ["lparra@seguraehijos.cl", "balcaino@seguraehijos.cl"]

def obtener_token():
    [cite_start]"""Obtiene el token de autenticación mediante el método Login [cite: 157, 162]"""
    url = f"{BASE_URL}/api/v1/Login"
    try:
        resp = requests.post(url, json={"User": API_KEY, "Password": API_SECRET}, timeout=20)
        return resp.json().get('token') if resp.status_code == 200 else None
    except Exception as e:
        logging.error(f"Error en obtención de token: {e}")
        return None

def clean_rut(rut_str):
    if pd.isna(rut_str): return ""
    return re.sub(r'[^0-9kK]', '', str(rut_str)).upper()

def extract_hour_decimal(iso_date_str):
    [cite_start]"""Convierte formato de fecha de la API (YYYYMMDDHHMMSS) a decimal [cite: 182, 195]"""
    if not iso_date_str or pd.isna(iso_date_str) or str(iso_date_str).strip() == "":
        return None
    try:
        s_str = str(iso_date_str)
        h = int(s_str[8:10])
        m = int(s_str[10:12])
        return h + (m / 60)
    except: return None

def main():
    logging.info("🚀 INICIANDO AUDITORÍA INTEGRAL EN GITHUB ACTIONS (SOLO ACTIVOS)")
    
    # Validación de credenciales antes de iniciar
    if not all([API_KEY, API_SECRET, CLAVE_APP]):
        logging.error("❌ Faltan secretos de GitHub (API_KEY, API_SECRET o CLAVE_APP).")
        return

    token = obtener_token()
    if not token:
        logging.error("No se pudo obtener el token de acceso.")
        return

    # 1. Carga de Base Personal (Debe estar en la raíz del repositorio)
    try:
        df_base = pd.read_excel(PATH_BASE_PERSONAL, sheet_name='Base')
        df_base['RUT'] = df_base.iloc[:, 1].apply(clean_rut)
        df_vals = df_base[['RUT', df_base.columns[5], df_base.columns[6],
                           df_base.columns[7], df_base.columns[8], df_base.columns[9]]].copy()
        df_vals.columns = ['RUT', 'Cargo', 'Gerencia', 'Unidad_Negocio', 'V_50', 'V_100']
    except Exception as e:
        logging.error(f"Error cargando Excel de base: {e}")
        return

    # 2. Obtener IDs y Filtrar por Estado Activo (Enabled == 1) 
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp_u = requests.post(f"{BASE_URL}/api/v1/User/List", json={}, headers=headers)
        u_data = resp_u.json()
        activos = [u for u in u_data if str(u.get('Enabled')) == "1"]
        lista_ids = [str(u.get('Identifier')) for u in activos if u.get('Identifier')]
        u_map = {str(u['Identifier']): f"{u.get('Name','')} {u.get('LastName','')}" for u in activos}
        logging.info(f"👥 Usuarios totales: {len(u_data)} | Activos a procesar: {len(lista_ids)}")
    except Exception as e:
        logging.error(f"Error obteniendo lista de usuarios: {e}")
        return

    # [cite_start]3. Descarga de Libro de Asistencia (AttendanceBook) [cite: 175, 179, 182]
    hoy = datetime.now()
    inicio = hoy.replace(day=1).strftime("%Y%m%d000000")
    fin = hoy.strftime("%Y%m%d235959")
    total_data = []

    for i in range(0, len(lista_ids), TAMANO_LOTE):
        lote = lista_ids[i : i + TAMANO_LOTE]
        payload = {"StartDate": inicio, "EndDate": fin, "UserIds": ",".join(lote)}
        try:
            resp = requests.post(f"{BASE_URL}/api/v1/AttendanceBook", json=payload, headers=headers)
            if resp.status_code == 200:
                users = resp.json().get('Users', [])
                for u in users:
                    rut = str(u.get('Identifier'))
                    for d in u.get('PlannedInterval', []):
                        punches = d.get('Punches', [])
                        if not punches: continue

                        ent_list = [p.get('Date') for p in punches if p.get('Type') in ["Ingreso", "Entrada"]]
                        sal_list = [p.get('Date') for p in punches if p.get('Type') in ["Salida", "Egreso"]]
                        
                        p_ent = min(ent_list) if ent_list else None
                        u_sal = max(sal_list) if sal_list else None
                        
                        dt = datetime.strptime(d['Date'][:8], "%Y%m%d")
                        es_festivo = str(d.get('Holiday')).lower() in ['true', '1']
                        dia_sem = dt.weekday()
                        
                        if es_festivo or dia_sem == 6:
                            tipo_dia, label = "Festivo", "V_100 (100% recargo)"
                        else:
                            tipo_dia, label = "Habil", "V_50 (50% recargo)"

                        dia_nom = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dia_sem]
                        total_data.append({
                            'RUT': rut, 'Fecha': dt.strftime("%Y-%m-%d"), 'Dia': dia_nom,
                            'Entrada_Raw': p_ent, 'Salida_Raw': u_sal, 
                            'Tipo_Dia': tipo_dia, 'Factor de pago aplicado': label
                        })
        except Exception: pass
        time.sleep(0.3)

    if not total_data:
        logging.warning("⚠️ No se recuperaron datos de asistencia.")
        return

    # 4. Cálculo de HE y Atrasos (Lógica Original) 
    df = pd.DataFrame(total_data).merge(df_vals, on='RUT', how='inner')
    df['Nombre'] = df['RUT'].map(u_map)

    def calcular_auditoria(row):
        he, atraso = 0.0, 0.0
        e_dec = extract_hour_decimal(row['Entrada_Raw'])
        s_dec = extract_hour_decimal(row['Salida_Raw'])
        
        if row['Tipo_Dia'] == "Habil" and row['Dia'] not in ["Sábado"]:
            p_ent = 8.0
            p_sal = 14.0 if row['Dia'] == "Viernes" else 18.0
            if e_dec and e_dec > p_ent: atraso = round(e_dec - p_ent, 2)
            if s_dec and s_dec > p_sal: he = round(s_dec - p_sal, 2)
        else:
            if e_dec and s_dec:
                he = round(s_dec - e_dec, 2)
            atraso = 0.0
        return pd.Series([he, atraso])

    df[['HE_Manual', 'AT_Manual']] = df.apply(calcular_auditoria, axis=1)

    # 5. Valorización y Costos
    df['COSTO_HE'] = df.apply(lambda r: r['HE_Manual'] * (r['V_100'] if "V_100" in str(r['Factor de pago aplicado']) else r['V_50']), axis=1)
    df['COSTO_ATRASO'] = df['AT_Manual'] * (df['V_50'] / 1.5)

    # 6. Guardado Final y Resumen Gerencial
    cols_finales = [
        'RUT', 'Nombre', 'Fecha', 'Dia', 'Tipo_Dia', 'Factor de pago aplicado',
        'Entrada_Raw', 'Salida_Raw', 'HE_Manual', 'AT_Manual',
        'Cargo', 'Gerencia', 'Unidad_Negocio', 'COSTO_HE', 'COSTO_ATRASO'
    ]
    
    try:
        with pd.ExcelWriter(RUTA_SALIDA, engine='xlsxwriter') as writer:
            df[cols_finales].fillna(0).to_excel(writer, sheet_name='Detalle_Auditado', index=False)
            resumen_gerencial = df.groupby(['Gerencia', 'Unidad_Negocio']).agg({'HE_Manual': 'sum', 'COSTO_HE': 'sum'}).reset_index()
            resumen_gerencial.to_excel(writer, sheet_name='Resumen_Gerencial', index=False)
        logging.info(f"✅ Excel generado exitosamente: {RUTA_SALIDA}")
        
        # 7. Notificación Automática
        enviar_email(resumen_gerencial)
    except Exception as e:
        logging.error(f"Error al guardar el archivo Excel: {e}")

def enviar_email(resumen):
    logging.info("📧 Enviando notificación ejecutiva desde la nube...")
    total_m = resumen['COSTO_HE'].sum()
    
    html = f"""
    <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #2E86C1;">Control de Horas Extras - Solo Personal Activo</h2>
        <p>Resumen de costos acumulados al {datetime.now().strftime('%d/%m/%Y')}:</p>
        <table border="1" style="border-collapse: collapse; width: 90%;">
            <tr style="background-color: #2E86C1; color: white;">
                <th>Gerencia</th><th>Unidad Negocio</th><th>Horas Totales</th><th>Costo Estimado</th>
            </tr>
    """
    for _, r in resumen.iterrows():
        html += f"<tr><td>{r['Gerencia']}</td><td>{r['Unidad_Negocio']}</td><td>{r['HE_Manual']:.2f} HH</td><td>${r['COSTO_HE']:,.0f}</td></tr>"
    
    html += f"""
            <tr style="background-color: #F4F6F7; font-weight: bold;">
                <td colspan="2">TOTAL GENERAL</td><td>{resumen['HE_Manual'].sum():.2f} HH</td><td>${total_m:,.0f}</td>
            </tr>
        </table>
        <p>Se adjunta reporte detallado con auditoría completa.</p>
        <hr><p style="font-size: 11px; color: gray;">Generado automáticamente por GitHub Actions.</p>
    </body></html>
    """

    msg = MIMEMultipart()
    msg['Subject'] = f"📊 Alerta Costos HH Extras - {datetime.now().strftime('%B %Y')}"
    msg['From'], msg['To'], msg['Cc'] = REMITENTE, ", ".join(DESTINATARIOS), ", ".join(CC)
    msg.attach(MIMEText(html, 'html'))

    try:
        with open(RUTA_SALIDA, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(RUTA_SALIDA)}")
            msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(REMITENTE, CLAVE_APP)
            s.sendmail(REMITENTE, DESTINATARIOS + CC, msg.as_string())
        logging.info("✅ Notificación enviada exitosamente.")
    except Exception as e:
        logging.error(f"Error al enviar el correo: {e}")

if __name__ == "__main__":
    main()