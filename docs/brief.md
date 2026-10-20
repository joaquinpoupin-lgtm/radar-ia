# Radar IA — Brief del proyecto (para kickoff en Claude Code)

> Central personal de noticias y avisos sobre inteligencia artificial: lo último en modelos, proyectos, tendencias, creadores y formas de sacarle provecho. Todo resumido con IA, en español simple, con link a la fuente original. **Costo cero.**

---

## 1. Visión

Un "radar" que lee por mí cientos de fuentes sobre IA, separa lo importante del ruido y me lo entrega resumido en español claro, sin jerga, cada día. Si algo es realmente relevante, me avisa al celular.

- **Para quién:** uso personal (yo, desde Santiago de Chile, hispanohablante).
- **Objetivo:** estar informado y al día de lo último en IA sin tener que leer todo.
- **Monetización:** NO por ahora. No descartada a futuro (ver sección 11), pero no debe influir en las decisiones actuales.

## 2. Principios no negociables

1. **Todo gratis.** Ningún servicio de pago, ninguna tarjeta de crédito. Si una pieza no tiene plan gratuito suficiente, se reemplaza o se elimina.
2. **Resumido con IA y fácil de entender.** Español neutro y simple. Nada de lenguaje demasiado técnico; si aparece un término técnico, se explica en una línea.
3. **Siempre con link a la fuente original** para leer más.
4. **Calidad sobre cantidad.** Mejor 15 noticias buenas que 200 sin filtrar. Deduplicar: si 5 fuentes hablan de lo mismo, es UNA noticia con varios links.
5. **Robusto ante límites.** Los planes gratuitos tienen cuotas; el sistema debe manejar errores 429, reintentar con backoff, tener proveedor de respaldo y nunca resumir dos veces lo mismo.
6. **Simple de mantener.** Preferir lo estático y sin servidores propios.

## 3. Qué cubre (contenido)

| Sección | Qué incluye |
|---|---|
| **Modelos y lanzamientos** | Modelos nuevos o actualizados (texto, imagen, video, voz, código): qué cambió, para qué sirve, si es gratis o de pago, comparación con el anterior. |
| **Herramientas y proyectos** | Apps, proyectos open source, agentes, automatizaciones que están apareciendo (GitHub, Hugging Face, Product Hunt). |
| **De qué habla la gente** | Temas que están subiendo en Reddit, Hacker News, YouTube. Termómetro de "qué está caliente esta semana". |
| **Radar de creadores** | Videos nuevos de canales de IA, resumidos en ~5 líneas. Qué tipo de proyectos están mostrando. |
| **Cómo la gente gana dinero con IA** | Casos reales y modelos de negocio: qué es, inversión/dificultad aproximada, si está saturado. |
| **Saca el máximo provecho** | Trucos, prompts y flujos de trabajo concretos y prácticos. |
| **Alertas** | Avisos al celular por palabras clave o por importancia alta. |

## 4. Funcionalidades por fase

### Fase 1 — MVP (prioridad)
- Recolector automático que corre varias veces al día.
- Lectura de fuentes vía RSS / APIs públicas gratuitas (ver sección 6).
- Deduplicación y agrupación de noticias sobre el mismo tema.
- Clasificación por sección + nivel de importancia (🔥 alta / normal).
- Resumen con IA en español simple (formato en sección 7).
- Web estática con:
  - **Brief del día** (lo más importante arriba, lectura de ~3 minutos).
  - Listado por secciones con filtros.
  - Archivo por fecha.
- Cada ítem con link(s) a la fuente original.

### Fase 2
- **Bot de Telegram:** brief diario por la mañana + alertas inmediatas para noticias 🔥 o palabras clave configurables (ej: "video", "gratis", "Claude", "agentes").
- **Radar de creadores de YouTube** completo (resumen de cada video nuevo, idealmente desde la transcripción si es gratis y viable; si no, desde título + descripción).
- **Resumen semanal** ("lo que pasó esta semana en IA").
- Mini **glosario** automático de términos técnicos que van apareciendo.

