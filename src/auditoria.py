"""Módulo de auditoría: carga masiva de Excel + consulta de cartas generadas.

Flujo pensado para auditoría del módulo de firmas: se sube un Excel (p. ej.
2000 filas), el bot genera todas las cartas firmadas en background y registra
cada una en MySQL (``bot_firmas``). El auditor luego lista las cartas, pide
una muestra aleatoria y abre cualquier PDF para revisar tamaño, diseño de la
firma y cómo se plasmó la información.

Interfaz web en ``GET /auditoria`` (página estática servida por FastAPI).
"""

from __future__ import annotations

import random
import re
import shutil
import tempfile
import traceback
import unicodedata
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from starlette.background import BackgroundTask

from src.db import Carga, Carta, finalizar_carga, nueva_sesion, registrar_carta
from src.firma_generator import SelectorDeEstilos
from src.firma_imagen import estampar_firma_imagen
from src.ingesta import leer_excel
from src.main import _nombre_archivo
from src.pdf_flatten import aplanar_campo, aplanar_pagina
from src.pdf_stamper import load_template_config, stamp_pdf
from src.summary import PoolDeIPs, generar_summary

router = APIRouter()

TEMPLATE_PATH = "templates/Obamacare  B2.pdf"
CARGAS_DIR = Path("output/cargas")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Módulo "otro": misma funcionalidad (mismos campos, misma firma), pero sobre
# la plantilla "Obamacare  B2 OtroM.pdf" y con dos pasos extra al final —
# ver ``src/pdf_flatten.py``:
# 1. En la página de consentimiento (índice 1, "página 2") se aplana SOLO el
#    campo "Fecha:" del bloque de contacto principal del hogar a un
#    pantallazo — el resto de esa página (nombre/teléfono/correo/firma del
#    bloque, y todo lo demás) queda vectorial, intacto.
# 2. La página de datos del cliente completa (la azul, 574x1020 — índice 2,
#    "página 3") se convierte en pantallazo entera.
# La última página (índice 3, "Firma Cliente:") queda vectorial, sin tocar.
# No afecta el flujo "original" en absoluto.
OTRO_TEMPLATE_PATH = "templates/Obamacare  B2 OtroM.pdf"
OTRO_CONFIG_PATH = "templates/config/obamacare_b2_otro.json"
OTRO_PAGINA_DATOS = 2

# Módulo "imagen": misma funcionalidad que el original, pero en vez de
# DIBUJAR una firma sintética (src/firma_generator) se PEGA una imagen de una
# firma real ya existente (src/firma_imagen) — el archivo se busca en
# IMAGEN_FIRMAS_DIR por el nombre del titular (nombre_completo de la fila del
# Excel, comparación insensible a mayúsculas/acentos/espacios). Si no se
# encuentra la imagen, la casilla "Firma Cliente:" queda vacía (no falla la
# carta) y el estilo registrado en BD queda como "imagen:sin_encontrar" para
# poder auditar cuáles faltaron.
IMAGEN_TEMPLATE_PATH = "templates/Obamacare sin firma.pdf"
IMAGEN_CONFIG_PATH = "templates/config/obamacare_sin_firma.json"
IMAGEN_SUMMARY_CONFIG_PATH = "templates/config/summary_imagen.json"
IMAGEN_FIRMAS_DIR = Path("firmas_reales")

MODULOS_VALIDOS = {"original", "otro", "imagen"}

# Pedido de Sebastián: dentro del módulo "otro", el pantallazo del campo
# "Fecha:" (paso 1 de arriba) no se aplica a TODAS las cartas del lote, solo
# a una porción — para poder comparar ambas variantes en la misma carga. El
# pantallazo de la página de datos completa (paso 2) siempre se aplica.
OTRO_PROB_FECHA_PANTALLAZO = 0.3

_otro_config = load_template_config(OTRO_CONFIG_PATH)
_CAMPO_FECHA_CONTACTO = next(
    f for f in _otro_config["textFields"] if f["id"] == "fecha_consentimiento"
)

_imagen_config = load_template_config(IMAGEN_CONFIG_PATH)
_CAMPO_FIRMA_IMAGEN = _imagen_config["signatureFields"][0]

_imagen_summary_config = load_template_config(IMAGEN_SUMMARY_CONFIG_PATH)
_CAMPO_FIRMA_IMAGEN_SUMMARY = _imagen_summary_config["signatureFields"][0]


