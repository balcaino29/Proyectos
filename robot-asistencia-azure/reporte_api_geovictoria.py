import requests
import json
import os
import time
from datetime import datetime, timedelta

# --- 1. CONFIGURACIÓN ---
API_KEY = os.environ.get("GEO_API_KEY", "827341")
API_SECRET = os.environ.get("GEO_API_SECRET", "21cab782")
BASE_URL = "https://customerapi.geovictoria.com"

try:
    CARPETA_TRABAJO = os.path.dirname(os.path.abspath(__file__))
except NameError:
    CARPETA_TRABAJO = os.getcwd()

ARCHIVO_SALIDA = os.path.join(CARPETA_TRABAJO, "asistencia_cruda.json")
TAMANO_LOTE = 50 

def logger(fase, mensaje):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{fase}] {mensaje}")

def obtener_token():
    url = f"{BASE_URL}/api/v1/Login"
    payload = {"User": API_KEY, "Password": API_SECRET}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            return resp.json().get('token')
        logger("ERROR", f"Falla en login: {resp.status_code}")
        return None
    except Exception as e:
        logger("ERROR", f"Excepción en conexión: {e}")
        return None

def obtener_solo_ids_activos(token):
    logger("FILTRO", "👥 Consultando lista de colaboradores...")
    url = f"{BASE_URL}/api/v1/User/List"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json={}, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            # Filtro: Solo Enabled == 1
            activos = [str(u['Identifier']) for u in data if str(u.get('Enabled')) == "1" and u.get('Identifier')]
            logger("FILTRO", f"✅ {len(activos)} colaboradores activos encontrados.")
            return activos
        return []
    except Exception as e:
        logger("ERROR", f"Error en usuarios: {e}")
        return []

def ejecutar_descarga(archivo_salida: str = None):
    ruta_salida = archivo_salida or ARCHIVO_SALIDA
    token = obtener_token()
    if not token: return
    lista_ids = obtener_solo_ids_activos(token)
    if not lista_ids: return

    # --- FECHAS: AYER ---
    hoy = datetime.now()
    if hoy.weekday() == 0: 
        inicio = (hoy - timedelta(days=3)).strftime("%Y%m%d000000")
        fin = (hoy - timedelta(days=3)).strftime("%Y%m%d235959")
    else: 
        inicio = (hoy - timedelta(days=1)).strftime("%Y%m%d000000")
        fin = (hoy - timedelta(days=1)).strftime("%Y%m%d235959")

    url_asistencia = f"{BASE_URL}/api/v1/AttendanceBook"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    datos_completos = []

    for i in range(0, len(lista_ids), TAMANO_LOTE):
        lote = lista_ids[i : i + TAMANO_LOTE]
        payload = {"StartDate": inicio, "EndDate": fin, "UserIds": ",".join(lote)}
        try:
            resp = requests.post(url_asistencia, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                usuarios = resp.json()
                if isinstance(usuarios, dict): usuarios = usuarios.get("Users", [])
                datos_completos.extend(usuarios)
        except Exception as e:
            logger("ERROR", f"Error lote {i}: {e}")
        time.sleep(0.5)

    with open(ruta_salida, 'w', encoding='utf-8') as f:
        json.dump(datos_completos, f, ensure_ascii=False, indent=4)
    logger("EXITO", f"Archivo guardado: {ruta_salida}")

if __name__ == "__main__":
    ejecutar_descarga()