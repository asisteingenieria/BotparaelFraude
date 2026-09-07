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

# Errores de tipeo puntuales vistos en exportes reales de CRM (no son un
# alias "oficial" del estado como los de _ESTADOS_EEUU, son faltas de
# ortografía) — se agregan aparte para no ensuciar esa lista. Sin esto no
# calzaban con ningún alias y la carta caía al azar entre TODOS los estados
# en vez de tomar la IP del estado real del cliente. Caso real
# (BBDD_Cartas_7.0, 2026-09-07): "albama" (Alabama, 9 clientes), "tennesse"
# (Tennessee, 6), "nortedecarolina" (North Carolina, 3) y "lussiana"
# (Louisiana, 1).
_ERRORES_TIPEO_CONOCIDOS = {
    "AL": ["albama"],
    "TN": ["tennesse"],
    "NC": ["nortedecarolina"],
    "LA": ["lussiana"],
}
for _abrev_typo, _formas_typo in _ERRORES_TIPEO_CONOCIDOS.items():
    for _forma_typo in _formas_typo:
        _ALIAS_A_ABREVIATURA[_normalizar_estado(_forma_typo)] = _abrev_typo


def _cargar_ips() -> pd.DataFrame:
    global _ips_df
    if _ips_df is None:
        _ips_df = pd.read_excel(IPS_XLSX, dtype=str)
    return _ips_df


class PoolDeIPs:
    """Reparte las IPs de ``ips.xlsx`` SIN repetirlas dentro de un mismo lote
    (una carga de Excel, o el conjunto de titulares que se estén procesando
    juntos), consumiendo el pool de cada estado a medida que se generan los
    Summary.

    ``ips.xlsx`` normalmente trae, para el/los estado(s) presentes en un
    Excel, EXACTAMENTE tantas IPs como titulares (una por titular, mezcla de
    IPv4/IPv6) — pensado para que cada Summary muestre una IP distinta.
    Elegir con ``random.choice`` en cada llamada, cada una con su propio
    ``random.Random()`` (como hacía la ``elegir_ip`` original, todavía
    disponible más abajo para usos sueltos), no respeta eso: con reemplazo,
    ~65% de las cartas de un lote real terminaban compartiendo IP con otra
    (comprobado 2026-09-07 sobre un lote real de 360 titulares). Esta clase
    corrige eso llevando la cuenta de qué filas de ``ips.xlsx`` ya se
    entregaron en el lote actual — se crea UNA sola instancia por lote (ver
    ``src/main.py`` y ``src/auditoria.py``) y se le pide una IP por titular.

    Reglas de reparto por titular, en orden:
    1. Una IP del estado del titular que no se haya usado en este lote.
    2. Si ese estado ya se quedó sin IPs sin usar (o el estado del titular no
       tiene NINGUNA fila en ``ips.xlsx``, ej. Illinois): cualquier IP sin
       usar de otro estado (decisión de Sebastián: siempre debe quedar una
       IP plasmada, aunque no coincida con el estado real del cliente).
    3. Si TODO ``ips.xlsx`` ya se repartió en este lote (lote con más
       titulares que IPs distintas tiene el archivo): se repite una IP,
       priorizando repetir una del mismo estado antes que una de otro
       estado.

    La unicidad se controla por el VALOR de la IP, no por la fila del Excel:
    ``ips.xlsx`` puede traer la misma IP repetida en varias filas del mismo
    estado (caso real detectado 2026-09-08: Tennessee traía la IP
    "172.58.145.102" copiada en 92 de sus 300 filas, dejando solo 208
    valores realmente distintos) — si se controlara por fila, dos titulares
    distintos podrían terminar con el mismo texto de IP en su Summary sin
    que esta clase lo detectara.
    """

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        df = _cargar_ips()
        self._estados = [_clave_estado(e) for e in df["Estado"].tolist()]
        self._ips = df["ip"].tolist()
        self._usadas: set[str] = set()  # valores de IP ya entregados en este lote

    def elegir(self, estado: str) -> str:
        clave = _clave_estado(estado)
        mismo_estado = [i for i, e in enumerate(self._estados) if e == clave]

        def sin_usar(indices: list[int]) -> list[int]:
            return [i for i in indices if self._ips[i] not in self._usadas]

        candidatos = sin_usar(mismo_estado)
        if not candidatos:
            candidatos = sin_usar(range(len(self._ips)))
        if not candidatos:
            candidatos = mismo_estado or list(range(len(self._ips)))

        elegido = self._rng.choice(candidatos)
        ip = self._ips[elegido]
        self._usadas.add(ip)
        return ip


def _clave_estado(estado: str) -> str:
    """Normaliza ``estado`` a su abreviatura ("NC") si se reconoce (viniendo
    en abreviatura, inglés o español — ver ``_ESTADOS_EEUU``); si no se
    reconoce, devuelve el texto ya normalizado tal cual, para poder comparar
    dos valores no reconocidos entre sí (ej. dos filas de ``ips.xlsx`` con el
    mismo estado "raro" siguen agrupándose juntas)."""
    normalizado = _normalizar_estado(estado)
    return _ALIAS_A_ABREVIATURA.get(normalizado, normalizado)


def elegir_ip(estado: str, rng: random.Random | None = None) -> str:
    """Elige una IP de ``ips.xlsx`` para el ``estado`` del cliente, sin tener
    en cuenta qué IPs se hayan entregado antes (cada llamada es independiente
    — sirve para un documento suelto, ej. ``POST /documentos`` en
    ``src/api.py``, fuera de cualquier lote).

    Para generar varios Summary juntos (una carga de Excel) usar
    ``PoolDeIPs`` en su lugar, que sí evita repetir IPs entre titulares del
    mismo lote — ver su docstring.
    """
    return PoolDeIPs(rng).elegir(estado)


def tipo_ip(ip: str) -> str:
    """"v6" si ``ip`` es una dirección IPv6 (trae ":"), si no "v4"."""
    return "v6" if ":" in ip else "v4"


def generar_summary(
    datos: dict, output_path: str | Path, rng: random.Random | None = None,
    *, config_path: str | Path = SUMMARY_CONFIG, pool: PoolDeIPs | None = None,
) -> str:
    """Genera el Summary de ``datos`` en ``output_path``.

    Reutiliza ``firma_nombre``/``firma_estilo_id`` ya presentes en ``datos``
    (los mismos con los que se firmó la carta principal) para que la firma
    del Summary coincida con la del documento. ``config_path`` permite usar
    una variante del config (ver ``templates/config/summary_imagen.json``,
    usado por el módulo "imagen" en ``src/auditoria.py`` para omitir el
    código corto bajo la firma cuando se va a pegar una imagen real ahí).

    ``pool``: instancia de ``PoolDeIPs`` COMPARTIDA entre todas las llamadas
    de un mismo lote (carga de Excel), para que ningún titular del lote
    repita la IP de otro — ver ``src/main.py``/``src/auditoria.py``. Si no se
    pasa (ej. un documento suelto vía API), se usa ``elegir_ip`` como antes,
    sin garantía de unicidad frente a otras llamadas.

    Devuelve la IP plasmada para que el llamador la pueda registrar en
    auditoría — ver ``ip_estado``/``ip_tipo`` en ``src/db.py``.
    """
    from src.pdf_stamper import stamp_pdf

    ip = pool.elegir(datos.get("estado", "")) if pool is not None else elegir_ip(datos.get("estado", ""), rng)
    datos_summary = dict(datos)
    datos_summary["ip_estado"] = ip
    stamp_pdf(SUMMARY_TEMPLATE, output_path, datos_summary, config_path=config_path)
    return ip
