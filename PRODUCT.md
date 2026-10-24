# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Una persona hispanohablante en Santiago de Chile, curiosa por la inteligencia artificial pero no ingeniera. Lee el Radar en el celular (vistazo rápido) y en el computador (lectura con calma). Quizás lo comparta con amigos o en redes, así que tiene que verse serio y confiable ante otros, no solo funcionar para él.

## Product Purpose

Radar IA lee cientos de fuentes públicas sobre IA, separa lo importante del ruido y entrega cada día un brief resumido en español simple, con link a la fuente original. Éxito: en ~3 minutos sé lo que pasó hoy en IA y puedo ir a la fuente si algo me interesa.

## Positioning

Un brief curado y en español neutro, sin jerga (cada término técnico explicado en una línea), donde varias fuentes que cuentan lo mismo son una sola noticia con varios links. Casi todo el contenido de IA está en inglés: el español claro es el diferenciador.

## Operating Context

- Se genera solo, 4 veces al día (GitHub Actions); la primera corrida del día (madrugada, hora de Chile) arma el brief.
- Lo primero que el lector quiere ver al abrir la portada: "Lo más importante hoy" (3 puntos clave), y debajo el detalle de las ≤10 noticias.
- Páginas: Brief del día (portada), Secciones con filtros (sección, 🔥, etiquetas), Archivo por fecha y una página por día.

## Capabilities and Constraints

- Sitio estático: HTML + un solo CSS + JS mínimo, generado con Jinja2 (`templates/`, `radar/sitio.py`). Sin Node ni paso de compilación; GitHub Pages en repo público.
- Costo cero: nada que cobre o pida tarjeta. Pocas dependencias.
- Cada noticia trae: sección (modelos, herramientas, tendencias, creadores, dinero, tips), importancia (🔥 alta / normal), título, "qué pasó", "por qué importa", términos explicados, etiquetas, fuentes con link y cuántas fuentes la cuentan.
- Mobile-first; páginas con `noindex` (uso personal por ahora).
- Interfaz y textos en español.

## Brand Commitments

- Nombre: **Radar IA**.
- Voz: español neutro, frases cortas, tono directo, sin clickbait ni exageraciones. Los rumores se marcan como rumores.
- El usuario rechazó el aspecto actual por verse "hecho con IA" y poco atractivo: no debe parecer plantilla genérica.

## Evidence on Hand

Datos reales en `data/AAAA-MM-DD.json` (noticias resumidas y brief de cada día desde el 2026-10-21). No hay logo, fotos, testimonios ni métricas de audiencia: no inventarlos.

## Product Principles

1. Lo importante primero: los 3 puntos clave antes que cualquier detalle.
2. Siempre el link original: la fuente es parte de la noticia, no un adorno.
3. Claridad antes que espectáculo: se lee en ~3 minutos en el celular.
4. Honestidad: el aviso de que los resúmenes son hechos con IA se mantiene visible.

## Accessibility & Inclusion

Lectura cómoda en celular (texto grande, buen contraste sobre el tema oscuro, que es fijo por decisión de diseño), sin depender del JS para ver las noticias; se respeta "reducir movimiento" del sistema.
