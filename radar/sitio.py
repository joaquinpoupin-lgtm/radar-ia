"""Sitio web estático: _site/ a partir de data/AAAA-MM-DD.json y templates/.

Páginas:
    index.html                 brief del día (portada)
    secciones.html             noticias de los últimos días con filtros (sección, 🔥, etiquetas)
    archivo/index.html         lista de días
    archivo/AAAA-MM-DD.html    brief + todas las noticias de ese día

Sin servidor ni frameworks: HTML generado con Jinja2, un solo CSS y un poco de JS para los filtros
y el "espectro" (cada noticia es una línea de color según su sección).
"""

import hashlib
import html
import json
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.almacen import fecha_anterior, noticias_por_id
from radar.config import RAIZ, cargar_config
from radar.filtrar import CARPETA_DATOS, hoy_chile
from radar.fuentes import crear_cliente
from radar.resumir import SECCIONES

CARPETA_PLANTILLAS = RAIZ / "templates"
CARPETA_SITIO = RAIZ / "_site"
PATRON_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
MAX_ETIQUETAS_FILTRO = 20  # en secciones.html solo las etiquetas más usadas (si no, el filtro no se lee)
# Se copian tal cual a _site/. La fuente Archivo (licencia libre OFL, ver archivo-OFL.txt) va dentro
# del sitio para no depender de Google Fonts.
ARCHIVOS_ESTATICOS = ["estilo.css", "archivo.woff2", "archivo-OFL.txt"]

NOMBRES_SECCION = {
    "modelos": "Modelos y lanzamientos",
    "herramientas": "Herramientas y proyectos",
    "tendencias": "De qué habla la gente",
    "creadores": "Radar de creadores",
    "dinero": "Dinero con IA",
    "tips": "Saca el máximo provecho",
}
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


# --- Datos ---

def cargar_dias(carpeta: Path = CARPETA_DATOS) -> dict[str, dict]:
    """Todos los días guardados, {fecha: día}. Solo lee: un archivo dañado se avisa y se salta
    (el Paso 8 ya lo aparta cuando vuelve a escribir ese día)."""
    dias = {}
    for ruta in sorted(carpeta.glob("*.json")):
        if not PATRON_DIA.match(ruta.name):
            continue
        try:
            dia = json.loads(ruta.read_text(encoding="utf-8"))
            if not isinstance(dia, dict) or not isinstance(dia.get("noticias"), list):
                raise ValueError("no tiene la lista 'noticias'")
        except (ValueError, OSError) as e:
            print(f"Aviso: {ruta.name} no se pudo leer ({type(e).__name__}); no aparece en el sitio.")
            continue
        dias[ruta.stem] = {"brief": None, "actualizado": None, **dia, "fecha": ruta.stem}
    return dias


def fecha_larga(fecha: str) -> str:
    d = date.fromisoformat(fecha)
    return f"{DIAS_SEMANA[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(fecha: str) -> str:
    d = date.fromisoformat(fecha)
    return f"{d.day} {MESES[d.month - 1][:3]}"


def hora_actualizado(dia: dict | None) -> str:
    """'21 oct, 12:31' (hora de Chile, como se guardó) o '' si no hay dato."""
    if not dia or not dia.get("actualizado"):
        return ""
    t = datetime.fromisoformat(dia["actualizado"])
    return f"{fecha_corta(t.date().isoformat())}, {t:%H:%M}"


def orden_importancia(noticias: list[dict]) -> list[dict]:
    """🔥 primero; el resto en el orden en que llegaron."""
    return sorted(noticias, key=lambda n: n["importancia"] != "alta")


def contenido_brief(dia: dict, dias: dict[str, dict]) -> dict | None:
    """Bullets + noticias del brief de un día (las de ayer se buscan en el archivo de ayer)."""
    if not dia.get("brief"):
        return None
    vacio = {"noticias": []}
    por_id = noticias_por_id(dia, dias.get(fecha_anterior(dia["fecha"]), vacio))
    return {"bullets": dia["brief"].get("lo_mas_importante", []),
            "noticias": [por_id[i] for i in dia["brief"].get("ids", []) if i in por_id]}


