import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router = APIRouter(prefix="/api", tags=["email"])

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "smtp_config.json")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")

DEFAULT_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "usuario": "",
    "password": "",
    "remitente": "",
    "use_tls": True,
}


def leer_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG


def guardar_config(data: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


@router.get("/smtp-config")
def get_smtp_config():
    cfg = leer_config()
    cfg.pop("password", None)
    return cfg


@router.post("/smtp-config")
def set_smtp_config(data: dict):
    cfg = leer_config()
    cfg.update(data)
    guardar_config(cfg)
    return {"mensaje": "Configuración guardada"}


class EmailPayload(BaseModel):
    destinatarios: List[str]
    asunto: str
    cuerpo: str
    adjunto_ids: Optional[List[int]] = []


@router.post("/documentos/{doc_id}/enviar-email")
def enviar_email(doc_id: int, payload: EmailPayload, db: Session = Depends(get_db)):
    doc = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    cfg = leer_config()
    if not cfg.get("usuario") or not cfg.get("password"):
        raise HTTPException(status_code=400, detail="Configura el servidor SMTP primero (Ajustes)")

    msg = MIMEMultipart()
    msg["From"] = cfg["remitente"] or cfg["usuario"]
    msg["To"] = ", ".join(payload.destinatarios)
    msg["Subject"] = payload.asunto
    msg.attach(MIMEText(payload.cuerpo, "plain", "utf-8"))

    # Adjuntar archivos seleccionados
    if payload.adjunto_ids:
        adjuntos = db.query(models.Adjunto).filter(
            models.Adjunto.id.in_(payload.adjunto_ids),
            models.Adjunto.documento_id == doc_id,
        ).all()
        for adj in adjuntos:
            ruta = os.path.join(UPLOAD_DIR, str(doc_id), adj.nombre_guardado)
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{adj.nombre_original}"')
                msg.attach(part)

    try:
        if cfg.get("use_tls"):
            server = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=15)
        server.login(cfg["usuario"], cfg["password"])
        server.sendmail(cfg["remitente"] or cfg["usuario"], payload.destinatarios, msg.as_string())
        server.quit()
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=401, detail="Credenciales SMTP incorrectas. Verifica usuario y contraseña.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar email: {str(e)}")

    return {"mensaje": f"Email enviado a {', '.join(payload.destinatarios)}"}
