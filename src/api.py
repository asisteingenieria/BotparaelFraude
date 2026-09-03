"""API HTTP del microservicio de firma para FirmaCloud.

Levantar con:
    python -m uvicorn src.api:app --reload --port 8000

Endpoints (documentación interactiva en http://127.0.0.1:8000/docs):
- POST /firmas/opciones: recibe el nombre del cliente y devuelve la galería de
  diseños de firma (PNG en base64) para que el cliente elija.
- POST /documentos: estampa la plantilla con los datos del body y plasma la
  firma del cliente en las casillas de firma. Mientras no hay frontend que
  permita elegir, usa el primer diseño del catálogo salvo que el body traiga
  ``firma_estilo_id``.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.auditoria import router as auditoria_router
from src.firma_generator import SelectorDeEstilos, generar_opciones, get_style
from src.pdf_stamper import stamp_pdf
from src.summary import generar_summary

TEMPLATE_PATH = "templates/Obamacare  B2.pdf"

app = FastAPI(title="Microservicio de firma FirmaCloud", version="2.0")
app.include_router(auditoria_router)
app.mount("/static/img", StaticFiles(directory="static/img"), name="static-img")

# Selector con memoria por nombre (vive lo que viva el proceso): en pruebas
# sin frontend, pedir varias cartas del mismo cliente va rotando el diseño
# para que se vea la variedad del catálogo.
_selector = SelectorDeEstilos()


class Beneficiario(BaseModel):
    nombre: str = ""
    estatus: str = ""


class DatosPersona(BaseModel):
    nombres: str
    apellidos: str
    social: str = ""
    numero_social: str = ""
    estatus_migratorio: str = ""
    estado: str = ""
    direccion: str = ""
    tipo_vivienda: str = ""
    codigo_postal: str = ""
    telefono_principal: str = ""
    telefono_adicional: str = ""
    tipo_ingresos: str = ""
    ingresos_totales: str = ""
    email: str = ""
    aseguradora: str = ""
    categoria_tipo_plan: str = ""
    nombre_plan: str = ""
    prima: str = ""
    valor_cotizacion: str = ""
    deducible: str = ""
    gasto_maximo_bolsillo: str = ""
    fecha_activacion: str = ""
    palabra_seguridad: str = ""
    fecha: str = ""
    agente_nombre: str = ""
    agente_npn: str = ""
    agente_telefono: str = ""
    agente_email: str = ""
    agencia_nombre: str = ""
    agencia_npn: str = ""
    agencia_propietario: str = ""
    agencia_telefono: str = ""
    agencia_email: str = ""
    contacto_nombre: str = ""
    contacto_telefono: str = ""
    contacto_email: str = ""
    beneficiarios: list[Beneficiario] = Field(default_factory=list)
    # --- datos de la firma (para probar desde Postman sin FirmaCloud) ---
    firma_estilo_id: str = ""
    # ID de la firma; vacío → se genera un UUID v4, igual que FirmaCloud
    # (uuidv4() en signatureController al crear la signature_request).
    firma_id: str = ""
    # Fecha/hora de la firma para el encabezado, formato del PDF de ejemplo:
    # "18-12-2025 12:24:52". Vacío → ahora en UTC.
    firma_fecha_hora: str = ""


class NombreFirma(BaseModel):
    nombre: str = Field(min_length=1)


@app.get("/", include_in_schema=False)
def interfaz_principal() -> RedirectResponse:
    return RedirectResponse(url="/auditoria")


@app.post("/firmas/opciones")
def opciones_de_firma(body: NombreFirma) -> dict:
    """Galería de diseños de firma para el nombre dado. Cada opción trae su
    ``estilo_id`` (el que luego se manda en ``firma_estilo_id``) y el preview
    PNG en base64."""
    nombre = body.nombre.strip()
    return {"nombre": nombre, "opciones": generar_opciones(nombre)}


@app.post("/documentos")
def generar_documento(datos: DatosPersona) -> FileResponse:
    data = datos.model_dump()
    data["nombre_completo"] = f"{datos.nombres} {datos.apellidos}".strip()

    # Diseño de firma: el elegido por el cliente o, para las pruebas sin
    # frontend, uno rotado por el selector (mismo nombre → diseño distinto
    # en cada petición, hasta agotar el catálogo).
    estilo_id = datos.firma_estilo_id or _selector.elegir(data["nombre_completo"])
    try:
        get_style(estilo_id)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"firma_estilo_id inválido: {estilo_id!r}")
    data["firma_nombre"] = data["nombre_completo"]
    data["firma_estilo_id"] = estilo_id

    # Rastro de auditoría, replicando el PDF firmado de ejemplo: ID UUID v4
    # (como FirmaCloud), correo del cliente y fecha/hora arriba de la carta.
    firma_id = datos.firma_id or str(uuid.uuid4())
    data["firma_id"] = firma_id
    data["firma_email"] = datos.email
    data["firma_fecha_hora"] = (
        datos.firma_fecha_hora
        or datetime.now(UTC).strftime("%d-%m-%Y %H:%M:%S")
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="bot_obamacare_"))
    nombre_archivo = data["nombre_completo"].replace(" ", "_") or "documento"
    salida = tmp_dir / f"{nombre_archivo}.pdf"

    stamp_pdf(TEMPLATE_PATH, salida, data)
    salida_summary = salida.with_name(f"{salida.stem}_Summary.pdf")
    generar_summary(data, salida_summary)

    # Registro de auditoría en MySQL (origen 'api'). Si la BD no está
    # disponible, el documento igual se entrega — solo se pierde el registro.
    try:
        from src.db import nueva_sesion, registrar_carta
        sesion = nueva_sesion()
        try:
            registrar_carta(
                sesion, firma_id=firma_id,
                nombre_completo=data["nombre_completo"], email=datos.email,
                estilo_id=estilo_id, fecha_hora=data["firma_fecha_hora"],
                pdf_path=salida, summary_pdf_path=salida_summary, origen="api",
            )
            sesion.commit()
        finally:
            sesion.close()
    except Exception as exc:  # pragma: no cover - solo si MySQL está caído
        print(f"[auditoria] No se pudo registrar la carta {firma_id}: {exc}")

    return FileResponse(
        salida, media_type="application/pdf", filename=salida.name,
        headers={"X-Firma-Id": firma_id, "X-Firma-Estilo": estilo_id},
    )
