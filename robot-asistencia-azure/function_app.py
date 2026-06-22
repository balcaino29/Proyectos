import azure.functions as func
import logging
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from blob_helper import descargar_blob, subir_blob, blob_existe, CONTAINER_DATOS, CONTAINER_MAESTROS

app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 11,12 * * 1-5", arg_name="myTimer", run_on_startup=False, use_monitor=True)
def robot_asistencia_seh(myTimer: func.TimerRequest) -> None:
    ahora_chile = datetime.now(ZoneInfo("America/Santiago"))
    if ahora_chile.hour != 8:
        logging.info(f"Skip: hora Chile = {ahora_chile.strftime('%H:%M')}")
        return
    if myTimer.past_due:
        logging.warning("El timer se ejecuto con retraso.")
    logging.info("=" * 60)
    logging.info(f">>> INICIANDO ROBOT ASISTENCIA SEH (Azure) - Hora Chile: {ahora_chile.strftime('%Y-%m-%d %H:%M')}")
    tmp            = tempfile.gettempdir()
    path_cruda     = os.path.join(tmp, "asistencia_cruda.json")
    path_historial = os.path.join(tmp, "historial_asistencia.json")
    path_base      = os.path.join(tmp, "BASE_PERSONAL_SEH.xlsx")
    if not descargar_blob(CONTAINER_MAESTROS, "BASE_PERSONAL_SEH.xlsx", path_base):
        logging.error("No se pudo descargar BASE_PERSONAL_SEH.xlsx. Abortando.")
        return
    if blob_existe(CONTAINER_DATOS, "historial_asistencia.json"):
        descargar_blob(CONTAINER_DATOS, "historial_asistencia.json", path_historial)
    logging.info(">>> FASE 1: Descarga GeoVictoria")
    try:
        from reporte_api_geovictoria import ejecutar_descarga
        ejecutar_descarga(archivo_salida=path_cruda)
    except Exception as e:
        logging.error(f"Fase 1 fallo: {e}")
        return
    if not os.path.exists(path_cruda):
        logging.error("Fase 1 no genero asistencia_cruda.json. Abortando.")
        return
    subir_blob(CONTAINER_DATOS, "asistencia_cruda.json", path_cruda)
    logging.info(">>> FASE 2: Procesamiento Excel")
    try:
        from procesamiento_reporte import procesar_datos
        path_excel = procesar_datos(archivo_entrada=path_cruda, carpeta_salida=tmp)
        if path_excel and os.path.exists(path_excel):
            subir_blob(CONTAINER_DATOS, os.path.basename(path_excel), path_excel)
    except Exception as e:
        logging.error(f"Fase 2 fallo: {e}")
    logging.info(">>> FASE 3: Notificacion")
    try:
        from notificar_atrasos import procesar_y_notificar
        procesar_y_notificar(path_data_cruda=path_cruda, path_base_personal=path_base, path_historial=path_historial)
    except Exception as e:
        logging.error(f"Fase 3 fallo: {e}")
    if os.path.exists(path_historial):
        subir_blob(CONTAINER_DATOS, "historial_asistencia.json", path_historial)
    logging.info(">>> ROBOT ASISTENCIA SEH FINALIZADO")
