# Diseño técnico de Radar IA (Fase 1)

Detalle de *cómo* se construye cada pieza del [plan](plan-fase-1.md). Las reglas de fondo están en [CLAUDE.md](../CLAUDE.md) y el *qué* en el [brief](brief.md). Si al implementar algo conviene cambiar este diseño, actualizar este archivo en el mismo paso.

## Estructura del repo

```
config.yaml            límites, modelos de IA, horarios (editable)
sources.yaml           fuentes y canales de YouTube (editable)       ← Paso 1
prompts/resumen.md     prompt de resumen + guía de estilo             ← Paso 7
prompts/brief.md       prompt de "Lo más importante hoy"              ← Paso 8
templates/             plantillas Jinja2 del sitio                    ← Paso 9
radar/
  cli.py               comandos (`python -m radar ...`)
  config.py            carga config.yaml y secretos (.env / entorno)
  fuentes.py           lee sources.yaml + comando `fuentes`           ← Paso 1
  recolectar.py        RSS/Atom + Hacker News → Candidato             ← Paso 2
  agrupar.py           URL canónica, id, agrupación por título        ← Paso 3
  filtrar.py           caché de procesados + pre-filtro sin IA + `filtrar` ← Paso 4
  ia.py                cliente Gemini/Groq con backoff y fallback     ← Pasos 5-6
  resumir.py           lotes → prompt → validación de esquema         ← Paso 7
  almacen.py           data/AAAA-MM-DD.json, guardar corrida, brief   ← Paso 8
  sitio.py             genera _site/ desde data/ + templates/         ← Paso 9
  pipeline.py          orquesta la corrida completa                   ← Paso 10
  simulacro.py         fallas a propósito para `correr --simular`     ← Paso 13
data/
  AAAA-MM-DD.json      noticias publicadas de ese día (hora de Chile)
  cache/procesados.json  ids ya resumidos o descartados
  pendientes.json      grupos que la IA no pudo procesar (se reintentan)
tests/                 sin red ni claves reales (fixtures en tests/fixtures/);
                       test_secretos.py vigila que ninguna clave se suba   ← Paso 11
_site/                 sitio generado (ignorado por git; lo publica Actions)
.github/workflows/radar.yml                                           ← Paso 12
```

## sources.yaml (Paso 1)

```yaml
fuentes:
  - nombre: Blog de Anthropic
    tipo: rss            # rss | hackernews | youtube | github | huggingface | papers
    url: https://...
    seccion: modelos     # sección por defecto (la IA puede cambiarla)
    idioma: en
    peso: 3              # 1 (ruido) a 3 (oficial/confiable); pesa en el pre-filtro
    activa: true
    max_por_corrida: 1   # opcional: tope propio en el pre-filtro (si no, prefiltro.max_por_fuente)
```

En `url`, `{desde}` se cambia por la fecha de hace `recolector.dias_tendencias` días (AAAA-MM-DD); hoy solo lo usa GitHub. `fuentes.url_real()` lo hace para `radar fuentes` y para el recolector.

Para YouTube, `url` es `https://www.youtube.com/feeds/videos.xml?channel_id=...` y `seccion: creadores`. Como esos feeds dan 404/500 a ratos desde fines de 2025, si el RSS falla se lee la página de videos del canal (`youtube.com/channel/<id>/videos?hl=<idioma>`, datos en `ytInitialData`): título, id y "hace 3 días" (fecha aproximada); solo para los videos recientes se abre su página para sacar la descripción (`shortDescription`, la misma del RSS). `hl` va en el idioma de la fuente porque en otro idioma YouTube traduce los títulos. `radar fuentes` y el log de la corrida avisan cuándo se usó la página del canal. Hacker News usa la API pública de Algolia (`hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points>=50`); el puntaje mínimo va en la URL y el filtro por palabras clave de IA lo hace el recolector (Paso 2).

