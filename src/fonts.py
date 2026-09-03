"""Registro de las fuentes TTF reales (Windows) usadas al estampar.

Se separa de ``pdf_stamper`` porque es infraestructura compartida, no
configuración de una plantilla en particular (esa vive en
``templates/config/*.json``, ver ``pdf_stamper.load_template_config``).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_WINFONTS = Path(r"C:\Windows\Fonts")

_TTF_FILES = {
    "Arial": "arial.ttf",
    "Arial-Bold": "arialbd.ttf",
    "Calibri": "calibri.ttf",
    "Calibri-Bold": "calibrib.ttf",
    "Calibri-Light": "calibril.ttf",
}


def ensure_fonts_registered() -> None:
    registered = pdfmetrics.getRegisteredFontNames()
    for name, filename in _TTF_FILES.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(_WINFONTS / filename)))
