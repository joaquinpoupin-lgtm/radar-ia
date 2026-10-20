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

from radar.config import cargar_config
from radar.fuentes import ErrorDescarga, ErrorFuentes, Fuente, cargar_fuentes, crear_cliente, descargar, fecha_entrada

# Extractos más cortos que esto (p. ej. "TBD") no sirven: se busca la descripción de la página.
MIN_EXTRACTO = 40
# De cada página solo se leen los primeros bytes: la descripción está en el <head>.
MAX_BYTES_PAGINA = 300_000
DOMINIOS_REDDIT = ("reddit.com", "redd.it")
URL_HN = "https://news.ycombinator.com/item?id={}"


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


# --- Recolección completa ---

def _leer_fuente(fuente: Fuente, cliente: httpx.Client, config: dict, patron: re.Pattern,
                 desde: datetime) -> tuple[list[Candidato], InformeFuente]:
    """Una fuente → sus candidatos recientes. Nunca lanza: el error queda en el informe."""
    informe = InformeFuente(fuente.nombre)
    largo = config["recolector"]["largo_extracto"]
    try:
        respuesta = descargar(fuente.url, cliente)
        if fuente.tipo == "hackernews":
            try:
                datos = respuesta.json()
            except ValueError:
                raise ErrorDescarga("la respuesta no es la API de Hacker News esperada")
            candidatos = candidatos_hn(fuente, datos, patron, largo)
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
    desde = ahora - timedelta(days=config["limites"]["dias_antiguedad_max"])
    patron = patron_ia(config["recolector"]["palabras_ia"])
    largo = config["recolector"]["largo_extracto"]
    resultado = Recoleccion()

    with cliente or crear_cliente(config) as c, ThreadPoolExecutor(config["fuentes"]["hilos"]) as hilos:
        for candidatos, informe in hilos.map(lambda f: _leer_fuente(f, c, config, patron, desde), fuentes):
            resultado.candidatos.extend(candidatos)
            resultado.informes.append(informe)

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
    # Una fuente caída no es un fallo de la corrida: solo falla si no se pudo leer ninguna.
    return 0 if any(not i.error for i in resultado.informes) else 1