- **Reddit** es `tipo: rss` con las 8 comunidades en **un solo feed combinado** (`/r/A+B+.../top/.rss?t=day&limit=50`): Reddit responde 429 si se piden varios feeds seguidos y 403 a su API JSON sin cuenta. El RSS no trae puntaje; "top del día" ya viene ordenado por popularidad.
- **Feeds comunitarios:** Anthropic (noticias y blog de Claude), Meta, Mistral y xAI no publican RSS. Se usan los que genera gratis `github.com/Olshansk/rss-feeds` (marcados con un comentario en `sources.yaml`).
- `radar/fuentes.py`: `cargar_fuentes()` valida todo `sources.yaml` y junta los errores en un solo mensaje; `crear_cliente(config)` es el cliente HTTP compartido (timeout y user-agent de `config.yaml`, lo reusa el recolector); `probar_todas()` prueba en paralelo (`fuentes.hilos`) y nunca lanza excepciones.
- **Fuentes en tendencia (Paso 14)**, todas APIs públicas sin cuenta (`TIPOS_JSON`; `items_json()` valida la forma de cada respuesta y `fecha_item_json()` da la fecha para "última novedad"):
  - `github`: `api.github.com/search/repositories` con `q=llm OR agent OR ai in:name,description,topics created:>={desde} stars:>=150`, orden por estrellas. Sin token: 10 búsquedas/min, de sobra para 1 por corrida (probado también desde Actions).
  - `huggingface`: `huggingface.co/api/models?sort=trendingScore&direction=-1&limit=30`.
  - `papers`: `huggingface.co/api/daily_papers?limit=100` (papers de arXiv que la comunidad sube y vota). Es la vía "muy filtrada" de arXiv: el API de arXiv no tiene ninguna señal de popularidad.
  - Product Hunt es `tipo: rss` (`producthunt.com/feed?category=artificial-intelligence`).
  - **Skills para Claude** (2026-10-26, sección `skills`): `GitHub (skills de Claude)` es otra búsqueda `github` (`q=skills claude in:name,description,topics created:>={desde} stars:>=100`); son 2 búsquedas por corrida, dentro del límite sin token. `Claude (blog)` es el feed comunitario `feed_claude.xml` de Olshansk.
- `radar fuentes` muestra una tabla: **OK**, **AVISO** (responde pero sin publicaciones, o sin novedades hace más de `fuentes.dias_aviso_sin_novedades` días) o **ERROR** (HTTP ≠ 200, sin conexión, contenido inválido). Sale con código 1 si alguna tiene ERROR.

## Candidato (salida del recolector, Paso 2)

Formato común para todo lo recolectado, antes de la IA:

```json
{"titulo": "...", "url": "https://...", "fuente": "Blog de X", "tipo": "rss",
 "seccion": "modelos", "idioma": "en", "peso": 3,
 "fecha": "2026-10-20T13:05:00+00:00", "extracto": "≤500 caracteres del RSS u og:description",
 "puntaje": 120}
```

`puntaje` solo existe en HN (el RSS de Reddit no lo trae). Las fechas se guardan en UTC y se convierten a hora de Chile solo para decidir "el día"; un candidato sin fecha se conserva y lo decide el pre-filtro.

Cómo trabaja `radar/recolectar.py`:

