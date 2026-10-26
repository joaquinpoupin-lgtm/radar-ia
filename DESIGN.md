---
name: Radar IA
description: El brief diario de IA en español, leído como un espectro de emisión sobre un riel.
colors:
  l589: "#ffd84a"
  l405: "#a07dff"
  l436: "#7084ff"
  l486: "#3ec3ff"
  l546: "#8fe36a"
  l615: "#ff9a45"
  l656: "#ff5d55"
  carbon-hondo: "#0c0d0e"
  carbon: "#121314"
  ceniza: "#1a1b1d"
  ceniza-alta: "#222327"
  borde: "#2c2d31"
  borde-fuerte: "#46474d"
  hueso: "#e6e1d5"
  hueso-2: "#b4afa2"
  hueso-3: "#8f8a7f"
typography:
  display:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(2.75rem, 12.6vw, 3.7rem)"
    fontWeight: 560
    lineHeight: 0.92
    letterSpacing: "-0.005em"
    fontVariation: "\"wdth\" 62"
  headline:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 580
    lineHeight: 1.05
    letterSpacing: "0.01em"
    fontVariation: "\"wdth\" 68"
  title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 620
    lineHeight: 1.22
    fontVariation: "\"wdth\" 90"
  lead:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 470
    lineHeight: 1.45
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "\"tnum\""
  label:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "0.16em"
  marca:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 640
    letterSpacing: "0.14em"
    fontVariation: "\"wdth\" 72"
rounded:
  none: "0px"
  nodo: "50%"
spacing:
  margen: "14px"
  hueco: "18px"
  der: "16px"
  tick: "9px"
  col: "42rem"
  col-computador: "58rem"
  ancho-foto: "19rem"
  bloque: "4rem"
components:
  barra:
    backgroundColor: "{colors.carbon-hondo}"
    height: "3.25rem"
  menu-enlace:
    textColor: "{colors.hueso-2}"
    typography: "{typography.label}"
    padding: "0 .4rem 0 .8rem"
    height: "3.25rem"
  menu-enlace-actual:
    textColor: "{colors.hueso}"
  lamina:
    backgroundColor: "{colors.ceniza}"
    textColor: "{colors.hueso}"
    width: "{spacing.col}"
  espectro-banda:
    backgroundColor: "{colors.carbon-hondo}"
    height: "7.5rem"
  boton:
    textColor: "{colors.hueso}"
    rounded: "{rounded.none}"
    padding: ".85rem 1.1rem .85rem 1.4rem"
    height: "3.25rem"
  boton-hover:
    backgroundColor: "{colors.ceniza-alta}"
  filtro:
    textColor: "{colors.hueso-2}"
    rounded: "{rounded.none}"
    padding: ".5rem .8rem .5rem 1.2rem"
    height: "2.5rem"
  filtro-activo:
    backgroundColor: "{colors.ceniza-alta}"
    textColor: "{colors.hueso}"
  filtro-chico:
    textColor: "{colors.hueso-2}"
    padding: ".35rem .4rem"
    height: "2.25rem"
  aviso:
    textColor: "{colors.hueso-2}"
    rounded: "{rounded.none}"
    padding: ".9rem 1.1rem"
  foto:
    backgroundColor: "{colors.carbon-hondo}"
    rounded: "{rounded.none}"
    width: "{spacing.ancho-foto}"
---

# Design System: Radar IA

## Overview

**Creative North Star: "Espectro en riel"**

El Radar lee la luz de cientos de fuentes y entrega el espectro del día: cada noticia es una línea de emisión. El marco es un continuo de carbón con bandas verticales y grano, como la placa de un espectrógrafo; encima corre una sola placa de lectura de ceniza lisa con texto hueso. El color no rellena nada: solo aparece como líneas finas, una longitud de onda por sección.

Todo cuelga de un riel vertical, el borde izquierdo de la placa. Los marcadores de cada noticia y de los puntos clave cruzan ese riel desde el margen; en el computador los datos de la noticia (sección, importancia) viven a la izquierda del riel y la lectura a la derecha. El estado se dice con la forma de la línea, no con chips ni insignias: doble es importante, media altura es de ayer, muñón es filtrado fuera.

