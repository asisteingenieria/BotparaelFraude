"""Estampa los datos de una persona sobre una plantilla PDF en blanco.

Mapeo de coordenadas inspirado en el patrón usado por el proyecto hermano
``firmacloudbackend`` (``src/config/templates/*.json`` +
``src/services/pdfService.js`` → ``fillContratoActivacion``): la plantilla
no vive hardcodeada en el código, sino en un JSON externo
(``templates/config/*.json``) con una lista plana de ``textFields``, cada
uno con su ``dataPath`` (qué dato pintar), página, posición y fuente. Añadir
o mover un campo es editar el JSON, no tocar Python.

Diferencias/mejoras respecto al original en Node:
- Las coordenadas ``y`` se guardan ya en el sistema nativo de PDF (origen
  abajo-izquierda), precalculadas una sola vez al generar el JSON — se evita
  repetir en cada render la conversión "top de página" -> "línea base".
- ``dataPath`` admite una cadena de alternativas separadas por ``|``
  (ej. ``"contacto_nombre|nombre_completo"``): usa el primer valor no vacío,
  para campos que heredan un valor por defecto de otro.
- El ajuste de ancho (encoger tamaño de letra / truncar) es genérico vía
  ``maxWidth``, no una función aparte por campo.

La firma del cliente se estampa en las casillas declaradas en
``signatureFields`` del JSON, usando el diseño elegido por el cliente
(``data["firma_estilo_id"]``, generado por ``src/firma_generator``).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from src.firma_generator import draw_signature, get_style
from src.fonts import ensure_fonts_registered

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "templates" / "config" / "obamacare_b2.json"


def load_template_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_value(data: dict, data_path: str) -> str:
    """Devuelve el primer valor no vacío entre las alternativas de ``data_path``
    (separadas por ``|``). Cada alternativa es una clave plana de ``data``."""
    for key in data_path.split("|"):
        value = data.get(key.strip())
        if value:
            return str(value)
    return ""


def _wrap_lines(text: str, font: str, size: float, max_width: float) -> list[str]:
    """Parte ``text`` en líneas que quepan en ``max_width`` (salto de línea
    por palabras). Una palabra suelta más ancha que la columna se encoge y
    trunca como último recurso (caso extremo)."""
    lineas: list[str] = []
    actual = ""
    for palabra in text.split():
        candidata = f"{actual} {palabra}".strip()
        if not actual or stringWidth(candidata, font, size) <= max_width:
            actual = candidata
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return [
        _fit_text(linea, font, size, max_width)[0] if
        stringWidth(linea, font, size) > max_width else linea
        for linea in (lineas or [""])
    ]


def _fit_text(text: str, font: str, size: float, max_width: float) -> tuple[str, float]:
    """Reduce el tamaño de letra (hasta un mínimo) para que el texto entre en
    ``max_width``; si aun así no cabe, lo trunca con puntos suspensivos."""
    if not text:
        return text, size
    current = size
    while current > 6.0 and stringWidth(text, font, current) > max_width:
        current -= 0.5
    if stringWidth(text, font, current) > max_width:
        while len(text) > 1 and stringWidth(text + "...", font, current) > max_width:
            text = text[:-1]
        text = text + "..."
    return text, current


class _TemplateRenderer:
    """Dibuja los overlays de una plantilla (config JSON) para un ``data`` dado."""

    def __init__(self, config: dict):
        self.config = config
        self.fonts = config["fonts"]  # {"regular": "Arial", ...} -> nombre real de fuente

    def _font(self, key: str) -> str:
        return self.fonts[key]

    def _draw(self, c: canvas.Canvas, text: str, x: float, y: float, size: float,
              font_key: str, max_width: float | None = None) -> None:
        if not text:
            return
        font = self._font(font_key)
        if max_width:
            text, size = _fit_text(text, font, size, max_width)
        c.setFont(font, size)
        c.drawString(x, y, text)

    def _draw_field(self, c: canvas.Canvas, field: dict, data: dict) -> None:
        value = _resolve_value(data, field["dataPath"])
        if not value:
            return
        if field.get("dashDates"):
            value = value.replace("/", "-")
        if "prefix" in field and not value.strip().upper().startswith(field["prefix"].strip().upper()):
            value = f"{field['prefix']}{value}"
        if "suffix" in field and not value.strip().upper().endswith(field["suffix"].strip().upper()):
            value = f"{value}{field['suffix']}"

        x = field["x"]
        if "label" in field:
            label = field["label"]
            label_font = self._font(field["labelFont"])
            c.setFont(label_font, field["labelSize"])
            c.drawString(x, field["labelY"], label)
            x = x + stringWidth(label, label_font, field["labelSize"]) + field.get("gap", 0)

        self._draw(
            c, value, x=x, y=field["y"], size=field["fontSize"],
            font_key=field["font"], max_width=field.get("maxWidth"),
        )

    def _draw_cover_rects(self, c: canvas.Canvas, page_index: int) -> None:
        for rect in self.config.get("coverRects", []):
            if rect["page"] != page_index:
                continue
            c.setFillColorRGB(1, 1, 1)
            c.rect(rect["x0"], rect["y0"], rect["x1"] - rect["x0"], rect["y1"] - rect["y0"], stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)

    def _draw_beneficiaries(self, c: canvas.Canvas, page_index: int, data: dict) -> None:
        """Bloques "Beneficiario N / Estatus migratorio" con flujo dinámico:
        los valores largos se envuelven en varias líneas (salto de línea, sin
        encoger ni truncar) y los bloques siguientes bajan lo necesario. Un
        piso (``minY``) garantiza que nunca se invada el pie de la página: si
        no caben todos, se anota cuántos quedaron por listar."""
        block = self.config.get("beneficiaryBlock")
        if not block or block["page"] != page_index:
            return

        label_font = self._font(block["labelFont"])
        value_font = self._font(block["font"])
        size = block["fontSize"]
        line_step = block["nameY0"] - block["statusY0"]   # entre renglón nombre y estatus
        block_gap = block["step"] - line_step             # entre un bloque y el siguiente
        wrap_lh = block.get("wrapLineHeight", 16.0)       # interlineado de líneas envueltas
        floor = block.get("minY", 255.0)

        benes = [b for b in data.get("beneficiarios", [])
                 if b.get("nombre") or b.get("estatus")]
        cursor = block["nameY0"]

        def draw_wrapped(label: str, valor: str, y: float) -> float:
            """Dibuja etiqueta + valor envuelto; devuelve el nuevo cursor."""
            c.setFont(label_font, block["labelSize"])
            c.drawString(block["x"], y, label)
            x_val = block["x"] + stringWidth(label, label_font, block["labelSize"]) + block["gap"]
            lineas = _wrap_lines(valor, value_font, size, block["maxX"] - x_val)
            c.setFont(value_font, size)
            for j, linea in enumerate(lineas):
                if j > 0:
                    y -= wrap_lh
                c.drawString(x_val, y, linea)
            return y

        for i, beneficiario in enumerate(benes):
            nombre = beneficiario.get("nombre", "")
            estatus = beneficiario.get("estatus", "")

            # altura estimada del bloque completo (con sus líneas envueltas)
            label_n = f"Beneficiario {i + 1}:"
            label_e = "Estatus migratorio:"
            x_n = block["x"] + stringWidth(label_n, label_font, block["labelSize"]) + block["gap"]
            x_e = block["x"] + stringWidth(label_e, label_font, block["labelSize"]) + block["gap"]
            extra_n = len(_wrap_lines(nombre, value_font, size, block["maxX"] - x_n)) - 1
            extra_e = len(_wrap_lines(estatus, value_font, size, block["maxX"] - x_e)) - 1
            altura = line_step + (extra_n + extra_e) * wrap_lh

            if cursor - altura < floor:
                c.setFont(label_font, 10)
                c.drawString(block["x"], max(cursor, floor),
                             f"... y {len(benes) - i} beneficiario(s) más")
                break

            cursor = draw_wrapped(label_n, nombre, cursor)
            cursor -= line_step
            cursor = draw_wrapped(label_e, estatus, cursor)
            cursor -= block_gap + line_step

    def _draw_bracket(self, c: canvas.Canvas, bracket: dict) -> None:
        """Corchete morado tipo DocuSign (abre hacia la derecha, esquinas
        redondeadas) — para plantillas donde el corchete original viene
        incrustado en una imagen que hay que tapar junto con la firma vieja."""
        x = bracket["x"]
        y_bottom = bracket["yBottom"]
        y_top = bracket["yTop"]
        radius = bracket.get("radius", 6.0)
        color = bracket.get("color", (80 / 255, 0 / 255, 253 / 255))
        k = radius * 0.5523
        p = c.beginPath()
        p.moveTo(x + radius, y_top)
        p.curveTo(x + radius - k, y_top, x, y_top - radius + k, x, y_top - radius)
        p.lineTo(x, y_bottom + radius)
        p.curveTo(x, y_bottom + radius - k, x + radius - k, y_bottom, x + radius, y_bottom)
        c.setStrokeColorRGB(*color)
        c.setLineWidth(1.3)
        c.drawPath(p, stroke=1, fill=0)
        c.setStrokeColorRGB(0, 0, 0)

    def _draw_static_labels(self, c: canvas.Canvas, page_index: int) -> None:
        for label in self.config.get("staticLabels", []):
            if label["page"] != page_index:
                continue
            c.setFillColorRGB(0, 0, 0)
            c.setFont(self._font(label["font"]), label["fontSize"])
            c.drawString(label["x"], label["y"], label["text"])

    def _draw_signatures(self, c: canvas.Canvas, page_index: int, data: dict) -> None:
        nombre = data.get("firma_nombre", "")
        estilo_id = data.get("firma_estilo_id", "")
        if not nombre or not estilo_id:
            return
        estilo = get_style(estilo_id)
        for field in self.config.get("signatureFields", []):
            if field["page"] != page_index:
                continue
            if field.get("bracket"):
                self._draw_bracket(c, field["bracket"])
            draw_signature(
                c, nombre, estilo, x=field["x"], y=field["y"],
                width=field["width"], height=field["height"],
            )

    def _draw_signature_meta(self, c: canvas.Canvas, page_index: int, data: dict) -> None:
        """Rastro de auditoría de la firma, replicando el PDF firmado de
        ejemplo (``templates/EDWIN AMAYA FONSECA.pdf``): encabezado con correo
        + fecha/hora en las páginas de carta, línea de ID de sobre en la
        última página y código corto bajo la casilla de firma."""
        meta = self.config.get("signatureMeta")
        if not meta:
            return
        firma_id = data.get("firma_id", "")

        header = meta.get("header")
        email = data.get("firma_email", "")
        fecha_hora = data.get("firma_fecha_hora", "").replace("/", "-")
        if header and page_index in header["pages"] and (email or fecha_hora):
            c.setFillColorRGB(0, 0, 0)
            c.setFont(self._font("regular"), header["fontSize"])
            c.drawString(header["x"], header["y"], f"{email} {fecha_hora}".strip())

        envelope = meta.get("envelope")
        if envelope and envelope["page"] == page_index and firma_id:
            c.setFillColorRGB(0, 0, 0)
            c.setFont(self._font("regular"), envelope["fontSize"])
            c.drawString(envelope["x"], envelope["y"], envelope["label"] + firma_id.upper())

        code = meta.get("code")
        if code and code["page"] == page_index and firma_id:
            corto = firma_id.replace("-", "").upper()[:15] + "..."
            c.setFillColorRGB(0, 0, 0)
            c.setFont(self._font("regular"), code["fontSize"])
            c.drawString(code["x"], code["y"], corto)

    def render_page(self, c: canvas.Canvas, page_index: int, data: dict) -> None:
        self._draw_cover_rects(c, page_index)
        self._draw_static_labels(c, page_index)

        title = self.config.get("title")
        if title and title["page"] == page_index:
            self._draw_field(c, title, data)

        for field in self.config["textFields"]:
            if field["page"] == page_index:
                self._draw_field(c, field, data)

        self._draw_beneficiaries(c, page_index, data)
        self._draw_signatures(c, page_index, data)
        self._draw_signature_meta(c, page_index, data)


def stamp_pdf(template_path: str | Path, output_path: str | Path, data: dict,
              config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Genera un PDF a partir de la plantilla en blanco con los datos de ``data``.

    ``data`` debe traer al menos ``nombre_completo`` y los campos definidos en
    ``src/ingesta.py``. Si trae ``firma_nombre`` y ``firma_estilo_id``, la firma
    se dibuja en las casillas de ``signatureFields`` del config.
    """
    ensure_fonts_registered()
    config = load_template_config(config_path)
    renderer = _TemplateRenderer(config)

    reader = PdfReader(str(template_path))
    writer = PdfWriter()

    pages_with_fields = {f["page"] for f in config["textFields"]}
    if config.get("title"):
        pages_with_fields.add(config["title"]["page"])
    if config.get("beneficiaryBlock"):
        pages_with_fields.add(config["beneficiaryBlock"]["page"])
    for f in config.get("signatureFields", []):
        pages_with_fields.add(f["page"])
    meta = config.get("signatureMeta", {})
    pages_with_fields.update(meta.get("header", {}).get("pages", []))
    for key in ("envelope", "code"):
        if key in meta:
            pages_with_fields.add(meta[key]["page"])
    for label in config.get("staticLabels", []):
        pages_with_fields.add(label["page"])

    overlays: dict[int, object] = {}
    for page_index in pages_with_fields:
        width, height = config["pageSizes"][str(page_index)]
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        renderer.render_page(c, page_index, data)
        c.save()
        buf.seek(0)
        overlays[page_index] = PdfReader(buf).pages[0]

    for i, page in enumerate(reader.pages):
        if i in overlays:
            page.merge_page(overlays[i])
        writer.add_page(page)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
