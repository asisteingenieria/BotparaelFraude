"""Persistencia de auditoría en MySQL (base propia del microservicio).

El microservicio usa su PROPIA base de datos ``bot_firmas`` con el usuario
dedicado ``botcartas`` — separada por completo de la base de FirmaCloud.
Credenciales en ``.env`` (BOT_DB_*), creadas junto con las tablas.

Dos tablas:
- ``cargas``: cada Excel subido (estado, progreso, conteos) — permite seguir
  el avance de un lote de 2000 filas desde la interfaz.
- ``cartas``: cada carta generada, con lo que un auditor necesita revisar:
  UUID de firma, cliente, correo, estilo del diseño, fecha/hora, ruta del
  PDF, tamaño en bytes y hash SHA-256 (integridad: prueba que el archivo no
  cambió después de generarse — mismo criterio que ``document_hash`` en
  FirmaCloud).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _database_url() -> str:
    user = os.environ["BOT_DB_USER"]
    password = os.environ["BOT_DB_PASSWORD"]
    host = os.environ.get("BOT_DB_HOST", "localhost")
    port = os.environ.get("BOT_DB_PORT", "3306")
    name = os.environ.get("BOT_DB_NAME", "bot_firmas")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


engine = create_engine(_database_url(), pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Carga(Base):
    __tablename__ = "cargas"

    id = Column(String(36), primary_key=True)
    archivo = Column(String(255), nullable=False)
    modulo = Column(Enum("original", "otro", "imagen"), nullable=False, default="original")
    total_filas = Column(Integer, nullable=False, default=0)
    filas_ok = Column(Integer, nullable=False, default=0)
    filas_error = Column(Integer, nullable=False, default=0)
    estado = Column(Enum("procesando", "completada", "fallida"), nullable=False,
                    default="procesando")
    error = Column(Text, nullable=True)
    creada_en = Column(DateTime, nullable=False, server_default=func.now())
    finalizada_en = Column(DateTime, nullable=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "archivo": self.archivo,
            "modulo": self.modulo,
            "total_filas": self.total_filas,
            "filas_ok": self.filas_ok,
            "filas_error": self.filas_error,
            "estado": self.estado,
            "error": self.error,
            "creada_en": self.creada_en.isoformat() if self.creada_en else None,
            "finalizada_en": self.finalizada_en.isoformat() if self.finalizada_en else None,
        }


class Carta(Base):
    __tablename__ = "cartas"

    id = Column(String(36), primary_key=True)  # firma_id (UUID v4)
    carga_id = Column(String(36), ForeignKey("cargas.id", ondelete="SET NULL"), nullable=True)
    fila_excel = Column(Integer, nullable=True)
    nombre_completo = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False, default="")
    firma_estilo_id = Column(String(50), nullable=False)
    firma_fecha_hora = Column(String(30), nullable=False)
    pdf_path = Column(String(500), nullable=False)
    pdf_bytes = Column(BigInteger, nullable=False)
    pdf_sha256 = Column(String(64), nullable=False)
    summary_pdf_path = Column(String(500), nullable=True)
    origen = Column(Enum("excel", "api"), nullable=False, default="excel")
    modulo = Column(Enum("original", "otro", "imagen"), nullable=False, default="original")
    fecha_pixelada = Column(Boolean, nullable=False, default=False)
    creada_en = Column(DateTime, nullable=False, server_default=func.now())

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "carga_id": self.carga_id,
            "fila_excel": self.fila_excel,
            "nombre_completo": self.nombre_completo,
            "email": self.email,
            "firma_estilo_id": self.firma_estilo_id,
            "firma_fecha_hora": self.firma_fecha_hora,
            "pdf_path": self.pdf_path,
            "pdf_bytes": self.pdf_bytes,
            "pdf_sha256": self.pdf_sha256,
            "tiene_summary": bool(self.summary_pdf_path),
            "origen": self.origen,
            "modulo": self.modulo,
            "fecha_pixelada": bool(self.fecha_pixelada),
            "creada_en": self.creada_en.isoformat() if self.creada_en else None,
        }


def nueva_sesion() -> Session:
    return SessionLocal()


def registrar_carta(sesion: Session, *, firma_id: str, nombre_completo: str, email: str,
                    estilo_id: str, fecha_hora: str, pdf_path: Path,
                    carga_id: str | None = None, fila_excel: int | None = None,
                    origen: str = "excel", summary_pdf_path: Path | None = None,
                    modulo: str = "original", fecha_pixelada: bool = False) -> Carta:
    """Inserta el registro de auditoría de una carta ya generada en disco."""
    import hashlib

    contenido = Path(pdf_path).read_bytes()
    carta = Carta(
        id=firma_id,
        carga_id=carga_id,
        fila_excel=fila_excel,
        nombre_completo=nombre_completo,
        email=email,
        firma_estilo_id=estilo_id,
        firma_fecha_hora=fecha_hora,
        pdf_path=str(pdf_path),
        pdf_bytes=len(contenido),
        pdf_sha256=hashlib.sha256(contenido).hexdigest(),
        summary_pdf_path=str(summary_pdf_path) if summary_pdf_path else None,
        origen=origen,
        modulo=modulo,
        fecha_pixelada=fecha_pixelada,
    )
    sesion.add(carta)
    return carta


def finalizar_carga(sesion: Session, carga: Carga, estado: str, error: str | None = None) -> None:
    carga.estado = estado
    carga.error = error
    carga.finalizada_en = datetime.now()
    sesion.commit()
