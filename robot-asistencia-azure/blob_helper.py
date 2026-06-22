"""
blob_helper.py
==============
Utilidades para leer y escribir archivos en Azure Blob Storage.
Reemplaza las operaciones de disco local (open/write) en los scripts del robot.

Contenedores esperados en la cuenta de almacenamiento:
  - datos    → asistencia_cruda.json, historial_asistencia.json
  - maestros → BASE_PERSONAL_SEH.xlsx
"""

import os
import logging
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

# La connection string se inyecta como variable de entorno en Azure Functions.
# Localmente se puede definir en local.settings.json o como variable de entorno.
_CONN_STR = os.environ.get("AzureWebJobsStorage", "")

CONTAINER_DATOS    = "datos"
CONTAINER_MAESTROS = "maestros"


def _cliente_blob(container: str, blob_name: str):
    client = BlobServiceClient.from_connection_string(_CONN_STR)
    return client.get_blob_client(container=container, blob=blob_name)


def descargar_blob(container: str, blob_name: str, local_path: str) -> bool:
    """
    Descarga un blob a un archivo local.
    Retorna True si tuvo éxito, False si el blob no existe.
    """
    try:
        blob = _cliente_blob(container, blob_name)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(blob.download_blob().readall())
        logging.info(f"[BLOB] Descargado: {container}/{blob_name} → {local_path}")
        return True
    except ResourceNotFoundError:
        logging.warning(f"[BLOB] No existe: {container}/{blob_name}")
        return False
    except Exception as e:
        logging.error(f"[BLOB] Error al descargar {container}/{blob_name}: {e}")
        return False


def subir_blob(container: str, blob_name: str, local_path: str) -> bool:
    """
    Sube un archivo local a Blob Storage, sobreescribiendo si ya existe.
    Retorna True si tuvo éxito.
    """
    try:
        blob = _cliente_blob(container, blob_name)
        with open(local_path, "rb") as f:
            blob.upload_blob(f, overwrite=True)
        logging.info(f"[BLOB] Subido: {local_path} → {container}/{blob_name}")
        return True
    except Exception as e:
        logging.error(f"[BLOB] Error al subir {container}/{blob_name}: {e}")
        return False


def blob_existe(container: str, blob_name: str) -> bool:
    """Verifica si un blob existe sin descargarlo."""
    try:
        return _cliente_blob(container, blob_name).exists()
    except Exception:
        return False
