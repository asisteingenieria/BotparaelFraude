"""Lee el Excel de entrada y lo normaliza a una lista de dicts listos para
``pdf_stamper.stamp_pdf``.

El emparejamiento de encabezados es tolerante a acentos, mayúsculas y
espacios ("Número Social", "numero social", "NUMEROSOCIAL" son equivalentes).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import openpyxl
import pandas as pd
from openpyxl.styles.numbers import BUILTIN_FORMATS

_FORMATOS_FABRICA = set(BUILTIN_FORMATS.values())

MAX_BENEFICIARIOS = 6

REQUIRED_KEYS = ("nombres", "apellidos")

# encabezado normalizado -> clave interna
_COLUMN_MAP = {
    "nombres": "nombres",
    "apellidos": "apellidos",
    "social": "social",
    "numerosocial": "numero_social",
    "estatusmigratorio": "estatus_migratorio",
    "estado": "estado",
    "direccion": "direccion",
    "tipovivienda": "tipo_vivienda",
    "codigopostal": "codigo_postal",
    "telefonoprincipal": "telefono_principal",
    "telefonoadicional": "telefono_adicional",
    "tipodeingresos": "tipo_ingresos",
    "ingresostotales": "ingresos_totales",
    "aseguradora": "aseguradora",
    "nombreaseguradora": "aseguradora",
    "categoriaytipodeplan": "categoria_tipo_plan",
    "nombredeplan": "nombre_plan",
    "prima": "prima",
    "valorcotizacion": "valor_cotizacion",
    "deducible": "deducible",
    "gastomaximobolsillo": "gasto_maximo_bolsillo",
    "fechadeactivacion": "fecha_activacion",
    "palabradeseguridad": "palabra_seguridad",
    "email": "email",
    "correo": "email",
    "fecha": "fecha",
    "agentenombre": "agente_nombre",
    "agentenpn": "agente_npn",
    "numerodeagenteproductornacional": "agente_npn",
    "agentetelefono": "agente_telefono",
    "agenteemail": "agente_email",
    "agencianombre": "agencia_nombre",
    "agencianpn": "agencia_npn",
    "agenciapropietario": "agencia_propietario",
    "propietariodelaagencia": "agencia_propietario",
    "agenciatelefono": "agencia_telefono",
    "agenciaemail": "agencia_email",
    "contactonombre": "contacto_nombre",
    "contactotelefono": "contacto_telefono",
    "contactoemail": "contacto_email",
    # Alias vistos en exportes de CRM (Prueba1botCartaObama.xlsx)
    "nombresyapellidos": "_nombre_completo_split",
    "correoelectronicocliente": "email",
    "numeroprincipal": "telefono_principal",
    "fechaactivacion": "fecha_activacion",
    "valorcotizaciondividir48": "valor_cotizacion",
    "plan": "categoria_tipo_plan",
    "fecharevocacion": "fecha",
    "gastomax": "gasto_maximo_bolsillo",
    "npn": "agente_nombre",
    "numero": "agente_npn",
    "numero1": "agente_telefono",
    "correonpn": "agente_email",
    "tiposolicitud": "tipo_solicitud",
    "parentesco": "parentesco",
    "fechadigitacion": "fecha_digitacion",
    # Alias vistos en "nuevo excel.xlsx" (variante distinta del mismo CRM)
    "numeronpn": "agente_npn",
    "numerodetelefono": "agente_telefono",
    "correoelectronicodelcliente": "email",
    "fechadedigitacion": "fecha_digitacion",
    "nuemerosocial": "numero_social",
    "etatusmigratorio": "estatus_migratorio",
    "nombreplan": "nombre_plan",
    "numeroprincipal1": "telefono_adicional",
    # Alias vistos en "BBDD_MOLINA.xlsx" (reporte de agente/bróker)
    "qifirstname": "nombres",
    "qilastname": "apellidos",
    "agentbrokernpn": "agente_npn",
    "phonenumber": "telefono_principal",
    "residentialaddressline1": "direccion",
    "residentialaddressline2": "tipo_vivienda",
    "residentialstatecode": "estado",
    "residentialzipcode": "codigo_postal",
    # Alias vistos en "BASE OSCAR 1 - 78.xlsx" (variante distinta del mismo CRM)
    "nombre": "nombres",
    "apellido": "apellidos",
    "numeroadicional": "telefono_adicional",
    # Alias vistos en otra exportación del mismo CRM (headers "Prima Mensual",
    # "Correo Electrónico", "Tipo de Vivienda", "Gasto Máximo") — sin estos,
    # esas columnas quedaban sin mapear y el campo salía vacío para TODAS las
    # filas (no solo cuando el valor era 0; "primamensual" no calzaba con el
    # alias "prima" existente por la palabra de más).
    "primamensual": "prima",
    "correoelectronico": "email",
    "tipodevivienda": "tipo_vivienda",
    "gastomaximo": "gasto_maximo_bolsillo",
    "tiposocial": "social",
}
for _i in range(1, MAX_BENEFICIARIOS + 1):
    _COLUMN_MAP[f"beneficiario{_i}nombre"] = f"beneficiario_{_i}_nombre"
    _COLUMN_MAP[f"beneficiario{_i}estatus"] = f"beneficiario_{_i}_estatus"
    _COLUMN_MAP[f"beneficiario{_i}estatusmigratorio"] = f"beneficiario_{_i}_estatus"


def _normalize(header: str) -> str:
    header = str(header).strip().lower()
    header = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode("ascii")
    header = re.sub(r"[^a-z0-9]", "", header)
    return header


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _formatear_fecha_mdy(valor: str, separador: str = "/") -> str:
    """Normaliza una fecha a mes-dia-año / mes/dia/año (formato EE.UU.).

    Tolera timestamps de Excel ("2026-01-01 00:00:00") y fechas ya en
    texto; si no logra interpretarla, la deja tal cual llegó.
    """
    if not valor:
        return valor
    ts = pd.to_datetime(valor, errors="coerce", dayfirst=False)
    if pd.isna(ts):
        return valor
    return ts.strftime(f"%m{separador}%d{separador}%Y")


def _formatear_fecha_ymd(valor: str, separador: str = "-") -> str:
    """Normaliza una fecha a año-mes-dia (ej. "2026-01-01")."""
    if not valor:
        return valor
    ts = pd.to_datetime(valor, errors="coerce", dayfirst=False)
    if pd.isna(ts):
        return valor
    return ts.strftime(f"%Y{separador}%m{separador}%d")


def _orden_fecha_celda(number_format: str) -> str | None:
    """Determina el orden día/mes de una celda de fecha real a partir de su
    ``number_format``, pero SOLO cuando ese formato es personalizado (no uno
    "de fábrica" de Excel): los formatos de fábrica (``numFmtId`` built-in,
    ej. "mm-dd-yy", id 14) se muestran según la configuración regional de
    quien abre el archivo — el código guardado no refleja lo que esa persona
    ve en pantalla, ya comprobado con el caso de Sebastián (2026-08-27). Un
    formato PERSONALIZADO (numFmtId >= 164, ej. "m\\-d\\-yyyy") es distinto:
    Excel lo renderiza literal, igual en cualquier equipo, así que el orden
    d/m que aparece en el código sí es confiable — caso real: "Bse_General.xlsx"
    (2026-09-01) trae ``FECHA DE DIGITACION`` con formato personalizado
    "m\\-d\\-yyyy" (mes primero) y Excel efectivamente lo muestra "2-6-2026"
    para el 6 de febrero de 2026; con la regla día-primero salía invertido
    ("06-02-2026" en vez de coincidir con lo que ese Excel muestra).

    Devuelve ``"dmy"``/``"mdy"``, o ``None`` si no hay información confiable
    (formato de fábrica, vacío, o sin token d/m reconocible) — en ese caso
    ``_fecha_tal_cual`` cae al default día/mes/año."""
    if not number_format or number_format in _FORMATOS_FABRICA:
        return None
    limpio = number_format.lower()
    pos_d = limpio.find("d")
    pos_m = limpio.find("m")
    if pos_d == -1 or pos_m == -1:
        return None
    return "dmy" if pos_d < pos_m else "mdy"


def _fecha_tal_cual(celda) -> str:
    """Texto de una celda de Excel para ``fecha_digitacion``: una celda de
    texto plano se devuelve literal, sin tocarla. Una celda de fecha REAL se
    escribe con "/" en el orden que indique ``_orden_fecha_celda`` (mes o día
    primero según el formato PERSONALIZADO de esa celda); si no hay formato
    personalizado confiable (formato de fábrica de Excel, ej. "mm-dd-yy"),
    el default es día/mes/año — confirmado con ejemplo concreto (2026-08-27):
    Sebastián escribe "12/09/2025" en su Excel (formato de fábrica, celda
    interpretada día/mes por su configuración regional al teclear) y quiere
    ver "12-09-2025" en la carta, no "09-12-2025"."""
    valor = celda.value
    if valor is None:
        return ""
    if hasattr(valor, "strftime"):
        orden = _orden_fecha_celda(celda.number_format)
        if orden == "mdy":
            return valor.strftime("%m/%d/%Y")
        return valor.strftime("%d/%m/%Y")
    return str(valor).strip()


@dataclass
class FilaInvalida:
    numero_fila: int
    motivo: str


@dataclass
class ResultadoIngesta:
    registros: list[dict] = field(default_factory=list)
    invalidas: list[FilaInvalida] = field(default_factory=list)
    columnas_no_mapeadas: list[str] = field(default_factory=list)


def leer_excel(ruta: str) -> ResultadoIngesta:
    df = pd.read_excel(ruta, dtype=str)

    columnas_no_mapeadas = []
    header_to_key = {}
    columna_fecha_digitacion = None
    for col in df.columns:
        key = _COLUMN_MAP.get(_normalize(col))
        if key is None:
            columnas_no_mapeadas.append(str(col))
        else:
            header_to_key[col] = key
            if key == "fecha_digitacion":
                columna_fecha_digitacion = col

    # Fecha de digitación: se lee celda por celda con openpyxl (no con
    # pandas) para poder respetar el formato de fecha real de esa celda —
    # ver ``_fecha_tal_cual``. ``col_idx_fecha`` es la posición dentro de
    # ``df.columns`` (asume que no hay columnas fantasma entre el Excel y
    # el DataFrame, cierto en una lectura simple como esta).
    hoja_fechas = None
    col_idx_fecha = None
    if columna_fecha_digitacion is not None:
        hoja_fechas = openpyxl.load_workbook(ruta, data_only=True, read_only=True).active
        col_idx_fecha = list(df.columns).index(columna_fecha_digitacion) + 1

    resultado = ResultadoIngesta(columnas_no_mapeadas=columnas_no_mapeadas)

    # Excel tipo CRM (una fila por persona): las filas "Beneficiario" que
    # siguen a un titular se pliegan como sus beneficiarios en vez de
    # generar documento propio. La columna que marca el tipo varía según el
    # Excel: unos traen "tipo_solicitud" (Cotizante/Beneficiario), otros
    # solo "parentesco" con valores Titular/Beneficiario — se usa la que
    # esté presente, priorizando tipo_solicitud si ambas están.
    if "tipo_solicitud" in header_to_key.values():
        campo_grupo = "tipo_solicitud"
    elif "parentesco" in header_to_key.values():
        campo_grupo = "parentesco"
    else:
        campo_grupo = None
    agrupar_por_solicitud = campo_grupo is not None
    cotizante_actual: dict | None = None

    for pos, row in df.iterrows():
        numero_fila = pos + 2  # +1 por encabezado, +1 por índice base-1
        datos = {key: _clean(row[col]) for col, key in header_to_key.items()}

        if datos.get("fecha_activacion"):
            datos["fecha_activacion"] = _formatear_fecha_ymd(datos["fecha_activacion"])
        if hoja_fechas is not None and datos.get("fecha_digitacion"):
            # +1 por encabezado, +1 porque openpyxl es base-1 (misma cuenta
            # que ``numero_fila``, pero contra la hoja, no el DataFrame).
            celda = hoja_fechas.cell(row=pos + 2, column=col_idx_fecha)
            texto = _fecha_tal_cual(celda)
            if texto:
                datos["fecha_digitacion"] = texto

        nombre_completo_raw = datos.pop("_nombre_completo_split", "")
        if nombre_completo_raw and not datos.get("nombres") and not datos.get("apellidos"):
            partes = nombre_completo_raw.split()
            datos["nombres"] = partes[0] if partes else ""
            datos["apellidos"] = " ".join(partes[1:])

        if agrupar_por_solicitud:
            tipo = datos.pop(campo_grupo, "").strip().lower()
            datos.pop("tipo_solicitud", None)
            datos.pop("parentesco", None)  # informativo; no tiene campo propio en la carta

            if tipo == "beneficiario":
                if cotizante_actual is None:
                    resultado.invalidas.append(
                        FilaInvalida(numero_fila, "fila de beneficiario sin un cotizante previo")
                    )
                    continue
                nombre = f"{datos.get('nombres', '')} {datos.get('apellidos', '')}".strip()
                estatus = datos.get("estatus_migratorio", "")
                beneficiarios = cotizante_actual["beneficiarios"]
                if (nombre or estatus) and len(beneficiarios) < MAX_BENEFICIARIOS:
                    beneficiarios.append({"nombre": nombre, "estatus": estatus})
                continue

            # tipo == "cotizante" (o vacío/valor inesperado): cierra el
            # hogar anterior y abre uno nuevo.
            cotizante_actual = None
            faltantes = [k for k in REQUIRED_KEYS if not datos.get(k)]
            if faltantes:
                resultado.invalidas.append(
                    FilaInvalida(numero_fila, f"faltan campos obligatorios: {', '.join(faltantes)}")
                )
                continue

            datos["nombre_completo"] = f"{datos['nombres']} {datos['apellidos']}".strip()
            datos["beneficiarios"] = []
            resultado.registros.append(datos)
            cotizante_actual = datos
            continue

        faltantes = [k for k in REQUIRED_KEYS if not datos.get(k)]
        if faltantes:
            resultado.invalidas.append(
                FilaInvalida(numero_fila, f"faltan campos obligatorios: {', '.join(faltantes)}")
            )
            continue

        datos["nombre_completo"] = f"{datos['nombres']} {datos['apellidos']}".strip()

        beneficiarios = []
        for i in range(1, MAX_BENEFICIARIOS + 1):
            nombre = datos.pop(f"beneficiario_{i}_nombre", "")
            estatus = datos.pop(f"beneficiario_{i}_estatus", "")
            if nombre or estatus:
                beneficiarios.append({"nombre": nombre, "estatus": estatus})
        datos["beneficiarios"] = beneficiarios

        resultado.registros.append(datos)

    return resultado