- Todas las fuentes se leen en paralelo con el cliente y la función `descargar()` de `radar/fuentes.py` (los mismos mensajes de error que `radar fuentes`). Una fuente caída, con HTTP ≠ 200 o con contenido inválido queda con su error en el informe y el resto sigue.
- De cada fuente se toman solo los de los últimos `limites.dias_antiguedad_max` días, los más nuevos primero, hasta `recolector.max_por_fuente`.
- **Extracto:** `summary` del feed (si es muy corto, `content`), limpio de HTML, de links sueltos y del relleno "The post … appeared first on …", cortado a `recolector.largo_extracto` sin partir palabras. Si queda con menos de 40 caracteres se lee el comienzo de la página (máx. 300 KB, solo HTML) y se usa `og:description` → `twitter:description` → `description`. Si la misma descripción aparece en varias páginas de una misma fuente, es la genérica del sitio y se descarta.
- **Hacker News:** solo historias cuyo título contiene alguna palabra de `recolector.palabras_ia` (palabra completa, sin importar mayúsculas). Sin `url` (Ask HN) se usa el link de la discusión y `story_text` como extracto.
- **Reddit:** el extracto es solo el texto del post (sin "submitted by…"); si el post apunta a un artículo externo, la `url` es la del artículo (imágenes/videos de `redd.it` se quedan con el link del post). A Reddit nunca se le piden páginas extra porque bloquea (429).
- **GitHub:** solo repos creados desde hace `dias_tendencias`; título `dueño/repo: descripción`, extracto = descripción + "N estrellas en GitHub · lenguaje · temas". La fecha es la de la **corrida** ("visto en alza hoy"): con la de creación, un repo de hace 5 días que está subiendo quedaría fuera de la ventana de 3 días. No se repite gracias a la caché.
- **Hugging Face (modelos):** igual de fecha y ventana; se saltan las copias cuantizadas (etiqueta `base_model:quantized:`). Extracto = "tipo · licencia · me gusta y descargas"; antes se le antepone el primer párrafo de presentación del `README.md` del modelo (`parrafo_readme()`: sin encabezado YAML, HTML, imágenes, tablas, listas ni código; ≥80 caracteres y ≥10 palabras; deja de buscar al llegar a un encabezado de uso, instalación, prompt, licencia, etc.). Del README se leen máx. 60 KB. La `og:description` de Hugging Face es la genérica del sitio y no sirve.
- **arXiv (destacados):** solo papers con ≥ `recolector.papers_votos_min` votos; link `arxiv.org/abs/<id>`, fecha = día en que salió en Daily Papers, extracto = comienzo del resumen + "N votos en Hugging Face".
- La popularidad (estrellas, me gusta, votos) va como dato en el extracto y no como `puntaje`: el bonus de HN las pondría por encima de las fuentes oficiales.
- `radar recolectar` muestra cuántos candidatos trajo cada fuente, cuántos extractos salieron de la página y los errores; `--mostrar N` imprime N ejemplos. Sale con código 1 solo si no se pudo leer ninguna fuente.

## Agrupar (Paso 3)

`radar/agrupar.py`; `radar recolectar` muestra al final "N candidatos → M noticias" y `--grupos` lista las que juntan más de un link.

- **URL canónica:** `https`, dominio en minúsculas y sin `www.`, sin `utm_*`/`ref`/`ref_src`/`fbclid`/`gclid`/`mc_cid`/`mc_eid`/`igshid`, demás parámetros ordenados, sin `#` ni `/` final. Los links de HN/Reddit que apuntan a un artículo ya llegan con la URL del artículo (Paso 2).
- **Agrupación** (unión de pares): misma URL canónica → mismo grupo siempre. Además, títulos parecidos **de fuentes distintas** (una misma fuente no repite noticias, pero sí títulos casi iguales para cosas distintas). Títulos normalizados (sin prefijo "Show HN:", sin tildes ni puntuación, minúsculas) y comparados **palabra por palabra** con `difflib.SequenceMatcher` ≥ `similitud_titulos`. Excepciones: si los números del título difieren no se agrupan ("Claude 4.5" ≠ "Claude 4.6"); si el título corto tiene ≥ 4 palabras y aparece entero y en orden en el largo, sí ("OpenAI acquires Orchestra Bio" = "OpenAI acquires startup Orchestra Bio to beef up…").
- **`Grupo`:** `candidatos` (el principal primero = el **más antiguo**; sin fecha al final), `id` = primeros 12 caracteres del SHA-1 de la URL canónica del principal, `confirmacion` = fuentes distintas, `fuentes` = `[{nombre, url}]` sin repetir la misma página (salen del recolector, nunca de la IA), `hashes` = hash de cada link del grupo. Al elegir como principal el más antiguo, el id no cambia cuando otras fuentes repiten la noticia después; igual la caché (Paso 4) revisa todos los `hashes` por si el principal salió de la ventana de días.
- Títulos en distintos idiomas o con otra redacción no se agrupan aquí; el prompt de la IA además une los ítems de un mismo lote que sean la misma noticia.

## Filtrar (Paso 4)

