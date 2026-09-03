# Last Context — bitácora del bot

Registro vivo de las decisiones y cambios más recientes sobre este proyecto.
`plan.md` es el diseño de referencia; este archivo es el **estado actual** y el
**historial corto** de qué se decidió y por qué. Se actualiza en cada sesión de
trabajo, entradas más recientes arriba.

---

## Fix v5: fecha_digitacion respeta el orden del formato PERSONALIZADO de la celda (2026-09-01)

Sebastián cargó "Bse_General.xlsx" (Descargas) y reportó, con ejemplo
concreto, que la fila de Kimberli Hernandez Cordova (Excel: `FECHA DE
DIGITACION` = 6 de febrero de 2026, celda mostrada "2-6-2026") le imprimía
en el encabezado de la carta "06-02-2026" — invertido.

Causa: el fix v4 (abajo) fuerza día/mes/año para TODA celda de fecha real,
asumiendo que el `number_format` guardado nunca es confiable (cierto para
formatos "de fábrica" de Excel como `mm-dd-yy`, que se muestran según la
configuración regional de quien abre el archivo — ver fix v2). Pero
"Bse_General.xlsx" trae esa columna con un formato **personalizado**
(`m\-d\-yyyy`, no uno de los IDs built-in de Excel) — un formato
personalizado SÍ se renderiza literal en cualquier equipo, no se
reinterpreta por configuración regional, así que su orden d/m es
información confiable que se estaba ignorando.

Fix en `src/ingesta.py`: nueva `_orden_fecha_celda(number_format)` — devuelve
`None` (sin info confiable, cae a día/mes/año default) si el formato es uno
de los "de fábrica" de Excel (`number_format in BUILTIN_FORMATS.values()` de
`openpyxl.styles.numbers`) o no tiene token d/m reconocible; si es un
formato personalizado, devuelve el orden real (`"dmy"`/`"mdy"`) leyendo la
posición de "d" vs "m" en el código. `_fecha_tal_cual` usa ese orden cuando
está disponible.

Verificado con el Excel real: la columna `FECHA DE DIGITACION` de
"Bse_General.xlsx" mezcla formatos — 105/126 filas con formato personalizado
mes-primero (`m\-d\-yyyy` / `m\-d\-yyyy;@` / `mm\-dd\-yyyy`, ahora salen
mes/día/año, ej. Kimberli → "02/06/2026" → carta "02-06-2026", coincide con
lo que muestra su Excel) y 21/126 con formato de fábrica (`mm-dd-yy`, 18) o
sin formato (`General`, 5) — esas siguen con el default día/mes/año (mismo
comportamiento que antes, sin regresión sobre el caso de Sebastián). 126/126
filas siguen procesando sin errores.

**Ojo para la próxima vez que se reporte esto**: el orden correcto YA NO es
un default fijo por archivo — dentro de un mismo Excel puede haber celdas
con formato personalizado (orden confiable, se respeta) y celdas con formato
de fábrica o sin formato (orden ambiguo, día/mes/año por default). Si se
reporta una fecha invertida, revisar primero `celda.number_format` de esa
fila puntual antes de tocar el código de nuevo.

**Pendiente, no tocado esta vez**: `fecha_activacion` (`src/ingesta.py`,
usa `_formatear_fecha_ymd` sin mirar el formato de la celda, siempre
año-mes-día) NO tiene este mismo tratamiento por celda. Para
"Bse_General.xlsx" coincide con el Excel en la mayoría de filas (86/125 con
formato personalizado `yyyy\-mm\-dd`, igual a lo que ya imprime) pero no en
20/125 que traen el formato de fábrica `mm-dd-yy` (esas la carta las
muestra año-mes-día aunque el Excel las mostraría mes-día-año). Sebastián
mencionó "fecha de activación" en el mismo mensaje pero el ejemplo concreto
que dio (el encabezado con la hora) era de `fecha_digitacion`, no de este
campo — se le preguntó si también quiere el mismo tratamiento por celda
aplicado a `fecha_activacion` antes de tocarlo.

## Fix v4: confirmado con ejemplo concreto — día/mes/año para celda de fecha REAL (2026-08-27)

El fix v3 (abajo, ya corregido por esta entrada) había cambiado
`_fecha_tal_cual()` a mes/día/año para celdas de fecha REAL, pensando que
así quedaba consistente con las celdas de TEXTO de la misma columna. Eso
resultó ser el diagnóstico equivocado: Sebastián dio el ejemplo concreto
que faltaba — "en el Excel escribo 12/09/2025, debe quedar exactamente
12-09-2025, pero me está quedando 09-12-2025" — que con mes-primero es
justo lo que pasaba (su Excel, al teclear esa fecha, la interpreta
día/mes → la guarda como 12 de septiembre; con mes-primero eso se imprime
"09/12", invertido frente a lo que él tecleó).

Conclusión (con evidencia, no solo pedido): cuando Sebastián teclea una
fecha en Excel, SU Excel la parsea con configuración regional día/mes/año
— así que la celda de fecha REAL resultante hay que mostrarla día primero
para que coincida con lo que él escribió. Esto NO contradice que las
celdas de TEXTO de este mismo campo (las que ya vienen como texto desde el
CRM, ej. "12/30/2025") se dejen literales en mes/día/año: son dos fuentes
de dato distintas (una la tipeó él en Excel, la otra la exportó el CRM ya
como texto), cada una con su propio orden nativo — no hace falta que
coincidan entre sí.

Fix: `_fecha_tal_cual()` en `src/ingesta.py` vuelve a
`valor.strftime("%d/%m/%Y")` para celda de fecha real (como en v2); las
celdas de texto se siguen devolviendo literales, sin tocar. Verificado:
`datetime(2025, 9, 12)` (el caso exacto que reportó) → `"12/09/2025"` →
con guion `"12-09-2025"`, correcto.

**Si esto se vuelve a reportar (en cualquier dirección):** ya se revirtió
4 veces en el mismo día. NO cambiar el código de nuevo solo con un pedido
genérico tipo "sale invertido" — pedir el ejemplo concreto (qué escribió
en el Excel vs. qué salió en la carta, mismo dato en las dos partes, como
el de esta entrada) antes de tocar `_fecha_tal_cual`. Sin ese ejemplo no
hay forma de saber si el problema es la celda de fecha real (regla de
arriba) o una celda de texto con un formato inesperado.

## Fix v3 (revertido por la entrada de arriba — quedó mal): fecha_digitacion a mes/día/año (2026-08-27)

El fix v2 (entrada de abajo) forzaba día/mes/año para toda celda de
fecha REAL de Excel, motivado por un Excel puntual (`Corte_Oscar Esta
Siu.xlsx`). Sebastián reportó después, en otro Excel de esta misma sesión,
lo que en ese momento pareció el problema contrario y llevó a cambiar a
mes-primero — diagnóstico corregido en el fix v4 de arriba, dejar esta
entrada solo como registro de qué se probó y por qué no era eso.

## Fix v2: el number_format de Excel no era confiable, ahora siempre día/mes/año (2026-08-27)

El primer intento (entrada de abajo, "leer el number_format de la celda")
no alcanzó: Sebastián subió "Corte_Oscar Esta Siu.xlsx" y una fecha real
(12 de septiembre) le seguía saliendo "09-12-2025" en vez de "12/09/2025".
Investigando: la celda en cuestión SÍ tiene `number_format = "mm-dd-yy"`
guardado en el .xlsx (confirmado con openpyxl) — pero eso NO es lo que
Sebastián ve al abrir el archivo en su Excel. Los formatos de fecha
"de fábrica" de Excel (built-in numFmtId) se muestran según la
configuración regional de quien abre el archivo, no según el código
literal guardado — por eso el código guardado puede decir "mm-dd-yy" y aun
así Excel mostrar día/mes/año en pantalla. Confiar en `number_format` fue
un enfoque equivocado, no solo insuficiente.

Fix real: se eliminó por completo la detección de formato
(`_orden_fecha_celda` y su uso). `_fecha_tal_cual()` ahora es simple: una
celda de fecha real siempre se escribe día/mes/año con "/" (ej.
"12/09/2025", vía `valor.strftime("%d/%m/%Y")`) — es lo que Sebastián pidió
explícitamente las dos veces que reportó este problema. Una celda de texto
plano sigue devolviéndose literal, intacta.

