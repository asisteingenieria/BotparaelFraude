# Microservicio de firma FirmaCloud

Microservicio que genera diseños de firma **dibujados** a partir del nombre del
cliente: el cliente escribe su nombre, recibe una galería de diseños, elige uno
y ese se plasma en la casilla de firma de la última página del documento. Las
firmas no son fuentes tipográficas (eso ya lo hace FirmaCloud): son trazos de
pluma sintéticos — esqueletos cursivos por letra, splines, presión variable y
temblor de mano — generados proceduralmente en Python. Incluye además el
estampado masivo de plantillas desde Excel (funcionalidad original del bot).

## Requisitos

- Python 3.11+

## Configuración del entorno

```powershell
# Crear entorno virtual (una sola vez)
python -m venv .venv

# Activar entorno virtual (cada sesión de terminal)
.\.venv\Scripts\Activate.ps1

# Instalar dependencias (incluye herramientas de desarrollo)
pip install -r requirements-dev.txt
```

## Estructura

```
data/            Excel de entrada y mapping.json
templates/       Plantilla(s) con placeholders
output/          Documentos generados
src/             Código fuente (ingesta, mapeo, relleno, firma, salida)
tests/           Pruebas
```

## Uso

```powershell
python -m src.main data/plantilla_datos.xlsx
```

Genera un PDF por fila del Excel en `output/documentos/`, usando por defecto
la plantilla `templates/Obamacare  B2.pdf`. Cada fila sale **firmada** (con su
UUID, correo y fecha/hora): el diseño se elige rotando el catálogo por nombre —
si el mismo cliente aparece en varias filas, cada carta recibe un diseño
distinto para ver la variedad en las pruebas (`SelectorDeEstilos`). La API hace
lo mismo entre peticiones consecutivas con el mismo nombre. Opciones:

```powershell
python -m src.main data/mis_datos.xlsx --template "templates/Obamacare  B2.pdf" --output output/documentos
```

El Excel debe tener una fila por persona con encabezados en español (tolera
acentos/mayúsculas): `Nombres`, `Apellidos`, `Social`, `Numero Social`,
`Estatus migratorio`, `Estado`, `Direccion`, `Tipo vivienda`,
`Codigo postal`, `Telefono principal`, `Telefono adicional`,
`Tipo de ingresos`, `Ingresos totales`, `Email`, `Aseguradora`,
`Categoria y tipo de plan`, `Nombre de plan`, `Prima`, `Valor cotizacion`,
`Deducible`, `Gasto maximo bolsillo`, `Fecha de activacion`,
`Palabra de seguridad`, `Fecha` (fecha del consentimiento),
`Agente nombre`, `Agente NPN`, `Agente telefono`, `Agente email`, y
opcionalmente `Agencia nombre/NPN/propietario/telefono/email`,
`Contacto nombre/telefono/email` (si el contacto del hogar no es el mismo
titular) y `Beneficiario 1 nombre` / `Beneficiario 1 estatus` (hasta 6).
Ver `data/plantilla_datos.xlsx` como ejemplo funcional.

**Excel tipo CRM (una fila por persona):** si el Excel trae la columna
`tipo_solicitud` (`Cotizante`/`Beneficiario`), el bot agrupa por hogar en
vez de generar un documento por fila: cada `Cotizante` abre una carta y las
filas `Beneficiario` que le siguen (hasta el próximo `Cotizante`) se pliegan
como sus beneficiarios. También tolera varios alias de encabezado propios de
ese formato (`nombres y Apellidos` en un solo campo, `correo_electronico_
Cliente`, `numero_principal`, `FECHA ACTIVACION`, `valor cotizacion (dividir
48)`, `PLAN`, `Gasto max`, y el bloque de agente bajo `NPN `/`Número`/
`Número.1`/`Correo NPN`). Si además trae `Fecha Digitación`, esa fecha (no
la hora real de generación) alimenta el encabezado de correo+fecha/hora de
las cartas y el campo `Fecha:` del bloque de contacto del hogar, con una
hora aleatoria entre 9:00 y 21:00 ya que el Excel no trae hora — pensado
para lotes de prueba, no para producción con fecha/hora real de firma.

## API de firma

```powershell
python -m uvicorn src.api:app --reload --port 8000
```

