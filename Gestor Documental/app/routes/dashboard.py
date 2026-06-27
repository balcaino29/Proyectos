from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app import models

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Documento.id)).scalar()

    # Conteo por estatus
    por_estatus = (
        db.query(models.Documento.estatus, func.count(models.Documento.id))
        .group_by(models.Documento.estatus)
        .all()
    )
    estatus_map = {e or "Sin estatus": c for e, c in por_estatus}

    # Conteo por disciplina
    por_disciplina = (
        db.query(models.Documento.disciplina, func.count(models.Documento.id))
        .group_by(models.Documento.disciplina)
        .all()
    )
    disciplina_map = {d or "Sin disciplina": c for d, c in por_disciplina}

    # Conteo por criticidad
    por_criticidad = (
        db.query(models.Documento.criticidad, func.count(models.Documento.id))
        .group_by(models.Documento.criticidad)
        .all()
    )
    criticidad_map = {str(c) if c else "Sin criticidad": cnt for c, cnt in por_criticidad}

    # Documentos en revisión (pendientes de respuesta cliente)
    en_revision = db.query(func.count(models.Documento.id)).filter(
        models.Documento.estatus.ilike("%revisión%")
        | models.Documento.estatus.ilike("%revision%")
        | models.Documento.estatus.ilike("%INN%")
    ).scalar()

    # Documentos aprobados
    aprobados = db.query(func.count(models.Documento.id)).filter(
        models.Documento.estatus.ilike("%aprobado%")
    ).scalar()

    # Documentos entregados
    entregados = db.query(func.count(models.Documento.id)).filter(
        models.Documento.estatus.ilike("%entregado%")
    ).scalar()

    # Total emisiones
    total_emisiones = db.query(func.count(models.Emision.id)).scalar()

    # Últimos 5 documentos modificados (con fecha de envío más reciente)
    recientes = (
        db.query(models.Documento)
        .filter(models.Documento.fecha_ultimo_envio.isnot(None))
        .order_by(models.Documento.fecha_ultimo_envio.desc())
        .limit(5)
        .all()
    )

    return {
        "total_documentos": total,
        "en_revision": en_revision,
        "aprobados": aprobados,
        "entregados": entregados,
        "total_emisiones": total_emisiones,
        "por_estatus": estatus_map,
        "por_disciplina": disciplina_map,
        "por_criticidad": criticidad_map,
        "recientes": [
            {
                "id": d.id,
                "descripcion": d.descripcion,
                "codigo_segura": d.codigo_segura,
                "sala_tag": d.sala_tag,
                "estatus": d.estatus,
                "fecha_ultimo_envio": d.fecha_ultimo_envio.isoformat() if d.fecha_ultimo_envio else None,
            }
            for d in recientes
        ],
    }
