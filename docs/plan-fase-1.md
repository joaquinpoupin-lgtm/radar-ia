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

- [ ] **Paso 2 — Recolector**
  Lee RSS/Atom y la API de Hacker News (filtrando IA) y convierte todo a un formato común (título, URL, fuente, fecha, extracto corto). Si el RSS no trae extracto, toma la descripción corta de la página (`og:description`). Una fuente caída no detiene el resto.
  **Verificación:** `radar recolectar` muestra cuántos candidatos trajo por fuente; un test con feeds de ejemplo pasa sin internet.

- [ ] **Paso 3 — Deduplicar y agrupar**
  URL limpia (sin `utm_`, etc.) → hash estable como `id`. Títulos parecidos de distintas fuentes se agrupan en una sola noticia con varios links (`confirmacion` = cuántas fuentes).
  **Verificación:** tests con duplicados de ejemplo; en una corrida real se ve "N candidatos → M noticias".

- [ ] **Paso 4 — Caché y pre-filtro sin IA**
  `data/cache/procesados.json` guarda los `id` ya resumidos. Pre-filtro por peso de fuente, puntaje (HN/Reddit), palabras clave y antigüedad; deja como máximo ~10 nuevas por corrida y respeta el tope de 25 al día.
  **Verificación:** correr dos veces seguidas → la segunda vez dice "0 noticias nuevas".

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
