"""Estampado de una firma REAL (pantallazo de una firma ya hecha) — módulo
independiente "firma_real".

A diferencia de ``src/firma_generator.py`` (que DIBUJA una firma sintética
procedural), aquí la "firma" es una imagen que ya trae el cliente —un
recorte/pantallazo de una firma manuscrita real ya existente, tal cual la
entrega el cliente (puede traer su propio corchete/etiqueta/línea si así fue
capturada, no se recorta ni se le quita nada)— y el único trabajo es
plasmarla, sin modificarla, dentro de la casilla "Firma Cliente:" de la
plantilla, escalada para caber sin deformarse.

No modifica ``src/pdf_stamper.py`` ni el flujo original: se usa como paso
posterior sobre un PDF ya generado por ``stamp_pdf`` (al que NO se le pasan
``firma_nombre``/``firma_estilo_id``, así que no dibuja ninguna firma
sintética — la casilla queda vacía, lista para esto).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def estampar_firma_imagen(
    pdf_path: str | Path, output_path: str | Path, imagen_path: str | Path,
    *, page_index: int, x: float, y: float, width: float, height: float,
) -> None:
    """Pega ``imagen_path`` (la firma real, sin recortar ni modificar) dentro
    de la caja cuyo vértice inferior-izquierdo es ``(x, y)`` en la página
    ``page_index`` de ``pdf_path`` — escalada para caber sin deformar
    proporciones, pegada contra el borde izquierdo de la caja (justo frente
    a la etiqueta "Firma Cliente:") y anclada abajo. El resto del PDF queda
    intacto."""
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()

    img = Image.open(imagen_path)
    img_w, img_h = img.size
    escala = min(width / img_w, height / img_h)
    draw_w, draw_h = img_w * escala, img_h * escala
    off_x = x

    page = reader.pages[page_index]
    pw = float(page.mediabox.width)
    ph = float(page.mediabox.height)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    c.drawImage(str(imagen_path), off_x, y, width=draw_w, height=draw_h,
               mask="auto", preserveAspectRatio=True)
    c.save()
    buf.seek(0)
    overlay = PdfReader(buf).pages[0]

    for i, pagina in enumerate(reader.pages):
        if i == page_index:
            pagina.merge_page(overlay)
        writer.add_page(pagina)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
