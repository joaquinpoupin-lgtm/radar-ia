"""Foto de cada noticia: la imagen de vista previa que publica la página original (og:image).

Solo se guarda el link a la imagen (nunca la imagen): el sitio la muestra desde la fuente, como una
vista previa de WhatsApp. Si ninguna fuente tiene una foto que sirva, la noticia queda con
`imagen: null` y el sitio dibuja una ilustración propia. Nada de esto detiene la corrida.

Comando `radar imagenes`: completa las noticias ya guardadas que todavía no tienen el campo.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from radar.almacen import cargar_dia, guardar_dia
from radar.config import cargar_config
from radar.filtrar import CARPETA_DATOS
from radar.fuentes import crear_cliente
from radar.recolectar import _LectorMeta, meta_pagina
from radar.sitio import PATRON_DIA

URL_MINIATURA_YOUTUBE = "https://i.ytimg.com/vi/{}/hqdefault.jpg"
# Imágenes que no son de la noticia sino del sitio (logos, íconos, la tarjeta genérica de Reddit).
PATRON_GENERICA = re.compile(r"logo|favicon|icon|default|placeholder|redditstatic|/static/|sprite", re.I)


def id_video_youtube(url: str) -> str | None:
    partes = urlsplit(url)
    if partes.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if partes.path.startswith("/shorts/"):
            return partes.path.split("/")[2] or None
        return (parse_qs(partes.query).get("v") or [None])[0]
    if partes.hostname == "youtu.be":
        return partes.path.strip("/") or None
    return None


def imagen_de_url(url: str, cliente: httpx.Client) -> str | None:
    """La foto de vista previa de una página, o None si no tiene una que sirva."""
    video = id_video_youtube(url)
    if video:
        return URL_MINIATURA_YOUTUBE.format(video)
    encontradas = meta_pagina(url, cliente)
    for clave in _LectorMeta.CLAVES_IMAGEN:
        imagen = encontradas.get(clave, "").strip()
        if imagen:
            imagen = urljoin(url, imagen)
            if imagen.startswith("https://") and not PATRON_GENERICA.search(imagen):
                return imagen
    return None


def imagen_noticia(noticia: dict, cliente: httpx.Client) -> str | None:
    """Prueba las fuentes de la noticia en orden hasta encontrar una foto."""
    for fuente in noticia.get("fuentes", []):
        imagen = imagen_de_url(fuente["url"], cliente)
        if imagen:
            return imagen
    return None


def poner_imagenes(noticias: list[dict], cliente: httpx.Client, hilos: int = 8) -> int:
    """Agrega `imagen` (link o None) a las noticias que aún no lo tienen. Devuelve cuántas tienen foto."""
    faltan = [n for n in noticias if "imagen" not in n]
    with ThreadPoolExecutor(hilos) as pool:
        for n, imagen in zip(faltan, pool.map(lambda n: imagen_noticia(n, cliente), faltan)):
            n["imagen"] = imagen
    return sum(1 for n in faltan if n["imagen"])


def comando_imagenes(args) -> int:
    config = cargar_config()
    ahora = datetime.now(timezone.utc)
    total = con_foto = 0
    with crear_cliente(config) as cliente:
        for ruta in sorted(CARPETA_DATOS.glob("*.json")):
            if not PATRON_DIA.match(ruta.name):
                continue
            dia = cargar_dia(ruta.stem, CARPETA_DATOS)
            faltan = sum(1 for n in dia["noticias"] if "imagen" not in n)
            if not faltan:
                continue
            encontradas = poner_imagenes(dia["noticias"], cliente, config["fuentes"]["hilos"])
            # Se conserva la hora de la última corrida: completar fotos no es una corrida nueva.
            hora = datetime.fromisoformat(dia["actualizado"]) if dia.get("actualizado") else ahora
            guardar_dia(dia, hora, config, CARPETA_DATOS)
            total += faltan
            con_foto += encontradas
            print(f"{ruta.stem}: {encontradas} de {faltan} noticias con foto")
    print(f"Listo: {con_foto} de {total} noticias con foto (las demás usan la ilustración propia).")
    return 0