def minutos_lectura(brief: dict | None, palabras_por_minuto: int) -> int:
    """Lo que se lee del brief: bullets + título, qué pasó y por qué importa de cada noticia
    (los términos van plegados y los links se leen afuera)."""
    if not brief:
        return 0
    textos = list(brief["bullets"])
    for n in brief["noticias"]:
        textos += [n["titulo"], n["que_paso"], n["por_que_importa"]]
    palabras = sum(len(t.split()) for t in textos)
    return max(1, round(palabras / palabras_por_minuto))


def datos_portada(dias: dict[str, dict], hoy: str, config: dict) -> dict:
    """El brief más reciente. Si el de hoy aún no está (corrida de las 00:30), se muestra el de ayer
    y se avisa; además se cuenta cuántas noticias de hoy hay fuera del brief."""
    con_brief = [f for f in sorted(dias, reverse=True) if dias[f].get("brief") and f <= hoy]
    fecha = con_brief[0] if con_brief else None
    brief = contenido_brief(dias[fecha], dias) if fecha else None
    en_brief = {n["id"] for n in (brief or {}).get("noticias", [])}
    hoy_fuera = [n for n in dias.get(hoy, {"noticias": []})["noticias"] if n["id"] not in en_brief]
    return {"fecha": fecha, "es_hoy": fecha == hoy, "brief": brief, "hoy": hoy,
            "minutos": minutos_lectura(brief, config["sitio"]["palabras_por_minuto"]),
            "hoy_fuera": len(hoy_fuera), "hay_hoy": hoy in dias}


def noticias_recientes(dias: dict[str, dict], hoy: str, cantidad_dias: int) -> list[dict]:
    """Las noticias de los últimos `cantidad_dias` días, de la más nueva a la más vieja."""
    desde = (date.fromisoformat(hoy) - timedelta(days=cantidad_dias - 1)).isoformat()
    recientes = []
    for fecha in sorted(dias, reverse=True):
        if desde <= fecha <= hoy:
            recientes += reversed(dias[fecha]["noticias"])  # dentro del día se fueron sumando al final
    return recientes


def espectro(noticias: list[dict], fecha: str | None = None) -> list[dict]:
    """Una línea por noticia para la banda del "espectro": la banda se divide en una franja por sección
    (en el orden de SECCIONES) y las noticias de una misma sección se reparten dentro de su franja.
    `x` es la posición en % del ancho; un pequeño corrimiento fijo por noticia evita que parezca un
    código de barras. Con `fecha`, las noticias de otro día (las "de ayer" del brief) se marcan."""
    ancho = 100 / len(SECCIONES)
    lineas = []
    for k, seccion in enumerate(SECCIONES):
        grupo = [n for n in noticias if n["seccion"] == seccion]
        paso = min(ancho * 0.72 / (len(grupo) - 1), 2.4) if len(grupo) > 1 else 0
        for j, n in enumerate(grupo):
            corrimiento = (sum(map(ord, n["id"])) % 11 - 5) / 10 * paso * 0.5
            x = (k + 0.5) * ancho + (j - (len(grupo) - 1) / 2) * paso + corrimiento
            lineas.append({"id": n["id"], "seccion": seccion, "x": round(x, 2), "titulo": n["titulo"],
                           "alta": n["importancia"] == "alta", "etiquetas": n.get("etiquetas", []),
                           "de_ayer": bool(fecha) and n["fecha"] != fecha})
    for i, linea in enumerate(lineas):
        linea["i"] = i
    return lineas


def ilustracion(id_noticia: str, cantidad: int = 9) -> list[dict]:
    """Ilustración propia para una noticia sin foto: líneas del color de su sección en posiciones y
    alturas sacadas del id (siempre las mismas para la misma noticia, distintas entre noticias)."""
    bytes_ = hashlib.sha1(id_noticia.encode()).digest()
    return [{"x": round(6 + bytes_[i] / 255 * 88, 1), "h": round(30 + bytes_[i + 9] / 255 * 62),
             "o": round(.45 + bytes_[i + 4] / 255 * .55, 2), "doble": bytes_[i + 2] > 215}
            for i in range(cantidad)]