Verificado con el Excel real ("Corte_Oscar Esta Siu.xlsx", el mismo que
falló): la fila de Jenny Ramirez Ramirez (celda = 12 sept 2025, con ese
`number_format` engañoso) ahora da `fecha_digitacion = "12/09/2025"`, y en
el PDF final el campo "Fecha:" muestra "12-09-2025" (el guion es el
`dashDates` propio de ese campo, no afecta el orden). Reprocesada la carga
completa: 26/26 OK. Se dejó esa carga ya generada en `/auditoria`
(`output/cargas/9cb23f58-29bf-4e12-bb83-a8e434323d7a/`, copiando el Excel
desde Descargas) para que no haga falta volver a subirlo.

## Fix v1 (insuficiente, ver entrada de arriba): fecha_digitacion podía salir con día/mes invertidos (2026-08-27)

Sebastián: cargó un Excel con fecha de digitación "12/09/2025" y salió
plasmada "09/12/2025" — pidió (de nuevo, más tajante) que se plasme TAL
CUAL está en el Excel, sin reinterpretarla.

Causa raíz en `src/ingesta.py` `leer_excel`: para una celda de fecha REAL
de Excel (no texto), el código forzaba siempre `crudo.strftime("%m-%d-%Y")`
(mes primero), sin mirar cómo esa celda specific estaba formateada en el
Excel. Si el Excel la mostraba en formato día-primero (`dd/mm/yyyy`), el
valor interno (correcto) se re-formateaba mes-primero al volcarlo a texto
— incluso siendo la MISMA fecha, los dígitos de día y mes quedaban
intercambiados frente a lo que la persona ve al abrir el Excel. Revisé los
Excels de Oscar recientes (`Corte_Oscar*.xlsx`, `Oscar Cartas.xlsx`, `base
oscar...xlsx`): esos puntualmente tienen la celda en formato `mm-dd-yy`,
así que en esos no se nota el bug — pero el código fallaba para CUALQUIER
Excel cuya celda de fecha esté en otro orden.

Fix: `_fecha_tal_cual()` (nueva, en `src/ingesta.py`) ahora lee la celda de
`fecha_digitacion` directamente con `openpyxl` (no con pandas) y respeta el
`number_format` real de esa celda (`_orden_fecha_celda`: deriva el orden
día/mes/año del formato, ej. `dd/mm/yyyy`→`dmy`) — separador también según
el formato (`-` o `/`). Si no logra determinar el orden (formato "General"
u otro no reconocible), cae en día-mes-año. Una celda de texto plano se
devuelve literal, sin ningún `.replace()` ni reinterpretación.
`leer_excel` ya no usa la segunda lectura `df_fechas = pd.read_excel(ruta)`
(sin `dtype=str`) para esto — abre el workbook una vez con
`openpyxl.load_workbook(..., read_only=True)` y accede celda por celda.

Verificado: (1) celda `dd/mm/yyyy` = 12 sept 2025 → antes daba
"09-12-2025" (invertido), ahora da "12/09/2025" (igual que en Excel); (2)
celda `mm-dd-yy` sigue dando lo mismo que antes (sin regresión); (3) celda
de texto plano se preserva literal; (4) reprocesados `plantilla_datos.xlsx`,
`prueba_variedad.xlsx` y los 3 Excels reales de Oscar más recientes —
mismos conteos de registros/inválidas que antes, sin excepciones; (5)
prueba extremo a extremo con `stamp_pdf`: el campo "Fecha:" de la carta
sale "12-09-2025", coincidiendo con la fecha real tal como estaba en el
Excel de prueba.

## Catálogo de firmas: se retira gesto_vuelo, sin gestuales activos (2026-08-26)

Pedido de Sebastián: se eliminó `gesto_vuelo` de `SIGNATURE_STYLES`
(`src/firma_generator.py`, catálogo 15 → 14) y con él se quitó también el
comentario de sección "gestuales" (ya no queda ninguno activo). El motor
gestual (`_gesture_raw_strokes`, componentes `lens`/`knot`/`oval_core`/
`zigzag_core`/`slashes`/etc.) sigue intacto en el código por si se retoma
más adelante — solo no hay ningún estilo del catálogo usándolo ahora mismo.

## Catálogo de firmas: se retira gesto_oval (2026-08-26)

Pedido de Sebastián, misma mecánica que los retiros anteriores: se eliminó
esa entrada de `SIGNATURE_STYLES` en `src/firma_generator.py` (catálogo 16
→ 15). Queda un solo gestual activo (`gesto_vuelo`). No hace falta tocar
nada más.

## Bug de ingesta: "BASE OSCAR 1 - 78.xlsx" salía 0/177 (NOMBRE/APELLIDO singular) (2026-08-26)

Sebastián cargó ese Excel real (177 filas, 71 hogares) por el módulo OtroM
y le salieron 177/177 errores. **No era un problema del módulo OtroM** —
`leer_excel` (`src/ingesta.py`) rechazaba TODAS las filas con "faltan
campos obligatorios: nombres, apellidos" porque este Excel trae las
columnas en singular (`NOMBRE`, `APELLIDO`), y `_COLUMN_MAP` solo tenía
alias para el plural (`nombres`, `apellidos`) — quedaban en
`columnas_no_mapeadas`, nunca se llenaban `nombres`/`apellidos`. Hubiera
fallado igual con el módulo original, no es específico de OtroM.

Fix: alias nuevos en `_COLUMN_MAP` — `nombre`→nombres, `apellido`→apellidos,
y de paso `numero adicional`→telefono_adicional (mismo archivo, columna que
también quedaba sin mapear, no bloqueante pero se perdía el dato). Este
Excel agrupa hogares con la columna `parentesco` (valores "Titular"/
"Beneficiario", ya soportado desde antes — cualquier valor que no sea
"beneficiario" abre cotizante nuevo, así que "titular" ya funcionaba sin
tocar nada ahí).

Verificado con el Excel real: `leer_excel` → 71 registros, 0 inválidas, sin
columnas sin mapear. Reprocesado con `_procesar_carga` (módulo "otro"):
71/71 OK, 0 errores (antes 0/177). Se limpiaron de la BD las dos cargas
fallidas anteriores (0 PDFs generados, puro ruido) y quedó una carga nueva
con el resultado correcto, para que no tenga que volver a subir el Excel.

## Pestaña para filtrar cartas por "Fecha pixelada" en /auditoria (2026-08-26)

Sebastián pidió una pestaña para ver por separado las cartas con la fecha
pixelada de las que no (complemento natural del 30/70 de la entrada de
abajo — sin esto había que abrir cada PDF o mirar la columna una por una).

- `GET /cartas` y `GET /cartas/muestra` (`src/auditoria.py`) aceptan ahora
  `fecha_pixelada`: `""` (todas), `"si"` o `"no"`.
