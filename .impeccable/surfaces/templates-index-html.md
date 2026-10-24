---
version: 1
slug: "templates-index-html"
primary_target: "templates/index.html"
related_targets: ["templates/secciones.html","templates/archivo.html","templates/dia.html"]
---

# Sitio Radar IA (portada, secciones, archivo, día)

Modo: Read. Lector hispanohablante no técnico; vistazo en el celular y lectura con calma en el computador. Lo primero que quiere ver: los 3 puntos clave del día. Contenido real en data/*.json (≤10 noticias en el brief). Restricciones: HTML + un CSS + JS mínimo, sin build, sin depender del JS para leer.

## Direction contract

THESIS: El Radar lee la luz de cientos de fuentes y entrega el espectro del día: cada noticia es una línea de emisión. Rechaza el portal de tarjetas con etiquetas y el newsletter crema con serif.

OWN-WORLD: Continuo de carbón con bandas y grano como fondo del marco; columna de lectura sobre una placa de ceniza plana, texto hueso. Color SOLO como líneas finas en siete longitudes de onda: 405 violeta (modelos), 436 índigo (herramientas), 486 cian (tendencias), 546 verde (creadores), 615 naranja (dinero), 656 rojo (tips); 589 sodio, en doblete, reservado para los 3 puntos clave. Un solo grotesco (Archivo, ejes de ancho y peso): condensado en mayúsculas para títulos, rótulos a un solo tamaño ordenados por espaciado y tinta. Estado por forma de línea: doble = importante, media altura = de ayer, muñón = filtrado fuera.

STORY: El lector ve de un vistazo la composición del día (qué secciones se movieron), lee los 3 puntos clave y baja por las noticias con su fuente a mano.

FIRST VIEWPORT: Barra con RADAR IA y la navegación; banda del espectro del día a todo el ancho con sus secciones al pie; la fecha en condensado grande; los 3 puntos clave cruzando el riel con dobletes de sodio. En el computador la fecha vive en la columna de margen, a la izquierda del riel, y los puntos clave a la derecha.

FORM: Espectro en riel (emission line rail), challenger elegido por el usuario; seed 9fce6c9f. Interacción firma: las líneas del espectro son links a cada noticia (lectura al pasar o enfocar) y en Secciones reaccionan a los filtros: las que quedan suben a altura completa con un resorte, el resto baja a muñón.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
