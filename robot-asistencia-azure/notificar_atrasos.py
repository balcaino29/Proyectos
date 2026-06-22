"""
notificar_atrasos.py  (v5 – exclusión de feriados legales chilenos)
====================================================================
Fase 3 del robot de asistencia SEH.

Flujo de ejecución:
  1. reverificar_permisos_mes()
       Consulta la API desde el 01 del mes hasta ayer y corrige el historial:
       si una fecha guardada como "inasistencia" ahora tiene permiso en la API,
       se mueve automáticamente a "con_permiso" → las alertas se recalculan limpias.

  2. procesar_y_notificar()
       Procesa el día anterior (asistencia_cruda.json) y envía los correos.
       Los feriados legales chilenos se detectan y se omiten completamente:
       no se registran como incidencias ni se envían correos ese día.
"""

import pandas as pd
import requests
import smtplib
import ssl
import json
import os
import time as time_module
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, time, date, timedelta

from historial_asistencia import HistorialAsistencia, es_dia_habil, _feriados_chile

# --------------------------------------------------------------------------- #
#  CONFIGURACIÓN
# --------------------------------------------------------------------------- #
SMTP_SERVER     = "smtp.gmail.com"
SMTP_PORT       = 465
EMAIL_REMITENTE = os.environ.get("EMAIL_REMITENTE", "notificacionesseh@gmail.com")
PASSWORD_GMAIL  = os.environ.get("GMAIL_PASSWORD", "jssi gzwx yxsl xjst")
GLOBAL_CC       = ["jrojas@seguraehijos.cl","mcampos@seguraehijos.cl",
                   "isegura@seguraehijos.cl","lparra@seguraehijos.cl","balcaino@seguraehijos.cl"]

CARPETA_BASE       = r"C:\Users\balcaino\Desktop"
PATH_DATA_CRUDA    = os.path.join(CARPETA_BASE, "Robot Asistencia y Atrasos", "asistencia_cruda.json")
PATH_BASE_PERSONAL = os.path.join(CARPETA_BASE, "HH", "BASE_PERSONAL_SEH.xlsx")
PATH_HISTORIAL     = os.path.join(CARPETA_BASE, "Robot Asistencia y Atrasos", "historial_asistencia.json")

API_KEY     = os.environ.get("GEO_API_KEY", "827341")
API_SECRET  = os.environ.get("GEO_API_SECRET", "21cab782")
BASE_URL    = "https://customerapi.geovictoria.com"
TAMANO_LOTE = 50

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s: %(message)s',
                    datefmt='%H:%M:%S')


# --------------------------------------------------------------------------- #
#  CARGA DE DATOS MAESTROS
# --------------------------------------------------------------------------- #
def cargar_mapeo_jefaturas(path_base: str = None) -> dict:
    try:
        df = pd.read_excel(path_base or PATH_BASE_PERSONAL, sheet_name="Base")
        col_rut = next((c for c in ['R.U.T.', 'RUT', 'Rut'] if c in df.columns), None)
        if not col_rut:
            logging.error("No se encontró columna de RUT.")
            return {}
        df['RUT_CLEAN'] = (df[col_rut].astype(str)
                           .str.replace(r"[\.\-]", "", regex=True)
                           .str.upper().str.strip().str.lstrip("0"))
        return df.set_index('RUT_CLEAN')['Jefatura'].to_dict()
    except Exception as e:
        logging.error(f"Error cargando Base Personal: {e}")
        return {}


# --------------------------------------------------------------------------- #
#  REVERIFICACIÓN MENSUAL DE PERMISOS
# --------------------------------------------------------------------------- #
def _obtener_token() -> str | None:
    try:
        resp = requests.post(f"{BASE_URL}/api/v1/Login",
                             json={"User": API_KEY, "Password": API_SECRET}, timeout=20)
        if resp.status_code == 200:
            return resp.json().get('token')
        logging.error(f"Login fallido: {resp.status_code}")
    except Exception as e:
        logging.error(f"Error de conexión API: {e}")
    return None


