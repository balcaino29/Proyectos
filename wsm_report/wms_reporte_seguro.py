"""
WMS Segura - Extracción de Stock Crítico con alertas por correo.

Versión instrumentada para diagnóstico:
- Distingue "tabla no existe" vs "tabla vacía" vs "tabla con datos".
- Guarda screenshot + HTML en ./diagnostico/ cuando algo falla.
- Modo visible con --debug (headless=False + slow_mo) para observar el flujo.
- Logging a consola y a wms_reporte.log.

Uso:
    python wms_reporte_seguro.py --run-now            # ejecuta una vez ahora
    python wms_reporte_seguro.py --run-now --debug    # ejecuta una vez con navegador visible
    python wms_reporte_seguro.py                      # solo deja el scheduler corriendo (L-V 08:00)
"""

import argparse
import asyncio
import logging
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

# Carga opcional de .env (no rompe si python-dotenv no está instalado)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# =====================================================================
# 1. CONFIGURACIÓN
#    Los secretos se leen de variables de entorno (.env). Se dejan los
#    valores actuales como fallback SOLO para no romper tu flujo, pero
#    deberías migrarlos a .env y rotar la contraseña de aplicación de Gmail.
# =====================================================================
WMS_USUARIO = os.getenv("WMS_USUARIO", "balcaino@seguraehijos.cl")
WMS_CONTRASENA = os.getenv("WMS_CONTRASENA", "123456")

SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR", "smtp.gmail.com")
SMTP_PUERTO = int(os.getenv("SMTP_PUERTO", "587"))
SMTP_REMITENTE = os.getenv("SMTP_REMITENTE", "notificacionesseh@gmail.com")
SMTP_CONTRASENA = os.getenv("SMTP_CONTRASENA", "jssi gzwx yxsl xjst")
CORREO_DESTINATARIO = os.getenv(
    "CORREO_DESTINATARIO",
    "fmedina@seguraehijos.cl, mcampos@seguraehijos.cl, balcaino@seguraehijos.cl,rfernandez@seguraehijos.cl,nvargas@seguraehijos.cl,lsoto@seguraehijos.cl,freinanco@seguraehijos.cl"
)

URL_LOGIN = "https://wms.coretec.cl/wms/vistas/login.html"
URL_REPORTE = "https://wms.coretec.cl/wms/vistas/reporte-stockminimo.html"

# Selectores (ajusta aquí si el diagnóstico revela que alguno cambió)
SEL_USUARIO = 'input[name="usuario"]'
SEL_CLAVE = 'input[name="clave"]'
SEL_LOGIN_BTN = 'button[type="submit"]'
SEL_FILTRO_CRITICO = "#filtro-critico"
SEL_FILTRO_SEGUIMIENTO = "#filtro-seguimiento"
SEL_BTN_GENERAR = "#btn-generar"
SEL_TBODY = "#stockminimo-tbody"
SEL_BTN_NEXT = "button[data-nav='next']"

DIAG_DIR = "diagnostico"

# Estado global de ejecución (lo setea main según los flags)
MODO_DEBUG = False

