from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from math import ceil
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/api/documentos", tags=["documentos"])


@router.get("")
def listar_documentos(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sala_tag: Optional[str] = Query(None),
    disciplina: Optional[str] = Query(None),
    estatus: Optional[str] = Query(None),
    criticidad: Optional[str] = Query(None),
    buscar: Optional[str] = Query(None),
):
    q = db.query(models.Documento)

    if sala_tag:
        q = q.filter(models.Documento.sala_tag == sala_tag)
    if disciplina:
        q = q.filter(models.Documento.disciplina == disciplina)
    if estatus:
        q = q.filter(models.Documento.estatus.ilike(f"%{estatus}%"))
    if criticidad:
        q = q.filter(models.Documento.criticidad == criticidad)
    if buscar:
        q = q.filter(
            or_(
                models.Documento.descripcion.ilike(f"%{buscar}%"),
                models.Documento.codigo_segura.ilike(f"%{buscar}%"),
                models.Documento.codigo_inn.ilike(f"%{buscar}%"),
            )
        )

    total = q.count()
    docs = q.order_by(models.Documento.item).offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [
            {
                "id": d.id,
                "item": d.item,
                "sala_tag": d.sala_tag,
                "codigo_segura": d.codigo_segura,
                "codigo_inn": d.codigo_inn,
                "descripcion": d.descripcion,
                "disciplina": d.disciplina,
                "criticidad": d.criticidad,
                "estatus": d.estatus,
                "revision_actual": d.revision_actual,
                "fecha_ultimo_envio": d.fecha_ultimo_envio.isoformat() if d.fecha_ultimo_envio else None,
                "fecha_respuesta_cliente": d.fecha_respuesta_cliente.isoformat() if d.fecha_respuesta_cliente else None,
                "acta_trl": d.acta_trl,
                "num_emisiones": len(d.emisiones),
                "num_adjuntos": len(d.adjuntos),
                "deadline_cliente": d.deadline_cliente,
                "compromiso_entrega": d.compromiso_entrega,
            }
            for d in docs
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": ceil(total / limit) if total else 1,
    }


@router.get("/filtros")
def get_filtros(db: Session = Depends(get_db)):
    sala_tags = db.query(models.Documento.sala_tag).distinct().filter(models.Documento.sala_tag.isnot(None)).all()
    disciplinas = db.query(models.Documento.disciplina).distinct().filter(models.Documento.disciplina.isnot(None)).all()
    criticidades = db.query(models.Documento.criticidad).distinct().filter(models.Documento.criticidad.isnot(None)).all()
    estatuses = db.query(models.Documento.estatus).distinct().filter(models.Documento.estatus.isnot(None)).all()
    return {
        "sala_tags": sorted([r[0] for r in sala_tags]),
        "disciplinas": sorted([r[0] for r in disciplinas]),
        "criticidades": sorted([str(r[0]) for r in criticidades]),
        "estatuses": sorted([r[0] for r in estatuses]),
    }


@router.get("/{doc_id}")
def obtener_documento(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return {
        "id": doc.id,
        "item": doc.item,
        "tipo_ing": doc.tipo_ing,
        "sala_tag": doc.sala_tag,
        "codigo_segura": doc.codigo_segura,
        "codigo_inn": doc.codigo_inn,
        "codigo_codelco": doc.codigo_codelco,
        "descripcion": doc.descripcion,
        "compromiso_entrega": doc.compromiso_entrega,
        "criticidad": doc.criticidad,
        "deadline_cliente": doc.deadline_cliente,
        "comentario_interno": doc.comentario_interno,
        "disciplina": doc.disciplina,
        "revision_actual": doc.revision_actual,
        "acta_trl": doc.acta_trl,
        "fecha_ultimo_envio": doc.fecha_ultimo_envio.isoformat() if doc.fecha_ultimo_envio else None,
        "fecha_respuesta_cliente": doc.fecha_respuesta_cliente.isoformat() if doc.fecha_respuesta_cliente else None,
        "estatus": doc.estatus,
        "emisiones": [
            {
                "id": e.id,
                "numero": e.numero,
                "revision": e.revision,
                "transmittal_seh": e.transmittal_seh,
                "fecha_envio": e.fecha_envio.isoformat() if e.fecha_envio else None,
                "transmittal_cliente": e.transmittal_cliente,
                "fecha_respuesta": e.fecha_respuesta.isoformat() if e.fecha_respuesta else None,
                "tiempo_respuesta": e.tiempo_respuesta,
                "observaciones": e.observaciones,
            }
            for e in doc.emisiones
        ],
        "adjuntos": [
            {
                "id": a.id,
                "nombre_original": a.nombre_original,
                "content_type": a.content_type,
                "tamanio": a.tamanio,
                "creado_en": a.creado_en.isoformat() if a.creado_en else None,
            }
            for a in doc.adjuntos
        ],
    }


@router.post("", response_model=dict)
def crear_documento(doc: schemas.DocumentoCreate, db: Session = Depends(get_db)):
    nuevo = models.Documento(**doc.model_dump())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"id": nuevo.id, "mensaje": "Documento creado"}


@router.put("/{doc_id}", response_model=dict)
def actualizar_documento(doc_id: int, doc: schemas.DocumentoUpdate, db: Session = Depends(get_db)):
    existing = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    for key, val in doc.model_dump(exclude_unset=True).items():
        setattr(existing, key, val)
    db.commit()
    return {"mensaje": "Documento actualizado"}


@router.delete("/{doc_id}", response_model=dict)
def eliminar_documento(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    db.delete(doc)
    db.commit()
    return {"mensaje": "Documento eliminado"}


@router.post("/{doc_id}/emisiones", response_model=dict)
def agregar_emision(doc_id: int, emision: schemas.EmisionCreate, db: Session = Depends(get_db)):
    doc = db.query(models.Documento).filter(models.Documento.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    nueva = models.Emision(documento_id=doc_id, **emision.model_dump())
    db.add(nueva)
    if emision.fecha_envio:
        doc.fecha_ultimo_envio = emision.fecha_envio
    if emision.revision:
        doc.revision_actual = emision.revision
    if emision.transmittal_seh:
        doc.acta_trl = emision.transmittal_seh
    db.commit()
    return {"id": nueva.id, "mensaje": "Emisión registrada"}


@router.put("/emisiones/{emision_id}", response_model=dict)
def actualizar_emision(emision_id: int, data: schemas.EmisionUpdate, db: Session = Depends(get_db)):
    emision = db.query(models.Emision).filter(models.Emision.id == emision_id).first()
    if not emision:
        raise HTTPException(status_code=404, detail="Emisión no encontrada")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(emision, key, val)
    if data.fecha_respuesta:
        emision.documento.fecha_respuesta_cliente = data.fecha_respuesta
    if data.observaciones:
        emision.documento.estatus = data.observaciones
    db.commit()
    return {"mensaje": "Emisión actualizada"}