def _normalizar_nombre_archivo(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sin_acentos.lower())


def _buscar_imagen_firma(nombre_completo: str) -> Path | None:
    """Busca en ``IMAGEN_FIRMAS_DIR`` el archivo cuyo nombre coincide con
    ``nombre_completo`` (ignorando mayúsculas, acentos, espacios/guiones y la
    extensión). Devuelve ``None`` si la carpeta no existe o no hay match."""
    if not IMAGEN_FIRMAS_DIR.is_dir():
        return None
    objetivo = _normalizar_nombre_archivo(nombre_completo)
    for archivo in IMAGEN_FIRMAS_DIR.iterdir():
        if archivo.is_file() and archivo.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            if _normalizar_nombre_archivo(archivo.stem) == objetivo:
                return archivo
    return None


def _procesar_carga(carga_id: str, excel_path: Path, modulo: str = "original") -> None:
    """Genera y registra todas las cartas de un Excel (corre en background)."""
    sesion = nueva_sesion()
    carga = sesion.get(Carga, carga_id)
    try:
        resultado = leer_excel(str(excel_path))
        carga.total_filas = len(resultado.registros) + len(resultado.invalidas)
        carga.filas_error = len(resultado.invalidas)
        sesion.commit()

        selector = SelectorDeEstilos()  # nombre repetido -> diseño distinto
        pool_ips = PoolDeIPs()  # una IP por titular, sin repetir dentro de esta carga
        destino = CARGAS_DIR / carga_id
        destino.mkdir(parents=True, exist_ok=True)
        usados: set[str] = set()

        for i, datos in enumerate(resultado.registros, start=1):
            try:
                firma_id = str(uuid.uuid4())
                fecha_digitacion = datos.get("fecha_digitacion", "")
                if fecha_digitacion:
                    hora_aleatoria = (
                        f"{random.randint(9, 21):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
                    )
                    fecha_hora = f"{fecha_digitacion} {hora_aleatoria}"
                else:
                    fecha_hora = datetime.now(UTC).strftime("%m-%d-%Y %H:%M:%S")
                if modulo == "imagen":
                    datos["firma_nombre"] = ""  # casilla vacía: no se dibuja firma sintética
                    datos["firma_estilo_id"] = ""
                else:
                    datos["firma_nombre"] = datos["nombre_completo"]
                    datos["firma_estilo_id"] = selector.elegir(datos["nombre_completo"])
                datos["firma_id"] = firma_id
                datos["firma_email"] = datos.get("email", "")
                datos["firma_fecha_hora"] = fecha_hora

                salida = destino / _nombre_archivo(datos, usados)
                fecha_pixelada = False
                imagen_firma = None
                if modulo == "imagen":
                    temporal = salida.with_name(f"{salida.stem}__vector.pdf")
                    stamp_pdf(IMAGEN_TEMPLATE_PATH, temporal, datos, config_path=IMAGEN_CONFIG_PATH)
                    imagen_firma = _buscar_imagen_firma(datos["nombre_completo"])
                    if imagen_firma:
                        estampar_firma_imagen(
                            temporal, salida, imagen_firma,
                            page_index=_CAMPO_FIRMA_IMAGEN["page"],
                            x=_CAMPO_FIRMA_IMAGEN["x"], y=_CAMPO_FIRMA_IMAGEN["y"],
                            width=_CAMPO_FIRMA_IMAGEN["width"], height=_CAMPO_FIRMA_IMAGEN["height"],
                        )
                        temporal.unlink(missing_ok=True)
                        datos["firma_estilo_id"] = f"imagen:{imagen_firma.stem}"[:50]
                    else:
                        temporal.replace(salida)
                        datos["firma_estilo_id"] = "imagen:sin_encontrar"
                elif modulo == "otro":
                    temporal = salida.with_name(f"{salida.stem}__vector.pdf")
                    temporal_campo = salida.with_name(f"{salida.stem}__campo.pdf")
                    stamp_pdf(OTRO_TEMPLATE_PATH, temporal, datos, config_path=OTRO_CONFIG_PATH)

                    origen_pagina = temporal
                    if random.random() < OTRO_PROB_FECHA_PANTALLAZO:
                        aplano_fecha = aplanar_campo(
                            temporal, temporal_campo,
                            page_index=_CAMPO_FECHA_CONTACTO["page"],
                            x=_CAMPO_FECHA_CONTACTO["x"], y=_CAMPO_FECHA_CONTACTO["y"],
                        )
                        if aplano_fecha:
                            origen_pagina = temporal_campo
                            fecha_pixelada = True

                    aplanar_pagina(origen_pagina, salida, page_index=OTRO_PAGINA_DATOS)
                    temporal.unlink(missing_ok=True)
                    temporal_campo.unlink(missing_ok=True)
                else:
                    stamp_pdf(TEMPLATE_PATH, salida, datos)
                salida_summary = salida.with_name(f"{salida.stem}_Summary.pdf")
                if modulo == "imagen":
                    ip_estado = generar_summary(
                        datos, salida_summary, config_path=IMAGEN_SUMMARY_CONFIG_PATH, pool=pool_ips,
                    )
                    if imagen_firma:
                        temporal_summary = salida_summary.with_name(f"{salida_summary.stem}__vector.pdf")
                        salida_summary.replace(temporal_summary)
                        estampar_firma_imagen(
                            temporal_summary, salida_summary, imagen_firma,
                            page_index=_CAMPO_FIRMA_IMAGEN_SUMMARY["page"],
                            x=_CAMPO_FIRMA_IMAGEN_SUMMARY["x"], y=_CAMPO_FIRMA_IMAGEN_SUMMARY["y"],
                            width=_CAMPO_FIRMA_IMAGEN_SUMMARY["width"], height=_CAMPO_FIRMA_IMAGEN_SUMMARY["height"],
                        )
                        temporal_summary.unlink(missing_ok=True)
                else:
                    ip_estado = generar_summary(datos, salida_summary, pool=pool_ips)

                registrar_carta(
                    sesion, firma_id=firma_id,
                    nombre_completo=datos["nombre_completo"],
                    email=datos.get("email", ""),
                    estilo_id=datos["firma_estilo_id"],
                    fecha_hora=fecha_hora, pdf_path=salida,
                    summary_pdf_path=salida_summary,
                    carga_id=carga_id, fila_excel=i, origen="excel",
                    modulo=modulo, fecha_pixelada=fecha_pixelada,
                    ip_estado=ip_estado,
                )
                carga.filas_ok += 1
            except Exception:
                carga.filas_error += 1
                traceback.print_exc()
            if i % 10 == 0:
                sesion.commit()  # progreso visible desde la interfaz
        finalizar_carga(sesion, carga, "completada")
    except Exception as exc:
        traceback.print_exc()
        finalizar_carga(sesion, carga, "fallida", error=str(exc))
    finally:
        sesion.close()


