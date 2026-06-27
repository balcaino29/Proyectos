import os
import uuid
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router = APIRouter(prefix="/api", tags=["adjuntos"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

PREVIEWABLE = {"application/pdf", "image/png", "image/jpeg", "image/gif",
               "image/webp", "image/svg+xml", "text/plain"}


def _doc_dir(doc_id: int) -> str:
    path = os.path.join(UPLOAD_DIR, str(doc_id))
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/documentos/{doc_id}/adjuntos")
async def subir_adjunto(doc_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    doc = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    nombre_guardado = f"{uuid.uuid4().hex}{ext}"
    ruta = os.path.join(_doc_dir(doc_id), nombre_guardado)

    content = await file.read()
    with open(ruta, "wb") as f:
        f.write(content)

    ct = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    adjunto = models.Adjunto(
        documento_id=doc_id,
        nombre_original=file.filename,
        nombre_guardado=nombre_guardado,
        content_type=ct,
        tamanio=len(content),
    )
    db.add(adjunto)
    db.commit()
    db.refresh(adjunto)
    return {
        "id": adjunto.id,
        "nombre_original": adjunto.nombre_original,
        "content_type": adjunto.content_type,
        "tamanio": adjunto.tamanio,
    }


@router.get("/adjuntos/{adj_id}/download")
def descargar_adjunto(adj_id: int, db: Session = Depends(get_db)):
    adj = db.query(models.Adjunto).filter(models.Adjunto.id == adj_id).first()
    if not adj:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    ruta = os.path.join(_doc_dir(adj.documento_id), adj.nombre_guardado)
    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")
    return FileResponse(ruta, filename=adj.nombre_original, media_type=adj.content_type)


@router.get("/adjuntos/{adj_id}/preview")
def preview_adjunto(adj_id: int, db: Session = Depends(get_db)):
    adj = db.query(models.Adjunto).filter(models.Adjunto.id == adj_id).first()
    if not adj:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    ruta = os.path.join(_doc_dir(adj.documento_id), adj.nombre_guardado)
    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")
    ct = adj.content_type or "application/octet-stream"
    if ct not in PREVIEWABLE:
        raise HTTPException(status_code=415, detail="Tipo de archivo no previsualizable")
    return FileResponse(ruta, media_type=ct, headers={"Content-Disposition": "inline"})


@router.delete("/adjuntos/{adj_id}")
def eliminar_adjunto(adj_id: int, db: Session = Depends(get_db)):
    adj = db.query(models.Adjunto).filter(models.Adjunto.id == adj_id).first()
    if not adj:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    ruta = os.path.join(_doc_dir(adj.documento_id), adj.nombre_guardado)
    if os.path.exists(ruta):
        os.remove(ruta)
    db.delete(adj)
    db.commit()
    return {"mensaje": "Archivo eliminado"}