### Fase 3
- **Detector de hype:** nota de "¿es real o es humo?" según cuántas fuentes serias lo confirman.
- **Tendencias:** qué temas suben/bajan semana a semana.
- **Oportunidades:** "esto está creciendo y casi nadie lo hace en español".
- **Tabla viva de modelos** (comparativa por tipo, precio, gratis o no).
- **Personalización:** marco las herramientas que uso y me prioriza lo que las afecta.
- **Línea de tiempo** por empresa/tecnología.
- (Opcional) Brief en audio tipo podcast, solo si existe una vía gratuita.

## 5. Arquitectura propuesta (100 % gratis)

```
[GitHub Actions — cron cada ~4-6 h]
        │
        ▼
  1. Recolectar (RSS / APIs públicas)
  2. Normalizar + deduplicar (hash de URL + similitud de títulos)
  3. Filtrar ítems ya procesados (caché en el repo)
  4. Resumir y clasificar con IA (Gemini free → fallback Groq free)
  5. Guardar como JSON en el repo (data/AAAA-MM-DD.json)
  6. Generar sitio estático
        │
        ├──► Web estática (GitHub Pages o Vercel Hobby)
        └──► Bot de Telegram (Fase 2)
```

### Piezas y por qué
| Pieza | Elección | Notas de costo |
|---|---|---|
| Automatización | **GitHub Actions** (cron) | Gratis e ilimitado en repos públicos; en repos privados, 2.000 min/mes gratis (de sobra). |
| IA principal | **Gemini API** (modelos Flash / Flash-Lite, plan gratis) | Clave gratis en Google AI Studio. Tiene límites por minuto y por día; revisar los límites vigentes en AI Studio. En plan gratis los datos pueden usarse para entrenamiento y no se permite uso comercial (OK para noticias públicas y uso personal). |
| IA respaldo | **Groq** (plan gratis) | Sin tarjeta. API compatible con OpenAI. Límites por minuto/día. |
| Datos | **Archivos JSON en el mismo repo** | Cero infraestructura. Migrar a Supabase (plan gratis, ya conectado) solo si hace falta. |
| Web | **GitHub Pages** o **Vercel Hobby** | Ambos gratis. Ya tengo Vercel conectado. |
| Alertas | **Bot de Telegram** (BotFather) | Gratis. |

### Stack sugerido (a confirmar en el kickoff)
- **Recolector y resúmenes:** Python (feedparser, httpx, etc.) o Node/TypeScript. Elegir lo más simple de mantener.
- **Web:** sitio estático (Astro, o HTML + JS simple). Mobile-first: lo voy a leer mucho desde el celular.
- **Idioma de la interfaz:** español.

### Estrategias para no pasarse de las cuotas gratis
- No resumir nada dos veces (caché por hash).
- Agrupar varias noticias por llamada a la IA (batch en un solo prompt).
- Pre-filtrar sin IA (palabras clave, puntaje de Reddit/HN, fuente) antes de gastar llamadas.
- Usar el modelo más liviano (Flash-Lite) para clasificar y el más capaz gratis solo para el brief del día.
- Backoff exponencial ante 429; fallback a Groq; si ambos fallan, dejar el ítem pendiente para la próxima corrida (nunca romper el pipeline).

## 6. Fuentes iniciales (verificar URLs de RSS durante el desarrollo)

**Oficiales (empresas de IA):** blogs/newsrooms de Anthropic, OpenAI, Google DeepMind / Google AI, Meta AI, Mistral, Hugging Face, Microsoft AI, NVIDIA, xAI, DeepSeek, Qwen (Alibaba).

**Comunidad y tendencias:**
- Hacker News (API pública gratuita; filtrar por IA)
- Reddit vía RSS: r/LocalLLaMA, r/artificial, r/singularity, r/OpenAI, r/ClaudeAI, r/ChatGPT, r/StableDiffusion, r/aivideo
- GitHub Trending (repos de IA)
- Hugging Face (modelos y papers en tendencia)
- Product Hunt (categoría IA)
- arXiv (solo lo muy destacado; no inundar con papers)

**Creadores de YouTube** (RSS gratis por canal: `https://www.youtube.com/feeds/videos.xml?channel_id=...`). Lista inicial a confirmar/editar:
- En español: DotCSV, Xavier Mitjana
- En inglés: Matt Wolfe, AI Explained, Two Minute Papers, Fireship, Matthew Berman, Wes Roth
- La lista debe ser un archivo de configuración fácil de editar (agregar/quitar canales sin tocar código).

**Newsletters/medios** (si tienen RSS): sitios de noticias tech con sección IA.

