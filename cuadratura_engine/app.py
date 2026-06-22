import streamlit as st
from cuadratura_engine import ejecutar_proceso_cuadratura

st.set_page_config(
    page_title="Cuadratura Previsional",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Cuadratura Previsional Mensual")
st.markdown("""
Esta plataforma realiza la cuadratura automática entre el **Libro de Remuneraciones Electrónico (LRE)**, 
el archivo **Previred.xlsx** y el reporte de **Costo Empresa (KAME)** aplicando las reglas de la Reforma Previsional chilena.
""")

st.sidebar.header("📁 Carga de Archivos")

lre_input = st.sidebar.file_uploader("1. Libro de Remuneraciones (LRE) [.csv]", type=["csv"])
pr_input = st.sidebar.file_uploader("2. Reporte Previred [.xlsx]", type=["xlsx"])
ce_input = st.sidebar.file_uploader("3. Costo Empresa KAME [.xlsx]", type=["xlsx"])

st.sidebar.markdown("---")
procesar_btn = st.sidebar.button("🚀 Ejecutar Cuadratura", use_container_width=True)

if procesar_btn:
    if not (lre_input and pr_input and ce_input):
        st.error("❌ Por favor, debes cargar los 3 archivos mandatorios antes de procesar.")
    else:
        with st.spinner("Procesando datos y aplicando lógica previsional..."):
            try:
                # Ejecutar el motor
                excel_buffer, periodo, total_ruts = ejecutar_proceso_cuadratura(lre_input, pr_input, ce_input)
                
                st.success(f"✅ ¡Proceso completado con éxito para el período: **{periodo}**!")
                
                # Despliegue de métricas en tarjetas
                col1, col2 = st.columns(2)
                with col1:
                    st.metric(label="Trabajadores Totales Analizados", value=f"{total_ruts} RUTs")
                with col2:
                    st.metric(label="Período de Remuneraciones Detectado", value=periodo)
                
                st.markdown("### 📥 Descarga de Resultados")
                st.markdown("El archivo consolidado incluye el **Cuadro de Imposiciones por Pagar**, Resumen de KPIs y la **Semaforización Detallada** por trabajador.")
                
                st.download_button(
                    label="📥 Descargar Excel de Cuadratura",
                    data=excel_buffer,
                    file_name=f"Cuadratura_Previsional_{periodo.replace('/', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error("❌ Ocurrió un error al procesar las estructuras de los archivos.")
                st.info(f"Detalle técnico del error: {str(e)}")
else:
    st.info("💡 Sube los archivos requeridos en la barra lateral izquierda y presiona 'Ejecutar Cuadratura'.")