# =====================================================================
# LOGGING
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("wms_reporte.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("wms")


# =====================================================================
# 2. UTILIDADES DE DIAGNÓSTICO
# =====================================================================
async def guardar_diagnostico(page, etiqueta):
    """Guarda screenshot + HTML de la página actual para inspección manual."""
    os.makedirs(DIAG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(DIAG_DIR, f"{etiqueta}_{ts}")
    try:
        await page.screenshot(path=f"{base}.png", full_page=True)
        html = await page.content()
        with open(f"{base}.html", "w", encoding="utf-8") as f:
            f.write(html)
        log.info("🧪 Diagnóstico guardado: %s.png / .html (URL actual: %s)", base, page.url)
    except Exception as e:
        log.warning("No se pudo guardar el diagnóstico: %s", e)


# =====================================================================
# 3. LOGIN
# =====================================================================
async def hacer_login(page):
    log.info("Abriendo login: %s", URL_LOGIN)
    await page.goto(URL_LOGIN, wait_until="domcontentloaded")
    await page.fill(SEL_USUARIO, WMS_USUARIO)
    await page.fill(SEL_CLAVE, WMS_CONTRASENA)
    await page.click(SEL_LOGIN_BTN)
    await page.wait_for_load_state("networkidle")

    # Heurística suave: si seguimos en login.html, probablemente falló.
    if "login.html" in page.url.lower():
        await guardar_diagnostico(page, "login_sospechoso")
        log.warning(
            "Seguimos en la página de login tras autenticar (%s). "
            "Si el resto falla, revisa credenciales o el selector del botón.",
            page.url,
        )
    else:
        log.info("Login OK. URL actual: %s", page.url)


# =====================================================================
# 4. NAVEGACIÓN AL REPORTE + APLICAR FILTROS
# =====================================================================
async def abrir_reporte_y_filtrar(page):
    log.info("Navegando al reporte: %s", URL_REPORTE)
    await page.goto(URL_REPORTE, wait_until="domcontentloaded")

    # Esperar a que la página termine de cargar su JS ANTES de interactuar.
    # Esto evita la carrera de hacer clic en Generar antes de que su handler
    # esté enganchado (que haría que el clic no dispare ninguna búsqueda).
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass

    try:
        await page.wait_for_selector(SEL_FILTRO_CRITICO, state="visible", timeout=20000)
    except PWTimeout:
        await guardar_diagnostico(page, "sin_filtros")
        raise RuntimeError(
            f"No apareció el filtro {SEL_FILTRO_CRITICO}. "
            "Posible sesión no iniciada (redirección a login) o id distinto. "
            "Revisa ./diagnostico."
        )

    # Marcar filtros y CONFIRMAR que quedaron en el estado esperado.
    await page.check(SEL_FILTRO_CRITICO)
    await page.check(SEL_FILTRO_SEGUIMIENTO)
    await page.wait_for_timeout(300)  # dejar que se asienten los eventos 'change'
    log.info(
        "Estado de filtros -> critico=%s | seguimiento=%s",
        await page.is_checked(SEL_FILTRO_CRITICO),
        await page.is_checked(SEL_FILTRO_SEGUIMIENTO),
    )

    # Asegurar que el botón Generar es interactuable y hacer clic.
    # NOTA: este WMS filtra del lado del CLIENTE. Los datos se cargan al abrir la
    # página (durante el wait_for_load_state networkidle de arriba); el clic en
    # Generar solo re-renderiza la tabla, sin hacer una nueva petición de red.
    # Por eso NO esperamos ninguna XHR aquí: basta el clic y luego el polling de
    # filas en obtener_filas_validas.
    await page.wait_for_selector(SEL_BTN_GENERAR, state="visible", timeout=10000)
    log.info("Clic en Generar...")
    await page.click(SEL_BTN_GENERAR)


# =====================================================================
# 5. ESPERA ROBUSTA DE LA TABLA (el corazón del fix)
# =====================================================================
SEL_MSG_VACIO = "text=No se encontraron resultados"


async def obtener_filas_validas(page):
    """
    Devuelve la lista de <tr> con datos reales.

    OJO: en este WMS el #stockminimo-tbody SIEMPRE existe en el DOM, pero su
    contenedor #tabla-reporte está display:none mientras no hay resultados.
    Por eso esperamos state="attached" (que exista), NO visibilidad, y luego
    decidimos entre: (a) hay filas, o (b) el WMS muestra "No se encontraron
    resultados".
    """
    # (1) El tbody debe existir en el DOM (puede estar oculto)
    try:
        await page.wait_for_selector(SEL_TBODY, state="attached", timeout=20000)
    except PWTimeout:
        await guardar_diagnostico(page, "sin_tbody")
        raise RuntimeError(
            f"No apareció el contenedor {SEL_TBODY} en el DOM. Revisa ./diagnostico."
        )

    # (2) Dar tiempo a que la consulta AJAX responda
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        pass  # algunos sitios nunca quedan "idle" por polling; seguimos

    # (3) Polling: o aparecen filas, o aparece el mensaje de "sin resultados"
    for _ in range(20):
        filas = await page.query_selector_all(f"{SEL_TBODY} tr")
        validas = []
        for f in filas:
            if len(await f.query_selector_all("td")) >= 8:
                validas.append(f)
        if validas:
            log.info("Tabla cargada con %d fila(s) de datos.", len(validas))
            return validas

        msg_vacio = await page.query_selector(SEL_MSG_VACIO)
        if msg_vacio and await msg_vacio.is_visible():
            log.info(
                "El WMS devolvió 'No se encontraron resultados' con los filtros "
                "actuales. No hay nada que reportar hoy con esa combinación."
            )
            return []

        await page.wait_for_timeout(1000)

    # (4) Ni filas ni mensaje claro tras esperar -> sí es anómalo
    await guardar_diagnostico(page, "tabla_sin_filas")
    log.warning(
        "No hubo filas ni mensaje de 'sin resultados' tras esperar. "
        "Revisa ./diagnostico para confirmar."
    )
    return []


def parse_int(texto):
    t = (texto or "").strip()
    return int(t) if t.replace("-", "").isdigit() else 0


async def extraer_fila(fila):
    celdas = await fila.query_selector_all("td")
    if len(celdas) < 8:
        return None
    return {
        "SKU": (await celdas[0].inner_text()).strip(),
        "Descripción": (await celdas[1].inner_text()).strip(),
        "Familia": (await celdas[2].inner_text()).strip(),
        "Stock Actual": parse_int(await celdas[3].inner_text()),
        "Stock Mínimo": parse_int(await celdas[4].inner_text()),
        "Diferencia": parse_int(await celdas[5].inner_text()),
        "Seguimiento": (await celdas[6].inner_text()).strip(),
        "Estado": (await celdas[7].inner_text()).strip(),
    }


# =====================================================================
# 6. PAGINACIÓN
# =====================================================================
async def recorrer_paginas(page):
    datos = []
    pagina = 1

    # Primera página
    filas = await obtener_filas_validas(page)
    if not filas:
        return datos  # vacío legítimo o error ya diagnosticado

    while True:
        log.info("Procesando página %d...", pagina)
        for fila in await page.query_selector_all(f"{SEL_TBODY} tr"):
            registro = await extraer_fila(fila)
            if registro:
                datos.append(registro)

        # ¿Hay botón siguiente y está habilitado?
        boton = await page.query_selector(SEL_BTN_NEXT)
        if not boton:
            break
        if await boton.evaluate("btn => btn.disabled"):
            break

        # Guardamos el SKU actual para detectar el cambio de página
        primera = await page.query_selector(f"{SEL_TBODY} tr td")
        sku_previo = await primera.inner_text() if primera else ""

        await boton.click()
        pagina += 1

        try:
            await page.wait_for_function(
                "(prev) => { const el = document.querySelector('%s tr td');"
                " return el && el.innerText !== prev; }" % SEL_TBODY,
                arg=sku_previo,
                timeout=8000,
            )
        except PWTimeout:
            await page.wait_for_timeout(2000)

    return datos


# =====================================================================
# 7. ENVÍO DE CORREO EJECUTIVO
# =====================================================================
def enviar_correo_ejecutivo(nombre_archivo, datos):
    if not datos:
        return

    df = pd.DataFrame(datos)
    total_criticos = len(df)
    quiebre_total_stock_cero = len(df[df["Stock Actual"] == 0])
    insumos_mas_criticos = df.sort_values(by="Diferencia").head(5)
    familia_mas_afectada = (
        df["Familia"].value_counts().idxmax() if not df.empty else "N/A"
    )
    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    msg = MIMEMultipart()
    msg["From"] = SMTP_REMITENTE
    msg["To"] = CORREO_DESTINATARIO
    msg["Subject"] = f"⚠️ [ALERTA DE STOCK CRÍTICO] - Resumen Ejecutivo WMS ({fecha_hoy})"

    tabla_top5_html = ""
    for _, fila in insumos_mas_criticos.iterrows():
        estilo_cero = (
            "background-color: #fce4d6; font-weight: bold; color: #c00000;"
            if fila["Stock Actual"] == 0
            else ""
        )
        tabla_top5_html += f"""
        <tr style="{estilo_cero}">
            <td style="padding: 8px; border: 1px solid #ddd;">{fila['SKU']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{fila['Descripción']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{fila['Familia']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{fila['Stock Actual']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{fila['Stock Mínimo']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: red; font-weight: bold;">{fila['Diferencia']}</td>
        </tr>
        """

    alerta_quiebre = (
        "<div style='background-color: #f8d7da; color: #721c24; padding: 10px; "
        "border-radius: 4px; font-weight: bold; margin-bottom: 20px; text-align: center; "
        "border: 1px solid #f5c6cb;'>⚠️ ATENCIÓN: Existen materiales con quiebre total "
        "(Stock 0) que pueden paralizar frentes de trabajo.</div>"
        if quiebre_total_stock_cero > 0
        else ""
    )

    cuerpo_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 700px; margin: 0 auto; border: 1px solid #e0e0e0; padding: 20px; border-radius: 5px;">
            <div style="background-color: #2c3e50; color: white; padding: 15px; text-align: center; border-radius: 3px 3px 0 0;">
                <h2 style="margin: 0; font-size: 18px; letter-spacing: 1px;">INFORME DIARIO: GESTIÓN DE STOCK CRÍTICO</h2>
                <p style="margin: 5px 0 0 0; font-size: 13px; color: #bdc3c7;">Reporte Automatizado - Maestranza & Bodega ({fecha_hoy})</p>
            </div>
            <p style="margin-top: 20px;">Estimado Equipo de Operaciones y Adquisiciones,</p>
            <p>Se ha ejecutado el control de inventario programado en el WMS Coretec. A continuación, se presenta el <strong>Resumen Ejecutivo</strong> con los insumos y herramientas bajo el umbral mínimo permitido:</p>
            <div style="display: flex; gap: 10px; margin: 20px 0;">
                <div style="flex: 1; background-color: #f8d7da; border-left: 5px solid #dc3545; padding: 10px; border-radius: 4px; text-align: center;">
                    <span style="font-size: 11px; text-transform: uppercase; color: #721c24; font-weight: bold;">SKUs Críticos</span><br>
                    <span style="font-size: 24px; font-weight: bold; color: #721c24;">{total_criticos}</span>
                </div>
                <div style="flex: 1; background-color: #fff3cd; border-left: 5px solid #ffc107; padding: 10px; border-radius: 4px; text-align: center;">
                    <span style="font-size: 11px; text-transform: uppercase; color: #856404; font-weight: bold;">En Stock Cero (0)</span><br>
                    <span style="font-size: 24px; font-weight: bold; color: #856404;">{quiebre_total_stock_cero}</span>
                </div>
                <div style="flex: 1; background-color: #d1ecf1; border-left: 5px solid #17a2b8; padding: 10px; border-radius: 4px; text-align: center;">
                    <span style="font-size: 11px; text-transform: uppercase; color: #0c5460; font-weight: bold;">Familia más afectada</span><br>
                    <span style="font-size: 16px; font-weight: bold; color: #0c5460; display: block; margin-top: 5px;">{familia_mas_afectada}</span>
                </div>
            </div>
            {alerta_quiebre}
            <h3 style="color: #2c3e50; border-bottom: 2px solid #34495e; padding-bottom: 5px; font-size: 14px;">TOP 5 INSUMOS CON MAYOR DÉFICIT DE UNIDADES</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 20px;">
                <thead>
                    <tr style="background-color: #f2f2f2; text-align: left;">
                        <th style="padding: 8px; border: 1px solid #ddd;">SKU</th>
                        <th style="padding: 8px; border: 1px solid #ddd;">Descripción</th>
                        <th style="padding: 8px; border: 1px solid #ddd; text-align: center;">Familia</th>
                        <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Stock Actual</th>
                        <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Stock Mín</th>
                        <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Diferencia</th>
                    </tr>
                </thead>
                <tbody>
                    {tabla_top5_html}
                </tbody>
            </table>
            <p style="font-size: 13px;">📌 <em>Nota: Se adjunta el archivo Excel con el desglose completo de todas las páginas del WMS para gestionar las órdenes de compra (O/C) correspondientes.</em></p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 11px; color: #999; text-align: center;">Correo automático generado por el sistema WMS Segura.<br>Por favor no responder a esta dirección.</p>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(cuerpo_html, "html"))

    try:
        with open(nombre_archivo, "rb") as f:
            adjunto = MIMEApplication(f.read(), _subtype="xlsx")
            adjunto.add_header(
                "Content-Disposition", "attachment", filename=nombre_archivo
            )
            msg.attach(adjunto)
    except Exception as e:
        log.warning("No se pudo adjuntar el Excel: %s", e)

    try:
        log.info("Conectando al SMTP para enviar alertas a: %s", CORREO_DESTINATARIO)
        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PUERTO, timeout=30) as server:
            server.starttls()
            server.login(SMTP_REMITENTE, SMTP_CONTRASENA)
            destinatarios = [c.strip() for c in CORREO_DESTINATARIO.split(",")]
            server.sendmail(SMTP_REMITENTE, destinatarios, msg.as_string())
        log.info("✉️ Correo ejecutivo enviado con éxito.")
    except Exception as e:
        log.error("❌ Error al enviar el correo por SMTP: %s", e)


# =====================================================================
# 8. ORQUESTACIÓN
# =====================================================================
async def ejecutar_extraccion_diaria():
    log.info("🤖 Iniciando proceso de extracción automatizado...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not MODO_DEBUG,
            slow_mo=400 if MODO_DEBUG else 0,
            # Necesario al correr como root dentro de un contenedor (Azure):
            # --no-sandbox: Chromium no puede usar el sandbox como root.
            # --disable-dev-shm-usage: evita cuelgues por /dev/shm pequeño.
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await hacer_login(page)
            await abrir_reporte_y_filtrar(page)
            datos = await recorrer_paginas(page)

            if datos:
                fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                nombre_archivo = f"Reporte_Stock_Critico_{fecha_hoy}.xlsx"
                pd.DataFrame(datos).to_excel(nombre_archivo, index=False)
                log.info("✅ Excel guardado: '%s' (%d filas).", nombre_archivo, len(datos))
                enviar_correo_ejecutivo(nombre_archivo, datos)
            else:
                log.warning("⚠️ Sin alertas críticas hoy (o revisa el diagnóstico generado).")
        except Exception as e:
            log.error("❌ Error en el proceso: %s", e)
            await guardar_diagnostico(page, "error_general")
        finally:
            await browser.close()


def tarea_programada():
    asyncio.run(ejecutar_extraccion_diaria())


def main():
    global MODO_DEBUG
    parser = argparse.ArgumentParser(description="WMS Segura - Reporte de stock crítico")
    parser.add_argument("--run-now", action="store_true", help="Ejecuta una vez ahora y termina")
    parser.add_argument("--debug", action="store_true", help="Navegador visible + slow_mo")
    args = parser.parse_args()
    MODO_DEBUG = args.debug

    log.info("🚀 Servidor 'WMS Segura' con Módulo de Alertas por Correo.")

    if args.run_now:
        tarea_programada()
        return

    # 'schedule' solo se usa para el modo scheduler local. En Azure NO se usa:
    # el cron lo maneja Container Apps Jobs y el contenedor corre con --run-now.
    import schedule

    for dia in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
        getattr(schedule.every(), dia).at("08:00").do(tarea_programada)

    log.info("Scheduler activo (L-V 08:00). Esperando...")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()