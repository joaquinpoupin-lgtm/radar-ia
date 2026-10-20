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
  filtrar.py           caché de procesados + pre-filtro sin IA        ← Paso 4
  ia.py                cliente Gemini/Groq con backoff y fallback     ← Pasos 5-6
  resumir.py           lotes → prompt → validación de esquema         ← Paso 7
  almacen.py           data/AAAA-MM-DD.json, pendientes, brief        ← Paso 8
  sitio.py             genera _site/ desde data/ + templates/         ← Paso 9
  pipeline.py          orquesta la corrida completa                   ← Paso 10
data/
  AAAA-MM-DD.json      noticias publicadas de ese día (hora de Chile)
  cache/procesados.json  ids ya resumidos o descartados
  pendientes.json      grupos que la IA no pudo procesar (se reintentan)
tests/                 sin red ni claves reales (fixtures en tests/fixtures/)
_site/                 sitio generado (ignorado por git; lo publica Actions)
.github/workflows/radar.yml                                           ← Paso 12
```

## sources.yaml (Paso 1)

```yaml
fuentes:
  - nombre: Blog de Anthropic
    tipo: rss            # rss | hackernews | youtube   (Paso 14 suma: github, huggingface, producthunt, arxiv)
    url: https://...
    seccion: modelos     # sección por defecto (la IA puede cambiarla)
    idioma: en
    peso: 3              # 1 (ruido) a 3 (oficial/confiable); pesa en el pre-filtro
    activa: true
```

Para YouTube, `url` es `https://www.youtube.com/feeds/videos.xml?channel_id=...` y `seccion: creadores`. Hacker News usa la API pública de Algolia (`hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points>=50`); el puntaje mínimo va en la URL y el filtro por palabras clave de IA lo hace el recolector (Paso 2).

- **Reddit** es `tipo: rss` con las 8 comunidades en **un solo feed combinado** (`/r/A+B+.../top/.rss?t=day&limit=50`): Reddit responde 429 si se piden varios feeds seguidos y 403 a su API JSON sin cuenta. El RSS no trae puntaje; "top del día" ya viene ordenado por popularidad.
- **Feeds comunitarios:** Anthropic, Meta, Mistral y xAI no publican RSS. Se usan los que genera gratis `github.com/Olshansk/rss-feeds` (marcados con un comentario en `sources.yaml`).
- `radar/fuentes.py`: `cargar_fuentes()` valida todo `sources.yaml` y junta los errores en un solo mensaje; `crear_cliente(config)` es el cliente HTTP compartido (timeout y user-agent de `config.yaml`, lo reusa el recolector); `probar_todas()` prueba en paralelo (`fuentes.hilos`) y nunca lanza excepciones.
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
- `radar recolectar` muestra cuántos candidatos trajo cada fuente, cuántos extractos salieron de la página y los errores; `--mostrar N` imprime N ejemplos. Sale con código 1 solo si no se pudo leer ninguna fuente.

## Agrupar (Paso 3)

`radar/agrupar.py`; `radar recolectar` muestra al final "N candidatos → M noticias" y `--grupos` lista las que juntan más de un link.

- **URL canónica:** `https`, dominio en minúsculas y sin `www.`, sin `utm_*`/`ref`/`ref_src`/`fbclid`/`gclid`/`mc_cid`/`mc_eid`/`igshid`, demás parámetros ordenados, sin `#` ni `/` final. Los links de HN/Reddit que apuntan a un artículo ya llegan con la URL del artículo (Paso 2).
- **Agrupación** (unión de pares): misma URL canónica → mismo grupo siempre. Además, títulos parecidos **de fuentes distintas** (una misma fuente no repite noticias, pero sí títulos casi iguales para cosas distintas). Títulos normalizados (sin prefijo "Show HN:", sin tildes ni puntuación, minúsculas) y comparados **palabra por palabra** con `difflib.SequenceMatcher` ≥ `similitud_titulos`. Excepciones: si los números del título difieren no se agrupan ("Claude 4.5" ≠ "Claude 4.6"); si el título corto tiene ≥ 4 palabras y aparece entero y en orden en el largo, sí ("OpenAI acquires Orchestra Bio" = "OpenAI acquires startup Orchestra Bio to beef up…").
- **`Grupo`:** `candidatos` (el principal primero = el **más antiguo**; sin fecha al final), `id` = primeros 12 caracteres del SHA-1 de la URL canónica del principal, `confirmacion` = fuentes distintas, `fuentes` = `[{nombre, url}]` sin repetir la misma página (salen del recolector, nunca de la IA), `hashes` = hash de cada link del grupo. Al elegir como principal el más antiguo, el id no cambia cuando otras fuentes repiten la noticia después; igual la caché (Paso 4) revisa todos los `hashes` por si el principal salió de la ventana de días.
- Títulos en distintos idiomas o con otra redacción no se agrupan aquí; el prompt de la IA además une los ítems de un mismo lote que sean la misma noticia.

