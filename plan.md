# Plan detallado — Bot de automatización de plantillas desde Excel

## 1. Objetivo

Construir un bot que, a partir de un archivo Excel, reconozca automáticamente los
nombres de los campos (encabezados) y genere de forma masiva documentos con la
información colocada en el lugar correcto de una plantilla. El proceso debe ser lo
más automático posible: cargar el Excel, correr el bot y obtener un documento por
cada fila.

Incluye además una casilla de firma rellenada con un **placeholder de prueba**
(ver alcance más abajo), para validar que el maquetado del documento funciona.

---

## 2. Alcance de la funcionalidad de firma

Este proyecto **si** genera firmas manuscritas realistas de personas reales ni IDs
que imiten códigos de auditoría auténticos.

Lo que sí incluye, para pruebas de maquetado (QA), dos opciones legítimas:

- **Garabatos sintéticos de marcador de posición**: trazos generados de forma
  procedural, útiles para verificar que la firma cae en el
  recuadro correcto.




---

## 3. Stack tecnológico recomendado

**Lenguaje: Python.** Es el más adecuado por la madurez de sus librerías de Excel
y documentos y por lo sencillo que resulta automatizar el proceso.

| Necesidad | Librería | Notas |
|---|---|---|
| Leer Excel | `openpyxl` o `pandas` | Leen encabezados y filas; `pandas` es cómodo para validar y limpiar datos |
| Plantilla Word | `docxtpl` | Placeholders tipo `{{ nombre }}` dentro del `.docx` |
| Plantilla PDF (formulario) | `pypdf` / `pdfrw` | Rellena campos de formulario existentes |
| Plantilla PDF (plano) | `reportlab` + `pdfplumber` | Overlay de texto por coordenadas |
| Placeholder de firma | `Pillow` (PIL) | Render de fuente manuscrita o dibujo de trazos sintéticos |
| Exportar Word → PDF (opcional) | `docx2pdf` o LibreOffice headless | Para salida final en PDF |

La elección entre Word y PDF depende del formato de tu plantilla. **Word con
`docxtpl` es lo más limpio y mantenible** si tienes libertad de diseñar la
plantilla.

---

## 4. Flujo lógico general

```
Cargar Excel
   → Detectar encabezados
   → Mapear encabezados ↔ placeholders de la plantilla
   → Por cada fila:
        → Rellenar placeholders con los datos de la fila
        → Generar placeholder de firma (prueba) y colocarlo
        → Guardar documento (nombre derivado del Excel)
   → (Opcional) Exportar todo a PDF
```

---

## 5. Plan por fases

### Fase 1 — Ingesta de datos
- Cargar el archivo Excel.
- Detectar automáticamente la fila de encabezados.
- Validar filas: campos vacíos, tipos de dato, duplicados.
- Reportar filas inválidas en lugar de fallar en silencio.

### Fase 2 — Mapeo de campos
- Emparejar cada encabezado del Excel con su placeholder en la plantilla.
- Soportar dos modos:
  - **Automático:** coincidencia por nombre exacto (encabezado == placeholder).
  - **Configurable:** un diccionario/archivo de equivalencias
    (`"Nombre completo" → "nombre"`) para cuando no coinciden literalmente.
- Avisar de placeholders sin datos y de columnas sin destino.

### Fase 3 — Relleno del documento
- Iterar cada fila del Excel.
- Sustituir los placeholders con los valores correspondientes.
- Manejar formatos (fechas, montos, mayúsculas) según se requiera.

### Fase 4 — Placeholder de firma (versión de prueba)
- Por cada fila, generar la marca sintética dibujada.
- Colocarla en la posición configurada del documento (coordenadas o placeholder
  de imagen).


### Fase 5 — Salida
- Guardar un archivo por fila.
- Derivar el nombre de archivo de una columna del Excel (p. ej. ID + nombre).
- Opcional: exportar a PDF y/o comprimir todo en un `.zip`.
- Generar un log de resultados (qué se generó, qué falló y por qué).

---

## 6. Estructura de carpetas propuesta

```
bot_plantillas/
├── data/
│   ├── input.xlsx            # Excel de entrada
│   └── mapping.json          # (opcional) equivalencias encabezado→placeholder
├── templates/
│   └── plantilla.docx        # Plantilla con placeholders {{ ... }}
├── output/
│   └── documentos/           # Documentos generados
├── src/
│   ├── ingesta.py            # Fase 1: leer y validar Excel
│   ├── mapeo.py              # Fase 2: emparejar campos
│   ├── relleno.py            # Fase 3: rellenar plantilla
│   ├── firma_prueba.py       # Fase 4: placeholder de firma
│   ├── salida.py             # Fase 5: guardar/exportar
│   └── main.py               # Orquestador
├── requirements.txt
└── README.md
```

---

## 7. Configuración de campos (ejemplo de `mapping.json`)

```json
{
  "campos": {
    "Nombre completo": "nombre",
    "Cédula": "documento",
    "Fecha de emisión": "fecha"
  },
  "firma": {
    "modo": "fuente_manuscrita",
    "posicion": { "pagina": 1, "x": 120, "y": 640 },
    "etiqueta_prueba": true
  },
  "salida": {
    "nombre_archivo": "{documento}_{nombre}",
    "exportar_pdf": true
  }
}
```

---

## 8. Requisitos para arrancar

Para dejar el código base funcionando necesito de tu parte:

1. **Formato de la plantilla:** ¿Word (`.docx`) o PDF? ¿El PDF tiene campos de
   formulario o es plano?
2. **Ejemplo del Excel** (puede ser con datos ficticios) para ver los encabezados
   reales.
3. **Ejemplo de la plantilla** con las posiciones donde va cada dato.

Con esos tres insumos completo el mapeo real, la estructura y el código de cada
fase.

---

## 9. Dependencias iniciales (`requirements.txt`)

```
pandas
openpyxl
docxtpl
Pillow
pypdf
reportlab
```

(Se ajusta según el formato final de la plantilla.)

VEVE
.\.venv\Scripts\Activate.ps1