`radar/filtrar.py`; `radar filtrar` recolecta, agrupa y muestra qué se mandaría a la IA con su puntaje (no usa IA). `--marcar` guarda lo elegido en la caché como si la IA lo hubiera procesado (para probar sin IA; borrar `procesados.json` después).

- **Caché** `data/cache/procesados.json`: `{"<hash de un link>": "AAAA-MM-DD"}` para todo lo resumido **o descartado** por la IA. Se guardan los hashes de **todos** los links del grupo y una noticia cuenta como procesada si **cualquiera** de sus links ya está: así se reconoce aunque cambie el principal. Se podan las entradas de más de `cache.dias` días. Si el archivo está dañado se avisa y se parte de cero (a lo más se repite una corrida; nunca se cae).
- **Pre-filtro:** fuera lo ya procesado y lo que supera `dias_antiguedad_max`. Puntaje = mayor peso del grupo + `bonus_por_fuente_extra` por cada fuente adicional (máx. +3) + bonus por puntos de HN (`bonus_hn`, el mayor alcanzado) + `bonus_palabra_clave` si algún título tiene una de `palabras_clave` − `castigo_por_dia` × días de antigüedad (sin fecha = la ventana completa). Todo en `config.yaml` → `prefiltro`.
- **Topes:** cupo = `max_nuevas_por_corrida`, sin pasar de `max_por_dia` − publicadas hoy (largo de `noticias` en `data/<hoy>.json`, hoy en hora de Chile); y máximo `prefiltro.max_por_fuente` de una misma fuente por corrida, para que haya variedad. Una fuente con `max_por_corrida` en `sources.yaml` usa ese tope (`prefiltrar(..., topes=topes_por_fuente(fuentes))`): las 4 del Paso 14 tienen 1, así nunca aportan más de 4 de las 10 de una corrida.
- Lo no elegido **no** se marca: se reconsidera en la corrida siguiente hasta que sale de la ventana de días.
- **Pendientes** (Paso 6) `data/pendientes.json`: `{"grupos": [{"id", "titulo", "candidatos": [Candidato]}]}`. Se guardan los candidatos completos (título, link, extracto corto, nunca el artículo) para reintentar aunque la noticia ya no salga en el feed; un candidato sin fecha queda con la de la corrida para que igual expire. `sumar_pendientes()` los junta con lo recolectado (si la noticia volvió a aparecer se usa la versión nueva, sin duplicar) y `prefiltrar(..., pendientes=)` los pone **primero**, antes que el puntaje (sí respetan el cupo y el tope por fuente). Después de la IA, `actualizar_pendientes()` deja los que fallaron ahora + los anteriores sin procesar, sin los ya procesados ni los que salieron de la ventana de días. Archivo dañado = aviso y se parte sin pendientes.

## IA (Pasos 5-7)

- `ia.py` expone `pedir_json(prompt) -> dict`. Llamadas HTTP directas con `httpx`:
  - Gemini: `POST https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent` con la clave en la cabecera `x-goog-api-key` (nunca en la URL) y `responseMimeType: application/json`.
  - Groq: `POST https://api.groq.com/openai/v1/chat/completions` (formato OpenAI) con `response_format: {"type": "json_object"}`.