@router.get("/auditoria")
def interfaz_auditoria() -> FileResponse:
    return FileResponse(STATIC_DIR / "auditoria.html", media_type="text/html")


@router.get("/firmas-reales")
def listar_firmas_reales() -> list[dict]:
    """Imágenes ya cargadas en ``IMAGEN_FIRMAS_DIR`` para el módulo "imagen"
    (una por titular, nombre de archivo = nombre_completo del Excel)."""
    if not IMAGEN_FIRMAS_DIR.is_dir():
        return []
    archivos = sorted(
        (a for a in IMAGEN_FIRMAS_DIR.iterdir()
         if a.is_file() and a.suffix.lower() in {".png", ".jpg", ".jpeg"}),
        key=lambda a: a.name.lower(),
    )
    return [{"nombre": a.name, "bytes": a.stat().st_size} for a in archivos]


@router.post("/firmas-reales")
async def subir_firmas_reales(archivos: list[UploadFile] = File(...)) -> dict:
    """Sube una o varias imágenes de firma real para el módulo "imagen".

    Cada imagen se guarda tal cual con su nombre de archivo original (sin
    ruta, para evitar path traversal) — ``_buscar_imagen_firma`` matchea ese
    nombre contra ``nombre_completo`` del Excel, así que el nombre del
    archivo debe corresponder al titular (ej. "Juan Sebastian Acosta.png")."""
    IMAGEN_FIRMAS_DIR.mkdir(parents=True, exist_ok=True)
    guardados = []
    for archivo in archivos:
        nombre = Path(archivo.filename or "").name
        if not nombre.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        (IMAGEN_FIRMAS_DIR / nombre).write_bytes(await archivo.read())
        guardados.append(nombre)
    return {"guardados": guardados}


