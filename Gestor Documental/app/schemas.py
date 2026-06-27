from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class EmisionBase(BaseModel):
    numero: int
    revision: Optional[str] = None
    transmittal_seh: Optional[int] = None
    fecha_envio: Optional[date] = None
    transmittal_cliente: Optional[str] = None
    fecha_respuesta: Optional[date] = None
    tiempo_respuesta: Optional[int] = None
    observaciones: Optional[str] = None


class EmisionCreate(EmisionBase):
    pass


class EmisionUpdate(BaseModel):
    revision: Optional[str] = None
    transmittal_seh: Optional[int] = None
    fecha_envio: Optional[date] = None
    transmittal_cliente: Optional[str] = None
    fecha_respuesta: Optional[date] = None
    tiempo_respuesta: Optional[int] = None
    observaciones: Optional[str] = None


class Emision(EmisionBase):
    id: int
    documento_id: int

    class Config:
        from_attributes = True


class DocumentoBase(BaseModel):
    item: Optional[int] = None
    tipo_ing: Optional[str] = None
    sala_tag: Optional[str] = None
    codigo_segura: Optional[str] = None
    codigo_inn: Optional[str] = None
    codigo_codelco: Optional[str] = None
    descripcion: Optional[str] = None
    compromiso_entrega: Optional[str] = None
    criticidad: Optional[str] = None
    deadline_cliente: Optional[str] = None
    comentario_interno: Optional[str] = None
    disciplina: Optional[str] = None
    revision_actual: Optional[str] = None
    acta_trl: Optional[int] = None
    fecha_ultimo_envio: Optional[date] = None
    fecha_respuesta_cliente: Optional[date] = None
    estatus: Optional[str] = None


class DocumentoCreate(DocumentoBase):
    pass


class DocumentoUpdate(DocumentoBase):
    pass


class Documento(DocumentoBase):
    id: int
    emisiones: List[Emision] = []

    class Config:
        from_attributes = True


class DocumentoLista(DocumentoBase):
    id: int
    num_emisiones: int = 0

    class Config:
        from_attributes = True