- `llamar(proveedor, modelo, prompt, clave, cliente) -> str` (Paso 5) hace una llamada sin reintentos y lanza `ErrorIA` con `motivo`: `clave` (401/403 o clave inválida), `modelo` (404 o retirado), `cuota` (429), `red` (5xx, timeout, sin conexión) o `respuesta` (vacía o sin formato). Gemini: se ignoran las partes de razonamiento (`thought: true`). Los mensajes nunca copian el cuerpo del error ni la clave.
- `radar probar-ia` (Paso 5) pide `{"respuesta": "OK"}` a principal y respaldo; si el modelo no existe, lista los modelos que la clave puede usar (`GET /models`). Modelos vigentes: `gemini-3.5-flash-lite` y `openai/gpt-oss-120b` (Groq gratis: 30 pedidos/min, 1.000/día, 8K tokens/min).
- `pedir_json(prompt, config, cliente, validar=None) -> dict` (Paso 6) es la única puerta a la IA. Por proveedor (principal y luego respaldo):
  - `cuota` (429) o `red` (5xx, timeout, sin conexión): espera `espera_inicial_seg * 2^intento` (o lo que pida el servicio: cabecera `Retry-After` o `retryDelay` de Gemini), nunca más de `espera_max_seg`, hasta `reintentos` intentos.
  - `clave` o `modelo` (o clave faltante): reintentar no sirve → pasa directo al respaldo.
  - `respuesta` (no es JSON, no es objeto o `validar` lanza `ValueError`): se pide una vez más sin esperar y luego pasa al respaldo.
  - Si ambos fallan lanza `IANoDisponible(fallos)` (motivos sin claves) y el lote va a `pendientes.json`. Imprime una línea por reintento para el log de Actions.
- `llamar(..., opciones)`: `ia.<rol>.opciones` de `config.yaml` se suman al pedido (Gemini: dentro de `generationConfig`; Groq: arriba). Groq usa `reasoning_effort: low`: un lote de 10 gastaba ~6K tokens (casi 2K de razonamiento) contra un límite de 8K/min; con `low`, ~4,8K. Un 400 muestra solo el código corto del error (p. ej. `json_validate_failed`).
- **Resumir** (Paso 7, `radar/resumir.py`): `resumir(grupos, config, cliente, hoy)` manda lotes de `tamano_lote` con el prompt `prompts/resumen.md` (marcador `{{NOTICIAS}}`). Cada noticia va a la IA como `{n, titulo, fuente, tipo, sitio, seccion_sugerida, idioma, extracto, otras_fuentes?}` — sin URLs, para que no pueda inventar links; `otras_fuentes` trae título y extracto de las demás fuentes del grupo.
- **Respuesta de la IA:** `{"noticias": [...]}` con **una entrada por cada `n`**: resumida (`titulo`, `que_paso`, `por_que_importa`, `seccion`, `importancia`, `terminos`, `etiquetas`), `{"n", "descartar": true, "motivo"}` o `{"n", "misma_que": k}` (misma noticia que otra del lote: sus links se suman a `k`). `validar_respuesta()` revisa todo (n completos y sin repetir, campos de texto no vacíos, sección e importancia válidas, términos y etiquetas bien formados, `misma_que` apuntando a una resumida); si falla, `pedir_json` la cuenta como respuesta mala.
- **Salida por noticia:** el esquema de la sección 7 del brief. `id`, `fecha` (hoy en Chile), `fuentes` y `confirmacion` los pone el código a partir del grupo; etiquetas en minúsculas, sin repetir, máx. 4. `Resultado` trae `noticias`, `descartadas` (con motivo), `unidas`, `procesados` (todo lo que la IA vio → caché) y `fallidos` (→ pendientes). Si un lote falla con `IANoDisponible`, ese y los siguientes van a `fallidos` sin gastar más intentos.
- `radar resumir [--json]` es la prueba del prompt: recolecta, elige como una corrida real y muestra los resúmenes; no toca la caché ni los pendientes.

## Día y brief (Paso 8)

`radar/almacen.py`. `data/AAAA-MM-DD.json`:

```json
{"fecha": "2026-10-20", "actualizado": "2026-10-20T12:31:00-03:00",
 "brief": {"lo_mas_importante": ["...", "...", "..."], "ids": ["a1b2c3d4e5f6", "..."]},
 "noticias": [ { ...esquema sección 7... } ]}
```

