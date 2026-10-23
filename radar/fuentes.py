"""Lectura de sources.yaml y comando `fuentes`, que prueba cada fuente."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import feedparser
import httpx
import yaml

from radar.config import RAIZ, cargar_config

RUTA_FUENTES = RAIZ / "sources.yaml"

TIPOS = {"rss", "hackernews", "youtube", "github", "huggingface", "papers"}
# Tipos que se leen desde una API JSON (no RSS). Paso 14: github (búsqueda de repos), huggingface (modelos
# en tendencia) y papers (Daily Papers de Hugging Face, que son papers de arXiv votados por la comunidad).
TIPOS_JSON = {"hackernews", "github", "huggingface", "papers"}
SECCIONES = {"modelos", "herramientas", "tendencias", "creadores", "dinero", "tips"}
IDIOMAS = {"es", "en"}
CAMPOS = ("nombre", "tipo", "url", "seccion", "idioma", "peso")


class ErrorFuentes(ValueError):
    """sources.yaml tiene errores; el mensaje los lista todos."""


@dataclass(frozen=True)
class Fuente:
    nombre: str
    tipo: str
    url: str
    seccion: str
    idioma: str
    peso: int
    activa: bool = True
    max_por_corrida: int | None = None  # tope propio en el pre-filtro (si no, prefiltro.max_por_fuente)


def cargar_fuentes(ruta: Path = RUTA_FUENTES, solo_activas: bool = True) -> list[Fuente]:
    """Lee y valida sources.yaml. Si hay errores, los junta todos en un solo mensaje."""
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    crudas = datos.get("fuentes")
    if not isinstance(crudas, list) or not crudas:
        raise ErrorFuentes(f"{ruta.name}: falta la lista 'fuentes'.")

    errores, fuentes, nombres = [], [], set()
    for i, cruda in enumerate(crudas, start=1):
        if not isinstance(cruda, dict):
            errores.append(f"fuente #{i}: no es una entrada válida")
            continue
        quien = f"fuente #{i} ({cruda.get('nombre', 'sin nombre')})"
        faltan = [c for c in CAMPOS if cruda.get(c) in (None, "")]
        if faltan:
            errores.append(f"{quien}: faltan campos: {', '.join(faltan)}")
            continue
        if cruda["tipo"] not in TIPOS:
            errores.append(f"{quien}: tipo '{cruda['tipo']}' no existe (usar: {', '.join(sorted(TIPOS))})")
        if cruda["seccion"] not in SECCIONES:
            errores.append(f"{quien}: sección '{cruda['seccion']}' no existe (usar: {', '.join(sorted(SECCIONES))})")
        if cruda["idioma"] not in IDIOMAS:
            errores.append(f"{quien}: idioma '{cruda['idioma']}' no soportado (usar: es, en)")
        if not isinstance(cruda["peso"], int) or not 1 <= cruda["peso"] <= 3:
            errores.append(f"{quien}: peso debe ser 1, 2 o 3")
        if not str(cruda["url"]).startswith(("https://", "http://")):
            errores.append(f"{quien}: la url debe empezar con https://")
        tope = cruda.get("max_por_corrida")
        if tope is not None and (not isinstance(tope, int) or isinstance(tope, bool) or tope < 1):
            errores.append(f"{quien}: max_por_corrida debe ser un número entero desde 1")
        if cruda["nombre"] in nombres:
            errores.append(f"{quien}: nombre repetido")
        nombres.add(cruda["nombre"])
        fuentes.append(Fuente(**{c: cruda[c] for c in CAMPOS}, activa=bool(cruda.get("activa", True)),
                              max_por_corrida=tope))

    if errores:
        raise ErrorFuentes(f"{ruta.name} tiene errores:\n  - " + "\n  - ".join(errores))
    return [f for f in fuentes if f.activa or not solo_activas]


def topes_por_fuente(fuentes: list[Fuente]) -> dict[str, int]:
    """{nombre: tope} de las fuentes con `max_por_corrida` propio (para el pre-filtro)."""
    return {f.nombre: f.max_por_corrida for f in fuentes if f.max_por_corrida}


def url_real(fuente: Fuente, ahora: datetime, config: dict) -> str:
    """La URL a pedir: `{desde}` se cambia por la fecha de hace `recolector.dias_tendencias` días (AAAA-MM-DD)."""
    desde = ahora - timedelta(days=config["recolector"]["dias_tendencias"])
    return fuente.url.replace("{desde}", desde.strftime("%Y-%m-%d"))


def _fecha_iso(texto) -> datetime | None:
    """"2026-10-17T02:40:38.000Z" → datetime en UTC (None si no viene o no se entiende)."""
    try:
        fecha = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def items_json(tipo: str, datos) -> list[dict]:
    """La lista de ítems de una respuesta JSON según el tipo. Lanza ValueError si no tiene la forma esperada."""
    try:
        if tipo == "hackernews":
            items = datos["hits"]
        elif tipo == "github":
            items = datos["items"]
        else:  # huggingface y papers responden directamente una lista
            items = datos
    except (KeyError, TypeError):
        items = None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError(f"la respuesta no es la API de {NOMBRE_API[tipo]} esperada")
    return items


NOMBRE_API = {"hackernews": "Hacker News", "github": "GitHub", "huggingface": "Hugging Face",
              "papers": "Hugging Face Daily Papers"}


def fecha_item_json(tipo: str, item: dict) -> datetime | None:
    """Fecha de publicación de un ítem JSON (en `radar fuentes` sirve para "última novedad")."""
    if tipo == "hackernews":
        return datetime.fromtimestamp(item["created_at_i"], timezone.utc) if item.get("created_at_i") else None
    if tipo == "github":
        return _fecha_iso(item.get("created_at"))
    if tipo == "huggingface":
        return _fecha_iso(item.get("createdAt"))
    paper = item.get("paper") if isinstance(item.get("paper"), dict) else {}
    return _fecha_iso(paper.get("submittedOnDailyAt") or item.get("publishedAt"))


def crear_cliente(config: dict) -> httpx.Client:
    """Cliente HTTP con el timeout y la identificación (user-agent) de config.yaml."""
    return httpx.Client(
        timeout=config["red"]["timeout_seg"],
        follow_redirects=True,
        headers={"User-Agent": config["red"]["user_agent"]},
    )


@dataclass
class Resultado:
    fuente: Fuente
    estado: str  # OK | AVISO | ERROR
    items: int = 0
    ultima: datetime | None = None  # fecha de la publicación más reciente (UTC)
    detalle: str = ""


def fecha_entrada(entrada) -> datetime | None:
    t = entrada.get("published_parsed") or entrada.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def _leer(fuente: Fuente, respuesta: httpx.Response) -> tuple[int, datetime | None]:
    """Devuelve (cantidad de ítems, fecha más reciente). Lanza ValueError si el contenido no sirve."""
    if fuente.tipo in TIPOS_JSON:
        try:
            datos = respuesta.json()
        except json.JSONDecodeError:
            raise ValueError(f"la respuesta no es la API de {NOMBRE_API[fuente.tipo]} esperada")
        items = items_json(fuente.tipo, datos)
        fechas = [f for f in (fecha_item_json(fuente.tipo, i) for i in items) if f]
        return len(items), max(fechas, default=None)

    feed = feedparser.parse(respuesta.content)
    if not feed.entries and feed.bozo:
        raise ValueError("no es un RSS/Atom válido")
    fechas = [f for f in map(fecha_entrada, feed.entries) if f]
    return len(feed.entries), max(fechas, default=None)


class ErrorDescarga(Exception):
    """La fuente no se pudo descargar; el mensaje explica por qué en palabras simples."""


def descargar(url: str, cliente: httpx.Client) -> httpx.Response:
    """GET que devuelve la respuesta si es 200 o lanza ErrorDescarga con un motivo legible."""
    try:
        respuesta = cliente.get(url)
    except httpx.TimeoutException:
        raise ErrorDescarga("no respondió a tiempo")
    except httpx.HTTPError as e:
        raise ErrorDescarga(f"error de conexión ({type(e).__name__})")

    if respuesta.status_code != 200:
        detalle = f"HTTP {respuesta.status_code}"
        if respuesta.status_code == 429:
            detalle += " (demasiados pedidos; probar más tarde)"
        elif respuesta.status_code in (404, 410):
            detalle += " (la dirección ya no existe)"
        raise ErrorDescarga(detalle)
    return respuesta


# --- YouTube: respaldo cuando el RSS está caído ---
# Desde fines de 2025 los feeds de YouTube responden 404/500 a ratos (sobre todo a servidores en la nube),
# mientras la página de videos del canal sigue abriendo. Esa página no trae la fecha exacta, sino
# "3 days ago" / "hace 3 días", así que la fecha de esos videos es aproximada. Se pide en el idioma del
# canal (`hl`) porque en otro idioma YouTube muestra los títulos traducidos.

URL_CANAL_YOUTUBE = "https://www.youtube.com/channel/{}/videos?hl={}"
HACE = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago"
                  r"|hace\s+(\d+)\s+(segundo|minuto|hora|día|semana|mes|año)", re.I)
SEGUNDOS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400,
            "month": 30 * 86400, "year": 365 * 86400,
            "segundo": 1, "minuto": 60, "hora": 3600, "día": 86400, "semana": 7 * 86400,
            "mes": 30 * 86400, "año": 365 * 86400}


def _buscar(nodo, clave: str):
    """Todos los valores de `clave` en cualquier nivel de un JSON."""
    if isinstance(nodo, dict):
        if clave in nodo:
            yield nodo[clave]
        for valor in nodo.values():
            yield from _buscar(valor, clave)
    elif isinstance(nodo, list):
        for valor in nodo:
            yield from _buscar(valor, clave)


def videos_canal(pagina: str, ahora: datetime) -> list[dict]:
    """Página de videos de un canal de YouTube → [{"id", "titulo", "fecha"}]. Lanza ValueError si no sirve."""
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", pagina, re.S)
    try:
        datos = json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        datos = None
    if datos is None:
        raise ValueError("la página del canal no trae la lista de videos")
    videos = []
    for video in _buscar(datos, "lockupViewModel"):
        if video.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO" or not video.get("contentId"):
            continue
        meta = video.get("metadata", {}).get("lockupMetadataViewModel", {})
        titulo = re.sub(r"\s+", " ", meta.get("title", {}).get("content", "")).strip()
        filas = meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
        textos = [p.get("accessibilityLabel") or p.get("text", {}).get("content", "")
                  for fila in filas for p in fila.get("metadataParts", [])]
        hace = next((h for h in map(HACE.search, textos) if h), None)
        if titulo and hace:  # sin "hace X" (p. ej. un estreno programado) no se sabe si es reciente
            cantidad, unidad = (hace[1], hace[2]) if hace[1] else (hace[3], hace[4])
            fecha = ahora - timedelta(seconds=int(cantidad) * SEGUNDOS[unidad.lower()])
            videos.append({"id": video["contentId"], "titulo": titulo, "fecha": fecha})
    return videos


def leer_canal_youtube(fuente: Fuente, cliente: httpx.Client, ahora: datetime) -> list[dict]:
    """Videos del canal leídos desde su página (ver `videos_canal`). Lanza ErrorDescarga con un motivo legible."""
    canal = parse_qs(urlparse(fuente.url).query).get("channel_id")
    if not canal:
        raise ErrorDescarga("la URL no trae channel_id")
    respuesta = descargar(URL_CANAL_YOUTUBE.format(canal[0], fuente.idioma), cliente)
    try:
        return videos_canal(respuesta.text, ahora)
    except ValueError as e:
        raise ErrorDescarga(str(e))


def probar_fuente(fuente: Fuente, cliente: httpx.Client, ahora: datetime, dias_aviso: int,
                  url: str | None = None) -> Resultado:
    """Descarga la fuente (o `url`, si ya trae la fecha puesta) y dice si funciona. Nunca lanza excepciones."""
    nota = ""
    try:
        items, ultima = _leer(fuente, descargar(url or fuente.url, cliente))
    except (ErrorDescarga, ValueError) as e:
        if fuente.tipo != "youtube":
            return Resultado(fuente, "ERROR", detalle=str(e))
        try:
            videos = leer_canal_youtube(fuente, cliente, ahora)
        except ErrorDescarga as e2:
            return Resultado(fuente, "ERROR", detalle=f"RSS: {e} · página del canal: {e2}")
        items, ultima = len(videos), max((v["fecha"] for v in videos), default=None)
        nota = f"RSS caído ({e}); se leyó la página del canal"

    if items == 0:
        return Resultado(fuente, "AVISO", detalle="responde, pero no trae publicaciones")
    if ultima and (ahora - ultima).days > dias_aviso:
        detalle = f"sin novedades hace {(ahora - ultima).days} días" + (f" · {nota}" if nota else "")
        return Resultado(fuente, "AVISO", items, ultima, detalle)
    return Resultado(fuente, "OK", items, ultima, nota)


def probar_todas(fuentes: list[Fuente], config: dict, ahora: datetime | None = None,
                 cliente: httpx.Client | None = None) -> list[Resultado]:
    """Prueba todas las fuentes en paralelo; el orden del resultado es el de sources.yaml."""
    ahora = ahora or datetime.now(timezone.utc)
    dias_aviso = config["fuentes"]["dias_aviso_sin_novedades"]
    with cliente or crear_cliente(config) as c, ThreadPoolExecutor(config["fuentes"]["hilos"]) as hilos:
        return list(hilos.map(lambda f: probar_fuente(f, c, ahora, dias_aviso, url_real(f, ahora, config)),
                              fuentes))


def _hace(ultima: datetime | None, ahora: datetime, zona: ZoneInfo) -> str:
    if not ultima:
        return "-"
    dias = (ahora.astimezone(zona).date() - ultima.astimezone(zona).date()).days
    if dias <= 0:
        return "hoy"
    return "ayer" if dias == 1 else f"hace {dias} días"


def tabla(resultados: list[Resultado], ahora: datetime, zona: str = "America/Santiago") -> str:
    """Tabla de texto con una fila por fuente y un resumen al final."""
    z = ZoneInfo(zona)
    filas = [("Estado", "Fuente", "Tipo", "Ítems", "Última novedad", "Detalle")]
    for r in resultados:
        filas.append((r.estado, r.fuente.nombre, r.fuente.tipo, str(r.items) if r.items else "-",
                      _hace(r.ultima, ahora, z), r.detalle))
    anchos = [max(len(f[i]) for f in filas) for i in range(len(filas[0]) - 1)]
    lineas = ["  ".join(c.ljust(a) for c, a in zip(f, anchos)) + "  " + f[-1] for f in filas]
    lineas.insert(1, "-" * len(lineas[0]))
    cuenta = {e: sum(r.estado == e for r in resultados) for e in ("OK", "AVISO", "ERROR")}
    lineas.append("")
    lineas.append(f"{len(resultados)} fuentes: {cuenta['OK']} OK · {cuenta['AVISO']} con aviso · "
                  f"{cuenta['ERROR']} con error")
    return "\n".join(l.rstrip() for l in lineas)


def comando_fuentes(_args) -> int:
    config = cargar_config()
    try:
        fuentes = cargar_fuentes()
    except ErrorFuentes as e:
        print(e)
        return 1
    print(f"Probando {len(fuentes)} fuentes...\n")
    ahora = datetime.now(timezone.utc)
    resultados = probar_todas(fuentes, config, ahora)
    print(tabla(resultados, ahora, config["zona_horaria"]))
    return 1 if any(r.estado == "ERROR" for r in resultados) else 0
