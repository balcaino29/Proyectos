"""
main.py - API REST del Agente FAST
"""

import os
import json
import tempfile
import traceback
from flask import Flask, request, jsonify, send_file
from google.cloud import storage

from validador import ejecutar_validacion, stage5_generar_excel

app = Flask(__name__)

BUCKET_NAME    = os.environ.get("GCS_BUCKET", "fast-agente-bucket")
TARIFARIO_PATH = os.environ.get("TARIFARIO_PATH", "config/tarifas_FAST.xlsx")


def descargar_blob(bucket_name, blob_name, dest_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_name)
    blob.download_to_filename(dest_path)


def subir_blob(bucket_name, blob_name, src_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_name)
    blob.upload_from_filename(src_path)
    return f"gs://{bucket_name}/{blob_name}"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servicio": "Agente FAST"}), 200


@app.route("/validar", methods=["POST"])
def validar():
    try:
        body        = request.get_json()
        archivo_gcs = body.get("archivo_gcs")

        if not archivo_gcs:
            return jsonify({"error": "Debes indicar el campo 'archivo_gcs'"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            path_fast      = os.path.join(tmpdir, "fast.xlsx")
            path_tarifario = os.path.join(tmpdir, "tarifas.xlsx")
            path_salida    = os.path.join(tmpdir, "FAST_validado.xlsx")

            descargar_blob(BUCKET_NAME, archivo_gcs,    path_fast)
            descargar_blob(BUCKET_NAME, TARIFARIO_PATH, path_tarifario)

            resultado = ejecutar_validacion(path_fast, path_tarifario, path_salida)

            nombre_salida = archivo_gcs.replace("uploads/", "resultados/").replace(".xlsx", "_validado.xlsx")
            gcs_salida    = subir_blob(BUCKET_NAME, nombre_salida, path_salida)

            stats = resultado["resultado_audit"]["estadisticas"]
            return jsonify({
                "status":            "completado",
                "total_awbs":        stats["total_awbs"],
                "awbs_ok":           stats["ok"],
                "awbs_alertas":      stats["alertas"],
                "awbs_criticos":     stats["criticos"],
                "hay_criticos":      stats["hay_criticos"],
                "destrucciones":     len(resultado["resultado_audit"]["destrucciones"]),
                "archivo_resultado": gcs_salida,
                "ruta_descarga":     nombre_salida,
                "contexto_gemini":   resultado["contexto_gemini"],
            }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/explicar_anomalia", methods=["POST"])
def explicar_anomalia():
    try:
        body        = request.get_json()
        archivo_gcs = body.get("archivo_gcs")
        awb_buscar  = body.get("awb", "").strip()

        if not archivo_gcs or not awb_buscar:
            return jsonify({"error": "Faltan campos 'archivo_gcs' o 'awb'"}), 400

        import pandas as pd
        with tempfile.TemporaryDirectory() as tmpdir:
            path_resultado = os.path.join(tmpdir, "resultado.xlsx")
            blob_path = archivo_gcs.replace(f"gs://{BUCKET_NAME}/", "")
            descargar_blob(BUCKET_NAME, blob_path, path_resultado)

            filas_awb = []
            for hoja in ["Aqua_Latam", "Aqua_Otras_Aerolineas", "Otros A&A"]:
                try:
                    df  = pd.read_excel(path_resultado, sheet_name=hoja)
                    sub = df[df["Awb"].astype(str).str.strip() == awb_buscar]
                    if not sub.empty:
                        cols = ["Nombre Servicio", "Unidad Cobro",
                                "Cantidad A Cobro Ajustada", "Tarifa (CLP)",
                                "Valor cobro Ajustado", "Valor_Calculado",
                                "Diferencia_CLP", "Estado_Validacion", "Nota_Validacion"]
                        filas_awb.extend(sub[cols].to_dict(orient="records"))
                except Exception:
                    continue

            if not filas_awb:
                return jsonify({"awb": awb_buscar, "encontrado": False,
                                "mensaje": f"No se encontro el AWB {awb_buscar}"}), 200

            return jsonify({"awb": awb_buscar, "encontrado": True,
                            "lineas": filas_awb,
                            "total_lineas": len(filas_awb)}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/descargar/<path:ruta_archivo>", methods=["GET"])
def descargar_archivo(ruta_archivo):
    """
    Endpoint de descarga directa. El agente entrega esta URL al usuario.
    Cloud Run descarga el archivo de GCS y lo sirve directamente al navegador.
    No requiere permisos especiales de firma.
    URL ejemplo: https://agente-fast-xxx.run.app/descargar/resultados/fast_prueba_validado.xlsx
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            nombre_archivo = ruta_archivo.split("/")[-1]
            path_local     = os.path.join(tmpdir, nombre_archivo)

            descargar_blob(BUCKET_NAME, ruta_archivo, path_local)

            return send_file(
                path_local,
                as_attachment=True,
                download_name=nombre_archivo,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/link_descarga", methods=["POST"])
def link_descarga():
    """
    Retorna la URL de descarga directa via el endpoint /descargar/.
    No requiere firma ni permisos especiales de GCS.
    """
    try:
        body        = request.get_json()
        archivo_gcs = body.get("archivo_gcs", "")

        # Extraer ruta relativa
        ruta = archivo_gcs.replace(f"gs://{BUCKET_NAME}/", "").strip()
        if not ruta:
            return jsonify({"error": "archivo_gcs no valido"}), 400

        # Construir URL de descarga directa via Cloud Run
        base_url = os.environ.get(
            "SERVICE_URL",
            "https://agente-fast-451607402839.us-central1.run.app"
        )
        url = f"{base_url}/descargar/{ruta}"

        return jsonify({
            "url":       url,
            "expira_en": "no expira",
            "nota":      "Descarga directa disponible. Haz clic en el link para descargar el archivo."
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)