- `POST /firmas/opciones` — body `{"nombre": "Juan Sebastián Acosta"}`.
  Devuelve la galería de 16 diseños:
  `[{estilo_id, nombre_estilo, imagen_base64}, ...]` (PNG en base64, listos
  para `<img src="data:image/png;base64,...">`). Los 7 primeros son firmas
  **gestuales** (imitan la anatomía de una firma real rápida — núcleo de
  trazos veloces derivado de la inicial, lazos horizontales aplanados, rayas
  cruzadas, nudos y óvalos — modeladas sobre la firma real de
  `templates/EDWIN AMAYA FONSECA.pdf`); el resto dibuja el primer nombre en
  cursiva con decoraciones (óvalo, barrido tipo logo, bucles).
- `POST /documentos` — body `DatosPersona` (ver `/docs`). Estampa la plantilla
  y **plasma la firma** del cliente (el primer nombre del campo `nombres`) en
  la casilla de firma de la **última página**. El diseño se elige con
  `firma_estilo_id` (un `estilo_id` de la galería); si no se envía, se elige
  **uno al azar** del catálogo en cada petición (modo pruebas) y el elegido se
  informa en el header de respuesta `X-Firma-Estilo`. La firma se escala y
  ancla dentro del corchete morado "Firmado por:", apoyada 1pt arriba de la
  línea de firma, con el ID truncado debajo — igual al PDF firmado de ejemplo.

  El PDF sale con el rastro de auditoría replicado del PDF firmado de ejemplo
  (`templates/EDWIN AMAYA FONSECA.pdf`): correo + fecha/hora arriba de las
  páginas de carta, `FirmaCloud ID: <UUID>` arriba de la última página y el
  código corto bajo la casilla de firma. El ID es un **UUID v4** (igual que lo
  genera FirmaCloud en `signatureController`) y también se devuelve en el
  header HTTP `X-Firma-Id`.

  Body mínimo para probar en Postman:

  ```json
  {
    "nombres": "Juan Sebastian",
    "apellidos": "Acosta",
    "email": "cliente@correo.com",
    "fecha": "08/25/2026",
    "firma_estilo_id": "gesto_oval",
    "firma_fecha_hora": "25-08-2026 14:30:12",
    "firma_id": ""
  }
  ```

  `firma_fecha_hora` vacío usa la hora actual UTC; `firma_id` vacío genera el
  UUID automáticamente (pásalo solo si quieres fijarlo en una prueba).

El diseño es determinista: `nombre + estilo_id` siempre producen el mismo
trazo (la semilla sale de `sha256(nombre|estilo)`), así que el preview elegido
y la firma estampada son idénticos sin guardar imágenes. Motor y catálogo de
estilos en `src/firma_generator.py` (dibujo procedural: esqueletos cursivos por
letra, splines Catmull-Rom, presión de pluma y rúbricas Bézier — sin fuentes).
La casilla de firma se declara en `signatureFields` del JSON de la plantilla
(`templates/config/obamacare_b2.json`).

## Módulo de auditoría (interfaz web + MySQL)

Pensado para que auditen el módulo: se cargan lotes grandes por Excel (p. ej.
2000 filas), el auditor elige cartas al azar y revisa tamaño, diseño de firma
y cómo se plasmó la información.

- **Interfaz**: con el servidor corriendo, abrir <http://127.0.0.1:8000/auditoria>.
  Permite subir el Excel (con barra de progreso), listar/filtrar las cartas
  gestionadas, pedir una **muestra aleatoria de N** y ver cada PDF embebido
  con sus metadatos (UUID, SHA-256, tamaño, diseño, fecha/hora).
- **Base de datos propia**: MySQL `bot_firmas` con usuario dedicado
  `botcartas` — separada por completo de la BD de FirmaCloud. Credenciales en
  `.env` (no versionado). Tablas: `cargas` (cada Excel subido, progreso y
  conteos) y `cartas` (una fila por carta: UUID de firma, cliente, correo,
  estilo, fecha/hora, ruta del PDF, tamaño en bytes y hash SHA-256 para
  probar integridad).
- **Endpoints**: `POST /cargas` (subir Excel, procesa en background),
  `GET /cargas`, `GET /cargas/{id}` (progreso), `GET /cartas` (paginado,
  filtros `carga_id`/`q`), `GET /cartas/muestra?n=10` (muestreo aleatorio) y
  `GET /cartas/{id}/pdf`. Las cartas generadas por `POST /documentos` también
  quedan registradas (origen `api`).
- Los PDF de cada lote quedan en `output/cargas/<carga_id>/`.

## Desarrollo

```powershell
ruff check .      # linting
pytest            # pruebas
```


