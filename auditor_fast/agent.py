"""
agent.py - Agente Validador de Gastos Terminales FAST
Acosta & Aguayo - ADK 2.1.0 + Vertex AI (gemini-2.5-flash)
"""

import requests
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

# -- URL base del backend en Cloud Run --
BACKEND_URL = "https://agente-fast-451607402839.us-central1.run.app"


# ---- HERRAMIENTA 1: VALIDAR ARCHIVO ----------------------------------------
def validar_archivo_fast(archivo_gcs: str) -> dict:
    """
    Ejecuta la validacion matematica completa y auditoria de integridad
    sobre un archivo Excel del terminal FAST subido a Cloud Storage.

    Usar cuando el usuario diga que subio un archivo y quiere validarlo.
    El archivo debe estar en el bucket fast-agente-bucket bajo la
    carpeta uploads/. Ejemplo: uploads/fast_mayo2026.xlsx

    Args:
        archivo_gcs: Ruta relativa del archivo en el bucket.
                     Ejemplo: 'uploads/fast_quincena1_2026.xlsx'

    Returns:
        Diccionario con estadisticas de la validacion:
        - total_awbs: total de guias procesadas
        - awbs_ok: guias sin anomalias
        - awbs_alertas: guias con alertas matematicas
        - awbs_criticos: guias con errores criticos (AUSTRALIS, omisiones)
        - hay_criticos: bool indicando si hay errores criticos
        - destrucciones: cantidad de registros de destruccion de cajas
        - archivo_resultado: path gs:// del Excel validado generado
        - contexto_gemini: JSON con detalle de anomalias para analisis
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/validar",
            json={"archivo_gcs": archivo_gcs},
            timeout=280
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"Error del backend: HTTP {response.status_code}",
                "detalle": response.text[:500]
            }
    except requests.Timeout:
        return {"error": "El archivo es muy grande o el proceso tardo mas de 280s. Intenta de nuevo."}
    except Exception as e:
        return {"error": f"Error de conexion con el backend: {str(e)}"}


# ---- HERRAMIENTA 2: EXPLICAR ANOMALIA DE UN AWB ----------------------------
def explicar_anomalia_awb(archivo_gcs: str, awb: str) -> dict:
    """
    Obtiene el detalle completo linea por linea de todas las validaciones
    de un AWB especifico en el archivo ya procesado.

    Usar cuando el usuario pregunte por un numero de AWB concreto,
    pida explicacion de una anomalia, o quiera entender por que
    una guia tiene diferencias matematicas.

    Args:
        archivo_gcs: Ruta del archivo RESULTADO (ya validado) en GCS.
                     Ejemplo: 'resultados/fast_quincena1_2026_validado.xlsx'
                     OJO: usar la ruta del resultado, no del archivo original.
        awb: Numero completo del AWB. Formato XXX-XXXXXXXX.
             Ejemplo: '045-22332144'

    Returns:
        Diccionario con:
        - encontrado: bool
        - awb: numero consultado
        - lineas: lista de servicios con valor_cobrado, valor_calculado,
                  diferencia, estado y nota de validacion
        - total_lineas: cantidad de lineas encontradas
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/explicar_anomalia",
            json={"archivo_gcs": archivo_gcs, "awb": awb},
            timeout=60
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"Error del backend: HTTP {response.status_code}",
                "detalle": response.text[:500]
            }
    except Exception as e:
        return {"error": f"Error de conexion: {str(e)}"}


# ---- HERRAMIENTA 3: GENERAR LINK DE DESCARGA --------------------------------
def generar_link_descarga(archivo_gcs: str) -> dict:
    """
    Genera un link de descarga temporal con validez de 1 hora para que
    el usuario pueda descargar el Excel validado con todas las columnas
    de auditoria y el informe de anomalias.

    Usar cuando el usuario pida descargar el resultado, el archivo final,
    o quiera llevarse el Excel validado.

    IMPORTANTE: Si hay anomalias CRITICAS, advertir al usuario antes
    de entregar el link que el archivo requiere revision antes de Odoo.

    Args:
        archivo_gcs: Ruta completa gs:// del archivo resultado.
                     Ejemplo: 'gs://fast-agente-bucket/resultados/fast_validado.xlsx'

    Returns:
        Diccionario con:
        - url: link de descarga firmado (valido 1 hora)
        - expira_en: '1 hora'
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/link_descarga",
            json={"archivo_gcs": archivo_gcs},
            timeout=30
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"Error generando link: HTTP {response.status_code}",
                "detalle": response.text[:500]
            }
    except Exception as e:
        return {"error": f"Error de conexion: {str(e)}"}


# ---- DEFINICION DEL AGENTE --------------------------------------------------
root_agent = Agent(
    name="agente_validador_fast",
    model="gemini-2.5-flash",
    description=(
        "Agente especializado en validacion y auditoria de cobros del terminal FAST "
        "para Acosta & Aguayo. Valida archivos Excel quincenales contra el tarifario "
        "vigente, detecta anomalias, y genera informes de auditoria."
    ),
    instruction="""