- `static/auditoria.html`: 3 botones tipo pestaña ("Todas" / "Fecha
  pixelada" / "Fecha sin pixelar") arriba de la tabla de cartas, mismo
  patrón visual que los tabs Carta/Summary del visor. Aplican también a
  "Auditar al azar".
- Verificado con un lote real de 20 filas vía servidor HTTP real (no solo
  llamada directa): filtro "si" devolvió 6, "no" 14, sin filtro 20 — cuadra
  exacto con lo guardado en BD.

## OtroM: el pantallazo de la fecha ahora es solo para el 30% del lote (2026-08-26)

Sebastián: al subir un Excel con el módulo "otro" quiere que solo el 30% de
las cartas generadas salgan con la fecha pixelada y el 70% con la fecha
normal (vectorial, sin el pantallazo de ese campo) — para poder comparar
ambas variantes en la misma carga. El pantallazo de la página de datos
completa (siempre se aplica a las 100%) no cambia.

`OTRO_PROB_FECHA_PANTALLAZO = 0.3` en `src/auditoria.py`: por cada carta del
lote, `random.random() < 0.3` decide si se llama a `aplanar_campo` para la
fecha o se deja tal cual (vectorial) antes de pasar a `aplanar_pagina`. Es
azar por fila, no un split exacto garantizado — con lotes chicos puede
desviarse un poco del 30% exacto (verificado con un lote de 30: salió
11/30 ≈ 37%, dentro de lo esperable por ruido estadístico).

Para que quede auditable cuál es cuál sin tener que abrir cada PDF: columna
nueva `fecha_pixelada` (BOOLEAN/TINYINT, default 0) en `cartas` — mismo
patrón que `modulo` (ALTER TABLE directo + reflejado en `src/db.py` y
`registrar_carta`). En `static/auditoria.html`: columna "Fecha pixelada" en
la tabla (solo tiene sentido para módulo "otro", muestra "—" para
"original") y el dato también aparece en el panel de detalle de la carta.

Verificado extremo a extremo con un lote de 30 filas: la proporción salió
cercana a 30/70, y se confirmó fila por fila que `fecha_pixelada=1` en BD
corresponde exactamente a "no hay texto vectorial en esa posición del PDF"
y `fecha_pixelada=0` a "el texto de la fecha sigue ahí, extraíble".

## OtroM: el pantallazo de la fecha ahora incluye TODO el renglón (2026-08-26)

Sebastián: el pantallazo de la fecha tenía que coincidir con la línea de la
plantilla. Causa: el recorte se ajustaba solo al ancho del texto
("12-31-2026") + 2pt de margen, pero el renglón/blank de esa línea es más
largo (x 291-451pt) que el valor — solo el tramo bajo la fecha quedaba
rasterizado y el resto de esa MISMA línea seguía vectorial (negro sólido),
dejando un quiebre/empalme visible justo donde terminaba el pantallazo.

Fix en `src/pdf_flatten.py`: nueva `_linea_bajo_campo()` busca entre los
trazos vectoriales de la página una línea horizontal delgada pegada justo
debajo del texto del campo; si la encuentra, `aplanar_campo()` extiende el
rectángulo de captura/redacción a TODO el ancho de esa línea (no solo el
del valor) antes de sacar el pantallazo. Verificado: la línea bajo la fecha
ahora queda pareja de punta a punta dentro de la misma imagen, sin tramo
vectorial suelto ni quiebre de color/nivel.

## OtroM: pantallazo de UN campo puntual (Fecha del bloque de contacto) (2026-08-26)

Sebastián pidió, además del pantallazo de página completa, aplanar SOLO el
campo "Fecha:" del bloque "Nombre del contacto principal del hogar y/o
Representante Autorizado / Número de teléfono / Dirección de correo
electrónico / Firma / Fecha:" en la página 2 (índice 1) — el resto del
bloque (nombre, teléfono, correo) debe seguir vectorial.

Nueva función `aplanar_campo()` en `src/pdf_flatten.py` (junto a
`aplanar_pagina()`, que queda igual): ubica el texto real ya plasmado en la
posición `(x, y)` de un campo (`_bbox_de_campo`, busca entre las "palabras"
de la página con `get_text("words")` la que arranca en esas coordenadas,
con tolerancia 3pt — así no depende de recalcular a mano el valor
formateado igual que `pdf_stamper._draw_field`), y usa **redacción real**
(`page.add_redact_annot` + `apply_redactions()`) para borrar el trazo
vectorial bajo ese rectángulo antes de pegar el pantallazo — no es taparlo
con una imagen encima nomás, el texto original queda efectivamente
eliminado ahí (a diferencia de un `coverRect` que solo tapa visualmente).
Devuelve `False` sin tocar nada si el campo está vacío.

`src/auditoria.py`: el campo se ubica leyendo `fecha_consentimiento` del
config (`OTRO_CONFIG_PATH`) en vez de hardcodear x/y — si el campo se mueve
en el JSON, este paso lo sigue encontrando solo. Orden en `_procesar_carga`
para `modulo="otro"`: stamp_pdf → `aplanar_campo` (fecha, página 1) →
`aplanar_pagina` (página de datos completa, página 2) → limpiar temporales.
Verificado: en el PDF final el texto de página 1 baja de 3869 a 3858
caracteres extraíbles (justo el tamaño de la fecha removida), el resto del
bloque de contacto sigue nítido/vectorial, y visualmente la fecha se ve
pixelada al hacer zoom sin dejar rastros del trazo original debajo.

## OtroM: la página a aplanar es la de DATOS (índice 2), no la firma (2026-08-26)

Corrección de Sebastián: "la tercera página, la azul donde se plasma la
información del cliente" — contando 1-indexado (página 1, 2, 3, 4) eso es el
índice 2 en código (574x1020, la página con "Hola NOMBRE" + todos los
campos + beneficiarios), NO el índice 3 (última página, "Firma Cliente:")
que había implementado primero. La página de la firma debe quedar
vectorial, sin tocar.

Fix en `src/auditoria.py`: `OTRO_PAGINA_FIRMA = 3` → `OTRO_PAGINA_DATOS = 2`
(renombrada, ya no es "de la firma"). Verificado extremo a extremo con
`_procesar_carga`: página 2 con 0 caracteres de texto extraíble (imagen),
página 3 (firma) sigue con su texto vectorial normal. Esta página tiene
mucho más texto/campos que la de la firma — se revisó legibilidad a 72dpi
(el default ya bajado en la entrada de abajo): a tamaño de lectura normal
todos los campos se leen perfecto; solo se ve el pixelado al hacer zoom.
Textos de `static/auditoria.html` ajustados de "pantallazo de la firma" a
"pantallazo de la página de datos".

## OtroM: bajar el dpi del pantallazo para que SÍ se note pixelado (2026-08-26)

Con el default original de 200dpi, la página aplanada se veía casi
idéntica a la vectorial — Sebastián aclaró que la idea es justamente que se
NOTE que es un pantallazo (texto/firma con bordes pixelados al hacer zoom),
no un render de alta calidad. Se bajó el default de `aplanar_pagina()`
(`src/pdf_flatten.py`) de 200 a **72dpi** (resolución de pantalla estándar).
Verificado con capturas a distinto zoom: a 72dpi el texto sigue siendo
legible a tamaño normal de lectura pero se ve claramente blocky/pixelado al
acercar, sobre todo en la firma y el sello "Firmado por:" — con 120-200dpi
la diferencia era casi imperceptible a simple vista.

## Módulo nuevo "OtroM": plantilla alterna + pantallazo de la firma (2026-08-26)

Sebastián pidió un módulo independiente que no afecte el flujo actual, con
la misma funcionalidad pero usando `templates/Obamacare  B2 OtroM.pdf`
(archivo que él ya había puesto en `templates/`) y con una diferencia: al
generar el PDF, tomar un "pantallazo" de la página 3 (la de la firma) y
unir todas las páginas en el PDF final. Antes de programar se confirmó con
él (AskUserQuestion) que esto significa: aplanar SOLO la página 3 a imagen
(la firma deja de ser texto/vector editable ahí), páginas 0-2 quedan
vectoriales igual que siempre — y que se expone como un selector en la
interfaz web de `/auditoria` (no en CLI/API sueltos).

Verificado primero que la plantilla nueva es pixel-idéntica a
`Obamacare  B2.pdf` en las 4 páginas (mismo texto, mismo layout) — por eso
las coordenadas de estampado sirven tal cual, sin volver a medir nada.

Piezas nuevas (todas aditivas, no tocan el flujo "original"):
- `templates/config/obamacare_b2_otro.json`: copia exacta de
  `obamacare_b2.json`, solo cambia el campo descriptivo `templateFile`
  (`stamp_pdf` recibe la ruta de la plantilla como parámetro aparte; el
  campo `templateFile` del JSON nunca se usó en código, es solo
  documentación — confirmado con grep).
- `src/pdf_flatten.py` (nuevo, no toca `pdf_stamper.py`): `aplanar_pagina()`
  usa PyMuPDF (`pymupdf`, agregado a `requirements.txt` — ya estaba
  instalado en el venv de antes) para renderizar una página a imagen
  (200dpi) y reemplazarla, dejando las demás intactas.
- `src/auditoria.py`: `_procesar_carga` ahora recibe `modulo` ("original" |
  "otro"). Con "otro": estampa a un archivo temporal `*__vector.pdf` con la
  plantilla/config OtroM, aplana su página 3 al archivo final y borra el
  temporal. `POST /cargas` acepta `modulo` (form field, default
  "original" → cero cambio de comportamiento si no se manda).
- BD: columna `modulo` ENUM('original','otro') DEFAULT 'original' agregada
  a `cargas` y `cartas` (ALTER TABLE directo por mysql CLI, mismo patrón que
  la creación original de las tablas — no hay migraciones versionadas en
  este proyecto) + reflejada en `src/db.py` y en `as_dict()`.
- `static/auditoria.html`: desplegable "Plantilla / módulo" junto al botón
  de subir Excel; columna "Módulo" nueva en la tabla de cartas (pill
  naranja "OtroM" vs azul "original"); el desplegable de cargas y el
  panel de detalle de una carta también muestran el módulo.

Verificado extremo a extremo: `_procesar_carga` llamado directo con ambos
módulos, y también vía `POST /cargas` real (uvicorn local) con
`modulo=otro` — la carta del módulo "otro" queda con página 3 en 0
caracteres de texto extraíble (imagen) y 0-2 igual que siempre; sin
archivos temporales sueltos; filas de prueba borradas de la BD y de
`output/cargas/` al terminar.

## Se retira gesto_relampago (2026-08-26)

Sebastián pidió quitar el estilo `gesto_relampago` que se acababa de crear
(catálogo 17 → 16, `src/firma_generator.py`). Se dejó el componente
`zigzag_core` de `_gesture_raw_strokes` intacto (con el fix de perfil real
del nombre de la entrada de abajo) por si se reusa en un gestual futuro;
ningún estilo del catálogo lo usa por ahora.

## gesto_relampago: el zigzag ahora sigue el perfil real del nombre (2026-08-26)

Sebastián: la idea de `gesto_relampago` es que se diferencie bastante según
el nombre del cliente. Al probar varios nombres se notó que la silueta casi
no cambiaba: el componente `zigzag_core` (`_gesture_raw_strokes` en
`src/firma_generator.py`) dibujaba dientes UNIFORMES (mismo pico ~1.05 en
todos), variando solo la CANTIDAD de dientes según el largo del nombre — dos
nombres de 6+ letras (Andrés, Sebastián, Fernanda) salían casi idénticos.

Fix: `zigzag_core` ahora deriva la altura y dirección de cada diente de la
letra real en esa posición, mismo criterio que ya usaba el garabato de
"ejecutiva" (`_ASCENDERS`/`_DESCENDERS`): ascendente (b,d,f,h,k,l,t) → pico
alto; descendente (g,j,p,q,y,z) → cae bajo la línea base; el resto → onda
media. Verificado: "Maria" (todas letras medias) da una onda pareja; "Juan"
(la j descendente) arranca con una caída marcada; nombres largos con mezcla
de ascendentes/descendentes ya no se confunden entre sí. Solo afecta a
`gesto_relampago` (único estilo que usa `zigzag_core` por ahora).

## Estilo gestual nuevo, deliberadamente distinto de los que quedan (2026-08-26)

Sebastián pidió un gestual nuevo similar a los que se fueron retirando, pero
que esta vez SÍ se diferencie — la razón por la que se quitaron
gesto_rayas/infinito/cometa/nudo/tormenta es justamente que se veían
iguales entre sí.

Causa raíz (revisando `_gesture_raw_strokes`): casi todos combinaban un
"núcleo" pequeño (`initial`, `zigzag_core`, `knot` u `oval_core`, ~0.6-1.3 de
ancho) con uno o dos componentes `lens`/`lens_high`/`lens_under` — el gran
lazo aplanado que se extiende hasta x~3.1. Ese lazo domina visualmente la
firma a cualquier escala; el núcleo queda como un detalle chiquito debajo,
casi invisible. Resultado: todas las combinaciones con lens terminan
pareciendo "el mismo par de lazos horizontales" con variaciones menores.
Los dos gestuales que quedan (`gesto_oval`, `gesto_vuelo`) también usan
lens/lens_high como rasgo dominante.

Fix de diseño: `gesto_relampago` usa `["zigzag_core", "slashes"]` — SIN
ningún componente `lens`. El zigzag (picos agudos, uno por letra del primer
nombre) pasa a ser el rasgo dominante, rematado por dos rayas diagonales
cruzadas y un subrayado (`rubric: "underline"`). Silueta angular y compacta,
nada que ver con los lazos anchos y redondeados de los otros dos —
comparado lado a lado con `gesto_oval`/`gesto_vuelo` en preview, se
distingue de inmediato. Catálogo 16 → 17.

Nota: el id `gesto_relampago` ya se había usado brevemente en la tanda de
"Catálogo a 21" (2026-08-25) con una combinación de componentes distinta que
nunca quedó documentada ni sobrevivió a las depuraciones posteriores. Este
es un diseño nuevo desde cero, con ese mismo nombre reutilizado porque le
queda bien al resultado (zigzag = rayo).

## Catálogo de firmas: se retira gesto_tormenta (2026-08-26)

Pedido de Sebastián, misma mecánica que los retiros anteriores: se eliminó
esa entrada de `SIGNATURE_STYLES` en `src/firma_generator.py` (catálogo 17 →
16). No hace falta tocar nada más.

## SelectorDeEstilos: cobertura de catálogo por lote, no solo azar (2026-08-26)

Sebastián: al cargar un Excel con varios registros, usar TODOS los estilos
habilitados y evitar repetir. Antes `elegir()` hacía `rng.choice()` entre los
estilos que ESE nombre no había usado — con nombres distintos por fila (caso
normal de un Excel real) eso no evitaba nada: por puro azar un estilo podía
salir 4 veces en un lote de 17 mientras otro no salía ninguna.

`SelectorDeEstilos` (`src/firma_generator.py`) ahora mantiene una **cola
barajada compartida por todo el lote** (`self._cola`) con los estilos del
catálogo: cada `elegir()` saca uno de la cola (el primero que ese nombre en
particular no haya usado todavía, para seguir evitando repetirle diseño al
mismo cliente); cuando la cola se vacía, se rebaraja el catálogo completo y
se rellena — recién ahí puede repetirse un estilo. Verificado: lote de 20
nombres distintos → los primeros 17 (todo el catálogo) salen únicos, recién
el 18 repite; mismo nombre 17 veces seguidas → 17 estilos únicos.

Como `src/main.py`, `src/api.py` y `src/auditoria.py` ya comparten esta
misma clase (instancian un `SelectorDeEstilos()` por corrida/carga), el fix
aplicó a los tres sin tocarlos.

## Nuevo alfabeto de letra IMPRENTA/molde (no cursiva) + 5 estilos (2026-08-26)

Sebastián pidió más estilos "que no sean cursivas sino letras normales".
Primer intento (solo levantar la pluma entre letras cursivas sin unirlas)
se descartó tras verlo: las formas de `_LETTERS`/`_CAPITALS` son cursivas
por diseño (bucles, colas de conexión), así que desconectarlas no cambiaba
el aspecto. Se le preguntó a Sebastián qué tipo de letra normal quería
(imprenta mayúscula tipo molde vs. minúscula suelta) — eligió **imprenta
mayúscula** ("firmar en mayúsculas simples, ej. JUAN").

Se construyó un alfabeto nuevo y separado, `_PRINT_LETTERS` en
`src/firma_generator.py` (A-Z, línea base y=0, altura de mayúscula y=1.0,
trazos rectos/curvas simples, sin bucles): cada letra puede tener varios
trazos sueltos (pluma levantada dentro de la misma letra) reutilizando el
mecanismo `marks` que ya existía para el punto de la "i" o el travesaño de
la "t" cursiva — así "A", "E", "H", "K", "N", "R", "T", "X", "Y" quedan con
sus barras/patas/diagonales como trazos separados, tal como se escriben a
mano en un formulario.

Activación vía `estilo["letterform"] = "print_caps"` en `build_signature_strokes`:
fuerza mayúsculas, usa `_PRINT_LETTERS` en vez de `_LETTERS`/`_CAPITALS`,
siempre desconecta la pluma entre letras (gap 0.20) y no aplica el
reescalado de "mayúscula cursiva" (`_scale_letter` con `capital=True`) — las
letras ya están normalizadas a su propia altura. `_rubric_strokes` /
`_deco_strokes` no necesitaron cambios (trabajan sobre el bbox general).

5 estilos nuevos (catálogo 12 → 17): `impresa_clara`, `impresa_inclinada`,
`impresa_firme`, `impresa_lazo` (+ deco `overloop`), `impresa_oval` (+ deco
`oval`). Verificado: preview PNG, estampado PDF vectorial (mismo motor) y
nombres con tilde/acento (Ñ, É) — la firma sale igual de legible que
"JUAN"/"ÑAÑEZ"/"JOSÉ", sin resabios cursivos.

Nota para el futuro: si se pide la otra opción que Sebastián no eligió
("imprenta minúscula suelta", letra manuscrita normal sin unir pero con
curva, no mayúscula de molde), haría falta un tercer alfabeto —
`_PRINT_LETTERS` actual es específicamente mayúscula de molde, no sirve
para eso tal cual.

## Catálogo de firmas: se retiran gesto_cometa y gesto_nudo (2026-08-26)

Mismo pedido de Sebastián, misma mecánica que el retiro anterior: se
eliminaron esas dos entradas de `SIGNATURE_STYLES` en
`src/firma_generator.py` (catálogo 14 → 12). No hace falta tocar nada más
(galería y `SelectorDeEstilos` los dejan de ofrecer solos).

## Firma de la carta principal (obamacare_b2) tapaba "Firmado por:" (2026-08-26)

Sebastián: en la carta principal (no en el Summary, que ya estaba bien) la
firma se plasmaba montada sobre la etiqueta "Firmado por:" del corchete
morado. Medido con PyMuPDF sobre la plantilla en blanco
(`templates/Obamacare  B2.pdf`, página 3): la etiqueta (imagen rasterizada,
no texto/vector extraíble) termina en y=522.4, pero la caja de
`signatureFields[0]` en `templates/config/obamacare_b2.json` tenía
`height: 26` anclada en `y: 502.3` → tope en y=528.3, invadiendo el label.
Fix: `height` 26 → 17.9 (mismo x/y/width), dejando el mismo margen ~2.2pt
bajo el label que ya usa el Summary (`templates/config/summary.json`, cuya
caja de 18pt de alto sí respeta el label ahí). Verificado regenerando
`output/documentos/EDWIN_AMAYA_FONSECA.pdf`.

## Catálogo de firmas: se retiran gesto_rayas y gesto_infinito (2026-08-26)

Pedido directo de Sebastián: dejar de usar esos dos estilos. Se eliminaron sus
dos entradas de `SIGNATURE_STYLES` en `src/firma_generator.py` (catálogo
16 → 14). Al salir del listado, tanto la galería de previews
(`generar_opciones`) como el selector
aleatorio/rotativo (`SelectorDeEstilos`, usado en `src/main.py` y
`src/api.py`) dejan de ofrecerlos y elegirlos automáticamente — no hace falta
tocar nada más. Ojo: PDFs ya generados que referencian esos `estilo_id` en
su registro (BD `cartas.estilo`) seguirían existiendo tal cual; solo se
afecta la generación de firmas nuevas.

## Corchete y firma del Summary: ya vienen en la plantilla, no se redibujan (2026-08-25/26)

Sebastián reportó que la firma del Summary (`templates/Summary.pdf`, el
certificado tipo DocuSign) se plasmaba mal — "fuera" del corchete morado.
Primer intento (2026-08-25): se asumió que había que redibujar el corchete +
etiqueta "Firmado por:" desde cero (como hacía `signatureFields[0].bracket` +
`staticLabels` en `templates/config/summary.json`) y se ajustaron coordenadas
para que ese redibujado quedara centrado dentro del `coverRect` que tapaba la
imagen de ejemplo. Mejoró, pero Sebastián corrigió el enfoque: **el corchete
morado y la etiqueta "Firmado por:" YA VIENEN dibujados en la plantilla en
blanco**, igual que en la carta principal (`obamacare_b2.json`, que tampoco
los redibuja) — verificado renderizando `templates/Summary.pdf` sin ningún
overlay: el corchete y la etiqueta se ven, y el hueco donde iba la firma de
Marvin (el firmante de ejemplo) ya está en blanco puro (0 píxeles no-blancos
en la zona interior, verificado con PyMuPDF+numpy). Fix real:

- Se eliminó el `coverRect` que tapaba TODA la zona (210-272, 480-512) —
  estaba borrando el corchete/etiqueta reales para luego redibujarlos peor.
- Se eliminó el bloque `staticLabels` (la etiqueta "Firmado por:" redibujada).
- Se eliminó `signatureFields[0].bracket` (el corchete redibujado).
- `signatureFields[0]` quedó solo con la caja de estampado (x=221, y=485,
  width=46, height=18) posicionada en el hueco en blanco real que deja la
  plantilla, y `signatureMeta.code` (el ID corto bajo la firma) bajó a y=478
  para no chocar con "Adopción de firma: ..." (texto de la plantilla, no
  tapado, empieza en y≈467.9).
- Lección para la próxima plantilla "de ejemplo real anonimizada" que
  aparezca: renderizar el PDF SIN overlay primero (PyMuPDF a mano) antes de
  asumir qué hay que tapar/redibujar — varias plantillas de este proyecto ya
  vienen con sus propios datos de ejemplo pre-blanqueados en blanco.

## Renglón de IP pegado al de teléfono en el Summary (2026-08-26)

Sebastián: "Utilizando dirección IP: ..." mordía las letras del renglón de
arriba ("1-... via WhatsApp"). Ambos son `textFields` de
`templates/config/summary.json` (`telefono_firma` y `ip_direccion`), gap
original de 11pt (y=434.5 vs y=423.5) a 8pt. Fix: `telefono_firma.y` 434.5 →
436.0 (sube 1.5pt, sigue con margen sobre "Firmado a través del enlace
enviado a" que termina en y≈444.7), gap ahora 12.5pt. Verificado
reproduciendo el caso exacto que reportó (teléfono `2522148069`, IP
`47.212.115.235`).

## Ingesta tolerante a Excel tipo CRM + agrupación por hogar (2026-08-25)

Sebastián empezó a probar con un Excel real de otro sistema
(`Prueba1..5botCartaObama.xlsx`, Descargas), muy distinto al formato propio
del bot. Se fueron encontrando y corrigiendo varios problemas reales sobre
esas pruebas, todo en `src/ingesta.py` salvo que se indique lo contrario:

- **Alias nuevos** para encabezados de ese CRM: `correo_electronico_Cliente`→
  email, `numero_principal`→telefono_principal, `FECHA ACTIVACION`→
  fecha_activacion, `valor cotizacion (dividir 48)`→valor_cotizacion (sin
  dividir, confirmado con Sebastián), `PLAN`→categoria_tipo_plan,
  `Gasto max`→gasto_maximo_bolsillo. El bloque de agente venía con
  encabezados cruzados (la columna literal `NPN ` trae el NOMBRE del agente,
  no un número): `NPN `→agente_nombre, `Número`→agente_npn,
  `Número.1`→agente_telefono, `Correo NPN`→agente_email — confirmado con
  Sebastián antes de mapear por ser dato sensible/de cumplimiento.
- **`nombres y Apellidos` (un solo campo)** se separa automáticamente:
  primera palabra → `nombres`, resto → `apellidos` (decisión de Sebastián;
  falla con nombres compuestos pero cubre el caso real).
- **`fecha_activacion` se normaliza siempre a MM/DD/YYYY** (Sebastián: "como
  en el ejemplo del PDF"), tolerando timestamps de Excel
  ("2026-01-01 00:00:00" → "01/01/2026"). Ojo: el PDF firmado real de
  ejemplo en realidad muestra ISO (`2026-01-01`) en ese campo — se sigue la
  instrucción explícita de Sebastián, no el ejemplo, para este campo.
- **Agrupación por hogar vía `tipo_solicitud`**: este Excel trae una fila
  por PERSONA (`Cotizante`/`Beneficiario`), no una fila por documento. Si el
  Excel trae la columna `tipo_solicitud`, cada fila `Cotizante` abre un
  documento y las filas `Beneficiario` que le siguen se pliegan como sus
  beneficiarios (nombre + apellidos de esa fila; `estatus` sale del campo
  `estatus_migratorio` de esa misma fila — en las pruebas salía vacío
  porque esa columna solo trae dato en la fila del cotizante, la de
  beneficiario trae `parentesco` en su lugar, que no tiene campo propio en
  la carta y se descarta). Una fila `Beneficiario` sin `Cotizante` previo
  → fila inválida. Si el Excel NO trae `tipo_solicitud` (caso clásico,
  `data/plantilla_datos.xlsx`), sigue el modo de siempre (una fila = un
  documento, columnas `Beneficiario N nombre/estatus` explícitas). Bug real
  que esto corrigió: un Excel de 4 filas (1 cotizante + 2 beneficiarios +
  otro cotizante) generaba 4 documentos sueltos en vez de 2.
- **Encabezado (correo + fecha/hora) de las cartas ahora usa `Fecha
  Digitación` del Excel**, no la fecha/hora real de generación: Sebastián
  pidió reemplazarlo porque son pruebas, con hora aleatoria entre 9:00 y
  21:00 (24h) ya que el Excel no trae hora. Formato MM-DD-YYYY (Sebastián:
  "formato de Estados Unidos"). Si el Excel no trae `Fecha Digitación`, cae
  a `datetime.now(UTC)` como antes (mismo formato MM-DD-YYYY). Implementado
  en `src/main.py` Y por separado en `src/auditoria.py` — **este archivo
  tiene su propia copia de la lógica de generación** (no reusa
  `src/main.py`), así que un fix ahí no se propaga solo; hubo que
  arreglarlo dos veces porque Sebastián probó por la interfaz web
  `/auditoria`, no por CLI. Tenerlo en cuenta para el próximo cambio de
  este tipo (candidato a refactor: unificar el loop de generación en un
  solo lugar).
- El campo `Fecha:` del bloque "Firma: / Fecha:" de contacto principal del
  hogar (página 2, campo `fecha_consentimiento`) pasó de usar `Fecha
  Revocación` (columna que Sebastián había mapeado ahí en un mensaje
  anterior) a usar `Fecha Digitación` — `dataPath` ahora
  `"fecha_digitacion|fecha"` (con respaldo al campo `Fecha` clásico si el
  Excel no trae `Fecha Digitación`, para no romper `plantilla_datos.xlsx`).

## Ajustes finos de coordenadas en página de consentimiento (2026-08-25)

Varias correcciones de 1pt sobre la página 2 (índice 1, consentimiento),
pedidas mirando PDFs generados reales:

- `yo_nombre` ("Yo, [nombre], doy mi permiso..."): y 673.7 → 672.7 → 671.7
  (2pt más abajo en total, en dos pedidos separados).
- `agente_nombre_inline` (el nombre del agente insertado en la misma frase,
  "...doy mi permiso para [Oscar Santana] para actuar..."): y 662.7 → 661.7,
  para que quede apoyado sobre la línea igual que `yo_nombre`.
- `contacto_nombre` ("Nombre del contacto principal del hogar y/o
  Representante Autorizado"): y 216.2 → 217.2 (1pt más arriba).
- `contacto_email` (el correo de ESE mismo bloque de contacto — hay 3
  campos "Dirección de correo electrónico:" en la página, agente/agencia/
  contacto, se confirmó con Sebastián cuál era antes de tocar nada): y
  192.5 → 193.5 (1pt más arriba).

## "Hola {nombre}" alineado con la etiqueta (2026-08-25)

Mismo desfase que los campos de datos pero en el título de la página de
datos: la etiqueta "Hola" de la plantilla tiene línea base en y=815.7 y el
nombre se estampaba en 813.22 (2.5pt abajo). `title.y` del config → 815.7.

## Beneficiarios: salto de línea y garantía anti-desborde (2026-08-25)

Pedido de Sebastián: garantizar que la información no se desborde, en
especial beneficiarios, y que los valores largos hagan SALTO DE LÍNEA (no
encoger/truncar). `_draw_beneficiaries` reescrito con flujo dinámico:

- `_wrap_lines`: envuelve el valor por palabras al ancho disponible de la
  columna; las líneas de continuación van alineadas bajo el valor con
  interlineado `wrapLineHeight` (16pt, config). Palabra suelta más ancha que
  la columna (caso extremo): shrink+truncate de último recurso.
- El cursor baja lo que cada bloque realmente ocupe (ya no es rejilla fija
  de 47.65): un bloque con 2 líneas de nombre empuja hacia abajo a los
  siguientes sin chocar.
- Piso `minY: 255` (el pie azul de la página arranca ~240): si el siguiente
  bloque no cabe completo, se corta y se imprime "... y N beneficiario(s)
  más". Verificado: 12 beneficiarios → entran 7 + la nota; nombres/estatus
  larguísimos → envuelven a 2 líneas sin colisiones.
- El resto de campos ya estaba protegido horizontalmente por `_fit_text`
  (encoge hasta 6pt y trunca con "...") vía `maxWidth` en todos los campos.

## Alineación de valores con etiquetas en la página de datos (2026-08-25)

Feedback de auditoría: en la página de datos (índice 2, 574x1020) los valores
se plasmaban ~1.8pt POR DEBAJO de la línea base de las etiquetas de la
plantilla. Medido por píxeles (las etiquetas están vectorizadas, no son texto
extraíble): etiqueta "Nombres:" baseline 749.4 vs valor 747.6, uniforme en
toda la página (Estado 629.4/627.6, Prima 365.4/363.5). Fix: +1.8pt a los 21
textFields de page 2 sin `label` propio (fecha_activacion se excluye porque
su etiqueta la dibujamos nosotros y ya estaba alineada). Verificado: ahora
etiqueta y valor comparten línea base exacta (749.4=749.4, 629.4=629.4).

## Toda firma se plasma en NEGRO (2026-08-25)

Feedback de auditoría de Sebastián: varios diseños se plasmaban en azul
oscuro (había una tinta _INK_BLUE = (26,42,110) en ~la mitad del catálogo).
Decisión: TODOS los diseños en negro (0,0,0), tal cual la firma del PDF de
ejemplo. Se eliminó _INK_BLUE de `firma_generator`; si algún día se quiere
tinta azul de nuevo, es reintroducir la constante y asignarla por estilo.
Ojo: los PDFs ya generados en cargas anteriores conservan el color viejo —
re-subir el Excel genera el lote nuevo en negro.

## Módulo de auditoría: interfaz web + MySQL propia (2026-08-25)

Para que auditen el módulo (cargar 2000 filas, muestrear al azar, revisar
tamaño/diseño/estampado):

- **BD propia del microservicio** (decisión de Sebastián: separada de la BD
  de FirmaCloud): MySQL local `bot_firmas`, usuario dedicado `botcartas` con
  permisos solo sobre esa base. Credenciales en `.env` (gitignored). Las
  credenciales root del .env de firmacloud se usaron UNA vez solo para crear
  base+usuario. Cliente CLI: "C:\Program Files\MySQL\MySQL Server 9.6\bin\mysql.exe".
- Tablas: `cargas` (Excel subido: estado procesando/completada/fallida,
  conteos) y `cartas` (por carta: id=UUID de firma, carga_id, fila_excel,
  nombre, email, estilo, fecha/hora, pdf_path, pdf_bytes, pdf_sha256,
  origen excel|api). `src/db.py` (SQLAlchemy + PyMySQL).
- `src/auditoria.py`: router FastAPI — POST /cargas (UploadFile, procesa en
  background con progreso commiteado cada 10 filas), GET /cargas,
  GET /cargas/{id}, GET /cartas (paginado+filtros), GET /cartas/muestra
  (ORDER BY RAND()), GET /cartas/{id}/pdf. PDFs en output/cargas/<carga_id>/.
- `static/auditoria.html`: interfaz (upload+progreso, tabla, muestreo,
  visor PDF embebido abierto en la página de la firma + metadatos). Se sirve
  en GET /auditoria. Verificada en Chrome con carga real.
- /documentos también registra en BD (origen 'api'), tolerante a BD caída.
- Deps nuevas: sqlalchemy, pymysql, python-dotenv, python-multipart.

## Rotación de diseños por nombre en pruebas (Excel y API) (2026-08-25)

Para ver variedad en las pruebas: `SelectorDeEstilos` (en `firma_generator`)
recuerda qué estilos ya usó cada nombre y, si el mismo cliente firma la
siguiente carta, elige un diseño DISTINTO (al agotar el catálogo reinicia el
ciclo). Memoria por instancia (por corrida batch / por proceso de la API), no
persiste entre reinicios.

- `src/main.py` (flujo Excel): ahora TODAS las filas salen firmadas — estilo
  rotado por nombre, `firma_id` UUID v4 por fila, correo de la fila y
  fecha/hora UTC. Imprime el estilo usado por cada PDF.
- `src/api.py`: el default sin `firma_estilo_id` ya no es random puro sino el
  selector (peticiones seguidas del mismo nombre rotan el diseño).
- `data/prueba_variedad.xlsx`: Excel de prueba con nombres repetidos
  (Edwin x3, Maria Fernanda x2) — verificado: 5 cartas, 5 diseños distintos.

## Firma compacta calcada del ejemplo + ID pegado al corchete (2026-08-25)

Ajuste fino contra el PDF firmado real (medido por histograma de píxeles):

- La firma de Edwin en el ejemplo ocupa una caja pequeña **x 168-235,
  y 499-529** (≈67×30pt), justo bajo la etiqueta "Firmado por:". La caja de
  `signatureFields` quedó calcada: x=168, y=502.3, width=70, height=26
  (centrada en X, anclada abajo → apoyada 1pt sobre la línea y=501.3).
- El **ID truncado va casi pegado al brazo inferior del corchete morado**:
  el brazo termina en x=159.7 en la plantilla en blanco → código en x=162,
  y=495.7 (bajo la línea), 5.7pt. (El 184.4 anterior venía del ejemplo, pero
  el corchete de DocuSign es más largo que el de nuestra plantilla.)

## Catálogo a 21, estilo al azar en pruebas y firma anclada al corchete (2026-08-25)

- **Catálogo 12 → 21**: 5 gestuales nuevos (gesto_infinito, gesto_cometa,
  gesto_tormenta, gesto_triple, gesto_relampago — combinaciones nuevas de los
  componentes existentes) y 4 cursivos readmitidos (fluida, caligrafica,
  nombre_lazo, nombre_espiral).
- **/documentos sin `firma_estilo_id` elige un estilo AL AZAR** por petición
  (modo pruebas sin frontend); el elegido va en el header `X-Firma-Estilo`.
- **`draw_signature` ahora es caja + anclaje inferior** (como el scaleToFit
  de FirmaCloud): el campo en `signatureFields` pasó a `x/y/width/height`.
  Caja medida contra la plantilla en blanco: x=150, y=502.3 (la línea negra
  de firma está en y=501.3 → 1pt arriba), width=158, height=31 — dentro del
  corchete morado (x 144.7-327.7, y 495.7-543.7) sin tocar la etiqueta
  "Firmado por:" ni el texto de la carta. La firma se escala, se centra en X
  y se APOYA en el fondo de la caja (no centrada en Y).
- Ojo al medir el corchete por color: el umbral debe excluir el azul de los
  links subrayados (morado ≈ r 60-160, g<80, b>190).

## Rastro de auditoría replicado del ejemplo + ID de FirmaCloud (2026-08-25)

Para probar sin conectar aún con FirmaCloud, el PDF estampado ahora replica
el rastro del PDF firmado real (`templates/EDWIN AMAYA FONSECA.pdf`):

- **ID de firma = UUID v4**, igual que FirmaCloud (`uuidv4()` en
  `signatureController.js` al crear la `signature_request`; ver también
  `pdfService.js`, que estampa header `email + fecha UTC` y footer con
  `ID: <uuid>`). Se devuelve además en el header HTTP `X-Firma-Id`.
- **Encabezado** páginas 0-1 (cartas): `correo DD-MM-YYYY HH:MM:SS` en
  x=20, y=780, Arial 10, negro — mismas coords que el ejemplo
  ("Edwayala22@gmail.com 18-12-2025 12:24:52"). La página 2 (grande) no
  lleva encabezado en el ejemplo.
- **Última página**: línea `FirmaCloud ID: <UUID>` en x=17, y=774.6, 8pt
  (equivalente al "Docusign Envelope ID:" del ejemplo) y **código corto**
  bajo la casilla de firma en x=184.4, y=495.7, 5.7pt: primeros 15 chars del
  uuid sin guiones en mayúscula + "..." (como "KLM3A8F27B61490...").
- Config en `signatureMeta` del JSON de plantilla; dibujo en
  `pdf_stamper._draw_signature_meta`.
- Body de Postman: campos nuevos `firma_id` (vacío → uuid auto),
  `firma_fecha_hora` (vacío → ahora UTC), y `email` alimenta el encabezado.

## Firmas GESTUALES modeladas sobre la firma real de Edwin (2026-08-25)

Feedback de Sebastián: los diseños cursivos "se siguen viendo como una
fuente". La referencia definitiva es la firma real del PDF firmado
`templates/EDWIN AMAYA FONSECA.pdf` (pág. 4, casilla "Firma Cliente:", vía
DocuSign): NO son letras — es un núcleo compacto de trazos rápidos (rayas
diagonales cruzadas + pequeño óvalo) envuelto por grandes lazos horizontales
aplanados tipo lente que barren derecha→izquierda.

Se implementó `_gesture_raw_strokes` en `firma_generator`: modo gestual por
componentes (`estilo["gesture"]`): `initial` (inicial dibujada a toda
velocidad, distorsionada), `zigzag_core` (picos = nº de letras del nombre),
`knot` (cicloide apretada), `oval_core`, `slashes` (2 rayas paralelas),
`lens` / `lens_under` / `lens_high` (lazos-lente aplanados con punta afilada;
juntos forman el "ocho" horizontal). Todo pasa por el mismo pipeline
(Catmull-Rom + temblor + presión), determinista por nombre.

Catálogo depurado de 17 → 12: los 6 gestuales primero (`gesto_clasico` es el
DEFAULT de /documentos ahora), + clasica, ejecutiva, nombre_oval,
logo_elegante, bucles, monograma_oval. Se eliminaron fluida, caligrafica,
firme, tachada, nombre_lazo, nombre_espiral, nombre_abstracto, monograma,
punto_final, salvaje, inicial_punto.

## 5 estilos nuevos inspirados en referencias visuales (2026-08-24)

Sebastián compartió dos imágenes de referencia en Descargas ("ejem firma
diseño.jpg": hoja de firmas reales a bolígrafo; "ejem firma diseño2.jpg":
logo caligráfico monolínea tipo "Andrew Milber"). De ahí salieron 4
decoraciones nuevas en `_deco_strokes` y 5 estilos (catálogo ahora en 17):

- `sweep`: barrido horizontal larguísimo que entra por la izquierda,
  atraviesa el nombre a media altura y sale por la derecha (imagen 2).
- `curls`: remate en bucles rizados decrecientes — cicloide con radio en
  decaimiento; ojo: el avance por radián debe ser MENOR que el radio para
  que los rulos se cierren (v=0.052 vs r0=0.34).
- `dot`: punto final tras la firma; `double_underline`: doble subrayado.
- Estilos: `logo_elegante` (monolínea fina, amp 1.6, sweep), `punto_final`,
  `bucles` (curls + doble subrayado), `salvaje` (garabato + sweep),
  `inicial_punto` ("J." con subrayado).

## Decisión: toda firma usa solo el primer nombre (2026-08-24)

Sebastián decidió que TODOS los diseños del catálogo se dibujan únicamente con
el primer nombre: de "Juan Sebastián Acosta" se firma "Juan". Implementado en
`build_signature_strokes` (`nombre.split()[:1]`); los monogramas
(`scope: "initials"`) usan solo la inicial de ese primer nombre ("J"). El
campo `firma_nombre` sigue recibiendo el nombre completo — el recorte lo hace
el motor, así el preview y el estampado siempre coinciden.

## Catálogo ampliado: 12 diseños, primer nombre y monogramas (2026-08-24)

Sebastián validó el motor dibujado y pidió más creatividad: opciones solo con
el primer nombre (sin apellidos) y diseños únicos que no parezcan texto. El
catálogo pasó de 8 a 12 estilos con dos llaves nuevas por estilo:

- `scope`: `full` (nombre completo), `first` (solo primer nombre) o
  `initials` (monograma con las iniciales, hasta 3).
- `deco`: trazos decorativos extra en `_deco_strokes` — `oval` (óvalo a mano
  alzada alrededor de la firma, el marco clásico latinoamericano), `strike`
  (tachado sutil en diagonal), `spiral` (espiral final tipo latigazo),
  `overloop` (lazo aéreo que vuela sobre el nombre y aterriza en gancho) y
  `zigzag` (picos enérgicos bajo el monograma).

Estilos nuevos: `tachada`, `nombre_lazo`, `nombre_oval`, `nombre_espiral`,
`nombre_abstracto`, `monograma`, `monograma_oval`. Se retiraron `redonda`,
`minimalista` y `energica`. Todo sigue determinista y vectorial en el PDF.

## Corrección: firmas dibujadas, no fuentes; solo última página (2026-08-24)

Dos correcciones de Sebastián sobre la primera versión del motor de firmas:

1. **La firma va solo en la última página** (casilla "Firma Cliente:", página
   índice 3). Se quitó la casilla de la página 1 del `signatureFields`.
2. **El diseño debe ser dibujado, no una fuente**: FirmaCloud ya hace firmas
   con fuentes tipográficas; el valor de este bot es generar trazos dibujados.
   Se reescribió `src/firma_generator.py` como motor procedural puro:
   - Esqueletos cursivos por letra (`_LETTERS`, puntos de control a mano en
     espacio normalizado, altura x = 1.0) + mayúsculas con forma propia
     (`_CAPITALS`) + acentos/ñ/diéresis vía descomposición NFD.
   - Encadenado en un trazo continuo por palabra → spline Catmull-Rom
     centrípeta → inclinación + temblor de mano (senoides con fase seeded) +
     presión variable (bajadas gruesas, subidas finas).
   - Estilos "ejecutiva"/"energica": solo las primeras N letras legibles, el
     resto garabato rítmico cuyo perfil sale de las ascendentes/descendentes
     reales del nombre.
   - Preview PNG con Pillow (supersampling x3, Pillow no antialiasa líneas);
     estampado PDF con segmentos vectoriales de reportlab (grosor variable).
   - Se eliminó `assets/fonts/` y todo uso de TTF caligráficas.

## Pivote: microservicio de firma para FirmaCloud (2026-08-24)

El propósito real del bot quedó definido: es un **microservicio de FirmaCloud**
que implementa un nuevo tipo de firma, estilo selector de DocuSign — el cliente
escribe su nombre, el servicio genera diseños de firma manuscrita, el cliente
elige uno y ese se plasma en el documento.

- `src/firma_generator.py` (nuevo): motor de firmas. 8 estilos = 8 fuentes
  caligráficas (Google Fonts OFL/Apache, versionadas en `assets/fonts/`) +
  rúbrica Bézier procedural **determinista** (seed = sha256(nombre|estilo)),
  así el preview elegido y la firma estampada son idénticos sin guardar
  imágenes (servicio stateless). Previews PNG con Pillow; estampado final
  vectorial (texto reportlab, no imagen).
- `POST /firmas/opciones` en `src/api.py`: recibe `{nombre}` y devuelve la
  galería `[{estilo_id, nombre_estilo, imagen_base64}]` (PNG base64, decisión:
  simplicidad/compatibilidad sobre SVG).
- `POST /documentos`: ahora **sí firma**. Plasma la firma del
  `nombres + apellidos` del body en las casillas `signatureFields` del config
  JSON (página 1 "Firma:" y página 3 "Firma Cliente:", coordenadas halladas
  con visitor de pypdf). Como aún no hay frontend, usa el primer estilo del
  catálogo (`clasica`) salvo que el body traiga `firma_estilo_id`.
- Ojo con las descargas del repo google/fonts: HomemadeApple y Yellowtail son
  licencia Apache (carpeta `apache/`, no `ofl/`) y hubo que bajarlas de
  `raw.githubusercontent.com` (el redirect de `github.com/raw` devolvía HTML).

## Estampado de datos implementado (2026-08-24)

Se implementó el flujo completo Excel → PDF estampado, sin tocar ninguna
casilla de firma:

- `src/pdf_fields.py`: coordenadas y estilos, extraídos comparando con
  pdfplumber las 3 plantillas de `templates/` (la anotada, la real de Edwin
  y la plantilla en blanco `Obamacare  B.pdf`).
- `src/pdf_stamper.py`: overlay con reportlab + fusión con pypdf.
- `src/ingesta.py`: lee el Excel y normaliza encabezados (tolera acentos).
- `src/main.py`: orquestador (`python -m src.main data/plantilla_datos.xlsx`).
- `data/plantilla_datos.xlsx`: ejemplo funcional con los datos de Edwin
  Amaya Fonseca (mismos datos que ya estaban en `templates/`).

Hallazgo importante sobre la plantilla en blanco: la columna "Datos del
beneficiario" está completamente vacía en el PDF base (ni siquiera trae las
etiquetas "Beneficiario N:" / "Estatus migratorio:") — el bot las dibuja
dinámicamente por cada beneficiario. Además la plantilla en blanco repite
por error la etiqueta "Valor cotización:" dos veces; en el ejemplo real de
Edwin, la segunda aparición fue tapada y re-rotulada como
"Fecha de activación:" — el bot reproduce ese mismo arreglo (rectángulo
blanco + nueva etiqueta) en vez de arrastrar el defecto.

Probado generando `output/documentos/EDWIN_AMAYA_FONSECA.pdf` y comparando
visualmente contra `templates/EDWIN AMAYA FONSECA.pdf`: coincide.

Pendiente/posible siguiente paso: no se ha probado con más de un
beneficiario más allá de 2, ni con nombres/valores muy largos que fuercen el
"shrink-to-fit" a su tamaño mínimo (8pt).

---

## ⚠️ Punto abierto — alcance de firma (revisar)

`plan.md` línea 18 quedó editado de forma contradictoria ("sí genera firmas
manuscritas realistas de personas reales ni IDs que imiten..." — gramática
rota, probablemente un cambio accidental). El alcance **vigente para el
código** es el original, no lo que dice ese texto ahora mismo:

- **No** se genera firma manuscrita realista de una persona real, ni un ID que
  imite un código de auditoría auténtico. Eso es falsificación documental a
  escala, sin importar el propósito.
- Sí se genera, solo para QA de maquetado: garabato aleatorio con el tamaño de una firma para revisar las coordenadas sintético procedural,


---

## Referencia externa: `firmacloudbackend`

Proyecto ya en producción en
`C:\Users\juan.acosta\Desktop\Backend firmacloud\firmacloudbackend` que
resuelve una necesidad hermana (módulo de "cartas de tratamiento" de la
intranet Obama): Node/Express + MySQL, envío masivo de un documento a una
lista de destinatarios con **firma electrónica real** (el firmante dibuja su
firma en una página pública con token, se captura IP/geolocalización/hash, se
genera certificado de auditoría legal).

Piezas reutilizables como referencia de diseño (no se copia código, se copia
el patrón):

| Necesidad | Dónde está en firmacloud | Patrón a imitar |
|---|---|---|
| Leer Excel de destinatarios | `src/services/oleadaFileParser.js` | Alias de encabezados configurables (`nombre`/`name`/`cliente`...), fila por fila válida/inválida, no falla en silencio |
| Mapeo campo→posición | `src/config/templates/*.json` | Config externa por plantilla: `{ page, x, y, fontSize, dataPath }`, no hardcodeado en el código |
| Relleno del PDF | `src/services/pdfService.js` → `fillContratoActivacion()` | Overlay de texto por coordenadas con `pdf-lib`, wrap de texto propio |
| Envío masivo controlado | `src/services/oleadaBatchService.js` | Cupo diario, lotes por horario, no perder el hilo de qué falló y por qué |

Si en algún punto el bot necesita conectarse con un flujo de firma real (no
placeholder), el patrón a seguir es el de `signatureController.js` /
`publicController.js`: enlace público con token → el firmante dibuja su
propia firma → se estampa esa imagen real, nunca una generada.

---

## Estado actual del proyecto (bot Python)

- Estructura `src/` creada (`ingesta.py`, `mapeo.py`, etc. **aún no
  escritos** — falta contenido real).
- Entorno virtual `.venv/` con Python 3.14.2, dependencias instaladas
  (`pandas`, `openpyxl`, `docxtpl`, `Pillow`, `pypdf`, `reportlab` + `pytest`,
  `ruff` en dev).
- Git inicializado, sin commits todavía.
- **Bloqueado en:** faltan los 3 insumos para escribir el código real —
  formato de plantilla (Word/PDF), Excel de ejemplo, plantilla de ejemplo.

---

## Historial de cambios

### 2026-08-24
- Creado el scaffold del proyecto: carpetas, `venv`, `requirements.txt` /
  `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `git init`.
- Revisado `firmacloudbackend` como referencia de solución real para el
  módulo de cartas de tratamiento; se documentan los patrones reutilizables
  arriba.

