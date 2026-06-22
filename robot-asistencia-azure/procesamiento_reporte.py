import json
import pandas as pd
import os
import logging
from datetime import datetime, time

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURACIÓN ESTRATÉGICA ---
try:
    CARPETA_TRABAJO = os.path.dirname(os.path.abspath(__file__))
except NameError:
    CARPETA_TRABAJO = os.getcwd()

ARCHIVO_ENTRADA = os.path.join(CARPETA_TRABAJO, "asistencia_cruda.json")
HORA_ENTRADA_LIMITE = time(8, 6)

def procesar_datos(archivo_entrada: str = None, carpeta_salida: str = None):
    archivo_entrada = archivo_entrada or ARCHIVO_ENTRADA
    carpeta_salida = carpeta_salida or CARPETA_TRABAJO
    logging.info(">>> INICIANDO FASE 2: CLASIFICACIÓN Y AUDITORÍA")
    
    if not os.path.exists(archivo_entrada):
        logging.error(f"Archivo no encontrado: {archivo_entrada}")
        return

    try:
        with open(archivo_entrada, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"Error al leer JSON: {e}")
        return

    filas = []
    for user in data:
        if not isinstance(user, dict): continue

        rut = user.get('Identifier', 'S/D')
        nombre = f"{user.get('Name', '')} {user.get('LastName', '')}".strip()
        grupo = user.get('GroupDescription', 'Sin Grupo')

        for intervalo in user.get('PlannedInterval', []):
            fecha_raw = intervalo.get('Date', '')
            try:
                fecha_formateada = datetime.strptime(fecha_raw, "%Y%m%d%H%M%S").strftime("%d/%m/%Y")
            except: fecha_formateada = fecha_raw

            # Análisis de Permisos
            permisos = intervalo.get('TimeOffs', [])
            glosa_permiso = " / ".join([str(p.get('TimeOffTypeDescription', '')) for p in permisos]) if permisos else "Ninguno"
            
            # Análisis de Marcaciones (REGLA DE NEGOCIO OPTIMIZADA)
            marcas = intervalo.get('Punches', [])
            m_ingreso = next((m for m in marcas if m.get('Type') == "Ingreso"), None)
            m_salida = next((m for m in marcas if m.get('Type') == "Salida"), None)

            entrada_real = "SIN MARCA"
            salida_real = "SIN MARCA"
            obj_hora_entrada = None

            if m_ingreso:
                dt_i = datetime.strptime(m_ingreso.get('Date'), "%Y%m%d%H%M%S")
                entrada_real = dt_i.strftime("%H:%M")
                obj_hora_entrada = dt_i.time()
            if m_salida:
                salida_real = datetime.strptime(m_salida.get('Date'), "%Y%m%d%H%M%S").strftime("%H:%M")

            # Lógica de Estado
            turnos = intervalo.get('Shifts', [])
            tiene_turno = len(turnos) > 0
            detalle_marca = ""

            if glosa_permiso != "Ninguno":
                estado = "🟡 JUSTIFICADO"
            elif not tiene_turno:
                estado = "⚪ LIBRE"
            else:
                # Caso: No hay ninguna marca
                if not m_ingreso and not m_salida:
                    estado = "🔴 AUSENTE"
                    detalle_marca = "Inasistencia Total"
                # Caso: Falta una de las dos (Incumplimiento)
                elif not m_ingreso:
                    estado = "🟠 INCUMP. ENTRADA"
                    detalle_marca = "Marcó salida pero NO entrada"
                elif not m_salida:
                    estado = "🟠 INCUMP. SALIDA"
                    detalle_marca = "Marcó entrada pero NO salida"
                # Caso: Ambas marcas existen
                elif obj_hora_entrada and obj_hora_entrada > HORA_ENTRADA_LIMITE:
                    estado = "🟡 ATRASADO"
                else:
                    estado = "🟢 A TIEMPO"

            filas.append({
                "Grupo": grupo, "RUT": rut, "Nombre": nombre,
                "Fecha": fecha_formateada, 
                "Plan Entrada": turnos[0].get('StartTime', '-') if turnos else "-",
                "Real Entrada": entrada_real, "Real Salida": salida_real,
                "ESTADO FINAL": estado, "Detalle": detalle_marca, "Permiso": glosa_permiso
            })

    if filas:
        df = pd.DataFrame(filas)
        ruta_salida = os.path.join(carpeta_salida, f"Reporte_Final_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
        df.to_excel(ruta_salida, index=False)
        logging.info(f"Reporte generado en: {ruta_salida}")
        return ruta_salida

if __name__ == "__main__":
    procesar_datos()