- **Guardar:** `guardar_corrida(resultado, pendientes_anteriores, config, ahora)` hace todo lo que sigue a la IA: suma `resultado.noticias` al día de hoy (sin repetir `id`, ninguna sin link `http(s)`), marca `resultado.procesados` en la caché y reescribe `pendientes.json` con `actualizar_pendientes()`. El archivo se escribe a un `.tmp` y se reemplaza (nunca queda a medias). Si está dañado se renombra a `AAAA-MM-DD.danado.json` y se parte con el día vacío.
- **Cuándo:** `brief` es `null` hasta que la **primera corrida del día después de `brief.hora_desde`** (hora de Chile) lo arma; una vez armado no se rehace (salvo `radar brief --forzar`). Sin noticias no se arma y se intenta en la corrida siguiente.
- **Qué entra:** las noticias de hoy + las de ayer que no están en el brief de ayer (las de la tarde y la noche). Orden: 🔥 primero, después más `confirmacion`, y a igualdad las de hoy antes que las de ayer; se toman ≤ `max_brief`. Se guardan solo los `ids`: una noticia de ayer sigue viviendo en el archivo de ayer (el sitio las busca en ambos).
- **Bullets:** una llamada aparte con `prompts/brief.md` (marcadores `{{CANTIDAD}}` y `{{NOTICIAS}}`; la IA ve título, qué pasó, por qué importa e importancia, sin links). Respuesta `{"lo_mas_importante": [...]}` con exactamente `min(3, noticias del brief)` frases no vacías de ≤ 300 caracteres. Mismo modelo que los resúmenes. Si la IA no responde, el brief queda con sus `ids` y `lo_mas_importante: []`, y la corrida siguiente solo completa los bullets.
- **Revisión** `problemas_dia()` (lista vacía = OK): toda noticia del día y del brief con link, sin ids repetidos, ≤ `max_por_dia` noticias, brief ≤ `max_brief` y apuntando a noticias que existen, bullets bien formados.
- **Comandos:** `radar resumir --guardar` corre recolectar → filtrar → IA → `guardar_corrida` (sin `--guardar` sigue siendo la prueba que no toca nada). `radar brief [--forzar]` arma o completa el brief con lo ya guardado, lo muestra y corre la revisión (sale con 1 si hay problemas). El Paso 10 (`radar correr`) junta ambos.

## Sitio (Paso 9)

`radar/sitio.py` + `templates/` (Jinja2 con autoescape: el texto de la IA nunca se interpreta como HTML).