def _obtener_ids_activos(token: str) -> list:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(f"{BASE_URL}/api/v1/User/List", json={}, headers=headers, timeout=30)
        if resp.status_code == 200:
            return [str(u['Identifier'])
                    for u in resp.json()
                    if str(u.get('Enabled')) == "1" and u.get('Identifier')]
    except Exception as e:
        logging.error(f"Error obteniendo usuarios: {e}")
    return []


def reverificar_permisos_mes(historial: HistorialAsistencia, periodo: str):
    """
    Consulta la API desde el 01 del mes hasta ayer y corrige el historial:
    cualquier fecha registrada como inasistencia injustificada que ahora
    tenga un permiso/TimeOff en la API se mueve a 'con_permiso'.

    Solo actúa sobre fechas que YA están en el historial como inasistencias,
    así el impacto es mínimo y quirúrgico.
    """
    logging.info(">>> REVERIFICANDO PERMISOS DEL MES EN LA API...")

    token = _obtener_token()
    if not token:
        logging.warning("No se pudo obtener token — se omite la reverificación.")
        return

    lista_ids = _obtener_ids_activos(token)
    if not lista_ids:
        logging.warning("Sin usuarios activos — se omite la reverificación.")
        return

    # Rango: 01 del mes hasta ayer
    hoy        = date.today()
    inicio_mes = hoy.replace(day=1)
    ayer       = hoy - timedelta(days=1)

    # Si hoy es el primer día del mes no hay nada que reverificar
    if ayer < inicio_mes:
        logging.info("Primer día del mes, nada que reverificar.")
        return

    inicio_str = inicio_mes.strftime("%Y%m%d000000")
    fin_str    = ayer.strftime("%Y%m%d235959")
    headers    = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    correcciones = 0

    for i in range(0, len(lista_ids), TAMANO_LOTE):
        lote    = lista_ids[i: i + TAMANO_LOTE]
        payload = {"StartDate": inicio_str, "EndDate": fin_str,
                   "UserIds": ",".join(lote)}
        try:
            resp = requests.post(f"{BASE_URL}/api/v1/AttendanceBook",
                                 json=payload, headers=headers, timeout=60)
            if resp.status_code != 200:
                continue

            usuarios = resp.json()
            if isinstance(usuarios, dict):
                usuarios = usuarios.get("Users", [])

            for user in usuarios:
                rut_clean = (str(user.get('Identifier', ''))
                             .replace(".", "").replace("-", "")
                             .upper().strip().lstrip("0"))
                nombre = f"{user.get('Name', '')} {user.get('LastName', '')}".strip()

                # Solo procesar si tiene inasistencias guardadas en el historial
                inasistencias_guardadas = historial.get_inasistencias_mes(rut_clean, periodo)
                if not inasistencias_guardadas:
                    continue

                for intervalo in user.get('PlannedInterval', []):
                    raw_date = intervalo.get('Date')
                    if not raw_date:
                        continue
                    try:
                        fecha_str = datetime.strptime(raw_date, "%Y%m%d%H%M%S").strftime('%d/%m/%Y')
                    except Exception:
                        continue

                    # Solo actuar si esta fecha está guardada como inasistencia
                    if fecha_str not in inasistencias_guardadas:
                        continue

                    # Si ahora la API reporta un permiso para esa fecha → corregir
                    if intervalo.get('TimeOffs'):
                        historial.corregir_a_justificado(rut_clean, fecha_str)
                        correcciones += 1

        except Exception as e:
            logging.error(f"Error lote reverificación {i}: {e}")

        time_module.sleep(0.3)

    if correcciones > 0:
        logging.info(f">>> REVERIFICACIÓN: {correcciones} fecha(s) corregida(s) de falta → permiso.")
    else:
        logging.info(">>> REVERIFICACIÓN: Sin cambios en el historial.")


# --------------------------------------------------------------------------- #
#  GENERACIÓN DE HTML — LAYOUT EJECUTIVO
# --------------------------------------------------------------------------- #
_COLORES_TIPO = {
    "INASISTENCIA":  "#c0392b",
    "FALTA ENTRADA": "#e67e22",
    "FALTA SALIDA":  "#e67e22",
    "ATRASO":        "#d4ac0d",
}