## Filtrar (Paso 4)

- `procesados.json`: `{"<id>": "AAAA-MM-DD"}` para todo lo resumido **o descartado** por la IA. Se podan las entradas de más de 30 días.
- Pre-filtro: se descarta lo que supera `dias_antiguedad_max`. Puntaje = peso de la fuente + bonus por `confirmacion` + bonus por puntaje HN/Reddit + bonus por palabras clave (lanzamiento, modelo, gratis, open source, agente...). Se envían a la IA los `max_nuevas_por_corrida` mejores, sin pasar de `max_por_dia` publicadas ese día.
- Los pendientes de corridas anteriores tienen prioridad.

## IA (Pasos 5-7)

- `ia.py` expone `pedir_json(prompt) -> dict`. Llamadas HTTP directas con `httpx`:
  - Gemini: `POST https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent` con la clave en la cabecera `x-goog-api-key` (nunca en la URL) y `responseMimeType: application/json`.
  - Groq: `POST https://api.groq.com/openai/v1/chat/completions` (formato OpenAI) con `response_format: {"type": "json_object"}`.
- Ante 429/5xx/timeout: espera `espera_inicial_seg * 2^intento` (respetando `Retry-After` si viene) hasta `reintentos`; luego pasa al respaldo; si también falla, lanza `IANoDisponible` y el pipeline manda el lote a `pendientes.json`.
- Una respuesta que no cumple el esquema cuenta como fallo (se reintenta una vez y después queda pendiente).
- **Salida por noticia:** el esquema de la sección 7 del brief, más `"descartar": true` si no es relevante. `fuentes` y `confirmacion` los pone el código (no la IA) a partir del grupo, para que los links nunca sean inventados.
- Lote = `tamano_lote` grupos con título, extracto, fuente y URL. El prompt pide parafrasear, no inventar, marcar rumores, explicar términos y aplicar el filtro anti-humo de la sección "dinero".

## Día y brief (Paso 8)

`data/AAAA-MM-DD.json`:

```json
{"fecha": "2026-10-20", "actualizado": "2026-10-20T12:31:00-03:00",
 "brief": {"lo_mas_importante": ["...", "...", "..."], "ids": ["a1b2c3d4e5f6", "..."]},
 "noticias": [ { ...esquema sección 7... } ]}
```

- `brief` es `null` hasta que la **primera corrida del día después de `hora_desde`** lo arma: elige ≤ `max_brief` noticias del día (más las de la noche anterior aún no incluidas en un brief), con 🔥 primero, y pide los 3 bullets en una llamada aparte. Si la IA no está disponible, el brief se arma sin bullets y se reintentan en la corrida siguiente.

## Sitio (Paso 9)

- `python -m radar sitio` → `_site/`: `index.html` (brief de hoy), `secciones.html` (todas las noticias recientes con filtros por sección, 🔥 y etiquetas en JS simple), `archivo/AAAA-MM-DD.html` + `archivo/index.html`.
- Mobile-first, un solo CSS, sin frameworks ni CDNs, modo oscuro automático. Cada noticia muestra: título, qué pasó, por qué importa, términos explicados, etiquetas y links a las fuentes (abren en pestaña nueva).

## Automatización (Paso 12)

- `.github/workflows/radar.yml`: `schedule` con `cron: '30 0,6,12,18 * * *'` y `timezone: America/Santiago` (verificar la sintaxis contra la documentación oficial de GitHub al implementarlo) + `workflow_dispatch`.
- `concurrency: radar` (nunca dos corridas a la vez). Pasos: checkout → Python 3.12 → instalar → `python -m radar correr` → commit de `data/` con el bot si hubo cambios → subir `_site/` con `actions/upload-pages-artifact` + `actions/deploy-pages`.
- Secrets `GEMINI_API_KEY` y `GROQ_API_KEY` como variables de entorno del paso que corre el radar.
