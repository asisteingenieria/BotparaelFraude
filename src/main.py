"""Orquestador: Excel -> documentos estampados en output/documentos.

Uso:
    python -m src.main data/plantilla_datos.xlsx
    python -m src.main data/plantilla_datos.xlsx --template "templates/Obamacare  B2.pdf" --output output/documentos
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.firma_generator import SelectorDeEstilos
from src.ingesta import leer_excel
from src.pdf_stamper import stamp_pdf
from src.summary import PoolDeIPs, generar_summary

DEFAULT_TEMPLATE = "templates/Obamacare  B2.pdf"
DEFAULT_OUTPUT_DIR = "output/documentos"


def _nombre_archivo(datos: dict, usados: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9 _-]", "", datos["nombre_completo"]).strip().replace(" ", "_")
    base = base or "documento"
    nombre = f"{base}.pdf"
    contador = 2
    while nombre in usados:
        nombre = f"{base}_{contador}.pdf"
        contador += 1
    usados.add(nombre)
    return nombre


def procesar(excel_path: str, template_path: str, output_dir: str) -> int:
    resultado = leer_excel(excel_path)

    if resultado.columnas_no_mapeadas:
        print("Aviso: columnas del Excel sin destino conocido (se ignoran):")
        for col in resultado.columnas_no_mapeadas:
            print(f"  - {col}")

    for invalida in resultado.invalidas:
        print(f"Fila {invalida.numero_fila} omitida: {invalida.motivo}")

    if not resultado.registros:
        print("No hay filas válidas para procesar.")
        return 1

    usados: set[str] = set()
    selector = SelectorDeEstilos()  # nombre repetido -> diseño distinto
    pool_ips = PoolDeIPs()  # una IP por titular, sin repetir dentro de este lote
    generados = 0
    for datos in resultado.registros:
        datos["firma_nombre"] = datos["nombre_completo"]
        datos["firma_estilo_id"] = selector.elegir(datos["nombre_completo"])
        datos["firma_id"] = str(uuid.uuid4())
        datos["firma_email"] = datos.get("email", "")
        fecha_digitacion = datos.get("fecha_digitacion", "")
        if fecha_digitacion:
            hora_aleatoria = f"{random.randint(9, 21):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
            datos["firma_fecha_hora"] = f"{fecha_digitacion} {hora_aleatoria}"
        else:
            datos["firma_fecha_hora"] = datetime.now(UTC).strftime("%m-%d-%Y %H:%M:%S")

        nombre_archivo = _nombre_archivo(datos, usados)
        salida = Path(output_dir) / nombre_archivo
        stamp_pdf(template_path, salida, datos)
        salida_summary = salida.with_name(f"{salida.stem}_Summary.pdf")
        generar_summary(datos, salida_summary, pool=pool_ips)
        print(f"Generado: {salida} (firma: {datos['firma_estilo_id']}) + {salida_summary.name}")
        generados += 1

    print(f"\nListo: {generados} documento(s) generado(s) en {output_dir}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Estampa datos de un Excel sobre la plantilla Obamacare.")
    parser.add_argument("excel", help="Ruta al Excel con los datos (una fila por persona).")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="Plantilla PDF en blanco a usar.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="Carpeta de salida para los PDF generados.")
    args = parser.parse_args()

    sys.exit(procesar(args.excel, args.template, args.output))


if __name__ == "__main__":
    main()