_ICONOS_ALERTA = {
    "ALERTA_LUNES":       "📅",
    "ALERTA_MES":         "📊",
    "ALERTA_CONSECUTIVA": "⛔",
}

_TITULOS_ALERTA = {
    "ALERTA_LUNES":       "Lunes reincidente",
    "ALERTA_MES":         "Acumulado del mes",
    "ALERTA_CONSECUTIVA": "Días consecutivos",
}


def _badge(texto: str, color: str) -> str:
    return (f'<span style="background:{color};color:white;padding:3px 10px;'
            f'border-radius:12px;font-size:12px;font-weight:bold;">{texto}</span>')


def _seccion_alertas_criticas(alertas_por_persona: list) -> str:
    if not alertas_por_persona:
        return ""
    filas = ""
    for p in alertas_por_persona:
        for a in p["alertas"]:
            icono  = _ICONOS_ALERTA.get(a["codigo"], "⚠️")
            titulo = _TITULOS_ALERTA.get(a["codigo"], a["codigo"])
            fechas = " · ".join(a["fechas"])
            filas += f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #f5c6cb;
                         font-weight:600;color:#2c3e50;white-space:nowrap;">{p['nombre']}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f5c6cb;">
                {icono} <strong>{titulo}</strong></td>
              <td style="padding:10px 12px;border-bottom:1px solid #f5c6cb;
                         color:#7f8c8d;font-size:13px;">{fechas}</td>
            </tr>"""
    return f"""
    <div style="background:#fff5f5;border:2px solid #e74c3c;border-radius:8px;
                margin-bottom:24px;overflow:hidden;">
      <div style="background:#e74c3c;padding:12px 18px;">
        <span style="color:white;font-size:15px;font-weight:700;letter-spacing:0.5px;">
          🚨 ALERTAS CRÍTICAS DEL MES</span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#fdecea;">
          <th style="padding:8px 12px;text-align:left;font-size:12px;color:#c0392b;
                     text-transform:uppercase;letter-spacing:0.5px;
                     border-bottom:1px solid #f5c6cb;">Colaborador</th>
          <th style="padding:8px 12px;text-align:left;font-size:12px;color:#c0392b;
                     text-transform:uppercase;letter-spacing:0.5px;
                     border-bottom:1px solid #f5c6cb;">Tipo de alerta</th>
          <th style="padding:8px 12px;text-align:left;font-size:12px;color:#c0392b;
                     text-transform:uppercase;letter-spacing:0.5px;
                     border-bottom:1px solid #f5c6cb;">Fechas involucradas</th>
        </tr></thead>
        <tbody>{filas}</tbody>
      </table>
    </div>"""


def _card_persona(inc: dict, resumen: dict, fecha_reporte: str = "") -> str:
    color_tipo    = _COLORES_TIPO.get(inc["tipo"], "#7f8c8d")
    tiene_alertas = bool(resumen and resumen.get("alertas"))
    borde_card    = "#e74c3c" if tiene_alertas else "#dee2e6"
    n_atrasos     = len(resumen["atrasos"])       if resumen else 0
    n_inasist     = len(resumen["inasistencias"])  if resumen else 0
    alerta_badge  = (
        '<span style="background:#e74c3c;color:white;font-size:11px;'
        'padding:2px 8px;border-radius:10px;margin-left:8px;">⚠ Alerta activa</span>'
        if tiene_alertas else ""
    )
    try:
        _fdt = datetime.strptime(fecha_reporte, "%d/%m/%Y")
        label_dia = f"El viernes {_fdt.strftime('%d/%m')}" if _fdt.weekday() == 4 else "Ayer"
    except Exception:
        label_dia = "Ayer"

    return f"""
    <div style="border:1px solid {borde_card};border-radius:8px;margin-bottom:12px;overflow:hidden;
                {'box-shadow:0 0 0 2px #e74c3c22;' if tiene_alertas else ''}">
      <div style="background:#f8f9fa;padding:10px 16px;border-bottom:1px solid {borde_card};
                  display:flex;justify-content:space-between;align-items:center;">
        <span style="font-weight:700;color:#2c3e50;font-size:14px;">
          {inc['nombre']}{alerta_badge}</span>
        {_badge(inc['tipo'], color_tipo)}
      </div>
      <div style="padding:10px 16px;display:flex;gap:24px;flex-wrap:wrap;
                  background:white;align-items:center;">
        <span style="font-size:13px;color:#555;">
          {label_dia}: <strong>{inc['detalle']}</strong></span>
        <span style="color:#dee2e6;">|</span>
        <span style="font-size:13px;color:{'#e67e22' if n_atrasos else '#27ae60'};">
          🕐 {n_atrasos} atraso(s) en el mes</span>
        <span style="color:#dee2e6;">|</span>
        <span style="font-size:13px;color:{'#c0392b' if n_inasist else '#27ae60'};">
          📋 {n_inasist} inasistencia(s) en el mes</span>
      </div>
    </div>"""


def _tabla_detalle(incidencias: list) -> str:
    estilo_th = ("background:#2c3e50;color:white;padding:10px 14px;"
                 "border:1px solid #34495e;text-align:left;font-size:13px;")
    estilo_td = "padding:9px 14px;border:1px solid #ddd;font-size:13px;"
    filas = ""
    for inc in incidencias:
        color = _COLORES_TIPO.get(inc["tipo"], "#7f8c8d")
        filas += (f'<tr>'
                  f'<td style="{estilo_td}">{inc["nombre"]}</td>'
                  f'<td style="{estilo_td};color:{color};font-weight:bold;">{inc["tipo"]}</td>'
                  f'<td style="{estilo_td}">{inc["detalle"]}</td>'
                  f'</tr>')
    return f"""
    <div style="margin-top:28px;">
      <p style="color:#95a5a6;font-size:12px;text-transform:uppercase;
                letter-spacing:1px;margin-bottom:8px;">Detalle completo del día</p>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr>
          <th style="{estilo_th}">Colaborador</th>
          <th style="{estilo_th}">Incidencia</th>
          <th style="{estilo_th}">Detalle</th>
        </tr></thead>
        <tbody>{filas}</tbody>
      </table>
    </div>"""


def generar_html_profesional(area: str, incidencias: list, fecha: str,
                              resumenes_por_rut: dict) -> str:
    n_inasistencias = sum(1 for i in incidencias if i["tipo"] == "INASISTENCIA")
    n_atrasos       = sum(1 for i in incidencias if i["tipo"] == "ATRASO")
    n_faltas        = sum(1 for i in incidencias if "FALTA" in i["tipo"])

    def _kpi(valor, etiqueta, color):
        return (f'<div style="text-align:center;padding:12px 20px;">'
                f'<div style="font-size:28px;font-weight:800;color:{color};">{valor}</div>'
                f'<div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;'
                f'letter-spacing:0.5px;">{etiqueta}</div></div>')

    kpis = (
        _kpi(n_inasistencias, "Inasistencias", "#c0392b") +
        '<div style="width:1px;background:#eee;margin:8px 0;"></div>' +
        _kpi(n_atrasos, "Atrasos", "#d4ac0d") +
        '<div style="width:1px;background:#eee;margin:8px 0;"></div>' +
        _kpi(n_faltas, "Faltas de marca", "#e67e22")
    )

    alertas_consolidadas = []
    for inc in incidencias:
        rut = inc.get("rut")
        res = resumenes_por_rut.get(rut)
        if res and res.get("alertas"):
            if not any(p["nombre"] == inc["nombre"] for p in alertas_consolidadas):
                alertas_consolidadas.append({"nombre": inc["nombre"], "alertas": res["alertas"]})

    cards = ""
    procesados = set()
    for inc in incidencias:
        rut = inc.get("rut")
        if rut in procesados:
            continue
        procesados.add(rut)
        resumen = resumenes_por_rut.get(rut, {"atrasos": [], "inasistencias": [], "alertas": []})
        cards += _card_persona(inc, resumen, fecha)

    return f"""
    <html><body style="font-family:'Segoe UI',Arial,sans-serif;color:#333;
                       background:#f0f2f5;margin:0;padding:20px;">
    <div style="max-width:700px;margin:0 auto;">
      <div style="background:#2c3e50;border-radius:10px 10px 0 0;padding:20px 24px;">
        <div style="color:white;font-size:18px;font-weight:700;">
          Reporte de Asistencia — {area}</div>
        <div style="color:#95a5a6;font-size:13px;margin-top:4px;">{fecha}</div>
      </div>
      <div style="background:white;border-left:1px solid #ddd;border-right:1px solid #ddd;
                  padding:4px 0;display:flex;justify-content:space-around;">
        {kpis}
      </div>
      <div style="background:white;border:1px solid #ddd;border-top:none;
                  border-radius:0 0 10px 10px;padding:24px;">
        {_seccion_alertas_criticas(alertas_consolidadas)}
        <p style="color:#95a5a6;font-size:12px;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:12px;">Incidencias del día</p>
        {cards}
        {_tabla_detalle(incidencias)}
        <div style="margin-top:30px;padding-top:15px;border-top:1px solid #eee;
                    font-size:11px;color:#bdc3c7;text-align:center;">
          Reporte automático · Sistema de Control SEH · No responder este correo
        </div>
      </div>
    </div></body></html>"""


# --------------------------------------------------------------------------- #
#  ENVÍO DE CORREO
# --------------------------------------------------------------------------- #
def enviar_mail(jefatura_email: str, area: str, cuerpo: str, fecha_reporte: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔴 Asistencia {area} — {fecha_reporte}"
    msg["From"]    = EMAIL_REMITENTE
    msg["To"]      = jefatura_email
    msg["Cc"]      = ", ".join(GLOBAL_CC)
    msg.attach(MIMEText(cuerpo, "html"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx) as server:
            server.login(EMAIL_REMITENTE, PASSWORD_GMAIL)
            server.sendmail(EMAIL_REMITENTE, [jefatura_email] + GLOBAL_CC, msg.as_string())
        logging.info(f"ÉXITO: Reporte '{area}' → {jefatura_email}")
    except Exception as e:
        logging.error(f"FALLO al enviar a {jefatura_email}: {e}")


# --------------------------------------------------------------------------- #
#  PROCESO PRINCIPAL
# --------------------------------------------------------------------------- #
def procesar_y_notificar(path_data_cruda: str = None, path_base_personal: str = None, path_historial: str = None):
    logging.info(">>> INICIANDO FASE 3: AUDITORIA, HISTORIAL Y NOTIFICACION")
    path_data_cruda    = path_data_cruda    or PATH_DATA_CRUDA
    path_base_personal = path_base_personal or PATH_BASE_PERSONAL
    path_historial     = path_historial     or PATH_HISTORIAL

    if not os.path.exists(path_data_cruda):
        logging.error(f"No existe: {path_data_cruda}")
        return

    with open(path_data_cruda, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    # ── Fecha del reporte ────────────────────────────────────────────────── #
    fecha_str = datetime.now().strftime('%d/%m/%Y')
    for u in datos:
        for intervalo in u.get('PlannedInterval', []):
            raw = intervalo.get('Date')
            if raw:
                try:
                    fecha_str = datetime.strptime(raw, "%Y%m%d%H%M%S").strftime('%d/%m/%Y')
                    break
                except Exception:
                    pass
        else:
            continue
        break

    # ── Verificar si el día reportado es feriado ─────────────────────────── #
    fecha_dt = datetime.strptime(fecha_str, '%d/%m/%Y').date()
    feriados_año = _feriados_chile(fecha_dt.year)

    if fecha_dt in feriados_año:
        nombre_feriado = ""
        try:
            import holidays as hl
            nombre_feriado = hl.Chile(years=fecha_dt.year).get(fecha_dt, "")
        except Exception:
            pass
        logging.info(
            f">>> DÍA FERIADO DETECTADO: {fecha_str}"
            + (f" ({nombre_feriado})" if nombre_feriado else "")
            + " — No se procesarán incidencias ni se enviarán correos."
        )
        return

    periodo = datetime.strptime(fecha_str, '%d/%m/%Y').strftime('%Y-%m')

    mapeo_jefes = cargar_mapeo_jefaturas(path_base_personal)
    historial   = HistorialAsistencia(path_historial)

    # ── PASO 1: Reverificar permisos del mes antes de procesar el día ────── #
    reverificar_permisos_mes(historial, periodo)

    # ── PASO 2: Procesar el día anterior ─────────────────────────────────── #
    reporte_final: dict = {}

    for user in datos:
        rut_clean = (str(user.get('Identifier', ''))
                     .replace(".", "").replace("-", "")
                     .upper().strip().lstrip("0"))
        jefe_email  = mapeo_jefes.get(rut_clean)
        area_nombre = user.get('GroupDescription', 'Sin Área Definida')
        nombre      = f"{user.get('Name', '')} {user.get('LastName', '')}".strip()

        if not jefe_email or pd.isna(jefe_email):
            continue

        id_reporte = (jefe_email, area_nombre)
        if id_reporte not in reporte_final:
            reporte_final[id_reporte] = {
                "destinatario": jefe_email,
                "area":         area_nombre,
                "incidencias":  []
            }

        for intervalo in user.get('PlannedInterval', []):
            tiene_permiso = bool(intervalo.get('TimeOffs'))
            if tiene_permiso:
                historial.registrar_inasistencia(
                    rut_clean, fecha_str, nombre, area_nombre, con_permiso=True)
                continue

            turnos = intervalo.get('Shifts', [])
            if not turnos:
                continue

            marcas    = intervalo.get('Punches', [])
            m_ingreso = next((m for m in marcas if m.get('Type') == "Ingreso"), None)
            m_salida  = next((m for m in marcas if m.get('Type') == "Salida"),  None)

            if not m_ingreso and not m_salida:
                historial.registrar_inasistencia(
                    rut_clean, fecha_str, nombre, area_nombre, con_permiso=False)
                reporte_final[id_reporte]["incidencias"].append({
                    "rut": rut_clean, "nombre": nombre,
                    "tipo": "INASISTENCIA", "detalle": "Sin registro de entrada ni salida"
                })

            elif not m_ingreso:
                reporte_final[id_reporte]["incidencias"].append({
                    "rut": rut_clean, "nombre": nombre,
                    "tipo": "FALTA ENTRADA", "detalle": "Marcó salida pero NO entrada"
                })

            else:
                try:
                    dt_i = datetime.strptime(m_ingreso['Date'], "%Y%m%d%H%M%S")
                    if dt_i.time() > time(8, 6):
                        historial.registrar_atraso(rut_clean, fecha_str, nombre, area_nombre)
                        reporte_final[id_reporte]["incidencias"].append({
                            "rut": rut_clean, "nombre": nombre,
                            "tipo": "ATRASO", "detalle": dt_i.strftime("%H:%M")
                        })
                except Exception:
                    pass

                if not m_salida:
                    reporte_final[id_reporte]["incidencias"].append({
                        "rut": rut_clean, "nombre": nombre,
                        "tipo": "FALTA SALIDA", "detalle": "Sin registro de salida"
                    })

    # ── PASO 3: Guardar historial ya corregido y actualizado ─────────────── #
    historial.guardar()

    # ── PASO 4: Enviar correos ────────────────────────────────────────────── #
    def get_resumenes(incidencias: list) -> dict:
        ruts = {inc["rut"] for inc in incidencias if inc.get("rut")}
        return {rut: historial.resumen_persona(rut, periodo) for rut in ruts}

    orden = {"INASISTENCIA": 0, "FALTA ENTRADA": 1, "FALTA SALIDA": 1, "ATRASO": 2}
    count = 0
    for id_reporte, contenido in reporte_final.items():
        if not contenido["incidencias"]:
            continue
        contenido["incidencias"].sort(key=lambda x: orden.get(x["tipo"], 9))
        resumenes = get_resumenes(contenido["incidencias"])
        cuerpo    = generar_html_profesional(
            contenido["area"], contenido["incidencias"], fecha_str, resumenes)
        enviar_mail(contenido["destinatario"], contenido["area"], cuerpo, fecha_str)
        count += 1

    logging.info(f">>> PROCESO FINALIZADO: {count} reportes enviados.")


if __name__ == "__main__":
    procesar_y_notificar()