@router.delete("/firmas-reales/{nombre}")
def borrar_firma_real(nombre: str) -> dict:
    destino = IMAGEN_FIRMAS_DIR / Path(nombre).name
    if not destino.is_file():
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    destino.unlink()
    return {"borrado": destino.name}


@router.post("/cargas")
async def subir_carga(
    archivo: UploadFile, tasks: BackgroundTasks, modulo: str = Form("original"),
) -> dict:
    """Sube un Excel y arranca la generación de cartas en background.

    ``modulo``: "original" (plantilla ``Obamacare  B2.pdf``, como siempre),
    "otro" (plantilla ``Obamacare  B2 OtroM.pdf`` + pantallazo de la página
    de la firma) o "imagen" (plantilla ``Obamacare sin firma.pdf`` con una
    imagen de firma real pegada en vez de una firma sintética — ver
    ``_procesar_carga``).
    """
    if not (archivo.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=422, detail="El archivo debe ser un Excel (.xlsx)")
    if modulo not in MODULOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"modulo debe ser uno de {sorted(MODULOS_VALIDOS)}")

    carga_id = str(uuid.uuid4())
    destino = CARGAS_DIR / carga_id
    destino.mkdir(parents=True, exist_ok=True)
    excel_path = destino / "origen.xlsx"
    excel_path.write_bytes(await archivo.read())

    sesion = nueva_sesion()
    carga = Carga(id=carga_id, archivo=archivo.filename, modulo=modulo)
    sesion.add(carga)
    sesion.commit()
    sesion.close()

    tasks.add_task(_procesar_carga, carga_id, excel_path, modulo)
    return {"carga_id": carga_id, "estado": "procesando"}


@router.get("/cargas")
def listar_cargas() -> list[dict]:
    sesion = nueva_sesion()
    try:
        cargas = sesion.execute(
            select(Carga).order_by(Carga.creada_en.desc()).limit(50)
        ).scalars().all()
        return [c.as_dict() for c in cargas]
    finally:
        sesion.close()


@router.get("/cargas/{carga_id}")
def detalle_carga(carga_id: str) -> dict:
    sesion = nueva_sesion()
    try:
        carga = sesion.get(Carga, carga_id)
        if not carga:
            raise HTTPException(status_code=404, detail="Carga no encontrada")
        return carga.as_dict()
    finally:
        sesion.close()


@router.delete("/cargas/{carga_id}")
def eliminar_carga(carga_id: str) -> dict:
    """Borra una carga completa para liberar espacio: sus cartas (registro en
    BD, incluye el summary de cada una) y la carga misma, más TODOS los PDFs
    en disco de ``output/cargas/<carga_id>/`` (cartas y summaries). Acción
    irreversible — no hay papelera ni respaldo."""
    sesion = nueva_sesion()
    try:
        carga = sesion.get(Carga, carga_id)
        if not carga:
            raise HTTPException(status_code=404, detail="Carga no encontrada")
        cartas_borradas = sesion.execute(
            select(func.count()).select_from(Carta).where(Carta.carga_id == carga_id)
        ).scalar_one()
        sesion.execute(delete(Carta).where(Carta.carga_id == carga_id))
        sesion.delete(carga)
        sesion.commit()
    finally:
        sesion.close()

    destino = CARGAS_DIR / carga_id
    if destino.exists():
        shutil.rmtree(destino)

    return {"carga_id": carga_id, "cartas_borradas": cartas_borradas}


@router.get("/cargas/{carga_id}/zip")
def descargar_zip(carga_id: str) -> FileResponse:
    """Empaqueta todos los PDF ya generados de una carga en un .zip."""
    sesion = nueva_sesion()
    try:
        carga = sesion.get(Carga, carga_id)
        if not carga:
            raise HTTPException(status_code=404, detail="Carga no encontrada")
    finally:
        sesion.close()

    origen = CARGAS_DIR / carga_id
    pdfs = sorted(origen.glob("*.pdf")) if origen.exists() else []
    if not pdfs:
        raise HTTPException(status_code=410, detail="No hay PDF generados para esta carga")

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdfs:
            zf.write(pdf, arcname=pdf.name)

    base = re.sub(r"[^A-Za-z0-9 _-]", "", Path(carga.archivo or carga_id).stem).strip().replace(" ", "_")
    nombre_zip = f"{base or carga_id}_cartas.zip"

    return FileResponse(
        tmp.name, media_type="application/zip", filename=nombre_zip,
        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)),
    )


