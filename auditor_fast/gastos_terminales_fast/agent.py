import pandas as pd
import numpy as np
from google.adk.agents.llm_agent import Agent
from google.adk.tools import tool

# =====================================================================
# HERRAMIENTA 1: EL AGENTE LA USA PARA INSPECCIONAR LA ESTRUCTURA
# =====================================================================
@tool
def leer_columnas_excel(ruta_archivo: str) -> list:
    """
    Abre un archivo Excel y devuelve la lista exacta de sus encabezados (columnas).
    Úsala para inspeccionar cómo viene estructurado el archivo antes de auditarlo.
    """
    try:
        df = pd.read_excel(ruta_archivo, nrows=2)
        return df.columns.tolist()
    except Exception as e:
        return [f"Error al leer columnas: {str(e)}"]

# =====================================================================
# HERRAMIENTA 2: EJECUCIÓN MATEMÁTICA CON PARÁMETROS DINÁMICOS
# =====================================================================
@tool
def ejecutar_calculo_auditoria(
    archivo_fast: str, archivo_hermes: str, archivo_tarifas: str, archivo_salida: str,
    col_exportador: str, col_servicio: str, col_guia: str, col_kilos: str
) -> dict:
    """
    Realiza la auditoría matemática final utilizando los nombres de columnas 
    que el agente identificó previamente.
    """
    try:
        df_fast = pd.read_excel(archivo_fast)
        df_hermes = pd.read_excel(archivo_hermes)
        df_tarifas = pd.read_excel(archivo_tarifas)
        
        # El agente le dice a Python cómo se llaman las columnas hoy
        df_fast['Exportador_Clean'] = df_fast[col_exportador].astype(str).str.strip().str.upper()
        df_fast['Servicio_Clean'] = df_fast[col_servicio].astype(str).str.strip().str.upper()
        df_fast['Guia_Clean'] = df_fast[col_guia].astype(str).str.strip()
        df_hermes['Guia_Clean'] = df_hermes['Guia_Aerea'].astype(str).str.strip()
        
        # REGLA EXCLUYENTE (Australis se va por trato directo)
        clientes_directos = ['AUSTRALIS', 'AUSTRALIA', 'AUSTRALIS MAR']
        df_fast = df_fast[~df_fast['Exportador_Clean'].isin(clientes_directos)]
        
        # REGLA VALIDACIÓN: Servicios mínimos
        alertas = []
        servicios_obligatorios = {'DESCARGA', 'RAYOS', 'FULL SERVICE'}
        for guia, grupo in df_fast.groupby('Guia_Clean'):
            servicios_presentes = set(grupo['Servicio_Clean'].unique())
            faltantes = servicios_obligatorios - servicios_presentes
            if faltantes:
                alertas.append(f"Guía {guia}: Faltan cobros obligatorios de FAST: {faltantes}")
                
        # CRUCE Y CÁLCULO DINÁMICO (P * Q)
        df_auditado = pd.merge(df_fast, df_tarifas[['Servicio', 'Precio_Tarifa', 'Tarifa_Olin_Fija']], left_on='Servicio_Clean', right_on='Servicio', how='left')
        df_auditado = pd.merge(df_auditado, df_hermes[['Guia_Clean', 'Kilos_Hermes', 'Modalidad_Venta']], on='Guia_Clean', how='left')
        
        df_auditado['Total_Compra'] = np.where(
            df_auditado['Servicio_Clean'] == 'ENMANTADO',
            df_auditado['Precio_Tarifa'] * df_auditado.get('Cantidad_Mantas', 1),
            df_auditado['Precio_Tarifa'] * df_auditado[col_kilos]
        )
        
        df_auditado['Total_Venta'] = np.where(
            df_auditado['Modalidad_Venta'] == 'OLIN',
            df_auditado['Tarifa_Olin_Fija'] * df_auditado[col_kilos],
            df_auditado['Total_Compra']
        )
        
        df_auditado.to_excel(archivo_salida, index=False)
        
        return {
            "status": "success",
            "alertas_operativas": alertas,
            "mensaje": f"Archivo guardado exitosamente como {archivo_salida}"
        }
    except Exception as e:
        return {"status": "error", "detalles": str(e)}

# =====================================================================
# EL CEREBRO DEL AGENTE (Aquí es donde toma las decisiones)
# =====================================================================
root_agent = Agent(
    model='gemini-2.5-flash',
    name='gastos_terminales_fast',
    description="Agente inteligente capaz de deducir la estructura de sábanas logísticas y auditarlas.",
    instruction=(
        "Eres un auditor financiero autónomo. Tu objetivo es procesar la auditoría del terminal FAST[cite: 8, 9]. "
        "Dado que los archivos Excel pueden cambiar el nombre de sus columnas, debes operar con el siguiente pensamiento analítico:\n\n"
        "1. Usa la herramienta `leer_columnas_excel` en 'fast.xlsx' para ver qué columnas tiene el archivo actualmente.\n"
        "2. Analiza la lista de columnas devuelta y DETERMINA inteligentemente cuál corresponde a:\n"
        "   - El Exportador/Cliente (ej. 'Exportador', 'CLIENTE', 'Razon Social')[cite: 42, 48].\n"
        "   - El Servicio cobrado (ej. 'Servicio', 'Concepto', 'Item')[cite: 42].\n"
        "   - La Guía Aérea (ej. 'Guia_Aerea', 'Nro Guia', 'AWB')[cite: 42].\n"
        "   - Los Kilos del terminal (ej. 'Kilos_Guia', 'Kilos', 'Peso')[cite: 42, 48].\n"
        "3. Una vez que hayas tomado la decisión de qué columna es cuál, invoca la herramienta `ejecutar_calculo_auditoria` "
        "pasándole explícitamente los nombres de columna que tú dedujiste.\n"
        "4. Al final, no te limites a dar un reporte seco. Explica con tus propias palabras qué debilidades o desviaciones "
        "encontraste en la facturación de FAST (por ejemplo, si omitieron el Full Service en alguna guía)[cite: 33, 45]."
    ),
    tools=[leer_columnas_excel, ejecutar_calculo_auditoria],
)