Es denso pero sereno, oscuro por decisión (no hay tema claro) y pensado primero para el celular. Rechaza el portal de tarjetas con etiquetas y el newsletter crema con serif.

**Key Characteristics:**
- Fondo de carbón con bandas y grano; placa de lectura de ceniza plana.
- Color solo como líneas de 1 px (doblete de 4 px para lo importante).
- Un solo grotesco variable (Archivo) usado por sus ejes de ancho y peso.
- Riel vertical con nodos circulares al inicio y al final.
- Estado por forma de línea; movimiento con resorte en las líneas.

## Colors

Neutros de carbón, ceniza y hueso casi sin croma, cortados por siete líneas espectrales saturadas.

### Primary
- **Sodio 589 nm** (l589): el doblete de "Lo más importante". También tiñe la selección de texto (a 32 % de opacidad). Ningún otro elemento lo usa.

### Secondary
Una longitud de onda por sección, aplicada vía `data-seccion` a la variable `--c`:
- **Violeta 405** (l405): modelos.
- **Índigo 436** (l436): herramientas.
- **Cian 486** (l486): tendencias.
- **Verde 546** (l546): creadores.
- **Naranja 615** (l615): dinero.
- **Rojo 656** (l656): tips.

### Neutral
- **Carbón hondo** (carbon-hondo): barra superior, fondo de la banda del espectro y de las miniaturas.
- **Carbón** (carbon): fondo de la página, con bandas y grano encima.
- **Ceniza** (ceniza): la placa de lectura.
- **Ceniza alta** (ceniza-alta): fondo de botones y filtros al pasar o activos.
- **Borde** (borde): filetes entre noticias, borde de la banda y de filtros en reposo.
- **Borde fuerte** (borde-fuerte): el riel, borde de botones, subrayados en reposo, líneas punteadas.
- **Hueso** (hueso): texto principal y estado actual o activo.
- **Hueso 2** (hueso-2): texto secundario, rótulos, "Por qué importa".
- **Hueso 3** (hueso-3): texto terciario (etiquetas, leyenda, íconos en reposo, nodos del riel). Contraste 5:1 sobre ceniza; no bajar de este tono para texto.

### Named Rules
**La Regla de la Línea Fina.** El color de sección vive solo en líneas de 1 px (doblete de 4 px, halo tenue de 11 a 17 px). Nunca rellena una superficie ni pinta texto; como mucho colorea un subrayado al pasar el mouse.

**La Regla del Sodio.** El amarillo 589 es exclusivo de los puntos clave y siempre va en doblete. Lo "importante" de una noticia se marca con doblete en su propio color de sección (o en hueso), no en sodio.

## Typography

**Display Font:** Archivo variable, autoalojada (`archivo.woff2`, OFL; ancho 62–125 %, peso 100–900), con Helvetica Neue y Arial de respaldo.
**Body Font:** la misma Archivo.

**Character:** un solo grotesco que cambia de voz por sus ejes: condensado y en mayúsculas para títulos, ancho normal para leer. Números tabulares en todo el sitio.

### Hierarchy
- **Display** (560, `clamp(2.75rem, 12.6vw, 3.7rem)`; 3.5rem en computador; ancho 62 %, mayúsculas): título de cada página, la fecha en la portada.
- **Headline** (580, 1.6rem, ancho 68 %, mayúsculas): "Lo más importante" y el título de la lista.
- **Title** (620, 1.4rem; 1.5rem desde 40rem; ancho 90 %): título de cada noticia, balanceado. En la noticia destacada: 1.75rem (2.1rem desde 40rem, 2.3rem en computador), ancho 84 %, máximo 28ch.
- **Lead** (470, 1.2rem; 1.32rem desde 40rem): los 3 puntos clave, en una medida de hasta 48rem.
- **Body** (400, 1.0625rem; 1.09rem desde 40rem; interlineado 1.6): "qué pasó" y "por qué importa", máximo 68ch.
- **Label** (500, .72rem, espaciado .12–.16em, mayúsculas): rótulos, menú, datos de la noticia, "Leer en".
- **Marca** (640, .95rem, ancho 72 %, espaciado .14em; .22em desde 40rem, mayúsculas): solo "Radar IA" en la barra.