Todas las fuentes en un archivo de config (`sources.yaml` o similar) con: nombre, tipo, URL, sección por defecto, idioma, peso/confiabilidad.

## 7. Formato de cada noticia (salida de la IA)

Esquema sugerido:

```json
{
  "id": "hash-estable",
  "fecha": "2026-10-20",
  "titulo": "Título claro en español",
  "que_paso": "2-3 líneas simples explicando la noticia.",
  "por_que_importa": "1 línea: qué significa para alguien que usa IA.",
  "seccion": "modelos | herramientas | tendencias | creadores | dinero | tips",
  "importancia": "alta | normal",
  "terminos": [{"termino": "RAG", "explicacion": "Técnica para que la IA consulte tus documentos antes de responder."}],
  "etiquetas": ["video", "gratis", "open source"],
  "fuentes": [{"nombre": "Blog de X", "url": "https://..."}],
  "confirmacion": 3
}
```

### Guía de estilo para el prompt de resumen
- Español neutro, frases cortas, tono cercano pero informativo.
- Explicar como a alguien curioso e inteligente que no es ingeniero.
- Sin exageraciones ni clickbait. Si es rumor o no está confirmado, decirlo.
- Nunca inventar datos: si la fuente no lo dice, no se incluye.
- No copiar texto de la fuente: siempre parafrasear (y el link original va siempre).
- Si la fuente está en inglés, el resumen igual va en español.

### Brief del día
- Máximo ~10 ítems, ordenados por importancia.
- Arriba: "Lo más importante hoy" en 3 bullets.
- Lectura total de ~3 minutos.

## 8. Requisitos previos (lo que tengo que tener listo)

- [ ] **Cuenta de GitHub** (gratis) y un repo nuevo para el proyecto (público = Actions ilimitado; privado también sirve).
- [ ] **Clave de Gemini API** gratis: Google AI Studio → "Get API key" (solo cuenta de Google, sin tarjeta). **No activar facturación.**
- [ ] **Clave de Groq** gratis (respaldo): console.groq.com, sin tarjeta.
- [ ] Guardar las claves como **GitHub Secrets** (`GEMINI_API_KEY`, `GROQ_API_KEY`), nunca en el código.
- [ ] (Fase 2) **Bot de Telegram:** crear con @BotFather, guardar `TELEGRAM_BOT_TOKEN` y mi `TELEGRAM_CHAT_ID` como secrets.
- [ ] (Opcional) Vercel para el hosting de la web (ya conectado), o usar GitHub Pages.
- [ ] Claude Code instalado para desarrollar.

## 9. Criterios de éxito del MVP

- Corre solo, varias veces al día, sin intervención.
- Cada mañana hay un brief del día legible en el celular en ~3 minutos.
- Los resúmenes se entienden sin saber de programación.
- Toda noticia tiene su link original funcionando.
- Costo mensual: **$0**. Nunca se pide tarjeta.
- Si la IA falla o se acaba la cuota, el sistema no se rompe: reintenta en la próxima corrida.

## 10. Fuera de alcance (por ahora)

- Usuarios, login, cuentas, pagos.
- Publicidad, afiliados, suscripciones.
- Generación de imágenes o video.
- Cualquier servicio de pago o con prueba gratuita que luego cobre.

## 11. Ideas a futuro (si algún día se monetiza)

- Newsletter gratis + premium con alertas personalizadas.
- Patrocinios de herramientas de IA, links de afiliado.
- Versión pública enfocada en Latinoamérica y en español (casi todo el contenido de IA está en inglés: diferenciador real).
- Canal de YouTube/TikTok alimentado con el mismo contenido.
- Comunidad: votar noticias, subir proyectos propios.
- **Ojo:** el plan gratis de Gemini no permite uso comercial; al monetizar, revisar proveedores/planes.

## 12. Preguntas abiertas para el kickoff

1. ¿Python o TypeScript para el recolector?
2. ¿GitHub Pages o Vercel para la web?
3. ¿Repo público o privado?
4. ¿Cada cuántas horas corre el recolector? (sugerido: cada 4-6 h + brief a las 7:00 hora de Chile)
5. ¿Resumir videos de YouTube desde la transcripción (si hay vía gratis) o solo título + descripción?
6. ¿Cuántos ítems máximo por día en total?
