"""Motor de firmas DIBUJADAS a partir del nombre del cliente.

A diferencia del render tipográfico (eso ya lo hace FirmaCloud con fuentes),
aquí la firma se construye como un trazo de pluma sintético:

1. Cada letra tiene un esqueleto cursivo propio (puntos de control definidos a
   mano en ``_LETTERS``, en un espacio normalizado donde la altura x = 1.0).
2. Los esqueletos se encadenan en un único trazo continuo por palabra, como al
   escribir sin levantar la pluma; puntos, tildes y barras de la "t" son
   trazos cortos aparte.
3. El trazo se suaviza con splines Catmull-Rom centrípetas, se le aplica
   inclinación, un temblor de mano (suma de senoides con fase aleatoria) y
   presión variable: bajadas gruesas y subidas finas, como pluma real.
4. Cada estilo del catálogo cambia inclinación, grosor, nerviosismo, amplitud
   y legibilidad (los estilos "ejecutiva"/"energica" dejan legibles solo las
   primeras letras y convierten el resto en un garabato rítmico cuyo perfil de
   picos sale de las ascendentes/descendentes reales del nombre).

Todo es determinista: la semilla sale de ``sha256(nombre|estilo)``, así el
preview que el cliente eligió y la firma estampada son trazos idénticos y el
servicio queda stateless.

Salidas:
- ``generar_opciones(nombre)``: galería de previews PNG en base64 (Pillow).
- ``draw_signature(canvas, ...)``: dibuja el mismo trazo, vectorial, sobre el
  canvas de reportlab al estampar el PDF.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import random
import unicodedata

from PIL import Image, ImageDraw
from reportlab.lib.colors import Color

# Tinta: negro, como la firma del PDF de ejemplo — TODOS los diseños se
# plasman en negro (decisión de producto; antes había estilos en azul).
_INK_BLACK = (0, 0, 0)

# Catálogo de estilos. ``slant`` en grados; ``width`` grosor base del trazo en
# unidades (altura x = 1.0); ``press`` cuánto engrosa las bajadas de pluma;
# ``jitter`` amplitud del temblor de mano; ``amp`` escala de ascendentes y
# descendentes; ``keep`` None = todas las letras legibles, N = solo las
# primeras N de cada palabra y el resto garabato; ``rubric`` trazo final;
# ``deco`` trazos decorativos extra ("oval", "strike", "spiral", "overloop",
# "zigzag", "sweep", "dot", "curls", "double_underline"); ``gesture`` activa
# el modo de firma GESTUAL abstracta (ver ``_gesture_raw_strokes``): la firma
# no escribe letras sino que imita la anatomía de una firma real rápida.
# ``connected`` (default True) = letras encadenadas en un solo trazo cursivo;
# False = letra "normal"/imprenta: se levanta la pluma entre letras (mismos
# esqueletos de ``_LETTERS``, pero cada una es su propio trazo suelto).
# Toda firma se dibuja solo con el primer nombre; los estilos con
# ``scope: "initials"`` son monogramas con la inicial de ese primer nombre.
SIGNATURE_STYLES: list[dict] = [
    # --- primer nombre dibujado en cursiva ---
    {"id": "clasica", "label": "Clásica elegante", "ink": _INK_BLACK,
     "slant": 14, "width": 0.050, "press": 0.55, "jitter": 0.018, "amp": 1.0,
     "keep": None, "rubric": "underline"},
    {"id": "fluida", "label": "Fluida moderna", "ink": _INK_BLACK,
     "slant": 22, "width": 0.038, "press": 0.35, "jitter": 0.030, "amp": 1.05,
     "keep": None, "rubric": "none"},
    {"id": "caligrafica", "label": "Caligráfica", "ink": _INK_BLACK,
     "slant": 8, "width": 0.056, "press": 0.75, "jitter": 0.014, "amp": 1.18,
     "keep": None, "rubric": "underline"},
    {"id": "ejecutiva", "label": "Ejecutiva abreviada", "ink": _INK_BLACK,
     "slant": 20, "width": 0.048, "press": 0.45, "jitter": 0.042, "amp": 1.05,
     "keep": 1, "rubric": "loop"},
    {"id": "nombre_lazo", "label": "Nombre con lazo aéreo", "ink": _INK_BLACK,
     "slant": 16, "width": 0.050, "press": 0.50, "jitter": 0.025, "amp": 1.0,
     "keep": None, "rubric": "none", "deco": ["overloop"]},
    {"id": "nombre_espiral", "label": "Nombre con espiral", "ink": _INK_BLACK,
     "slant": 14, "width": 0.046, "press": 0.45, "jitter": 0.028, "amp": 1.0,
     "keep": None, "rubric": "underline", "deco": ["spiral"]},
    {"id": "nombre_oval", "label": "Nombre enmarcado", "ink": _INK_BLACK,
     "slant": 10, "width": 0.048, "press": 0.50, "jitter": 0.022, "amp": 0.95,
     "keep": None, "rubric": "none", "deco": ["oval"]},
    {"id": "logo_elegante", "label": "Logo elegante", "ink": _INK_BLACK,
     "slant": 18, "width": 0.030, "press": 0.15, "jitter": 0.015, "amp": 1.6,
     "keep": None, "rubric": "none", "deco": ["sweep"]},
    {"id": "bucles", "label": "Remate en bucles", "ink": _INK_BLACK,
     "slant": 15, "width": 0.042, "press": 0.35, "jitter": 0.025, "amp": 1.05,
     "keep": None, "rubric": "none", "deco": ["curls", "double_underline"]},
    # --- primer nombre en letra IMPRENTA/molde mayúscula (alfabeto propio en
    # ``_PRINT_LETTERS``: trazos rectos, sin bucles cursivos, pluma levantada
    # entre letras — como firmar en mayúsculas de formulario, ej. "JUAN") ---
    {"id": "impresa_clara", "label": "Imprenta clara", "ink": _INK_BLACK,
     "slant": 0, "width": 0.052, "press": 0.30, "jitter": 0.018, "amp": 1.0,
     "keep": None, "rubric": "underline", "letterform": "print_caps"},
    {"id": "impresa_inclinada", "label": "Imprenta inclinada", "ink": _INK_BLACK,
     "slant": 10, "width": 0.050, "press": 0.35, "jitter": 0.022, "amp": 1.0,
     "keep": None, "rubric": "none", "letterform": "print_caps"},
    {"id": "impresa_firme", "label": "Imprenta firme", "ink": _INK_BLACK,
     "slant": 2, "width": 0.062, "press": 0.55, "jitter": 0.014, "amp": 0.95,
     "keep": None, "rubric": "loop", "letterform": "print_caps"},
    {"id": "impresa_lazo", "label": "Imprenta con lazo final", "ink": _INK_BLACK,
     "slant": 6, "width": 0.050, "press": 0.35, "jitter": 0.020, "amp": 1.0,
     "keep": None, "rubric": "none", "deco": ["overloop"], "letterform": "print_caps"},
    {"id": "impresa_oval", "label": "Imprenta enmarcada", "ink": _INK_BLACK,
     "slant": 4, "width": 0.050, "press": 0.35, "jitter": 0.018, "amp": 0.92,
     "keep": None, "rubric": "none", "deco": ["oval"], "letterform": "print_caps"},
]


def get_style(estilo_id: str) -> dict:
    for style in SIGNATURE_STYLES:
        if style["id"] == estilo_id:
            return style
    raise KeyError(f"Estilo de firma desconocido: {estilo_id!r}")


class SelectorDeEstilos:
    """Reparte diseños entre documentos con dos reglas a la vez:

    1. **Cobertura del catálogo por lote**: una cola barajada con TODOS los
       estilos habilitados se va consumiendo un estilo a la vez; cuando se
       vacía, se vuelve a barajar el catálogo completo y se rellena. Así,
       al cargar un Excel con varios registros, se usan todos los estilos
       disponibles antes de repetir ninguno (en vez de elegir al azar cada
       vez, que podía repetir uno varias veces y no usar otros).
    2. **Variedad por nombre**: si el mismo cliente firma más de una carta,
       se evita repetirle un estilo que ya usó (buscando en la cola el
       primero que ese nombre no haya usado todavía) — solo se repite si
       ese nombre ya agotó el catálogo completo.

    La memoria vive en la instancia (una por corrida del batch/carga o por
    proceso de la API); no persiste entre reinicios.
    """

    def __init__(self, rng: random.Random | None = None):
        self._usados_por_nombre: dict[str, set[str]] = {}
        self._rng = rng or random.Random()
        self._cola: list[str] = []

    def _rellenar_cola(self) -> None:
        ids = [s["id"] for s in SIGNATURE_STYLES]
        self._rng.shuffle(ids)
        self._cola.extend(ids)

    def elegir(self, nombre: str) -> str:
        clave = " ".join(nombre.split()).lower()
        usados = self._usados_por_nombre.setdefault(clave, set())

        if not self._cola:
            self._rellenar_cola()

        idx = next((i for i, sid in enumerate(self._cola) if sid not in usados), 0)
        elegido = self._cola.pop(idx)
        usados.add(elegido)
        return elegido


def _seed(nombre: str, estilo_id: str) -> int:
    digest = hashlib.sha256(f"{nombre}|{estilo_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


# ---------------------------------------------------------------------------
# Esqueletos cursivos por letra
# ---------------------------------------------------------------------------
# Espacio normalizado: línea base y=0, altura x = 1.0, ascendentes ~1.9,
# descendentes ~-0.85. Cada letra entra por (0, ~0.1) y sale por (adv, ~0.1)
# para poder encadenarse en un trazo continuo. ``marks`` son trazos cortos
# aparte (punto de la i, barra de la t, etc.).

_LETTERS: dict[str, dict] = {
    "a": {"adv": 0.68, "pts": [(0, 0.1), (0.40, 0.92), (0.16, 1.0), (0.0, 0.5),
                               (0.14, 0.06), (0.36, 0.45), (0.42, 0.92),
                               (0.50, 0.35), (0.62, 0.08)]},
    "b": {"adv": 0.66, "pts": [(0, 0.1), (0.20, 0.9), (0.34, 1.80), (0.22, 1.86), (0.12, 1.0),
                               (0.16, 0.12), (0.36, 0.08), (0.50, 0.45),
                               (0.42, 0.78), (0.60, 0.45)]},
    "c": {"adv": 0.60, "pts": [(0, 0.1), (0.42, 0.90), (0.20, 1.0), (0.02, 0.55),
                               (0.16, 0.08), (0.44, 0.28), (0.55, 0.12)]},
    "d": {"adv": 0.70, "pts": [(0, 0.1), (0.38, 0.90), (0.15, 1.0), (0.0, 0.5), (0.14, 0.06),
                               (0.38, 0.5), (0.46, 1.55), (0.50, 1.65), (0.55, 0.4), (0.66, 0.1)]},
    "e": {"adv": 0.55, "pts": [(0, 0.1), (0.30, 0.72), (0.15, 0.95), (0.02, 0.6),
                               (0.12, 0.08), (0.40, 0.32), (0.50, 0.12)]},
    "f": {"adv": 0.55, "pts": [(0, 0.1), (0.25, 1.2), (0.40, 1.85), (0.28, 1.90), (0.18, 1.1),
                               (0.20, 0.2), (0.18, -0.6), (0.05, -0.80), (0.02, -0.5),
                               (0.20, 0.15), (0.45, 0.18)]},
    "g": {"adv": 0.66, "pts": [(0, 0.1), (0.38, 0.90), (0.15, 1.0), (0.0, 0.5), (0.14, 0.06),
                               (0.36, 0.5), (0.42, 0.92), (0.46, 0.2), (0.44, -0.55),
                               (0.30, -0.85), (0.18, -0.60), (0.42, -0.05), (0.60, 0.15)]},
    "h": {"adv": 0.64, "pts": [(0, 0.1), (0.20, 1.0), (0.32, 1.85), (0.20, 1.88), (0.12, 1.0),
                               (0.14, 0.1), (0.30, 0.85), (0.44, 0.90), (0.52, 0.5), (0.58, 0.08)]},
    "i": {"adv": 0.42, "pts": [(0, 0.1), (0.18, 0.95), (0.26, 0.4), (0.36, 0.08)],
          "marks": [[(0.20, 1.30), (0.22, 1.38)]]},
    "j": {"adv": 0.45, "pts": [(0, 0.1), (0.20, 0.95), (0.22, 0.0), (0.20, -0.6),
                               (0.06, -0.85), (0.0, -0.55), (0.25, 0.1)],
          "marks": [[(0.22, 1.30), (0.24, 1.38)]]},
    "k": {"adv": 0.62, "pts": [(0, 0.1), (0.20, 1.0), (0.30, 1.85), (0.18, 1.86), (0.12, 0.9),
                               (0.14, 0.1), (0.35, 0.72), (0.45, 0.88), (0.30, 0.5),
                               (0.50, 0.18), (0.58, 0.08)]},
    "l": {"adv": 0.50, "pts": [(0, 0.1), (0.22, 1.1), (0.34, 1.85), (0.20, 1.90),
                               (0.10, 1.0), (0.18, 0.12), (0.40, 0.08)]},
    "m": {"adv": 0.92, "pts": [(0, 0.1), (0.14, 0.88), (0.22, 0.85), (0.28, 0.15), (0.36, 0.82),
                               (0.46, 0.88), (0.52, 0.15), (0.62, 0.82), (0.72, 0.88),
                               (0.80, 0.4), (0.86, 0.08)]},
    "n": {"adv": 0.70, "pts": [(0, 0.1), (0.14, 0.88), (0.24, 0.88), (0.30, 0.15),
                               (0.40, 0.82), (0.50, 0.88), (0.56, 0.4), (0.64, 0.08)]},
    "o": {"adv": 0.62, "pts": [(0, 0.1), (0.36, 0.90), (0.16, 1.0), (0.0, 0.5),
                               (0.16, 0.05), (0.40, 0.4), (0.42, 0.85), (0.58, 0.70)]},
    "p": {"adv": 0.64, "pts": [(0, 0.1), (0.20, 0.95), (0.24, 0.0), (0.26, -0.78), (0.20, -0.85),
                               (0.16, -0.2), (0.20, 0.55), (0.38, 0.85), (0.50, 0.5),
                               (0.44, 0.12), (0.60, 0.1)]},
    "q": {"adv": 0.68, "pts": [(0, 0.1), (0.38, 0.90), (0.15, 1.0), (0.0, 0.5), (0.14, 0.06),
                               (0.36, 0.5), (0.42, 0.92), (0.44, 0.0), (0.42, -0.68),
                               (0.52, -0.80), (0.60, -0.35), (0.62, 0.1)]},
    "r": {"adv": 0.56, "pts": [(0, 0.1), (0.16, 0.88), (0.22, 1.0), (0.30, 0.82),
                               (0.38, 0.88), (0.42, 0.5), (0.50, 0.08)]},
    "s": {"adv": 0.55, "pts": [(0, 0.1), (0.30, 0.88), (0.34, 1.0), (0.12, 0.55),
                               (0.32, 0.15), (0.20, 0.02), (0.12, 0.14),
                               (0.40, 0.2), (0.50, 0.12)]},
    "t": {"adv": 0.52, "pts": [(0, 0.1), (0.22, 1.0), (0.30, 1.50), (0.32, 1.0),
                               (0.36, 0.3), (0.46, 0.08)],
          "marks": [[(0.08, 1.02), (0.50, 1.10)]]},
    "u": {"adv": 0.68, "pts": [(0, 0.1), (0.16, 0.92), (0.20, 0.3), (0.30, 0.1),
                               (0.42, 0.5), (0.46, 0.92), (0.52, 0.3), (0.62, 0.08)]},
    "v": {"adv": 0.64, "pts": [(0, 0.1), (0.15, 0.88), (0.28, 0.12), (0.42, 0.82),
                               (0.52, 0.92), (0.60, 0.68)]},
    "w": {"adv": 0.80, "pts": [(0, 0.1), (0.14, 0.88), (0.24, 0.12), (0.36, 0.78),
                               (0.46, 0.12), (0.58, 0.82), (0.68, 0.92), (0.76, 0.68)]},
    "x": {"adv": 0.56, "pts": [(0, 0.1), (0.20, 0.88), (0.40, 0.15), (0.52, 0.08)],
          "marks": [[(0.44, 0.88), (0.10, 0.12)]]},
    "y": {"adv": 0.66, "pts": [(0, 0.1), (0.16, 0.88), (0.22, 0.3), (0.32, 0.12), (0.44, 0.55),
                               (0.48, 0.92), (0.50, 0.0), (0.46, -0.6), (0.32, -0.85),
                               (0.22, -0.60), (0.46, -0.05), (0.62, 0.12)]},
    "z": {"adv": 0.60, "pts": [(0, 0.1), (0.15, 0.82), (0.40, 0.88), (0.12, 0.15), (0.35, 0.1),
                               (0.44, -0.4), (0.30, -0.75), (0.20, -0.5),
                               (0.42, 0.02), (0.56, 0.12)]},
}

# Mayúsculas cursivas con forma propia (las que no estén aquí se dibujan como
# la minúscula agrandada, que en firmas reales es un gesto común).
_CAPITALS: dict[str, dict] = {
    "c": {"adv": 0.62, "pts": [(0.50, 1.55), (0.20, 1.75), (0.0, 1.0),
                               (0.15, 0.15), (0.45, 0.05), (0.60, 0.30)]},
    "e": {"adv": 0.60, "pts": [(0.40, 1.70), (0.15, 1.80), (0.05, 1.45), (0.30, 1.10),
                               (0.10, 0.95), (0.30, 0.85), (0.05, 0.35),
                               (0.20, 0.02), (0.50, 0.15)]},
    "j": {"adv": 0.60, "pts": [(0.30, 1.60), (0.45, 1.75), (0.50, 1.20), (0.40, 0.20),
                               (0.35, -0.50), (0.15, -0.80), (0.0, -0.45),
                               (0.30, 0.10), (0.50, 0.15)]},
    "l": {"adv": 0.60, "pts": [(0.35, 1.50), (0.50, 1.75), (0.30, 1.85), (0.10, 1.20),
                               (0.15, 0.30), (0.05, 0.05), (0.30, 0.10), (0.55, 0.20)]},
    "m": {"adv": 0.85, "pts": [(0.0, 0.10), (0.12, 1.50), (0.20, 1.70), (0.30, 0.20),
                               (0.45, 1.55), (0.55, 1.70), (0.68, 0.15), (0.80, 0.10)]},
    "p": {"adv": 0.62, "pts": [(0.05, 0.08), (0.15, 1.60), (0.22, 1.75), (0.45, 1.45),
                               (0.35, 0.95), (0.12, 0.90), (0.30, 0.40), (0.50, 0.15)]},
    "r": {"adv": 0.68, "pts": [(0.05, 0.05), (0.15, 1.70), (0.35, 1.75), (0.45, 1.35),
                               (0.20, 1.00), (0.45, 0.50), (0.55, 0.10), (0.65, 0.20)]},
    "s": {"adv": 0.58, "pts": [(0.45, 1.50), (0.30, 1.75), (0.10, 1.45), (0.40, 0.90),
                               (0.15, 0.25), (0.0, 0.40), (0.20, 0.05), (0.50, 0.15)]},
    "t": {"adv": 0.60, "pts": [(0.10, 1.55), (0.0, 1.70), (0.35, 1.75), (0.60, 1.65),
                               (0.35, 1.72), (0.30, 0.90), (0.25, 0.15), (0.45, 0.10)]},
}

# Alfabeto de letra IMPRENTA/molde (mayúsculas, trazos rectos/simples, sin
# bucles cursivos) — usado por los estilos con ``letterform: "print_caps"``.
# A diferencia de ``_LETTERS``/``_CAPITALS`` (una sola pluma que se encadena),
# cada letra aquí se escribe como en un formulario: se levanta la pluma entre
# trazos. ``pts`` es el primer trazo; ``marks`` son trazos adicionales sueltos
# de la misma letra (barras, patas, diagonales) — reutiliza el mecanismo ya
# usado para el punto de la "i" o el travesaño de la "t" cursiva. Espacio
# normalizado: línea base y=0, altura de mayúscula y=1.0.
_PRINT_LETTERS: dict[str, dict] = {
    "a": {"adv": 0.72, "pts": [(0, 0), (0.31, 1.0), (0.62, 0)],
          "marks": [[(0.16, 0.35), (0.47, 0.35)]]},
    "b": {"adv": 0.62, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.42, 0.95), (0.48, 0.78), (0.40, 0.55), (0, 0.52)],
                    [(0, 0.52), (0.46, 0.48), (0.52, 0.22), (0.40, 0.02), (0, 0)]]},
    "c": {"adv": 0.60, "pts": [(0.55, 0.85), (0.25, 1.0), (0, 0.7), (0, 0.3), (0.25, 0), (0.55, 0.15)]},
    "d": {"adv": 0.62, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.35, 0.97), (0.55, 0.75), (0.55, 0.25), (0.35, 0.03), (0, 0)]]},
    "e": {"adv": 0.58, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.5, 1.0)], [(0, 0.52), (0.4, 0.52)], [(0, 0), (0.5, 0)]]},
    "f": {"adv": 0.56, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.5, 1.0)], [(0, 0.52), (0.4, 0.52)]]},
    "g": {"adv": 0.62, "pts": [(0.55, 0.85), (0.25, 1.0), (0, 0.7), (0, 0.3), (0.25, 0), (0.60, 0), (0.60, 0.05)],
          "marks": [[(0.60, 0.4), (0.32, 0.4)]]},
    "h": {"adv": 0.62, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0.5, 0), (0.5, 1.0)], [(0, 0.52), (0.5, 0.52)]]},
    "i": {"adv": 0.30, "pts": [(0, 0), (0, 1.0)]},
    "j": {"adv": 0.48, "pts": [(0.4, 1.0), (0.4, 0.25), (0.30, 0.03), (0.12, 0), (0, 0.15)]},
    "k": {"adv": 0.60, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 0.5), (0.5, 1.0)], [(0, 0.5), (0.5, 0)]]},
    "l": {"adv": 0.54, "pts": [(0, 1.0), (0, 0), (0.45, 0)]},
    "m": {"adv": 0.82, "pts": [(0, 0), (0, 1.0), (0.35, 0.35), (0.7, 1.0), (0.7, 0)]},
    "n": {"adv": 0.66, "pts": [(0, 0), (0, 1.0), (0.55, 0), (0.55, 1.0)]},
    "o": {"adv": 0.66, "pts": [(0.3, 1.0), (0.55, 0.85), (0.62, 0.5), (0.55, 0.15), (0.3, 0),
                               (0.05, 0.15), (0, 0.5), (0.05, 0.85), (0.3, 1.0)]},
    "p": {"adv": 0.58, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.45, 0.95), (0.52, 0.75), (0.45, 0.58), (0, 0.55)]]},
    "q": {"adv": 0.68, "pts": [(0.3, 1.0), (0.55, 0.85), (0.62, 0.5), (0.55, 0.15), (0.3, 0),
                               (0.05, 0.15), (0, 0.5), (0.05, 0.85), (0.3, 1.0)],
          "marks": [[(0.35, 0.18), (0.62, -0.12)]]},
    "r": {"adv": 0.60, "pts": [(0, 0), (0, 1.0)],
          "marks": [[(0, 1.0), (0.45, 0.95), (0.52, 0.75), (0.45, 0.58), (0, 0.55)],
                    [(0.15, 0.55), (0.55, 0)]]},
    "s": {"adv": 0.56, "pts": [(0.55, 0.85), (0.30, 1.0), (0.05, 0.85), (0.05, 0.65), (0.30, 0.5),
                               (0.55, 0.35), (0.55, 0.15), (0.30, 0), (0.05, 0.15)]},
    "t": {"adv": 0.58, "pts": [(0, 1.0), (0.55, 1.0)],
          "marks": [[(0.28, 1.0), (0.28, 0)]]},
    "u": {"adv": 0.66, "pts": [(0, 1.0), (0, 0.3), (0.10, 0.05), (0.30, 0), (0.50, 0.05), (0.60, 0.3), (0.60, 1.0)]},
    "v": {"adv": 0.66, "pts": [(0, 1.0), (0.30, 0), (0.60, 1.0)]},
    "w": {"adv": 0.86, "pts": [(0, 1.0), (0.20, 0), (0.40, 0.65), (0.60, 0), (0.80, 1.0)]},
    "x": {"adv": 0.60, "pts": [(0, 1.0), (0.55, 0)],
          "marks": [[(0, 0), (0.55, 1.0)]]},
    "y": {"adv": 0.60, "pts": [(0, 1.0), (0.28, 0.5), (0.28, 0)],
          "marks": [[(0.56, 1.0), (0.28, 0.5)]]},
    "z": {"adv": 0.60, "pts": [(0, 1.0), (0.55, 1.0), (0, 0), (0.55, 0)]},
}

_ASCENDERS = set("bdfhklt")
_DESCENDERS = set("gjpqyz")

# Garabato: sustituto rítmico de una letra en los estilos abreviados; conserva
# el perfil del nombre (ascendente → pico, descendente → caída, resto → onda).
_SCRIBBLE = {
    "asc": {"adv": 0.34, "pts": [(0, 0.1), (0.12, 1.45), (0.20, 1.5), (0.26, 0.12)]},
    "desc": {"adv": 0.34, "pts": [(0, 0.1), (0.10, 0.6), (0.16, -0.65), (0.24, -0.6), (0.30, 0.1)]},
    "mid": {"adv": 0.30, "pts": [(0, 0.1), (0.10, 0.78), (0.18, 0.82), (0.26, 0.12)]},
}


def _letter_shape(char_lower: str) -> dict | None:
    return _LETTERS.get(char_lower)


def _decompose(char: str) -> tuple[str, list[str]]:
    """'á' -> ('a', ['acute']); 'ñ' -> ('n', ['tilde']); 'ü' -> ('u', ['dots'])."""
    accents = []
    base = char
    for c in unicodedata.normalize("NFD", char):
        if c == "́":
            accents.append("acute")
        elif c == "̃":
            accents.append("tilde")
        elif c == "̈":
            accents.append("dots")
        elif not unicodedata.combining(c):
            base = c
    return base, accents


def _accent_marks(kind: str, x: float, top: float) -> list[list[tuple[float, float]]]:
    if kind == "acute":
        return [[(x + 0.10, top + 0.25), (x + 0.28, top + 0.50)]]
    if kind == "tilde":
        return [[(x - 0.02, top + 0.28), (x + 0.14, top + 0.45),
                 (x + 0.28, top + 0.28), (x + 0.44, top + 0.45)]]
    if kind == "dots":
        return [[(x + 0.05, top + 0.30), (x + 0.07, top + 0.36)],
                [(x + 0.30, top + 0.30), (x + 0.32, top + 0.36)]]
    return []


# ---------------------------------------------------------------------------
# Construcción del trazo
# ---------------------------------------------------------------------------

def _catmull_rom(points: list[tuple[float, float]],
                 density: float = 26.0) -> list[tuple[float, float]]:
    """Muestrea una spline Catmull-Rom centrípeta que pasa por ``points``."""
    if len(points) < 3:
        return list(points)
    pts = [points[0]] + list(points) + [points[-1]]
    out: list[tuple[float, float]] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]

        def tj(ti, pa, pb):
            return ti + max(math.dist(pa, pb), 1e-6) ** 0.5

        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        n = max(3, min(18, int(math.dist(p1, p2) * density)))
        for s in range(n):
            t = t1 + (t2 - t1) * s / n
            a1 = tuple((t1 - t) / (t1 - t0) * p0[k] + (t - t0) / (t1 - t0) * p1[k] for k in (0, 1))
            a2 = tuple((t2 - t) / (t2 - t1) * p1[k] + (t - t1) / (t2 - t1) * p2[k] for k in (0, 1))
            a3 = tuple((t3 - t) / (t3 - t2) * p2[k] + (t - t2) / (t3 - t2) * p3[k] for k in (0, 1))
            b1 = tuple((t2 - t) / (t2 - t0) * a1[k] + (t - t0) / (t2 - t0) * a2[k] for k in (0, 1))
            b2 = tuple((t3 - t) / (t3 - t1) * a2[k] + (t - t1) / (t3 - t1) * a3[k] for k in (0, 1))
            c = tuple((t2 - t) / (t2 - t1) * b1[k] + (t - t1) / (t2 - t1) * b2[k] for k in (0, 1))
            out.append(c)
    out.append(points[-1])
    return out


def _scale_letter(shape: dict, capital: bool,
                  amp: float) -> tuple[list[tuple[float, float]], float, list]:
    """Aplica amplitud de asc/desc y agrandado de mayúscula a un esqueleto."""
    pts = shape["pts"]
    marks = [list(m) for m in shape.get("marks", [])]
    max_y = max(y for _, y in pts)

    sy_up = amp
    sx = 1.0
    if capital:
        target = 1.8
        sy_up *= target / max_y if max_y > 0 else 1.0
        sx = 1.3

    def f(p):
        x, y = p
        if y > 1.0:
            y = 1.0 + (y - 1.0) * sy_up
        elif capital and y > 0:
            y = y * sy_up
        elif y < 0:
            y = y * amp
        return (x * sx, y)

    return [f(p) for p in pts], shape["adv"] * sx, [[f(p) for p in m] for m in marks]


def _gesture_raw_strokes(nombre: str, estilo: dict,
                         rng: random.Random) -> list[list[tuple[float, float]]]:
    """Trazos crudos de una firma GESTUAL: no se escriben letras, se imita la
    anatomía de una firma real rápida (como la de referencia de Edwin): un
    núcleo compacto de trazos veloces derivado de la inicial, grandes lazos
    horizontales aplanados (lentes) que lo envuelven, rayas cruzadas, nudos y
    óvalos. Los componentes se eligen por estilo (``estilo["gesture"]``) y sus
    proporciones varían de forma determinista con la semilla del nombre.

    Espacio: el núcleo vive en x ∈ [0, ~1.3]; los lazos se extienden hasta
    x ~3.2 y por la izquierda hasta ~-0.7. Línea base y=0.
    """
    parts = estilo["gesture"]
    strokes: list[list[tuple[float, float]]] = []

    def r(a: float, b: float) -> float:
        return rng.uniform(a, b)

    primera = (nombre.split() or ["x"])[0]
    ini = primera[0].lower()
    shape = _CAPITALS.get(ini) or _LETTERS.get(ini) or _LETTERS["s"]

    if "initial" in parts:
        # La inicial dibujada a toda velocidad: comprimida, distorsionada y
        # con el trazo alargado al entrar y salir.
        d = 0.10
        pts = [(x * r(1.0, 1.25), y * r(0.70, 0.88)) for x, y in shape["pts"]]
        pts = [(x + r(-d, d), y + r(-d, d)) for x, y in pts]
        pts = [(-0.25, r(-0.1, 0.15))] + pts + [(pts[-1][0] + 0.45, pts[-1][1] + r(-0.1, 0.2))]
        strokes.append(pts)

    if "zigzag_core" in parts:
        # Núcleo de picos rápidos derivado del perfil REAL del nombre (mismo
        # criterio que el garabato de "ejecutiva": ascendente -> pico alto,
        # descendente -> caída bajo la base, resto -> onda media) en vez de
        # dientes uniformes — así dos nombres con la misma cantidad de letras
        # dan siluetas bien distintas, no solo el mismo zigzag repetido.
        letras = (primera.lower() or "x")[:6]
        n = max(3, len(letras))
        pts = [(0.0, 0.1)]
        for i in range(n):
            ch = letras[i % len(letras)]
            if ch in _ASCENDERS:
                peak = r(1.15, 1.45)
            elif ch in _DESCENDERS:
                peak = r(-0.55, -0.28)
            else:
                peak = r(0.55, 0.85)
            pts.append((0.12 + i * 0.24, peak))
            pts.append((0.24 + i * 0.24, 0.02 + r(-0.08, 0.08)))
        strokes.append(pts)

    if "knot" in parts:
        # Nudo: dos vueltas apretadas alrededor del núcleo (cicloide densa).
        kx, ky = r(0.45, 0.7), r(0.35, 0.5)
        r0 = r(0.24, 0.32)
        pts = []
        steps = 52
        for i in range(steps + 1):
            th = i / steps * 2 * math.tau
            pts.append((kx + 0.085 * th - r0 * math.sin(th),
                        ky + 0.62 * r0 * math.cos(th)))
        strokes.append(pts)

    if "oval_core" in parts:
        # Óvalo rápido alrededor del núcleo, abierto (como en la referencia).
        cx, cy = r(0.5, 0.75), r(0.35, 0.5)
        rx, ry = r(0.75, 0.95), r(0.42, 0.58)
        start = r(2.4, 2.9)
        arc = math.radians(r(320, 345))
        pts = []
        for i in range(41):
            th = start + arc * i / 40
            pts.append((cx + rx * math.cos(th), cy + ry * math.sin(th)))
        strokes.append(pts)

    if "slashes" in parts:
        # Dos rayas diagonales paralelas cruzando el núcleo, de un tirón.
        bx = r(0.65, 0.9)
        tilt = r(0.22, 0.38)
        for k in (0.0, r(0.22, 0.3)):
            x0s, y0s = bx + k, -0.25 + r(-0.06, 0.06)
            x1s, y1s = bx + k + tilt, 1.25 + r(-0.1, 0.15)
            strokes.append([(x0s, y0s), ((x0s + x1s) / 2, (y0s + y1s) / 2), (x1s, y1s)])

    if "lens" in parts:
        # Gran lazo-lente: barre a la derecha, gira y regresa por debajo
        # hasta pasar a la izquierda del núcleo. El sello de la referencia.
        wl = r(2.4, 3.1)
        tip_y = r(0.08, 0.18)
        strokes.append([
            (0.45, r(0.25, 0.38)),
            (1.4, r(0.5, 0.68)),
            (wl, r(0.3, 0.42)),
            (wl + 0.5, tip_y),          # punta afilada del lente
            (wl + 0.38, tip_y - 0.06),
            (1.6, r(-0.16, -0.05)),
            (0.2, r(-0.04, 0.06)),
            (-0.6, r(0.12, 0.28)),
        ])

    if "lens_under" in parts:
        # Segundo lazo, más bajo y contrapuesto: juntos forman el "ocho"
        # horizontal aplastado de las firmas gestuales.
        wl = r(2.3, 2.9)
        strokes.append([
            (-0.5, r(0.0, 0.12)),
            (0.9, r(-0.38, -0.26)),
            (wl, r(-0.2, -0.08)),
            (wl + 0.45, r(0.02, 0.12)),
            (1.4, r(0.2, 0.34)),
            (0.0, r(0.04, 0.15)),
        ])

    if "lens_high" in parts:
        # Lazo que vuela por encima del núcleo y aterriza a la izquierda.
        wl = r(2.2, 2.9)
        strokes.append([
            (0.3, r(0.6, 0.8)),
            (1.2, r(1.35, 1.65)),
            (wl, r(1.0, 1.3)),
            (wl + 0.4, r(0.35, 0.55)),
            (1.7, r(0.0, 0.15)),
            (0.3, r(0.15, 0.3)),
            (-0.5, r(0.5, 0.7)),
        ])

    return strokes


def build_signature_strokes(nombre: str, estilo: dict) -> list[list[tuple[float, float, float]]]:
    """Construye la firma como trazos ``[(x, y, grosor), ...]`` en espacio
    normalizado (línea base y=0, altura x=1, Y hacia arriba).

    Determinista: mismo nombre + estilo → mismos trazos exactos.
    """
    rng = random.Random(_seed(nombre, estilo["id"]))
    amp = estilo["amp"]
    keep = estilo["keep"]

    # Decisión de producto: la firma se dibuja SOLO con el primer nombre
    # ("Juan Sebastián Acosta" firma como "Juan"). Los estilos de monograma
    # (scope="initials") usan únicamente la inicial de ese primer nombre.
    scope = estilo.get("scope", "first")
    palabras = nombre.split()[:1]
    if scope == "initials" and palabras:
        palabras = [palabras[0][0].upper()]

    strokes_pts: list[list[tuple[float, float]]] = []  # trazos crudos (sin grosor)
    marks_pts: list[list[tuple[float, float]]] = []

    if estilo.get("gesture"):
        # Firma gestual abstracta (no letras): núcleo rápido + lazos + rayas.
        strokes_pts = _gesture_raw_strokes(nombre, estilo, rng)
        palabras = []

    # ``connected`` False = letra "normal"/imprenta: se levanta la pluma entre
    # letras (cada una es su trazo propio) en vez de encadenarlas en un único
    # trazo cursivo continuo. Reutiliza los mismos esqueletos de ``_LETTERS``.
    # ``letterform: "print_caps"`` va más allá: usa un alfabeto de letra molde
    # en mayúsculas (``_PRINT_LETTERS``, trazos rectos, sin bucles cursivos) en
    # vez de las formas cursivas — de ahí sí se ve "letra normal", no cursiva
    # desconectada. Siempre implica pluma levantada entre letras.
    print_mode = estilo.get("letterform") == "print_caps"
    connected = estilo.get("connected", True) and not print_mode

    cursor = 0.0
    # respiro entre letras (más aire en monogramas y en letra suelta/imprenta)
    if scope == "initials":
        gap = 0.30
    elif print_mode:
        gap = 0.20
    elif not connected:
        gap = 0.16
    else:
        gap = 0.10

    for word in palabras:
        word_pts: list[tuple[float, float]] = []
        for idx, char in enumerate(word):
            base, accents = _decompose(char)

            if print_mode:
                shape = _PRINT_LETTERS.get(base.lower())
                if shape is None:
                    cursor += 0.3
                    continue
                pts = [(x, y * amp) for x, y in shape["pts"]]
                marks = [[(x, y * amp) for x, y in m] for m in shape.get("marks", [])]
                adv = shape["adv"]
                legible = True
            else:
                shape = _letter_shape(base.lower())
                if shape is None:
                    cursor += 0.3
                    continue

                legible = keep is None or idx < keep
                if not legible:
                    lo = base.lower()
                    kind = "asc" if lo in _ASCENDERS else "desc" if lo in _DESCENDERS else "mid"
                    sc = _SCRIBBLE[kind]
                    pts, adv, marks = [(x, y * amp) for x, y in sc["pts"]], sc["adv"], []
                elif base.isupper() and base.lower() in _CAPITALS:
                    # forma capital propia, ya viene a altura de mayúscula
                    pts, adv, marks = _scale_letter(_CAPITALS[base.lower()], False, amp)
                else:
                    pts, adv, marks = _scale_letter(shape, base.isupper(), amp)

            letter_pts = [(cursor + x, y) for x, y in pts]
            if connected:
                word_pts.extend(letter_pts)
            elif letter_pts:
                strokes_pts.append(letter_pts)
            for m in marks:
                marks_pts.append([(cursor + x, y) for x, y in m])
            if legible:
                top = max(y for _, y in pts)
                for kind in accents:
                    marks_pts.extend(
                        [[(cursor + x, y) for x, y in m] for m in _accent_marks(kind, 0.1, top)]
                    )
            cursor += adv + gap
        if connected and word_pts:
            strokes_pts.append(word_pts)
        cursor += 0.45  # espacio entre palabras (con levantada de pluma)

    slant = math.tan(math.radians(estilo["slant"]))
    jitter = estilo["jitter"]
    base_w = estilo["width"]
    press = estilo["press"]

    def wobble(phase_a, phase_b, t):
        return (math.sin(t * 5.1 + phase_a) + 0.6 * math.sin(t * 11.7 + phase_b)) / 1.6

    result: list[list[tuple[float, float, float]]] = []
    for raw in strokes_pts + marks_pts:
        sampled = _catmull_rom(raw)
        pa, pb = rng.uniform(0, math.tau), rng.uniform(0, math.tau)
        pc, pd = rng.uniform(0, math.tau), rng.uniform(0, math.tau)
        out: list[tuple[float, float, float]] = []
        arc = 0.0
        for i, (x, y) in enumerate(sampled):
            if i > 0:
                arc += math.dist(sampled[i - 1], (x, y))
            # temblor de mano suave y determinista
            jx = jitter * wobble(pa, pb, arc)
            jy = jitter * wobble(pc, pd, arc)
            # presión: bajadas de pluma más gruesas, subidas más finas
            if 0 < i < len(sampled) - 1:
                dx = sampled[i + 1][0] - sampled[i - 1][0]
                dy = sampled[i + 1][1] - sampled[i - 1][1]
                ds = math.hypot(dx, dy) or 1e-6
                downness = max(0.0, -dy / ds)
                upness = max(0.0, dy / ds)
            else:
                downness = upness = 0.0
            w = base_w * (1.0 + press * downness - 0.45 * press * upness)
            out.append((x + y * slant + jx, y + jy, max(w, base_w * 0.35)))
        result.append(out)

    # Rúbrica bajo la firma y decoraciones extra, también como trazos dibujados.
    result.extend(_rubric_strokes(nombre, estilo, result))
    result.extend(_deco_strokes(nombre, estilo, result))
    return result


def _rubric_strokes(
    nombre: str, estilo: dict, strokes: list[list[tuple[float, float, float]]],
) -> list[list[tuple[float, float, float]]]:
    kind = estilo["rubric"]
    if kind == "none" or not strokes:
        return []

    s = _seed(nombre, estilo["id"])
    r1 = (s & 0xFFFF) / 0xFFFF
    r2 = ((s >> 16) & 0xFFFF) / 0xFFFF
    r3 = ((s >> 32) & 0xFFFF) / 0xFFFF

    xs = [p[0] for st in strokes for p in st]
    x0, x1 = min(xs), max(xs)
    width = x1 - x0
    base = -0.45  # bajo la línea base
    w = estilo["width"] * 0.9

    def bez(p0, p1, p2, p3, steps=48):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            pts.append((x, y, w))
        return pts

    if kind == "underline":
        dip = 0.15 + 0.15 * r1
        rise = 0.08 + 0.10 * r2
        return [bez(
            (x0 - width * 0.05, base),
            (x0 + width * (0.25 + 0.1 * r3), base - dip),
            (x0 + width * (0.65 + 0.1 * r1), base + rise),
            (x1 + width * 0.07, base - rise * 0.4),
        )]

    # "loop": subrayado que remata en un lazo al final.
    dip = 0.18 + 0.15 * r1
    loop_w = width * (0.08 + 0.05 * r2)
    first = bez(
        (x0 - width * 0.03, base),
        (x0 + width * 0.3, base - dip),
        (x0 + width * (0.55 + 0.1 * r3), base + dip * 0.5),
        (x1 + width * 0.02, base),
    )
    second = bez(
        (x1 + width * 0.02, base),
        (x1 + loop_w * 1.6, base + 0.45),
        (x1 - loop_w * 1.6, base + 0.50),
        (x1 - loop_w * 2.6, base - dip * 0.4),
    )
    return [first + second]


def _sample_bezier(p0, p1, p2, p3, w: float, steps: int = 48) -> list[tuple[float, float, float]]:
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y, w))
    return pts


def _deco_strokes(
    nombre: str, estilo: dict, strokes: list[list[tuple[float, float, float]]],
) -> list[list[tuple[float, float, float]]]:
    """Trazos decorativos que convierten la firma en un diseño único: óvalo
    envolvente, tachado sutil, espiral final, lazo aéreo o zigzag enérgico.
    Deterministas (semilla propia derivada de nombre+estilo)."""
    decos = estilo.get("deco", [])
    if not decos or not strokes:
        return []

    rng = random.Random(_seed(nombre, estilo["id"] + "|deco"))
    x0, y0, x1, y1 = _bounds(strokes)
    span = max(x1 - x0, 1e-6)
    cy = (y0 + y1) / 2
    w = estilo["width"] * 0.85
    out: list[list[tuple[float, float, float]]] = []

    for kind in decos:
        if kind == "oval":
            # Óvalo a mano alzada alrededor de la firma, abierto y con leve
            # ondulación: el clásico marco de las firmas latinoamericanas.
            cx = (x0 + x1) / 2
            rx = span / 2 + 0.55
            ry = (y1 - y0) / 2 + 0.42
            tilt = math.radians(rng.uniform(-6, -2))
            start = rng.uniform(2.7, 3.1)
            arc = math.radians(rng.uniform(332, 352))
            ph = rng.uniform(0, math.tau)
            pts = []
            n = 90
            for i in range(n + 1):
                th = start + arc * i / n
                wob = 1.0 + 0.035 * math.sin(3.0 * th + ph)
                ex, ey = rx * math.cos(th) * wob, ry * math.sin(th) * wob
                # rotación leve del óvalo completo
                rxx = ex * math.cos(tilt) - ey * math.sin(tilt)
                ryy = ex * math.sin(tilt) + ey * math.cos(tilt)
                taper = 0.55 + 0.45 * math.sin(math.pi * i / n)  # pluma que entra y sale
                pts.append((cx + rxx, cy + ryy, w * taper))
            out.append(pts)
        elif kind == "strike":
            # Tachado sutil en diagonal a media altura, de un solo golpe.
            out.append(_sample_bezier(
                (x0 - 0.15, cy + 0.30),
                ((x0 + x1) / 2, cy + 0.55),
                ((x0 + x1) / 2, cy - 0.45),
                (x1 + 0.30, cy - 0.05),
                w,
            ))
        elif kind == "spiral":
            # Espiral que remata la firma por la derecha, cerrándose hacia
            # adentro como un latigazo final de la pluma.
            scx, scy = x1 + 0.65, 0.35
            r0 = 0.55 * estilo["amp"]
            turns = rng.uniform(2.2, 2.8)
            pts = []
            n = 80
            for i in range(n + 1):
                t = i / n
                r = r0 * (1 - 0.85 * t)
                th = -math.pi / 2 + turns * math.tau * t
                pts.append((scx + r * math.cos(th), scy + 0.75 * r * math.sin(th),
                            w * (1.15 - 0.5 * t)))
            out.append(pts)
        elif kind == "overloop":
            # Lazo aéreo: un arco amplio que nace en la primera letra, vuela
            # por encima del nombre y aterriza con un ganchito al final.
            top = y1 + 0.30
            dome = _sample_bezier(
                (x0 + 0.15, 1.0),
                (x0 + span * 0.20, top + 0.95),
                (x0 + span * 0.80, top + 1.05),
                (x1 + 0.40, 0.55),
                w * 0.9,
            )
            hook = _sample_bezier(
                (x1 + 0.40, 0.55),
                (x1 + 0.75, 0.10),
                (x1 + 0.50, -0.40),
                (x1 + 0.05, -0.20),
                w * 0.9,
                steps=24,
            )
            out.append(dome + hook)
        elif kind == "zigzag":
            # Zigzag enérgico bajo el monograma, con picos irregulares.
            n_peaks = 4
            pts = [(x0 - 0.15, -0.35, w)]
            for i in range(n_peaks):
                t = (i + 0.5) / n_peaks
                px = x0 - 0.15 + (span + 0.45) * t
                py = -0.85 + rng.uniform(-0.08, 0.08)
                pts.append((px, py, w * 1.15))
                px2 = x0 - 0.15 + (span + 0.45) * (i + 1) / n_peaks
                pts.append((px2, -0.35 + rng.uniform(-0.06, 0.06), w))
            out.append(pts)
        elif kind == "sweep":
            # Barrido horizontal larguísimo que entra por la izquierda,
            # atraviesa el nombre a media altura y sale por la derecha
            # (el gesto del logo caligráfico de referencia).
            y_line = 0.32
            out.append(_sample_bezier(
                (x0 - 1.15, y_line - 0.12),
                (x0 + span * 0.30, y_line + 0.16),
                (x1 - span * 0.20, y_line - 0.14),
                (x1 + 1.30, y_line + 0.28),
                w * 0.75,
                steps=64,
            ))
        elif kind == "dot":
            # Punto final de la firma, como al rematar con el bolígrafo.
            out.append([(x1 + 0.38, 0.03, w * 1.4)])
        elif kind == "curls":
            # Remate en bucles rizados decrecientes que se alejan a la
            # derecha (cicloide con radio en decaimiento) y cola final.
            n_loops = 3
            steps = n_loops * 26
            sx, cy = x1 + 0.10, 0.30
            r0 = 0.34
            v = 0.052  # avance horizontal por radián (< radio ⇒ rulos cerrados)
            pts = []
            for i in range(steps + 1):
                th = i / steps * n_loops * math.tau
                r = r0 * math.exp(-0.10 * th)
                pts.append((sx + v * th - r * math.sin(th),
                            cy - r * math.cos(th), w))
            # cola final que se estira hacia la derecha
            ex, ey, _ = pts[-1]
            pts.extend([(ex + 0.35, ey + 0.05, w), (ex + 0.85, ey - 0.10, w * 0.8)])
            out.append(pts)
        elif kind == "double_underline":
            # Doble subrayado con onda, el segundo más corto y abajo.
            out.append(_sample_bezier(
                (x0 - 0.10, -0.42),
                (x0 + span * 0.35, -0.62),
                (x0 + span * 0.70, -0.26),
                (x1 + 0.55, -0.48),
                w,
            ))
            out.append(_sample_bezier(
                (x0 + span * 0.18, -0.68),
                (x0 + span * 0.45, -0.82),
                (x0 + span * 0.75, -0.58),
                (x1 + 0.25, -0.72),
                w * 0.9,
                steps=32,
            ))

    return out


# ---------------------------------------------------------------------------
# Render: preview PNG (Pillow)
# ---------------------------------------------------------------------------

_PREVIEW_W = 600
_PREVIEW_H = 200
_PREVIEW_MARGIN = 36


def _bounds(strokes: list[list[tuple[float, float, float]]]) -> tuple[float, float, float, float]:
    xs = [p[0] for st in strokes for p in st]
    ys = [p[1] for st in strokes for p in st]
    return min(xs), min(ys), max(xs), max(ys)


def render_preview_png(nombre: str, estilo: dict, width: int = _PREVIEW_W,
                       height: int = _PREVIEW_H) -> bytes:
    """PNG (fondo blanco) de la firma dibujada. Renderiza con supersampling x3
    porque las líneas de Pillow no llevan antialiasing propio."""
    strokes = build_signature_strokes(nombre, estilo)
    x0, y0, x1, y1 = _bounds(strokes)
    span_x = max(x1 - x0, 1e-6)
    span_y = max(y1 - y0, 1e-6)

    ss = 3
    w_px, h_px = width * ss, height * ss
    margin = _PREVIEW_MARGIN * ss
    scale = min((w_px - 2 * margin) / span_x, (h_px - 2 * margin) / span_y)
    off_x = (w_px - span_x * scale) / 2
    off_y = (h_px - span_y * scale) / 2

    img = Image.new("RGB", (w_px, h_px), "white")
    draw = ImageDraw.Draw(img)
    ink = estilo["ink"]

    for stroke in strokes:
        pix = [((x - x0) * scale + off_x, (y1 - y) * scale + off_y, wd * scale)
               for x, y, wd in stroke]
        if len(pix) == 1:
            x, y, wd = pix[0]
            draw.ellipse([x - wd, y - wd, x + wd, y + wd], fill=ink)
            continue
        for (ax, ay, aw), (bx, by, bw) in zip(pix, pix[1:]):
            lw = max(1, round((aw + bw) / 2))
            draw.line([(ax, ay), (bx, by)], fill=ink, width=lw)
            # tapones redondos para que los cambios de grosor no dejen escalones
            r = lw / 2
            draw.ellipse([bx - r, by - r, bx + r, by + r], fill=ink)

    img = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generar_opciones(nombre: str) -> list[dict]:
    """Galería de diseños de firma dibujados para ``nombre``: uno por estilo,
    cada uno como PNG en base64 listo para mostrar en un ``<img src=...>``."""
    opciones = []
    for estilo in SIGNATURE_STYLES:
        png = render_preview_png(nombre, estilo)
        opciones.append({
            "estilo_id": estilo["id"],
            "nombre_estilo": estilo["label"],
            "formato": "image/png",
            "imagen_base64": base64.b64encode(png).decode("ascii"),
        })
    return opciones


# ---------------------------------------------------------------------------
# Render: estampado final sobre el PDF (reportlab, vectorial)
# ---------------------------------------------------------------------------

def draw_signature(c, nombre: str, estilo: dict, x: float, y: float,
                   width: float, height: float) -> None:
    """Dibuja la firma en el canvas de reportlab DENTRO de la caja cuyo
    vértice inferior-izquierdo es ``(x, y)`` (coordenadas PDF).

    La firma completa (con lazos, rúbricas y descendentes) se escala para
    caber en la caja y se centra en ambos ejes — así nunca pisa la línea de
    firma ni se sale del corchete "Firmado por:" de la plantilla, igual que
    hace FirmaCloud con ``scaleToFit`` en ``pdfService.js``.

    Mismos trazos que el preview (mismo builder determinista), como vectores
    del PDF: nítidos a cualquier zoom.
    """
    strokes = build_signature_strokes(nombre, estilo)
    x0, y0, x1, y1 = _bounds(strokes)
    span_x = max(x1 - x0, 1e-6)
    span_y = max(y1 - y0, 1e-6)

    scale = min(width / span_x, height / span_y)
    off_x = x + (width - span_x * scale) / 2
    # Anclada al fondo de la caja (no centrada): la firma se apoya justo
    # encima de la línea de firma, como en el PDF de ejemplo.
    off_y = y

    ink = Color(*(v / 255 for v in estilo["ink"]))
    c.saveState()
    c.setStrokeColor(ink)
    c.setFillColor(ink)
    c.setLineCap(1)
    c.setLineJoin(1)

    for stroke in strokes:
        pts = [((px - x0) * scale + off_x, (py - y0) * scale + off_y, wd * scale)
               for px, py, wd in stroke]
        if len(pts) == 1:
            px, py, wd = pts[0]
            c.circle(px, py, wd, stroke=0, fill=1)
            continue
        for (ax, ay, aw), (bx, by, bw) in zip(pts, pts[1:]):
            c.setLineWidth(max((aw + bw) / 2, 0.35))
            c.line(ax, ay, bx, by)

    c.restoreState()
