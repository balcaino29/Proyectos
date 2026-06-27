from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Documento(Base):
    __tablename__ = "documentos"

    id = Column(Integer, primary_key=True, index=True)
    item = Column(Integer, nullable=True)
    tipo_ing = Column(String, nullable=True)
    sala_tag = Column(String, nullable=True)
    codigo_segura = Column(String, nullable=True)
    codigo_inn = Column(String, nullable=True)
    codigo_codelco = Column(String, nullable=True)
    descripcion = Column(Text, nullable=True)
    compromiso_entrega = Column(String, nullable=True)
    criticidad = Column(String, nullable=True)
    deadline_cliente = Column(String, nullable=True)
    comentario_interno = Column(Text, nullable=True)
    disciplina = Column(String, nullable=True)
    revision_actual = Column(String, nullable=True)
    acta_trl = Column(Integer, nullable=True)
    fecha_ultimo_envio = Column(Date, nullable=True)
    fecha_respuesta_cliente = Column(Date, nullable=True)
    estatus = Column(String, nullable=True)

    emisiones = relationship("Emision", back_populates="documento",
                             order_by="Emision.numero", cascade="all, delete-orphan")
    adjuntos = relationship("Adjunto", back_populates="documento",
                            order_by="Adjunto.creado_en", cascade="all, delete-orphan")


class Emision(Base):
    __tablename__ = "emisiones"

    id = Column(Integer, primary_key=True, index=True)
    documento_id = Column(Integer, ForeignKey("documentos.id"), nullable=False)
    numero = Column(Integer, nullable=False)
    revision = Column(String, nullable=True)
    transmittal_seh = Column(Integer, nullable=True)
    fecha_envio = Column(Date, nullable=True)
    transmittal_cliente = Column(String, nullable=True)
    fecha_respuesta = Column(Date, nullable=True)
    tiempo_respuesta = Column(Integer, nullable=True)
    observaciones = Column(Text, nullable=True)

    documento = relationship("Documento", back_populates="emisiones")


class Adjunto(Base):
    __tablename__ = "adjuntos"

    id = Column(Integer, primary_key=True, index=True)
    documento_id = Column(Integer, ForeignKey("documentos.id"), nullable=False)
    nombre_original = Column(String, nullable=False)
    nombre_guardado = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    tamanio = Column(Integer, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    documento = relationship("Documento", back_populates="adjuntos")
