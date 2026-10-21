"""Recolector: lee todas las fuentes y las convierte a un formato común (Candidato)."""

import html
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import httpx

from radar.agrupar import agrupar, resumen_agrupacion
from radar.config import cargar_config
from radar.fuentes import (TIPOS_JSON, ErrorDescarga, ErrorFuentes, Fuente, cargar_fuentes, crear_cliente,
                           descargar, fecha_entrada, fecha_item_json, items_json, url_real)

# Extractos más cortos que esto (p. ej. "TBD") no sirven: se busca la descripción de la página.
MIN_EXTRACTO = 40
# De cada página solo se leen los primeros bytes: la descripción está en el <head>.
MAX_BYTES_PAGINA = 300_000
DOMINIOS_REDDIT = ("reddit.com", "redd.it")
URL_HN = "https://news.ycombinator.com/item?id={}"
URL_HF_MODELO = "https://huggingface.co/{}"
URL_HF_README = "https://huggingface.co/{}/raw/main/README.md"
URL_ARXIV = "https://arxiv.org/abs/{}"
# Del README de un modelo solo se lee el comienzo: el párrafo que lo presenta está arriba.
MAX_BYTES_README = 60_000
# Encabezados del README desde donde ya no se busca la presentación del modelo.
SECCIONES_TECNICAS = re.compile(r"quick ?start|usage|how to|install|inference|deploy|getting started|"
                                r"prompt|encoding|license|citation|requirements|example", re.I)


@dataclass
class Candidato:
    titulo: str
    url: str
    fuente: str
    tipo: str
    seccion: str
    idioma: str
    peso: int
    fecha: datetime | None  # siempre en UTC
    extracto: str = ""
    puntaje: int | None = None  # solo Hacker News

    def a_dict(self) -> dict:
        datos = asdict(self)
        datos["fecha"] = self.fecha.isoformat() if self.fecha else None
        if self.puntaje is None:
            del datos["puntaje"]
        return datos


@dataclass
class InformeFuente:
    nombre: str
    candidatos: int = 0
    con_descripcion_pagina: int = 0  # extractos sacados de og:description
    error: str = ""


@dataclass
class Recoleccion:
    candidatos: list[Candidato] = field(default_factory=list)
    informes: list[InformeFuente] = field(default_factory=list)


# --- Limpieza de texto ---

def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _es_reddit(url: str) -> bool:
    d = _dominio(url)
    return any(d == r or d.endswith("." + r) for r in DOMINIOS_REDDIT)