@router.get("/cartas")
def listar_cartas(
    carga_id: str = "", q: str = "", fecha_pixelada: str = "", ip_tipo: str = "",
    pagina: int = Query(1, ge=1), por_pagina: int = Query(25, ge=1, le=200),
) -> dict:
    """``fecha_pixelada``: "" (todas), "si" o "no" — filtra por si esa carta
    salió con el pantallazo del campo Fecha (módulo "otro", ver
    ``OTRO_PROB_FECHA_PANTALLAZO``). Las del módulo "original" siempre
    quedan fuera de "si" (nunca tienen ese pantallazo).

    ``ip_tipo``: "" (todas), "v4" o "v6" — filtra por el tipo de IP plasmada
    en el Summary de esa carta (ver ``elegir_ip``/``tipo_ip`` en
    ``src/summary.py``)."""
    sesion = nueva_sesion()
    try:
        filtro = []
        if carga_id:
            filtro.append(Carta.carga_id == carga_id)
        if q:
            filtro.append(Carta.nombre_completo.like(f"%{q}%") | Carta.email.like(f"%{q}%"))
        if fecha_pixelada == "si":
            filtro.append(Carta.fecha_pixelada.is_(True))
        elif fecha_pixelada == "no":
            filtro.append(Carta.fecha_pixelada.is_(False))
        if ip_tipo in ("v4", "v6"):
            filtro.append(Carta.ip_tipo == ip_tipo)
        total = sesion.execute(
            select(func.count()).select_from(Carta).where(*filtro)
        ).scalar_one()
        cartas = sesion.execute(
            select(Carta).where(*filtro).order_by(Carta.creada_en.desc(), Carta.fila_excel)
            .offset((pagina - 1) * por_pagina).limit(por_pagina)
        ).scalars().all()
        return {"total": total, "pagina": pagina, "por_pagina": por_pagina,
                "cartas": [c.as_dict() for c in cartas]}
    finally:
        sesion.close()


@router.get("/cartas/muestra")
def muestra_aleatoria(n: int = Query(10, ge=1, le=200), carga_id: str = "",
                      fecha_pixelada: str = "", ip_tipo: str = "") -> dict:
    """Muestra aleatoria de cartas para auditar (ORDER BY RAND())."""
    sesion = nueva_sesion()
    try:
        filtro = [Carta.carga_id == carga_id] if carga_id else []
        if fecha_pixelada == "si":
            filtro.append(Carta.fecha_pixelada.is_(True))
        elif fecha_pixelada == "no":
            filtro.append(Carta.fecha_pixelada.is_(False))
        if ip_tipo in ("v4", "v6"):
            filtro.append(Carta.ip_tipo == ip_tipo)
        cartas = sesion.execute(
            select(Carta).where(*filtro).order_by(func.rand()).limit(n)
        ).scalars().all()
        return {"n": len(cartas), "cartas": [c.as_dict() for c in cartas]}
    finally:
        sesion.close()


@router.get("/cartas/{carta_id}/pdf")
def pdf_de_carta(carta_id: str) -> FileResponse:
    sesion = nueva_sesion()
    try:
        carta = sesion.get(Carta, carta_id)
    finally:
        sesion.close()
    if not carta:
        raise HTTPException(status_code=404, detail="Carta no encontrada")
    path = Path(carta.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="El PDF ya no está en disco")
    return FileResponse(path, media_type="application/pdf",
                        content_disposition_type="inline", filename=path.name)


@router.get("/cartas/{carta_id}/summary")
def summary_de_carta(carta_id: str) -> FileResponse:
    sesion = nueva_sesion()
    try:
        carta = sesion.get(Carta, carta_id)
    finally:
        sesion.close()
    if not carta:
        raise HTTPException(status_code=404, detail="Carta no encontrada")
    if not carta.summary_pdf_path:
        raise HTTPException(status_code=404, detail="Esta carta no tiene Summary generado")
    path = Path(carta.summary_pdf_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="El Summary ya no está en disco")
    return FileResponse(path, media_type="application/pdf",
                        content_disposition_type="inline", filename=path.name)
