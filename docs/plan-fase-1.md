# Plan Fase 1 — MVP de Radar IA

Cada paso es pequeño y termina con una **verificación** concreta. No se pasa al siguiente hasta que la verificación pasó. Marcar `[x]` al completar.

## Cómo fluye una corrida (idea general)

```
fuentes (sources.yaml)
  → recolectar (RSS, Hacker News)         ~cientos de candidatos
  → normalizar + deduplicar + agrupar     misma noticia = un grupo con varios links
  → quitar lo ya procesado (caché)        nunca resumir dos veces
  → pre-filtro sin IA (fuente, puntaje,   se quedan los ~10 mejores nuevos por corrida
    palabras clave)
  → IA: clasificar + resumir en lote      Gemini → si falla, Groq → si falla, pendiente
  → guardar data/AAAA-MM-DD.json
  → (corrida de 06:30) armar brief del día
  → generar sitio estático → GitHub Pages
```

---

## Bloque A — En tu Mac (sin cuentas todavía)

- [x] **Paso 0 — Base del proyecto**
  Carpetas, `git init`, `.gitignore` (incluye `.env`), entorno virtual de Python, `requirements.txt` (feedparser, httpx, jinja2, pyyaml), `config.yaml` y `.env.example`.
  **Verificación:** `python -m radar --help` muestra los comandos disponibles.

- [x] **Paso 1 — Fuentes base verificadas**
  `sources.yaml` con ~20 fuentes (blogs oficiales con RSS, Hacker News, subreddits, 8 canales de YouTube) con: nombre, tipo, URL, sección por defecto, idioma, peso. Comando `radar fuentes` que prueba cada una.
  **Verificación:** tabla con cada fuente en OK o con su error; las que fallan se arreglan o se quitan.

- [x] **Paso 2 — Recolector**
  Lee RSS/Atom y la API de Hacker News (filtrando IA) y convierte todo a un formato común (título, URL, fuente, fecha, extracto corto). Si el RSS no trae extracto, toma la descripción corta de la página (`og:description`). Una fuente caída no detiene el resto.
  **Verificación:** `radar recolectar` muestra cuántos candidatos trajo por fuente; un test con feeds de ejemplo pasa sin internet.

- [x] **Paso 3 — Deduplicar y agrupar**
  URL limpia (sin `utm_`, etc.) → hash estable como `id`. Títulos parecidos de distintas fuentes se agrupan en una sola noticia con varios links (`confirmacion` = cuántas fuentes).
  **Verificación:** tests con duplicados de ejemplo; en una corrida real se ve "N candidatos → M noticias".

- [x] **Paso 4 — Caché y pre-filtro sin IA**
  `data/cache/procesados.json` guarda los `id` ya resumidos. Pre-filtro por peso de fuente, puntaje (HN/Reddit), palabras clave y antigüedad; deja como máximo ~10 nuevas por corrida y respeta el tope de 25 al día.
  **Verificación:** correr dos veces seguidas (`radar filtrar --marcar`, que simula que la IA procesó lo elegido) → la segunda vez reconoce las ya procesadas y no repite ninguna; cuando no queda nada sin procesar dice "0 noticias nuevas" (test).

## Bloque B — La IA (aquí necesitamos tus claves de Gemini y Groq)

- [ ] **Paso 5 — Claves gratis** *(te guío paso a paso)*
  Clave de Gemini en Google AI Studio y de Groq en console.groq.com, sin tarjeta. En tu Mac van en el archivo `.env` (nunca se sube a GitHub).
  **Verificación:** `radar probar-ia` responde "OK" con cada proveedor, sin mostrar las claves.

- [ ] **Paso 6 — Cliente de IA robusto**
  Una sola función "pedir a la IA" que: reintenta con espera creciente ante 429, cambia a Groq si Gemini falla, y si ambos fallan deja las noticias en `data/pendientes.json`.
  **Verificación:** tests con un proveedor falso que simula 429 y caídas: nada se rompe y lo pendiente se reintenta en la corrida siguiente.

