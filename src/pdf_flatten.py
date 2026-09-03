"""Aplanado de PDF a imagen ("pantallazo") — módulo independiente.

Usado por el módulo "OtroM" (ver ``src/auditoria.py``, carga con
``modulo="otro"``): después de plasmar datos y firma con el flujo normal
(``src.pdf_stamper.stamp_pdf``, sin tocar), estas funciones reemplazan
contenido ya plasmado por un "pantallazo" — una imagen rasterizada de sí
mismo, a baja resolución a propósito para que se note que es un pantallazo
— y lo unen de nuevo en un único PDF con el resto del contenido intacto
(vectorial). Dos niveles:

- ``aplanar_pagina``: reemplaza una página completa.
- ``aplanar_campo``: reemplaza solo el texto de UN campo puntual (ubicado
  por su posición ``x, y`` en coordenadas PDF), dejando el resto de esa
  misma página sin tocar — usa redacción real (``apply_redactions``) para
  borrar el trazo/texto original bajo el pantallazo, no solo taparlo.

No modifica ``src/pdf_stamper.py`` ni el flujo original: se usan como paso
posterior y opcional sobre un PDF ya generado.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def aplanar_pagina(pdf_path: str | Path, output_path: str | Path,
                   page_index: int = 3, dpi: int = 72) -> None:
    """Lee ``pdf_path``, reemplaza la página ``page_index`` por un pantallazo
    (imagen rasterizada de sí misma a ``dpi``) y escribe el PDF resultante ya
    unido (todas las páginas juntas, las demás sin cambios) en ``output_path``.

    ``dpi`` bajo a propósito (72 = resolución de pantalla estándar): la idea
    es que se note que es un pantallazo (texto/firma con bordes pixelados al
    hacer zoom), no un render de alta calidad casi indistinguible del vector
    original — con 150-200dpi la diferencia era imperceptible a simple vista.
    """
    doc = pymupdf.open(str(pdf_path))
    if not (0 <= page_index < len(doc)):
        raise IndexError(f"La página {page_index} no existe (el PDF tiene {len(doc)} páginas)")

    page = doc[page_index]
    rect = page.rect
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))

    doc.delete_page(page_index)
    nueva = doc.new_page(page_index, width=rect.width, height=rect.height)
    nueva.insert_image(rect, pixmap=pix)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()


def _bbox_de_campo(page: "pymupdf.Page", x: float, y: float,
                   tol: float = 3.0) -> "pymupdf.Rect | None":
    """Ubica el rectángulo real (coords de página, origen arriba-izquierda,
    como usa PyMuPDF) del texto dibujado en ``(x, y)`` — coordenadas PDF
    nativas (origen abajo-izquierda, ``y`` = línea base), las mismas que usan
    los ``textFields`` de ``templates/config/*.json``. Busca entre las
    "palabras" de la página la que arranca ahí, con tolerancia ``tol``.
    Devuelve ``None`` si no hay texto en esa posición (campo vacío)."""
    h = page.rect.height
    for x0, y0, x1, y1, texto, *_ in page.get_text("words"):
        if texto.strip() and abs(x0 - x) <= tol and abs((h - y1) - y) <= tol:
            return pymupdf.Rect(x0, y0, x1, y1)
    return None


def _linea_bajo_campo(page: "pymupdf.Page", campo: "pymupdf.Rect",
                      tol: float = 4.0) -> "pymupdf.Rect | None":
    """Busca entre los trazos vectoriales de la página el renglón (línea
    horizontal delgada, el "blank" de un formulario) que queda justo debajo
    del texto de ``campo`` — para poder extender el pantallazo a TODO ese
    renglón, no solo al ancho del valor. Si no se hace esto, el tramo de la
    línea bajo el texto queda rasterizado y el resto de esa misma línea
    (donde no llegaba el texto) sigue vectorial: se nota un empalme/quiebre
    justo donde termina el pantallazo, aunque sea la misma línea recta de la
    plantilla. Devuelve ``None`` si no hay una línea así debajo (campo sin
    renglón propio)."""
    for d in page.get_drawings():
        r = d["rect"]
        if r.height > 2.0 or r.width < 1.0:
            continue  # no es una línea horizontal delgada
        if not (campo.y1 - tol <= r.y0 <= campo.y1 + tol):
            continue  # no está pegada justo debajo del texto
        if r.x0 > campo.x1 + tol:
            continue  # no arranca cerca de donde arranca el texto
        return r
    return None


def aplanar_campo(pdf_path: str | Path, output_path: str | Path, page_index: int,
                  x: float, y: float, dpi: int = 72, padding: float = 2.0) -> bool:
    """Reemplaza SOLO el texto ubicado en ``(x, y)`` (coordenadas PDF, igual
    que un ``textField`` del config) de la página ``page_index`` por un
    pantallazo de sí mismo — el resto de la página (y del PDF) queda
    intacto. Usa redacción real: borra el trazo original bajo el pantallazo,
    no lo tapa nomás. Si el campo tiene un renglón/línea de la plantilla
    justo debajo (``_linea_bajo_campo``), el pantallazo se extiende a TODO
    ese renglón para que coincida con la línea real, sin quiebres visibles
    donde el pantallazo termina y la línea vectorial original continúa.
    Devuelve ``False`` sin escribir nada si el campo está vacío (no hay
    texto que aplanar) — en ese caso el llamador debe usar ``pdf_path`` tal
    cual como si esta función no se hubiera llamado.
    """
    doc = pymupdf.open(str(pdf_path))
    page = doc[page_index]
    palabra = _bbox_de_campo(page, x, y)
    if palabra is None:
        doc.close()
        return False

    rect = pymupdf.Rect(palabra.x0 - padding, palabra.y0 - padding,
                        palabra.x1 + padding, palabra.y1 + padding)

    linea = _linea_bajo_campo(page, palabra)
    if linea is not None:
        rect = pymupdf.Rect(
            min(rect.x0, linea.x0 - padding), rect.y0,
            max(rect.x1, linea.x1 + padding), max(rect.y1, linea.y1 + padding),
        )

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect)

    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    page.insert_image(rect, pixmap=pix)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()
    return True