Eres el Agente Validador de Gastos Terminales de Acosta & Aguayo,
especializado en el terminal FAST (Fast Air Services Terminal).

## TU ROL
Asistes a los analistas Cristian Molina y Victor Moncada en la validacion
y auditoria de los cobros quincenales del terminal FAST antes de
integrarlos al sistema Odoo.

## FLUJO DE TRABAJO TIPICO
1. El usuario te indica que subio un archivo Excel al bucket GCS
2. Llamas a validar_archivo_fast con la ruta del archivo
3. Presentas el resumen de resultados de forma clara
4. Si el usuario pregunta por un AWB especifico, llamas a explicar_anomalia_awb
5. Cuando el usuario quiere el archivo final, llamas a generar_link_descarga

## REGLAS DE NEGOCIO QUE CONOCES
- Tarifario vigente: 09/02/2026 al 30/06/2026
- Cobro minimo $41.661 CLP: aplica SOLO a DESCARGA Y PALETIZAJE y TRASVASIJE
- FULL SERVICE, RX y EMIS NO tienen cobro minimo
- ALMACENAJE: primeras 24h gratis. Si supera: Cantidad x Tarifa x floor(horas/24)
- ENMANTADO: se replica por cada elemento fisico (columna ELEMENTO del archivo)
- AUSTRALIS: bloqueo absoluto. Ninguna AWB de este cliente se procesa bajo ninguna circunstancia
- PLASTICO SEPARACION AWB: siempre debe ser $0 (es cobro a la aerolinea, no a A&A)
- Por AWB debe existir exactamente: 1x DESCARGA Y PALETIZAJE, 1x FULL SERVICE, 1x RX o EMIS
- DESTRUCCION CAJAS: aislar en tabla separada con AWB y nombre del exportador

## COMO PRESENTAR LOS RESULTADOS
Cuando termines una validacion, presenta el resumen asi:

---
VALIDACION COMPLETADA - TERMINAL FAST
- Total AWBs procesadas: X
- Sin anomalias: X (X%)
- Con alertas: X
- CRITICOS: X
- Destrucciones de cajas: X
---

Si hay CRITICOS, muestra: "CRITICO: [descripcion]" para cada uno.
Luego pregunta si quiere revisar algun AWB especifico o descargar el resultado.

## INSTRUCCIONES DE COMPORTAMIENTO
- Habla siempre en espanol, con tono profesional y conciso.
- Montos siempre en formato $X.XXX CLP
- Nunca inventes numeros - usa solo lo que retornan las herramientas
- No proceses archivos de terminales distintos a FAST
- Ante AUSTRALIS: rechaza inmediatamente y explica el bloqueo
- Si hay CRITICOS: advierte antes de entregar el link de descarga
- Se conciso pero completo - los analistas valoran la precision
- NUNCA menciones nombres de personas internas (Cristian, Victor, etc) en tus respuestas
- Si hay un error tecnico, di simplemente: "Ocurrio un error tecnico. Por favor intenta de nuevo."
- NUNCA sugieras contactar a nadie ni revelar rutas internas del bucket al usuario
- Si el link de descarga falla, di: "No pude generar el link. Intenta solicitarlo nuevamente." 

## RUTAS EN CLOUD STORAGE
- Archivos que sube el usuario: gs://fast-agente-bucket/uploads/nombre_archivo.xlsx
- Archivos resultado validados: gs://fast-agente-bucket/resultados/nombre_archivo_validado.xlsx
- Para explicar_anomalia usa la ruta del RESULTADO (resultados/...) no del original
""",
    tools=[
        FunctionTool(validar_archivo_fast),
        FunctionTool(explicar_anomalia_awb),
        FunctionTool(generar_link_descarga),
    ],
)