- `python -m radar sitio [--revisar-links]` → `_site/`: `index.html` (brief), `secciones.html` (noticias de los últimos `sitio.dias_secciones` días con filtros), `archivo/index.html` (lista de días) y `archivo/AAAA-MM-DD.html` (bullets + todas las noticias del día, 🔥 primero, con día anterior/siguiente). Un solo `estilo.css`, sin frameworks ni CDNs, mobile-first, `noindex` (uso personal). La fuente Archivo (licencia libre OFL) va dentro del sitio (`templates/archivo.woff2`, se copia a `_site/` junto con el CSS y su licencia: `ARCHIVOS_ESTATICOS`).
- Se arma en `_site.tmp/` y recién al final reemplaza `_site/`: si algo falla, el sitio anterior queda entero. Solo **lee** `data/`: un día dañado se avisa y no aparece (el Paso 8 lo aparta al volver a escribir ese día).
- **Portada:** el brief más reciente (≤ hoy). Si el de hoy aún no está (corrida de las 00:30) muestra el de ayer con un aviso. Las noticias del brief que vienen de ayer se buscan en el archivo de ayer y llevan "de ayer". Debajo, un link a las noticias de hoy que quedaron fuera del brief. Muestra la lectura estimada: palabras de bullets + título, qué pasó y por qué importa ÷ `sitio.palabras_por_minuto` (200); los términos van plegados (`<details>`).
- **Diseño "Espectro en riel"** (rediseño del 2026-10-24; reglas visuales en `DESIGN.md`, producto en `PRODUCT.md`): tema oscuro fijo, fondo de carbón con bandas y la columna de lectura sobre una placa lisa; todo se alinea a un riel vertical (en el computador los datos de cada noticia cuelgan a su izquierda). Color solo como líneas finas, una por sección (modelos violeta, herramientas índigo, tendencias cian, creadores verde, dinero naranja, tips rojo); el amarillo sodio en doblete marca los 3 puntos clave. **Espectro:** `espectro(noticias, fecha)` da una línea por noticia con su posición `x` (%) dentro de la franja de su sección; en la plantilla la línea es doble si es importante y de media altura si es de ayer. En la portada y en cada día las líneas son links a la noticia (al pasar el mouse el pie dice cuál es); en Secciones son dibujo y siguen a los filtros (lo filtrado baja a un muñón). En el Archivo cada día lleva un espectro en miniatura.
- **Fotos** (2026-10-26, `radar/imagenes.py`): cada noticia guarda `imagen` = link a la foto de vista previa de su primera fuente que tenga una (`og:image` / `twitter:image`, leyendo solo el comienzo de la página como con `og:description`; YouTube → miniatura `i.ytimg.com` del video, también de los shorts). Se descartan logos e íconos (patrón en la URL). Solo se guarda el link, nunca la imagen; `imagen: null` = no hay foto. La corrida la busca después de la IA y antes de guardar; `radar imagenes` completa las noticias ya guardadas que no tienen el campo (sin cambiar la hora de actualización). En el sitio la foto se muestra desde la fuente y, si no hay o no carga, se ve la ilustración propia (`ilustracion(id)`: líneas del color de la sección). Las fotos no entran en `--revisar-links`.
- **Cada noticia:** importante, sección, fecha (en Secciones), "N fuentes la cuentan" si `confirmacion > 1` (puede haber menos links que fuentes: si HN comparte el artículo de The Verge es un solo link), título, qué pasó, por qué importa, términos, etiquetas y links "Leer en: X →" (pestaña nueva, `rel=noopener`).
- **Filtros (Secciones):** atributos `data-seccion`, `data-alta`, `data-etiquetas` en cada noticia y ~40 líneas de JS: una sección (o todas) + "solo importantes" + una etiqueta (las 20 más usadas), con contador y aviso si no queda ninguna. Sin JS los filtros no aparecen y se ven todas.
- **Revisión de links:** siempre se comprueba que los links entre páginas apunten a archivos que existen. Con `--revisar-links` además se prueba cada link a las fuentes (GET sin bajar la página, en paralelo, mismo user-agent que el recolector): 2xx/3xx = OK; 401/403/429/999 = AVISO (el sitio existe pero bloquea programas); 404, 5xx o sin conexión = ERROR (sale con 1).
- **Ver en local:** `.claude/launch.json` define el servidor `sitio` (`python -m http.server 8001 --directory _site`, Windows; en el Mac, `sitio-mac` en el puerto 8000); abrir el `index.html` directo con doble clic también funciona.

- **Vercel** (2026-10-26, además de GitHub Pages): proyecto `radar-ia` en la cuenta Hobby (gratis) del usuario, conectado al repositorio. `vercel.json` le dice cómo armarlo: crea `.venv` (el Python de Vercel no deja instalar paquetes en el sistema), instala `requirements.txt`, corre `python -m radar sitio` y publica `_site/`. Cada push a `main` (incluidos los del robot de datos) vuelve a publicar solo. Dirección pública: https://radar-ia-joaquin.vercel.app (`radar-ia.vercel.app` es de otra persona; las direcciones `*-joaquinpoupin-5629s-projects.vercel.app` piden iniciar sesión).

## Corrida completa (Paso 10)

`radar/pipeline.py`: `python -m radar correr [--forzar-brief]` es lo que correrá Actions.

- Tres etapas en orden: **Noticias** (recolectar → agrupar → sumar pendientes → pre-filtro → `resumir` → `guardar_corrida`), **Brief** (`actualizar_brief` + `problemas_dia`; el día se reescribe solo si el brief cambió) y **Sitio** (`generar_sitio` + links internos). Un solo cliente HTTP para la IA en toda la corrida.
- Cada etapa va envuelta: si explota por algo inesperado, se imprime el detalle técnico, se anota el error y se sigue; el sitio se genera igual con lo ya guardado.
- **Código de salida** (Actions lo usa para marcar verde/rojo): 0 si todo anduvo, aunque haya **avisos** esperables (fuentes caídas, IA sin cuota → pendientes, brief sin bullets). 1 si hubo **errores**: una etapa explotó, no se pudo leer *ninguna* fuente, la revisión del día encontró problemas o hay links internos rotos.
- Sin noticias nuevas no se toca `data/` (no se crea un día vacío). `--forzar-brief` arma el brief aunque sea antes de `brief.hora_desde` o lo rehace (para probar en local; en Actions no se usa).
- Imprime una sección por etapa con su duración y un resumen final (nuevas, pendientes, link al sitio, avisos, errores): queda legible en el log de Actions.