def limpiar_texto(texto: str, largo: int) -> str:
    """HTML → texto plano corto: sin etiquetas, sin links sueltos, espacios normalizados."""
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = html.unescape(texto)
    texto = re.sub(r"The post .{0,300}? appeared first on .*$", "", texto, flags=re.S)  # relleno de WordPress
    texto = re.sub(r"\s*Discussion\s*\|\s*Link\s*$", "", texto)  # relleno del feed de Product Hunt
    texto = re.sub(r"https?://\S+", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= largo:
        return texto
    corte = texto[: largo - 1].rsplit(" ", 1)[0]
    return corte.rstrip(" ,.;:") + "…"


def _limpiar_reddit(resumen: str) -> tuple[str, str | None]:
    """Del HTML de una publicación de Reddit saca (texto del post, link externo si apunta a un artículo)."""
    link = re.search(r'<a href="([^"]+)">\[link\]</a>', resumen or "")
    externo = html.unescape(link.group(1)) if link and not _es_reddit(link.group(1)) else None
    cuerpo = re.search(r'<div class="md">(.*?)</div>', resumen or "", flags=re.S)
    return (cuerpo.group(1) if cuerpo else ""), externo


# --- Descripción de la página (og:description) ---

class _LectorMeta(HTMLParser):
    CLAVES = ("og:description", "twitter:description", "description")

    def __init__(self):
        super().__init__()
        self.encontradas: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        clave = (a.get("property") or a.get("name") or "").lower()
        if clave in self.CLAVES and a.get("content"):
            self.encontradas.setdefault(clave, a["content"])


def descripcion_pagina(url: str, cliente: httpx.Client) -> str | None:
    """Lee el comienzo de la página y devuelve su og:description (o la descripción común). Nunca lanza."""
    try:
        with cliente.stream("GET", url) as r:
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                return None
            datos = b""
            for trozo in r.iter_bytes():
                datos += trozo
                if len(datos) >= MAX_BYTES_PAGINA:
                    break
        lector = _LectorMeta()
        lector.feed(datos.decode(r.encoding or "utf-8", errors="replace"))
    except Exception:  # una página rara nunca debe romper la recolección
        return None
    return next((lector.encontradas[c] for c in _LectorMeta.CLAVES if c in lector.encontradas), None)


# --- Lectura por tipo de fuente ---

def _base(fuente: Fuente, **datos) -> Candidato:
    return Candidato(fuente=fuente.nombre, tipo=fuente.tipo, seccion=fuente.seccion,
                     idioma=fuente.idioma, peso=fuente.peso, **datos)


def candidatos_feed(fuente: Fuente, contenido: bytes, largo: int) -> list[Candidato]:
    """RSS/Atom (incluye YouTube y Reddit) → candidatos."""
    feed = feedparser.parse(contenido)
    if not feed.entries and feed.bozo:
        raise ErrorDescarga("no es un RSS/Atom válido")
    salida = []
    for e in feed.entries:
        titulo = re.sub(r"\s+", " ", html.unescape(e.get("title", ""))).strip()
        url = e.get("link", "")
        if not titulo or not url:
            continue
        resumen = e.get("summary") or ""
        reddit = _es_reddit(url)
        if reddit:
            resumen, externo = _limpiar_reddit(resumen)
            url = externo or url
        extracto = limpiar_texto(resumen, largo)
        if len(extracto) < MIN_EXTRACTO and e.get("content") and not reddit:
            extracto = limpiar_texto(e.content[0].get("value", ""), largo)
        salida.append(_base(fuente, titulo=titulo, url=url, fecha=fecha_entrada(e), extracto=extracto))
    return salida


def patron_ia(palabras: list[str]) -> re.Pattern:
    """Expresión que encuentra cualquiera de las palabras como palabra completa (sin importar mayúsculas)."""
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in palabras) + r")\b", re.I)


def candidatos_hn(fuente: Fuente, datos: dict, patron: re.Pattern, largo: int) -> list[Candidato]:
    """Respuesta de la API de Hacker News → candidatos, solo los que hablan de IA."""
    try:
        hits = datos["hits"]
    except (KeyError, TypeError):
        raise ErrorDescarga("la respuesta no es la API de Hacker News esperada")
    salida = []
    for h in hits:
        titulo = (h.get("title") or "").strip()
        if not titulo or not patron.search(titulo):
            continue
        fecha = datetime.fromtimestamp(h["created_at_i"], timezone.utc) if h.get("created_at_i") else None
        salida.append(_base(fuente, titulo=titulo, url=h.get("url") or URL_HN.format(h["objectID"]),
                            fecha=fecha, extracto=limpiar_texto(h.get("story_text") or "", largo),
                            puntaje=h.get("points")))
    return salida


def _con_datos(texto: str, datos: list[str], largo: int) -> str:
    """Extracto = texto (cortado) + " · dato · dato", sin pasar de `largo` caracteres."""
    sufijo = "".join(f" · {d}" for d in datos if d)
    return (limpiar_texto(texto, max(largo - len(sufijo), 0)) + sufijo).strip(" ·")