### Named Rules
**La Regla del Rótulo Único.** Los rótulos tienen un solo tamaño (.72rem); se ordenan por espaciado y tinta (hueso, hueso-2, hueso-3), no por tamaño.

**La Regla del Ancho.** La jerarquía de títulos se hace con el eje de ancho (62 → 68 → 90 %) además del tamaño; no se agrega una segunda familia.

## Layout

La placa es una grilla de cuatro columnas: margen, hueco, columna de lectura (hasta 42rem) y derecha. Las listas y noticias usan `subgrid` para heredarla, así los marcadores caen siempre sobre el riel. El ancho total es `margen + hueco + col + der`, centrado; la barra y el pie usan el mismo cálculo.

- **Celular (base):** margen 14px, hueco 18px, derecha 16px, marcador 9px. Banda del espectro de 7.5rem.
- **Tablet (≥40rem):** margen 1.75rem, hueco 2.25rem, derecha 2rem, marcador 12px. Banda de 10rem; botones de "seguir" en dos columnas.
- **Computador (≥64rem):** margen 15.5rem, hueco 3rem, derecha 3rem, marcador 1.6rem; la columna crece hasta 58rem para que quepa la foto (19rem) a la derecha del texto. El título de la página ocupa la columna de margen, a la izquierda del riel; el espectro (17rem) va al lado. Los datos de cada noticia cuelgan a la izquierda del riel, alineados a la derecha.

Ritmo vertical amplio: 4rem antes de los puntos clave (1.3rem entre puntos), 4.5rem antes de la lista, 2.5–2.75rem arriba y abajo de cada noticia (3.25–3.5rem en computador). La barra es pegajosa y respeta las áreas seguras del celular.

### Named Rules
**La Regla del Riel.** Todo se alinea al borde izquierdo de la placa. Un marcador nuevo cruza el riel desde el margen con el ancho `marcador + hueco × .7`; nada se alinea a otra cosa.

## Elevation & Depth

Plano. No hay `box-shadow`. La profundidad sale de capas tonales: carbón hondo (barra, bandas) bajo carbón (página) bajo ceniza (placa) bajo ceniza alta (estado activo). La textura (bandas verticales y grano SVG) es exclusiva del fondo y de la banda del espectro; la placa de lectura siempre es lisa.

### Shadow Vocabulary
- **Brillo de emisión** (`filter: drop-shadow(0 0 3px <color de la línea>)`): solo en los dobletes (puntos clave y noticias importantes). Es luz de la línea, no sombra de un objeto.

### Named Rules
**La Regla de la Placa Lisa.** El grano y las bandas no entran a la placa de lectura; si un elemento necesita textura, va en carbón hondo (la banda del espectro, la miniatura del Archivo y el marco de la foto).

## Shapes

Esquinas rectas en todo (`border-radius: 0` explícito en los botones). Bordes de 1 px: continuos para lo navegable, punteados (`1px dashed`) para avisos, la lista de términos y el foco. El único círculo es el nodo del riel (7 px, borde hueso-3): marca el arranque bajo la barra y el final en el pie. Las líneas espectrales desvanecen sus extremos con una máscara (8 % arriba y abajo).

## Components

### Buttons
Rectos y sobrios; un muñón de línea a la izquierda anuncia que se pueden pulsar.
- **Shape:** esquinas rectas, borde 1px borde-fuerte, alto mínimo 3.25rem.
- **Primary (`.boton`):** texto hueso (.92rem, 560), flecha SVG a la derecha; muñón de 1px hueso-2 a 36 % de altura.
- **Hover / Focus:** borde hueso-3, fondo ceniza alta, el muñón sube a altura completa con resorte y la flecha avanza 3px. Foco: contorno punteado hueso de 1px.
- **Variantes:** `--atras` (flecha girada, retrocede al pasar), `--centro` (texto centrado).

### Chips (filtros de Secciones)
- **Style:** fondo transparente, borde 1px borde, texto hueso-2 (.84rem), contador en `small` hueso-3. Muñón del color de la sección a la izquierda.
- **State:** `aria-pressed="true"` = borde hueso-3, fondo ceniza alta, texto hueso, muñón a altura completa. "Solo importantes" lleva doblete hueso. Las etiquetas (`.chico`) no tienen borde: se marcan con subrayado (hueso cuando están activas).