## Automatización (Pasos 11-12)

- Repo público `joaquinpoupin-lgtm/radar-ia` (rama `main`), Pages con origen **GitHub Actions** (no una rama `gh-pages`): `https://joaquinpoupin-lgtm.github.io/radar-ia/`. Secrets `GEMINI_API_KEY` y `GROQ_API_KEY` ya guardados. Los commits usan el correo noreply de GitHub (también el robot del Paso 12 debe usar uno noreply).

- `.github/workflows/radar.yml`: `schedule` con `cron: '30 0,6,12,18 * * *'` y `timezone: "America/Santiago"` (sintaxis oficial de GitHub; minuto 30 porque a la hora en punto Actions se atrasa más) + `workflow_dispatch` (botón "Run workflow").
- `concurrency: {group: radar, cancel-in-progress: false}`: nunca dos corridas a la vez; la siguiente espera.
- Job `correr` (permiso `contents: write`): checkout → Python 3.12 (caché de pip) → `pip install -r requirements.txt` → `python -m radar correr` con `continue-on-error` → commit de `data/` como `github-actions[bot]` (correo noreply) solo si hubo cambios, con `git pull --rebase` antes del push → `upload-pages-artifact` con `_site/` si existe → si el radar falló, la corrida termina en rojo. Así un error no impide guardar lo ya hecho ni publicar el sitio.
- Job `publicar` (permisos `pages: write`, `id-token: write`, entorno `github-pages`): `deploy-pages`; corre aunque `correr` termine en rojo.
- Secrets `GEMINI_API_KEY` y `GROQ_API_KEY` solo como variables de entorno del paso que corre el radar (GitHub las tapa con `***` en el log). `tests/test_workflow.py` vigila horario, concurrencia, Secrets y correo noreply.
- El robot también escribe `data/`: en el Mac, `git pull` antes de correr el radar en local.
- `workflow_dispatch` tiene la entrada `simular` (texto, vacía por defecto): llega al paso del radar como variable `SIMULAR` y el comando es `python -m radar correr ${SIMULAR:+--simular "$SIMULAR"}` (nunca `${{ inputs... }}` dentro de `run`, para que no se pueda inyectar otro comando). Los horarios no tienen entradas: siempre corren normal.
- GitHub desactiva los horarios de un repo público tras 60 días sin actividad (se reactivan a mano); los commits del robot deberían mantenerlo activo, a confirmar en el Paso 15.

## Simulacros de fallas (Paso 13)

`radar/simulacro.py`: `python -m radar correr --simular FALLAS` (separadas por coma) provoca fallas a propósito solo en esa corrida; no toca `.env`, los Secrets ni `sources.yaml`. Los datos sí se guardan como en una corrida normal (de eso se trata: lo pendiente debe quedar y retomarse después).

- `sin-clave-gemini`: deja `GEMINI_API_KEY` vacía en el proceso (vacía y no borrada, para que `cargar_env()` no la vuelva a leer del `.env`) → `pedir_json` pasa directo a Groq.
- `cuota-gemini` / `cuota-todas`: el cliente de la IA usa `TransporteSinCuota`, que responde 429 a los servicios indicados (sin `Retry-After`, así se usa la espera creciente propia) y deja salir de verdad lo demás. Con `cuota-todas` lo elegido termina en `data/pendientes.json`.
- `fuente-caida`: suma `FUENTE_CAIDA` (`https://fuente-caida.invalid/feed.xml`; el dominio `.invalid` está reservado y nunca existe).
- La corrida imprime `SIMULACRO <nombre>: ...` al inicio y suma el aviso "simulacro activo" al resumen final. Un nombre desconocido termina con código 1 sin correr nada.