def _miles(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def candidatos_github(fuente: Fuente, items: list[dict], ahora: datetime, desde: datetime,
                      largo: int) -> list[Candidato]:
    """Búsqueda de repos de GitHub → candidatos (solo los creados desde `desde`).

    La fecha es la de la corrida ("visto en alza hoy"): un repo creado hace 5 días puede estar
    subiendo justo ahora, y con su fecha de creación quedaría fuera de la ventana de días.
    """
    salida = []
    for r in items:
        nombre, url = r.get("full_name"), r.get("html_url")
        creado = fecha_item_json("github", r)
        if not nombre or not url or (creado and creado < desde):
            continue
        descripcion = re.sub(r"\s+", " ", r.get("description") or "").strip()
        titulo = f"{nombre}: {descripcion}" if descripcion else nombre
        datos = [f"{_miles(r.get('stargazers_count'))} estrellas en GitHub",
                 f"lenguaje {r['language']}" if r.get("language") else "",
                 "temas: " + ", ".join(r["topics"][:5]) if r.get("topics") else ""]
        salida.append(_base(fuente, titulo=limpiar_texto(titulo, 160), url=url, fecha=ahora,
                            extracto=_con_datos(descripcion, datos, largo)))
    return salida


def candidatos_hf_modelos(fuente: Fuente, items: list[dict], ahora: datetime, desde: datetime,
                          largo: int) -> list[Candidato]:
    """Modelos en tendencia de Hugging Face → candidatos (solo los publicados desde `desde`, sin copias
    cuantizadas de otro modelo). El texto del extracto se completa después con el README (`parrafo_readme`)."""
    salida = []
    for m in items:
        ident = m.get("id") or m.get("modelId")
        creado = fecha_item_json("huggingface", m)
        etiquetas = [str(t) for t in m.get("tags") or []]
        if not ident or (creado and creado < desde) or any(t.startswith("base_model:quantized:") for t in etiquetas):
            continue
        licencia = next((t.split(":", 1)[1] for t in etiquetas if t.startswith("license:")), "")
        datos = [f"tipo: {m['pipeline_tag']}" if m.get("pipeline_tag") else "",
                 f"licencia {licencia}" if licencia else "",
                 f"{_miles(m.get('likes'))} me gusta y {_miles(m.get('downloads'))} descargas en Hugging Face"]
        salida.append(_base(fuente, titulo=ident, url=URL_HF_MODELO.format(ident), fecha=ahora,
                            extracto=_con_datos("", datos, largo)))
    return salida


def candidatos_papers(fuente: Fuente, items: list[dict], votos_min: int, largo: int) -> list[Candidato]:
    """Daily Papers de Hugging Face → candidatos con link a arXiv, solo los que tienen ≥ `votos_min` votos."""
    salida = []
    for item in items:
        paper = item.get("paper") if isinstance(item.get("paper"), dict) else {}
        ident, votos = paper.get("id"), paper.get("upvotes") or 0
        titulo = re.sub(r"\s+", " ", paper.get("title") or item.get("title") or "").strip()
        if not ident or not titulo or votos < votos_min:
            continue
        salida.append(_base(fuente, titulo=titulo, url=URL_ARXIV.format(ident),
                            fecha=fecha_item_json("papers", item),
                            extracto=_con_datos(paper.get("summary") or "", [f"{votos} votos en Hugging Face"],
                                                largo)))
    return salida


def parrafo_readme(texto: str, largo: int) -> str:
    """Primer párrafo de texto corrido de un README (sin encabezado YAML, HTML, imágenes, tablas ni código)."""
    texto = re.sub(r"\A---\n.*?\n---\n", "", texto, flags=re.S)
    texto = re.sub(r"```.*?(```|\Z)", "", texto, flags=re.S)
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)
    texto = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", texto)              # imágenes
    texto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", texto)           # [texto](link) → texto
    texto = re.sub(r"\*\*|__|`", "", texto)                             # negritas y código en línea
    for parrafo in re.split(r"\n\s*\n", texto):
        lineas = [l for l in parrafo.strip().splitlines() if l.strip()]
        if not lineas:
            continue
        primera = lineas[0].lstrip()
        if primera.startswith("#") and SECCIONES_TECNICAS.search(primera):
            break  # de aquí en adelante son instrucciones de uso, no la presentación del modelo
        if primera.startswith(("#", "|", ">", "- ", "* ", "=", "<")):
            continue
        limpio = limpiar_texto(" ".join(lineas), largo)
        if len(limpio) >= 80 and len(limpio.split()) >= 10:
            return limpio
    return ""