def etiquetas_frecuentes(noticias: list[dict], maximo: int = MAX_ETIQUETAS_FILTRO) -> list[tuple[str, int]]:
    cuenta = Counter(e for n in noticias for e in n.get("etiquetas", []))
    return sorted(cuenta.items(), key=lambda par: (-par[1], par[0]))[:maximo]


# --- Generar ---

def entorno() -> Environment:
    env = Environment(loader=FileSystemLoader(CARPETA_PLANTILLAS), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals.update(NOMBRES_SECCION=NOMBRES_SECCION, SECCIONES=SECCIONES, espectro=espectro,
                       ilustracion=ilustracion)
    env.filters.update(fecha_larga=fecha_larga, fecha_corta=fecha_corta)
    return env


@dataclass
class Generado:
    paginas: list[Path]
    noticias: int
    portada: dict


def generar_sitio(config: dict, ahora: datetime, datos: Path = CARPETA_DATOS,
                  destino: Path = CARPETA_SITIO) -> Generado:
    """Arma el sitio en una carpeta temporal y recién al final reemplaza `destino`:
    si algo falla a mitad de camino, el sitio anterior queda intacto."""
    dias = cargar_dias(datos)
    hoy = hoy_chile(ahora, config)
    env = entorno()
    temporal = destino.with_name(destino.name + ".tmp")
    shutil.rmtree(temporal, ignore_errors=True)
    (temporal / "archivo").mkdir(parents=True)
    paginas = []

    def escribir(ruta: str, plantilla: str, **contexto):
        destino_pagina = temporal / ruta
        raiz = "../" * ruta.count("/")
        destino_pagina.write_text(env.get_template(plantilla).render(raiz=raiz, **contexto), encoding="utf-8")
        paginas.append(destino_pagina)

    ultimo = dias[max(dias)] if dias else None
    comun = {"actualizado": hora_actualizado(ultimo)}

    portada = datos_portada(dias, hoy, config)
    escribir("index.html", "index.html", pagina="hoy", p=portada, **comun)

    recientes = noticias_recientes(dias, hoy, config["sitio"]["dias_secciones"])
    cuenta_secciones = Counter(n["seccion"] for n in recientes)
    escribir("secciones.html", "secciones.html", pagina="secciones", noticias=recientes,
             dias=config["sitio"]["dias_secciones"], cuenta_secciones=cuenta_secciones,
             etiquetas=etiquetas_frecuentes(recientes), altas=sum(n["importancia"] == "alta" for n in recientes),
             **comun)

    resumen_dias = [{"fecha": f, "noticias": len(dias[f]["noticias"]), "brief": bool(dias[f].get("brief")),
                     "lineas": espectro(dias[f]["noticias"])}
                    for f in sorted(dias, reverse=True)]
    escribir("archivo/index.html", "archivo.html", pagina="archivo", dias=resumen_dias, **comun)
    fechas = sorted(dias)
    for i, fecha in enumerate(fechas):
        dia = dias[fecha]
        escribir(f"archivo/{fecha}.html", "dia.html", pagina="archivo", fecha=fecha,
                 brief=contenido_brief(dia, dias), noticias=orden_importancia(dia["noticias"]),
                 anterior=fechas[i - 1] if i > 0 else None,
                 siguiente=fechas[i + 1] if i + 1 < len(fechas) else None, **comun)

    for archivo in ARCHIVOS_ESTATICOS:
        shutil.copy(CARPETA_PLANTILLAS / archivo, temporal / archivo)
    shutil.rmtree(destino, ignore_errors=True)
    temporal.replace(destino)
    paginas = [destino / p.relative_to(temporal) for p in paginas]
    return Generado(paginas, sum(len(d["noticias"]) for d in dias.values()), portada)


# --- Revisar links ---

PATRON_HREF = re.compile(r'\b(?:href|src)="([^"]+)"')
PATRON_SOLO_HREF = re.compile(r'\bhref="([^"]+)"')


def links_de(pagina: Path, patron: re.Pattern = PATRON_HREF) -> list[str]:
    return [html.unescape(h) for h in patron.findall(pagina.read_text(encoding="utf-8"))]


def links_internos_rotos(sitio: Path) -> list[str]:
    """Links entre páginas del sitio que apuntan a un archivo que no existe (sin red)."""
    rotos = []
    for pagina in sorted(sitio.rglob("*.html")):
        for href in links_de(pagina):
            partes = urlsplit(href)
            if partes.scheme or href.startswith("#"):
                continue
            objetivo = (pagina.parent / partes.path).resolve()
            if objetivo.is_dir():
                objetivo = objetivo / "index.html"
            if not objetivo.exists():
                rotos.append(f"{pagina.relative_to(sitio)} → {href}")
    return rotos


def links_externos(sitio: Path) -> list[str]:
    """Todos los links a otros sitios (las fuentes), sin repetir, en orden de aparición. Las fotos de
    las noticias no cuentan: si una no carga, el sitio muestra la ilustración propia."""
    vistos = {}
    for pagina in sorted(sitio.rglob("*.html")):
        for href in links_de(pagina, PATRON_SOLO_HREF):
            if href.startswith(("https://", "http://")):
                vistos.setdefault(href, None)
    return list(vistos)


@dataclass
class EstadoLink:
    url: str
    estado: str  # OK | AVISO | ERROR
    detalle: str = ""


# Responden, pero a un programa no lo dejan pasar (protección anti-robots): el link existe.
CODIGOS_BLOQUEO = {401, 403, 429, 999}


def probar_link(url: str, cliente: httpx.Client) -> EstadoLink:
    """GET sin descargar la página entera. Nunca lanza excepciones."""
    try:
        with cliente.stream("GET", url) as r:
            codigo = r.status_code
    except httpx.TimeoutException:
        return EstadoLink(url, "ERROR", "no respondió a tiempo")
    except httpx.HTTPError as e:
        return EstadoLink(url, "ERROR", f"error de conexión ({type(e).__name__})")
    if codigo < 400:
        return EstadoLink(url, "OK", f"HTTP {codigo}")
    if codigo in CODIGOS_BLOQUEO:
        return EstadoLink(url, "AVISO", f"HTTP {codigo} (el sitio existe pero bloquea a los programas)")
    return EstadoLink(url, "ERROR", f"HTTP {codigo}")


def revisar_links(urls: list[str], config: dict, cliente: httpx.Client | None = None) -> list[EstadoLink]:
    with cliente or crear_cliente(config) as c, ThreadPoolExecutor(config["fuentes"]["hilos"]) as hilos:
        return list(hilos.map(lambda u: probar_link(u, c), urls))


# --- Comando ---

def comando_sitio(args) -> int:
    config = cargar_config()
    ahora = datetime.now(timezone.utc)
    generado = generar_sitio(config, ahora)
    p = generado.portada
    print(f"Sitio generado en {CARPETA_SITIO.relative_to(RAIZ)}/: {len(generado.paginas)} páginas, "
          f"{generado.noticias} noticias en total.")
    if p["brief"]:
        cual = "de hoy" if p["es_hoy"] else f"del {p['fecha']} (el de hoy todavía no está armado)"
        print(f"Portada: brief {cual}, {len(p['brief']['noticias'])} noticias, lectura ~{p['minutos']} min.")
    else:
        print("Portada: todavía no hay brief.")
    print(f"Abrir en el navegador: {(CARPETA_SITIO / 'index.html').as_uri()}")

    codigo = 0
    rotos = links_internos_rotos(CARPETA_SITIO)
    print("\nLinks entre páginas: " + ("OK" if not rotos else f"{len(rotos)} ROTOS"))
    for r in rotos:
        print(f"  ! {r}")
        codigo = 1

    if args.revisar_links:
        urls = links_externos(CARPETA_SITIO)
        print(f"\nRevisando {len(urls)} links a las fuentes...")
        estados = revisar_links(urls, config)
        for e in estados:
            if e.estado != "OK":
                print(f"  {e.estado:5}  {e.url}\n         {e.detalle}")
        cuenta = Counter(e.estado for e in estados)
        print(f"{len(estados)} links: {cuenta['OK']} OK · {cuenta['AVISO']} con aviso · {cuenta['ERROR']} con error")
        if cuenta["ERROR"]:
            codigo = 1
    return codigo