- [ ] **Paso 7 — Prompt de resumen y validación**
  `prompts/resumen.md` con la guía de estilo del brief (sección 7) y el filtro anti-humo de "dinero". Se envían ~10 noticias por llamada; la respuesta se valida contra el esquema JSON. La IA puede descartar lo irrelevante.
  **Verificación:** corrida real con ~10 noticias; **tú** lees los resúmenes y confirmas que se entienden sin saber de programación. Ajustamos el prompt hasta que te convenza.

- [ ] **Paso 8 — Guardar el día y armar el brief**
  Las noticias se agregan a `data/AAAA-MM-DD.json` (hora de Chile). La corrida de 06:30 elige las ≤10 más importantes y genera "Lo más importante hoy" en 3 bullets (una llamada extra a la IA).
  **Verificación:** el JSON es válido, el brief tiene ≤10 ítems y cada uno tiene al menos un link.

## Bloque C — La web

- [ ] **Paso 9 — Sitio estático mobile-first**
  Páginas: Brief del día (portada), Secciones con filtros (sección, 🔥, etiquetas) y Archivo por fecha. HTML + CSS + un poco de JS, sin servidor.
  **Verificación:** se abre en el navegador en tamaño celular, se lee en ~3 minutos y un chequeo automático confirma que todos los links responden.

- [ ] **Paso 10 — Corrida completa local**
  `radar correr` hace todo de punta a punta: recolectar → resumir → guardar → sitio.
  **Verificación:** desde cero, un solo comando deja el sitio listo en tu Mac.

## Bloque D — Automático en internet (aquí necesitamos tu cuenta de GitHub)

- [ ] **Paso 11 — Repo en GitHub y Secrets** *(te guío paso a paso)*
  Repo público `radar-ia`, subir el código, guardar `GEMINI_API_KEY` y `GROQ_API_KEY` como Secrets, activar GitHub Pages.
  **Verificación:** el repo se ve en GitHub y no hay ninguna clave en el código (búsqueda automática).

- [ ] **Paso 12 — GitHub Actions**
  Workflow con cron 00:30 / 06:30 / 12:30 / 18:30 hora de Chile + botón manual. Guarda los datos con un commit del robot y publica el sitio en Pages. Nunca corren dos a la vez.
  **Verificación:** lanzamiento manual en verde y el sitio en `TUUSUARIO.github.io/radar-ia`.

- [ ] **Paso 13 — Prueba de fallas**
  Simular: sin clave de Gemini, cuota agotada, una fuente caída.
  **Verificación:** la corrida termina en verde, lo pendiente queda guardado y se resume en la siguiente.

- [ ] **Paso 14 — Ampliar fuentes**
  Sumar GitHub Trending (vía búsqueda de la API pública), Hugging Face en tendencia, Product Hunt (IA) y arXiv muy filtrado, verificando cada uno como en el Paso 1.
  **Verificación:** aparecen en `radar fuentes` en OK y no inundan el brief.

- [ ] **Paso 15 — Observación de 3 días**
  Dejarlo correr solo y revisar los criterios de éxito del brief (sección 9): corre solo, brief cada mañana legible en ~3 min, resúmenes claros, links funcionando, $0, sin roturas.
  **Verificación:** todos los criterios en OK → **MVP terminado** → recién ahí, Fase 2.

---

## Bitácora

Una línea por paso terminado: fecha · paso · qué se hizo · decisiones o problemas.