def leer_readme(ident: str, cliente: httpx.Client) -> str | None:
    """Comienzo del README de un modelo de Hugging Face. Nunca lanza."""
    try:
        with cliente.stream("GET", URL_HF_README.format(ident)) as r:
            if r.status_code != 200:
                return None
            datos = b""
            for trozo in r.iter_bytes():
                datos += trozo
                if len(datos) >= MAX_BYTES_README:
                    break
        return datos.decode("utf-8", errors="replace")
    except Exception:  # un README raro nunca debe romper la recolección
        return None


# --- Recolección completa ---

def _leer_fuente(fuente: Fuente, cliente: httpx.Client, config: dict, patron: re.Pattern,
                 ahora: datetime) -> tuple[list[Candidato], InformeFuente]:
    """Una fuente → sus candidatos recientes. Nunca lanza: el error queda en el informe."""
    informe = InformeFuente(fuente.nombre)
    rec = config["recolector"]
    largo = rec["largo_extracto"]
    desde = ahora - timedelta(days=config["limites"]["dias_antiguedad_max"])
    desde_tendencias = ahora - timedelta(days=rec["dias_tendencias"])
    try:
        respuesta = descargar(url_real(fuente, ahora, config), cliente)
        if fuente.tipo in TIPOS_JSON:
            try:
                datos = respuesta.json()
                items = items_json(fuente.tipo, datos)
            except ValueError as e:  # JSON roto o con otra forma
                raise ErrorDescarga(str(e) if "API" in str(e) else "la respuesta no es JSON válido")
            if fuente.tipo == "hackernews":
                candidatos = candidatos_hn(fuente, datos, patron, largo)
            elif fuente.tipo == "github":
                candidatos = candidatos_github(fuente, items, ahora, desde_tendencias, largo)
            elif fuente.tipo == "huggingface":
                candidatos = candidatos_hf_modelos(fuente, items, ahora, desde_tendencias, largo)
            else:
                candidatos = candidatos_papers(fuente, items, rec["papers_votos_min"], largo)
        else:
            candidatos = candidatos_feed(fuente, respuesta.content, largo)
    except ErrorDescarga as e:
        informe.error = str(e)
        return [], informe
    except Exception as e:  # algo inesperado en una fuente no detiene al resto
        informe.error = f"error inesperado ({type(e).__name__})"
        return [], informe

    # Solo lo reciente (sin fecha también entra; el pre-filtro decide), lo más nuevo primero.
    recientes = [c for c in candidatos if c.fecha is None or c.fecha >= desde]
    recientes.sort(key=lambda c: c.fecha or desde, reverse=True)
    recientes = recientes[: config["recolector"]["max_por_fuente"]]
    informe.candidatos = len(recientes)
    return recientes, informe


