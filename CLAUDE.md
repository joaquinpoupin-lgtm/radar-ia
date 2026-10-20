# Radar IA

Central personal de noticias sobre inteligencia artificial: lee fuentes públicas, filtra el ruido, resume con IA en español simple y publica una web estática con el brief del día. Uso personal, costo cero.

- **Fuente de verdad:** [docs/brief.md](docs/brief.md). Si algo aquí contradice el brief, gana el brief (y se avisa al usuario).
- **Plan vigente:** [docs/plan-fase-1.md](docs/plan-fase-1.md). Marcar cada paso como hecho solo cuando su verificación pasó.
- **Diseño técnico:** [docs/diseno.md](docs/diseno.md) (estructura, formatos de datos, cómo funciona cada pieza).

## Al empezar cada sesión

El usuario hace `/clear` entre pasos, así que el estado vive en los archivos, no en la conversación:

1. Leer el plan y la **bitácora** al final de [docs/plan-fase-1.md](docs/plan-fase-1.md); el paso a trabajar es el primero sin marcar `[x]`.
2. Leer la parte de [docs/diseno.md](docs/diseno.md) que corresponde a ese paso.
3. Hacer **solo ese paso**, correr su verificación y los tests, y mostrarle al usuario la evidencia.
4. Al terminar: marcar `[x]`, agregar una línea a la bitácora (fecha, qué se hizo, decisiones o problemas), actualizar `diseno.md` si el diseño cambió, hacer commit y preguntar si se sigue con el próximo paso.

## Comandos

```bash
source .venv/bin/activate                 # activar el entorno (o usar .venv/bin/python)
pip install -r requirements-dev.txt       # instalar dependencias
python -m radar --help                    # ver comandos (los no implementados dicen en qué paso se hacen)
python -m pytest -q                       # tests
```

## Principios no negociables

1. **Todo gratis, sin tarjeta.** Ningún servicio, plan, prueba gratuita ni dependencia que cobre o pida tarjeta. Antes de sumar cualquier servicio externo, confirmar que su plan gratis alcanza; si no, proponer alternativa gratuita o dejarlo fuera. Nunca activar facturación en Google AI Studio.
2. **Español simple.** Resúmenes en español neutro, frases cortas, para alguien curioso que no es ingeniero. Todo término técnico va explicado en una línea (campo `terminos`).
3. **Siempre el link original.** Ninguna noticia se publica sin al menos una fuente con URL funcionando.
4. **Nunca inventar.** Si la fuente no lo dice, no se incluye. Rumores se marcan como rumores. Sin clickbait ni exageraciones.
5. **No copiar texto de la fuente.** Siempre parafrasear. No guardar artículos completos en el repo; solo título, extracto corto del RSS y URL.
6. **Calidad sobre cantidad.** Máximo ~10 ítems en el brief y ~25 al día en total. Si varias fuentes cuentan lo mismo, es UNA noticia con varios links.
7. **Filtro anti-humo en "dinero".** Solo casos con datos concretos; promesas de ingresos ("gana $X al mes") se marcan como "sin confirmar" o se descartan.
8. **Robusto ante límites.** Backoff exponencial ante 429, fallback Gemini → Groq, y si ambos fallan el ítem queda pendiente para la próxima corrida. El pipeline nunca se cae por la IA ni por una fuente caída: se registra el error y se sigue.
9. **Nunca resumir dos veces lo mismo.** Caché por hash estable antes de cualquier llamada a la IA.
10. **Secretos fuera del código.** Claves solo en GitHub Secrets (`GEMINI_API_KEY`, `GROQ_API_KEY`; Fase 2: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) y, en local, en `.env` (ignorado por git). Nunca en código, commits, logs ni mensajes. `.env.example` lleva solo los nombres.
11. **Simple de mantener.** Estático, sin servidores propios, pocas dependencias. Agregar/quitar fuentes o canales = editar `sources.yaml`, sin tocar código.
12. **Por fases.** No empezar la Fase 2 hasta que el MVP funcione de punta a punta y cumpla los criterios de éxito (brief, sección 9).

## Decisiones técnicas (kickoff 2026-10-20)

| Tema | Decisión | Por qué |
|---|---|---|
| Lenguaje | Python 3.12+ | `feedparser`, scripts legibles, un solo lenguaje para todo |
| Web | HTML + CSS + JS mínimo generado con Jinja2 | Sin Node ni build; mobile-first |
| Repo / hosting | Repo **público** + **GitHub Pages** | Pages gratis solo en repos públicos; Actions ilimitado |
| Automatización | GitHub Actions, cron 00:30 / 06:30 / 12:30 / 18:30 `America/Santiago` | La de 06:30 arma el brief antes de las 7:00 aunque el cron se atrase |
| IA | Gemini (Flash-Lite) principal, Groq respaldo; llamadas HTTP directas con `httpx` | Ambos gratis sin tarjeta; nombres de modelo en config, no en código |
| Datos | JSON en el repo (`data/`) | Cero infraestructura |
| YouTube (MVP) | Resumen desde título + descripción del RSS | Transcripciones se evalúan en Fase 2 |
| Límites | ≤10 ítems en brief, ≤25/día, lotes de ~10 ítems por llamada | Cuotas gratis de Gemini cambian sin aviso: gastar lo mínimo |

## Convenciones

- Fechas y "día" del brief siempre en hora de Chile (`America/Santiago`).
- Límites, modelos, horarios y umbrales en `config.yaml`; fuentes en `sources.yaml`; prompts en `prompts/`.
- La salida de la IA se valida contra el esquema de la sección 7 del brief; si no es válida, se reintenta o queda pendiente (nunca se publica a medias).
- Los tests no usan red ni claves reales (fixtures y proveedores falsos).
- Interfaz, mensajes del programa y comentarios del código en español.

## Cómo trabajar con el usuario

- Explicar cada decisión técnica en lenguaje simple, sin jerga (o explicándola).
- Avanzar en pasos pequeños y verificables; mostrar la evidencia de que funciona antes de pasar al siguiente.
- Cuando haga falta una cuenta o clave, explicar paso a paso cómo obtenerla gratis y dónde guardarla; nunca pedir que la pegue en el chat ni en el código.