### Cards / Containers
No hay tarjetas. Las noticias son filas sobre la placa separadas por un filete de 1px (borde) que empieza en el riel. El aviso es un recuadro punteado (borde-fuerte) con texto hueso-2.

### Navigation
Barra pegajosa carbón hondo con filete inferior. Marca: cinco líneas espectrales en SVG + "RADAR IA" condensado. Menú en rótulos hueso-2; cada enlace lleva un muñón de línea a la izquierda que en la página actual sube a altura completa en hueso. El área de toque es de 3.25rem de alto.

### Espectro (componente firma)
La banda: fondo carbón hondo con grano, bandas finas y un resplandor central; una línea por noticia en `--x` %, del color de su sección. Formas: simple (1px; 1.5px en computador), doble (doblete de 4px = importante), media altura (de ayer), muñón (escala .16 y 45 % de opacidad = filtrada fuera). Debajo, el eje con las seis secciones (ticks alternados en celular) y un pie con leyenda y una línea de lectura que nombra la noticia al pasar o enfocar. En portada y días cada línea es un enlace; en Secciones es dibujo que sigue a los filtros. Al cargar, las líneas aterrizan desde la izquierda (0.95s, escalonadas 26ms). La miniatura del Archivo repite la banda a 2.6rem de alto sin halos.

### Noticia
Título (Title) con su marcador sobre el riel (1px del color de sección; doblete con brillo si es importante). Fila de datos en rótulos: sección con su trazo, "Importante" con doblete hueso, fecha y cuántas fuentes la cuentan. Cuerpo: "qué pasó" en hueso, "Por qué importa" en hueso-2 con rótulo inline. Términos en un `details` con "+" que gira 45°. Fuentes con subrayado borde-fuerte que toma el color de la sección al pasar; etiquetas con "#" en hueso-3.

### Foto de la noticia
La vista previa (og:image) de la fuente, mostrada desde su sitio (`referrerpolicy="no-referrer"`, carga diferida salvo la destacada). Va enmarcada en grafito: fondo carbón hondo con bandas, esquinas rectas y un filete de 1px del color de la sección arriba. La foto entra un poco apagada (`saturate(.8)`, `brightness(.94)`) y recupera su color al pasar el mouse sobre la noticia. Debajo siempre hay una **ilustración propia**: nueve líneas del color de la sección en posiciones y alturas sacadas del id, con su halo, y el nombre de la sección en rótulo; se ve si la noticia no tiene foto o si la foto no carga. Proporción 16:9. En el celular va arriba del título, del riel al borde de la placa. En el computador va a la derecha del texto (19rem); en la **noticia destacada** (la primera de la portada y de cada día) va arriba a todo el ancho, en 21:9.

### Lo más importante
Lista sin viñetas en Lead, separada por filetes; cada punto cruza el riel con un doblete sodio con brillo.

## Do's and Don'ts

### Do:
- **Do** asignar color solo vía `data-seccion` → `--c`, y usarlo en líneas de 1px.
- **Do** expresar estado con la forma de la línea: doble = importante, media altura = de ayer, muñón = fuera o en reposo.
- **Do** alinear cada marcador nuevo al riel con `--hueco` y `--tick-izq`.
- **Do** usar el resorte `cubic-bezier(.34, 1.56, .64, 1)` para escalar muñones y líneas, y `ease-out` de .2s para color y bordes; respetar "reducir movimiento".
- **Do** mantener la placa de lectura lisa (ceniza) y la textura en el fondo.

### Don't:
- **Don't** armar un portal de tarjetas con etiquetas de color ni un newsletter crema con serif.
- **Don't** rellenar superficies ni pintar texto con un color espectral.
- **Don't** usar el sodio 589 fuera de "Lo más importante".
- **Don't** redondear esquinas; el único círculo es el nodo del riel.
- **Don't** agregar `box-shadow`; el único brillo permitido es el de los dobletes.
- **Don't** sumar otra familia tipográfica ni otro tamaño de rótulo.