def recolectar(fuentes: list[Fuente], config: dict, ahora: datetime | None = None,
               cliente: httpx.Client | None = None) -> Recoleccion:
    ahora = ahora or datetime.now(timezone.utc)
    patron = patron_ia(config["recolector"]["palabras_ia"])
    largo = config["recolector"]["largo_extracto"]
    resultado = Recoleccion()

    with cliente or crear_cliente(config) as c, ThreadPoolExecutor(config["fuentes"]["hilos"]) as hilos:
        for candidatos, informe in hilos.map(lambda f: _leer_fuente(f, c, config, patron, ahora), fuentes):
            resultado.candidatos.extend(candidatos)
            resultado.informes.append(informe)

        # Modelos de Hugging Face: la API no trae descripción y la de la página es la genérica del sitio,
        # así que el extracto empieza con el primer párrafo del README del modelo (si lo hay).
        modelos = [x for x in resultado.candidatos if x.tipo == "huggingface"]
        readmes = list(hilos.map(lambda x: leer_readme(x.titulo, c), modelos))
        for modelo, readme in zip(modelos, readmes):
            parrafo = parrafo_readme(readme or "", largo - len(modelo.extracto) - 3)
            if parrafo:
                modelo.extracto = f"{parrafo} · {modelo.extracto}"

        # Los que no traen extracto útil: se busca la descripción de la página (menos Reddit, que bloquea).
        faltan = [x for x in resultado.candidatos
                  if len(x.extracto) < MIN_EXTRACTO and not _es_reddit(x.url)]
        descripciones = list(hilos.map(lambda x: descripcion_pagina(x.url, c), faltan))

    # Una descripción idéntica en varias páginas de la misma fuente es la genérica del sitio: no sirve.
    repetidas = Counter((x.fuente, d) for x, d in zip(faltan, descripciones) if d)
    por_nombre = {i.nombre: i for i in resultado.informes}
    for candidato, descripcion in zip(faltan, descripciones):
        if descripcion and repetidas[(candidato.fuente, descripcion)] == 1:
            candidato.extracto = limpiar_texto(descripcion, largo)
            por_nombre[candidato.fuente].con_descripcion_pagina += 1
    return resultado


def tabla(recoleccion: Recoleccion) -> str:
    filas = [("Fuente", "Candidatos", "Detalle")]
    for i in recoleccion.informes:
        if i.error:
            detalle = f"ERROR: {i.error}"
        elif i.con_descripcion_pagina:
            detalle = f"{i.con_descripcion_pagina} con extracto tomado de la página"
        else:
            detalle = ""
        filas.append((i.nombre, "-" if i.error else str(i.candidatos), detalle))
    anchos = [max(len(f[k]) for f in filas) for k in range(2)]
    lineas = [f"{f[0].ljust(anchos[0])}  {f[1].rjust(anchos[1])}  {f[2]}".rstrip() for f in filas]
    lineas.insert(1, "-" * len(lineas[0]))
    errores = sum(bool(i.error) for i in recoleccion.informes)
    sin_extracto = sum(not c.extracto for c in recoleccion.candidatos)
    lineas += ["", f"Total: {len(recoleccion.candidatos)} candidatos de {len(recoleccion.informes)} fuentes"
                   f" · {errores} fuentes con error · {sin_extracto} candidatos sin extracto"]
    return "\n".join(lineas)


def comando_recolectar(args) -> int:
    config = cargar_config()
    try:
        fuentes = cargar_fuentes()
    except ErrorFuentes as e:
        print(e)
        return 1
    print(f"Recolectando de {len(fuentes)} fuentes (últimos {config['limites']['dias_antiguedad_max']} días)...\n")
    resultado = recolectar(fuentes, config)
    print(tabla(resultado))

    if args.mostrar:
        zona = ZoneInfo(config["zona_horaria"])
        print(f"\nEjemplos ({min(args.mostrar, len(resultado.candidatos))}):")
        for c in resultado.candidatos[: args.mostrar]:
            fecha = c.fecha.astimezone(zona).strftime("%d-%m %H:%M") if c.fecha else "sin fecha"
            puntaje = f" · {c.puntaje} pts" if c.puntaje is not None else ""
            print(f"\n• [{c.fuente} · {fecha}{puntaje}] {c.titulo}\n  {c.url}\n  {c.extracto[:160] or '(sin extracto)'}")

    grupos = agrupar(resultado.candidatos, config["limites"]["similitud_titulos"])
    print(f"\nAgrupando: {resumen_agrupacion(resultado.candidatos, grupos)}")
    if args.grupos:
        for g in sorted((g for g in grupos if len(g.candidatos) > 1), key=lambda g: -len(g.candidatos)):
            print(f"\n• [{g.id} · {g.confirmacion} fuentes] {g.titulo}")
            for c in g.candidatos:
                print(f"  - {c.fuente}: {c.titulo}\n    {c.url}")
    # Una fuente caída no es un fallo de la corrida: solo falla si no se pudo leer ninguna.
    return 0 if any(not i.error for i in resultado.informes) else 1