- 2026-10-20 · Kickoff · Decisiones de la sección 12 aceptadas (todas las recomendaciones): Python, repo público + GitHub Pages, cron cada 6 h, YouTube por título + descripción, ≤10 en brief / ≤25 al día. Usuario de GitHub pendiente (se pide en el Paso 11).
- 2026-10-20 · Paso 0 · Estructura, git, `.venv`, dependencias fijadas, `config.yaml`, `.env.example`, CLI con comandos planeados y 4 tests en verde. Se agregó `docs/diseno.md` con el diseño de todos los pasos.
- 2026-10-20 · Paso 1 · `sources.yaml` con 26 fuentes (10 empresas, HN, Reddit, 5 medios/blogs, 9 canales de YouTube) y comando `radar fuentes` (prueba en paralelo, tabla OK/AVISO/ERROR, sale con error si alguna falla); 25 OK + 1 aviso (DotCSV sin videos hace 152 días; se deja y se sumó Dot CSV Lab, que sí publica). 16 tests en verde. Decisiones: Anthropic, Meta, Mistral y xAI no tienen RSS oficial → feed comunitario gratuito (github.com/Olshansk/rss-feeds); Reddit bloquea pedidos seguidos (429) y su API JSON (403) → las 8 comunidades van en un solo feed RSS combinado (sin puntaje; ordenado por "top del día"). Descartadas: Qwen (sin posts desde 2025), DeepSeek (sin RSS), feed viejo de Microsoft (410). Pendiente para el Paso 12: confirmar que Reddit responde desde GitHub Actions.
- 2026-10-20 · Paso 2 · `radar/recolectar.py` + `radar recolectar [--mostrar N]`: RSS/Atom/YouTube/Reddit y API de HN → `Candidato`; solo últimos `dias_antiguedad_max` días y máx. `recolector.max_por_fuente` por fuente; extractos limpios (sin HTML, sin links, ≤500 caracteres). Corrida real: 128 candidatos de 26 fuentes, 0 errores, ~6 s. 24 tests en verde sin internet. Decisiones: HN se filtra por palabras de IA en el título (`recolector.palabras_ia`, palabra completa); extractos de <40 caracteres (p. ej. "TBD") se completan con `og:description`, salvo Reddit; si la misma descripción se repite en varias páginas de una fuente es la genérica del sitio y se descarta (caso Hugging Face); en Reddit se usa el link al artículo si lo hay. Problema visto: Reddit responde 429 si se consulta varias veces en pocos minutos (con corridas cada 6 h no debería pasar; la fuente caída no frena al resto).
- 2026-10-20 · Paso 3 · `radar/agrupar.py` (URL canónica, id = SHA-1[:12], `Grupo` con `confirmacion`, `fuentes` y `hashes`) + `radar recolectar` muestra "N candidatos → M noticias" y `--grupos` lista las que juntan varios links. Corrida real: 128 candidatos → 125 noticias (DeepInfer: HN + 2 posts de Reddit; hackeo a John Deere: The Verge + HN); en otra corrida, "OpenAI acquires Orchestra Bio" (blog de OpenAI + TechCrunch). 31 tests en verde. Decisiones: títulos se comparan palabra por palabra (letra por letra, "Introducing Codex" ≈ "Introducing Sora"); si los números difieren no se agrupan ("4.5" ≠ "4.6"); un título corto (≥4 palabras) contenido entero en otro largo sí se agrupa; por título solo entre fuentes distintas; el principal es el candidato más antiguo para que el id no cambie cuando otras fuentes repiten la noticia. La mayoría de duplicados en distinto idioma o con otra redacción no se detectan aquí: los une la IA dentro del lote (Paso 7).
- 2026-10-20 · Paso 4 · `radar/filtrar.py` + comando `radar filtrar [--marcar]`: caché `data/cache/procesados.json` (`{hash: fecha}`, se guardan los hashes de **todos** los links del grupo, poda a `cache.dias`), puntaje sin IA (peso + fuentes extra + puntos HN + palabra clave − 0,5 por día) y topes por corrida (10), por día (25, contando `data/AAAA-MM-DD.json`) y por fuente (3). Corrida real: 1.ª elige 10 de 124; 2.ª dice "Ya procesadas antes: 10" y elige otras 10 sin repetir. 40 tests en verde. Decisiones: lo que el pre-filtro no elige **no** se marca: se vuelve a considerar en la corrida siguiente hasta que se pone viejo (por eso la 2.ª corrida no dice "0 nuevas" como decía el plan; el mensaje sale cuando ya no queda nada sin procesar y lo prueba un test); un `procesados.json` dañado se avisa y se parte de cero. Se sacó "agent/agents" de `recolector.palabras_ia` porque colaba noticias de HN sin relación con IA ("ICE agent"). La prioridad de `pendientes.json` queda para el Paso 6 (aún no existe).
