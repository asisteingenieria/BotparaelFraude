"""Genera el "Summary" (certificado de finalización estilo DocuSign) que
acompaña a cada carta: mismo nombre y firma del cliente, más una dirección IP
de prueba tomada de ``templates/ips.xlsx`` según el estado del cliente.

``templates/Summary.pdf`` es un certificado real ya firmado (de ejemplo); el
overlay tapa los datos de esa persona de ejemplo (nombre, teléfono, firma e
IP) y estampa los del cliente actual, igual que se hace con la plantilla de
la carta principal.
"""

from __future__ import annotations

import random
import re
import unicodedata
from pathlib import Path

import pandas as pd

SUMMARY_TEMPLATE = "templates/Summary.pdf"
SUMMARY_CONFIG = "templates/config/summary.json"
IPS_XLSX = Path(__file__).resolve().parent.parent / "templates" / "ips.xlsx"

_ips_df: pd.DataFrame | None = None

# (abreviatura postal, nombre en inglés, nombre en español) de los 50
# estados + DC. Sirve para reconocer el estado del cliente sin importar en
# qué idioma/forma venga (el CRM exporta en inglés, ej. "North Carolina",
# pero ``ips.xlsx`` lo mantiene Sebastián en español, ej. "Carolina del
# Norte" — sin esto, "North Carolina" no calzaba con "Carolina del Norte" y
# el emparejamiento fallaba silenciosamente, cayendo al azar entre TODOS los
# estados del archivo en vez de solo Carolina del Norte).
_ESTADOS_EEUU = [
    ("AL", "Alabama", "Alabama"),
    ("AK", "Alaska", "Alaska"),
    ("AZ", "Arizona", "Arizona"),
    ("AR", "Arkansas", "Arkansas"),
    ("CA", "California", "California"),
    ("CO", "Colorado", "Colorado"),
    ("CT", "Connecticut", "Connecticut"),
    ("DE", "Delaware", "Delaware"),
    ("DC", "District of Columbia", "Distrito de Columbia"),
    ("FL", "Florida", "Florida"),
    ("GA", "Georgia", "Georgia"),
    ("HI", "Hawaii", "Hawai"),
    ("ID", "Idaho", "Idaho"),
    ("IL", "Illinois", "Illinois"),
    ("IN", "Indiana", "Indiana"),
    ("IA", "Iowa", "Iowa"),
    ("KS", "Kansas", "Kansas"),
    ("KY", "Kentucky", "Kentucky"),
    ("LA", "Louisiana", "Luisiana"),
    ("ME", "Maine", "Maine"),
    ("MD", "Maryland", "Maryland"),
    ("MA", "Massachusetts", "Massachusetts"),
    ("MI", "Michigan", "Michigan"),
    ("MN", "Minnesota", "Minnesota"),
    ("MS", "Mississippi", "Misisipi"),
    ("MO", "Missouri", "Misuri"),
    ("MT", "Montana", "Montana"),
    ("NE", "Nebraska", "Nebraska"),
    ("NV", "Nevada", "Nevada"),
    ("NH", "New Hampshire", "Nueva Hampshire"),
    ("NJ", "New Jersey", "Nueva Jersey"),
    ("NM", "New Mexico", "Nuevo Mexico"),
    ("NY", "New York", "Nueva York"),
    ("NC", "North Carolina", "Carolina del Norte"),
    ("ND", "North Dakota", "Dakota del Norte"),
    ("OH", "Ohio", "Ohio"),
    ("OK", "Oklahoma", "Oklahoma"),
    ("OR", "Oregon", "Oregon"),
    ("PA", "Pennsylvania", "Pensilvania"),
    ("RI", "Rhode Island", "Rhode Island"),
    ("SC", "South Carolina", "Carolina del Sur"),
    ("SD", "South Dakota", "Dakota del Sur"),
    ("TN", "Tennessee", "Tennessee"),
    ("TX", "Texas", "Texas"),
    ("UT", "Utah", "Utah"),
    ("VT", "Vermont", "Vermont"),
    ("VA", "Virginia", "Virginia"),
    ("WA", "Washington", "Washington"),
    ("WV", "West Virginia", "Virginia Occidental"),
    ("WI", "Wisconsin", "Wisconsin"),
    ("WY", "Wyoming", "Wyoming"),
]


def _normalizar_estado(texto: str) -> str:
    texto = str(texto or "").lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", texto)


# clave normalizada (abreviatura, nombre inglés o nombre español) -> abreviatura
_ALIAS_A_ABREVIATURA = {}
for _abrev, _en, _es in _ESTADOS_EEUU:
    for _forma in (_abrev, _en, _es):
        _ALIAS_A_ABREVIATURA[_normalizar_estado(_forma)] = _abrev


def _cargar_ips() -> pd.DataFrame:
    global _ips_df
    if _ips_df is None:
        _ips_df = pd.read_excel(IPS_XLSX, dtype=str)
    return _ips_df


def elegir_ip(estado: str, rng: random.Random | None = None) -> str:
    """Elige una IP de ``ips.xlsx`` para el ``estado`` del cliente.

    El emparejamiento reconoce el estado sin importar si viene como
    abreviatura ("NC"), nombre en inglés ("North Carolina") o en español
    ("Carolina del Norte") — ver ``_ESTADOS_EEUU`` — para que un estado que sí
    tiene IPs registradas en ``ips.xlsx`` no caiga en el azar solo por venir
    en un idioma distinto al del archivo.

    Si el estado (ya reconocido o no) no tiene IPs registradas en
    ``ips.xlsx``, se toma una IP al azar de cualquiera de los estados
    disponibles (decisión de Sebastián: siempre debe quedar una IP plasmada,
    aunque no coincida con el estado real del cliente).
    """
    rng = rng or random.Random()
    df = _cargar_ips()
    abreviatura = _ALIAS_A_ABREVIATURA.get(_normalizar_estado(estado))
    if abreviatura is not None:
        abreviaturas_ips = df["Estado"].map(_normalizar_estado).map(_ALIAS_A_ABREVIATURA.get)
        coincidencias = df[abreviaturas_ips == abreviatura]
    else:
        estado_norm = _normalizar_estado(estado)
        coincidencias = df[df["Estado"].map(_normalizar_estado) == estado_norm]
    if coincidencias.empty:
        coincidencias = df
    return rng.choice(coincidencias["ip"].tolist())


def generar_summary(
    datos: dict, output_path: str | Path, rng: random.Random | None = None,
    *, config_path: str | Path = SUMMARY_CONFIG,
) -> None:
    """Genera el Summary de ``datos`` en ``output_path``.

    Reutiliza ``firma_nombre``/``firma_estilo_id`` ya presentes en ``datos``
    (los mismos con los que se firmó la carta principal) para que la firma
    del Summary coincida con la del documento. ``config_path`` permite usar
    una variante del config (ver ``templates/config/summary_imagen.json``,
    usado por el módulo "imagen" en ``src/auditoria.py`` para omitir el
    código corto bajo la firma cuando se va a pegar una imagen real ahí).
    """
    from src.pdf_stamper import stamp_pdf

    datos_summary = dict(datos)
    datos_summary["ip_estado"] = elegir_ip(datos.get("estado", ""), rng)
    stamp_pdf(SUMMARY_TEMPLATE, output_path, datos_summary, config_path=config_path)
