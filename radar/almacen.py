"""El día y su brief: data/AAAA-MM-DD.json (hora de Chile) y "Lo más importante hoy".

Formato del archivo del día:
    {"fecha": "AAAA-MM-DD", "actualizado": "...-03:00",
     "brief": null | {"lo_mas_importante": ["...", "...", "..."], "ids": ["a1b2c3d4e5f6", ...]},
     "noticias": [ {esquema de la sección 7 del brief} ]}
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from radar.config import RAIZ, cargar_config
from radar.filtrar import (CARPETA_DATOS, actualizar_pendientes, cargar_procesados, guardar_pendientes,
                           guardar_procesados, hoy_chile, marcar_procesados)
from radar.ia import IANoDisponible, pedir_json

RUTA_PROMPT_BRIEF = RAIZ / "prompts" / "brief.md"
MAX_BULLETS = 3  # "Lo más importante hoy" en 3 bullets (menos si el brief tiene menos noticias)
MAX_LARGO_BULLET = 300  # caracteres; un bullet más largo ya no se lee de un vistazo


# --- Archivo del día ---

def ruta_dia(fecha: str, carpeta: Path = CARPETA_DATOS) -> Path:
    return carpeta / f"{fecha}.json"


def dia_vacio(fecha: str) -> dict:
    return {"fecha": fecha, "actualizado": None, "brief": None, "noticias": []}


def cargar_dia(fecha: str, carpeta: Path = CARPETA_DATOS) -> dict:
    """Si el archivo no existe, un día vacío. Si está dañado, se guarda aparte (para no perder lo publicado
    al sobrescribirlo) y se parte de un día vacío: la corrida nunca se cae por esto."""
    ruta = ruta_dia(fecha, carpeta)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or not isinstance(datos.get("noticias"), list):
            raise ValueError("no tiene la lista 'noticias'")
        return {**dia_vacio(fecha), **datos}
    except FileNotFoundError:
        return dia_vacio(fecha)
    except (ValueError, OSError) as e:
        respaldo = ruta.with_name(f"{fecha}.danado.json")
        ruta.replace(respaldo)
        print(f"Aviso: {ruta.name} estaba dañado ({type(e).__name__}); se guardó como {respaldo.name} "
              "y se parte con el día vacío.")
        return dia_vacio(fecha)


def guardar_dia(dia: dict, ahora: datetime, config: dict, carpeta: Path = CARPETA_DATOS) -> Path:
    """Escribe primero a un archivo temporal y después lo reemplaza: nunca queda un JSON a medias."""
    dia["actualizado"] = ahora.astimezone(ZoneInfo(config["zona_horaria"])).isoformat(timespec="seconds")
    ruta = ruta_dia(dia["fecha"], carpeta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(dia, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporal.replace(ruta)
    return ruta


def tiene_link(noticia: dict) -> bool:
    return any(str(f.get("url", "")).startswith(("https://", "http://")) for f in noticia.get("fuentes", []))


def agregar_noticias(dia: dict, noticias: list[dict]) -> int:
    """Suma las noticias nuevas al día (sin repetir id; ninguna sin link). Devuelve cuántas entraron."""
    ids = {n["id"] for n in dia["noticias"]}
    agregadas = 0
    for n in noticias:
        if n["id"] in ids or not tiene_link(n):
            continue
        dia["noticias"].append(n)
        ids.add(n["id"])
        agregadas += 1
    return agregadas


def guardar_corrida(resultado, pendientes_anteriores: list, config: dict, ahora: datetime,
                    carpeta: Path = CARPETA_DATOS) -> int:
    """Después de la IA: noticias al día de hoy, lo que la IA vio a la caché (nunca se resume dos veces)
    y lo que no pudo procesar a pendientes. Devuelve cuántas noticias se agregaron al día."""
    hoy = hoy_chile(ahora, config)
    dia = cargar_dia(hoy, carpeta)
    agregadas = agregar_noticias(dia, resultado.noticias)
    guardar_dia(dia, ahora, config, carpeta)
    ruta_cache = carpeta / "cache" / "procesados.json"
    procesados = cargar_procesados(ruta_cache)
    marcar_procesados(procesados, resultado.procesados, hoy)
    guardar_procesados(procesados, hoy, config["cache"]["dias"], ruta_cache)
    guardar_pendientes(actualizar_pendientes(pendientes_anteriores, resultado.fallidos, procesados, config, ahora),
                       ahora, carpeta / "pendientes.json")
    return agregadas


# --- Brief del día ---

def fecha_anterior(fecha: str) -> str:
    return (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()


def toca_brief(dia: dict, ahora: datetime, config: dict) -> bool:
    """El brief lo arma la primera corrida del día después de `brief.hora_desde` (hora de Chile)."""
    local = ahora.astimezone(ZoneInfo(config["zona_horaria"]))
    return dia["brief"] is None and local.time() >= time.fromisoformat(config["brief"]["hora_desde"])


def candidatas_brief(dia: dict, anterior: dict) -> list[dict]:
    """Las de hoy + las de ayer que no entraron en el brief de ayer (las de la tarde y la noche)."""
    ya_en_brief = set((anterior.get("brief") or {}).get("ids", []))
    return dia["noticias"] + [n for n in anterior["noticias"] if n["id"] not in ya_en_brief]


def elegir_brief(candidatas: list[dict], maximo: int) -> list[dict]:
    """🔥 primero, después las que cuentan más fuentes; a igualdad, las de hoy antes que las de ayer."""
    orden = sorted(candidatas, key=lambda n: (n["importancia"] != "alta", -n.get("confirmacion", 1)))
    return orden[:maximo]


def cantidad_bullets(noticias: list) -> int:
    return min(MAX_BULLETS, len(noticias))


def armar_prompt_brief(noticias: list[dict], plantilla: str) -> str:
    resumen = [{"titulo": n["titulo"], "que_paso": n["que_paso"], "por_que_importa": n["por_que_importa"],
                "importancia": n["importancia"]} for n in noticias]
    return (plantilla.replace("{{CANTIDAD}}", str(cantidad_bullets(noticias)))
            .replace("{{NOTICIAS}}", json.dumps(resumen, ensure_ascii=False, indent=1)))


def validar_bullets(datos: dict, cantidad: int) -> None:
    bullets = datos.get("lo_mas_importante")
    if not isinstance(bullets, list) or len(bullets) != cantidad:
        raise ValueError(f"'lo_mas_importante' debe ser una lista de {cantidad} frases")
    for b in bullets:
        if not isinstance(b, str) or not b.strip():
            raise ValueError("hay un bullet vacío")
        if len(b) > MAX_LARGO_BULLET:
            raise ValueError("hay un bullet demasiado largo")


def pedir_bullets(noticias: list[dict], config: dict, cliente: httpx.Client,
                  pedir: Callable = pedir_json, plantilla: str | None = None) -> list[str]:
    """Una llamada extra a la IA. Lanza IANoDisponible si no responde."""
    plantilla = plantilla or RUTA_PROMPT_BRIEF.read_text(encoding="utf-8")
    cantidad = cantidad_bullets(noticias)
    datos = pedir(armar_prompt_brief(noticias, plantilla), config, cliente,
                  validar=lambda d: validar_bullets(d, cantidad))
    return [b.strip() for b in datos["lo_mas_importante"]]


def noticias_por_id(dia: dict, anterior: dict) -> dict[str, dict]:
    return {n["id"]: n for n in anterior["noticias"] + dia["noticias"]}


def actualizar_brief(dia: dict, anterior: dict, ahora: datetime, config: dict, cliente: httpx.Client,
                     pedir: Callable = pedir_json, forzar: bool = False) -> str:
    """Arma el brief si toca (o si `forzar`) y completa los bullets que falten. Devuelve qué hizo.

    Si la IA no responde, el brief queda con sus noticias pero sin bullets, y se reintentan en la corrida
    siguiente. Sin noticias no se arma: se vuelve a intentar en la próxima corrida.
    """
    if forzar or toca_brief(dia, ahora, config):
        elegidas = elegir_brief(candidatas_brief(dia, anterior), config["limites"]["max_brief"])
        if not elegidas:
            dia["brief"] = None
            return "sin noticias todavía: el brief se arma en la próxima corrida"
        dia["brief"] = {"lo_mas_importante": [], "ids": [n["id"] for n in elegidas]}
        hecho = f"brief armado con {len(elegidas)} noticias"
    elif dia["brief"] is not None and not dia["brief"]["lo_mas_importante"]:
        hecho = "brief ya armado; faltaban los bullets"
    else:
        return "brief ya completo" if dia["brief"] else "todavía no toca armar el brief"

    por_id = noticias_por_id(dia, anterior)
    try:
        dia["brief"]["lo_mas_importante"] = pedir_bullets(
            [por_id[i] for i in dia["brief"]["ids"] if i in por_id], config, cliente, pedir)
    except IANoDisponible as e:
        return f"{hecho}, sin bullets (la IA no respondió; se reintentan en la próxima corrida): {e}"
    return f"{hecho} + {len(dia['brief']['lo_mas_importante'])} bullets"


def problemas_dia(dia: dict, anterior: dict, config: dict) -> list[str]:
    """Revisión del día antes de publicar. Lista vacía = todo bien."""
    problemas = []
    por_id = noticias_por_id(dia, anterior)
    brief = dia["brief"]
    revisar = dia["noticias"] + [por_id[i] for i in (brief or {}).get("ids", []) if i in por_id]
    for n in {n["id"]: n for n in revisar}.values():
        if not tiene_link(n):
            problemas.append(f"la noticia {n['id']} no tiene link")
    if len({n.get("id") for n in dia["noticias"]}) != len(dia["noticias"]):
        problemas.append("hay noticias repetidas")
    if len(dia["noticias"]) > config["limites"]["max_por_dia"]:
        problemas.append(f"hay más de {config['limites']['max_por_dia']} noticias en el día")
    if brief is not None:
        if len(brief["ids"]) > config["limites"]["max_brief"]:
            problemas.append(f"el brief tiene más de {config['limites']['max_brief']} ítems")
        faltan = [i for i in brief["ids"] if i not in por_id]
        if faltan:
            problemas.append(f"el brief apunta a noticias que no existen: {faltan}")
        if brief["lo_mas_importante"]:
            try:
                validar_bullets(brief, cantidad_bullets(brief["ids"]))
            except ValueError as e:
                problemas.append(f"bullets: {e}")
    return problemas


def texto_brief(dia: dict, anterior: dict) -> str:
    """El brief como se leería, para revisarlo en la terminal."""
    brief = dia["brief"]
    if brief is None:
        return f"Brief del {dia['fecha']}: todavía no está armado."
    lineas = [f"Brief del {dia['fecha']}", "", "Lo más importante hoy:"]
    lineas += [f"  • {b}" for b in brief["lo_mas_importante"]] or ["  (sin bullets todavía)"]
    lineas.append("")
    por_id = noticias_por_id(dia, anterior)
    for i, id_ in enumerate(brief["ids"], 1):
        n = por_id.get(id_)
        if n is None:
            lineas.append(f"{i}. (no encontrada: {id_})")
            continue
        fuego = "🔥 " if n["importancia"] == "alta" else ""
        ayer = " (de ayer)" if n["fecha"] != dia["fecha"] else ""
        lineas.append(f"{i}. {fuego}[{n['seccion']}] {n['titulo']}{ayer}")
        lineas += [f"   → {f['nombre']}: {f['url']}" for f in n["fuentes"]]
    return "\n".join(lineas)


def comando_brief(args) -> int:
    """Arma (o completa) el brief de hoy con lo que ya está guardado en data/ y lo revisa."""
    config = cargar_config()
    ahora = datetime.now(timezone.utc)
    hoy = hoy_chile(ahora, config)
    dia, anterior = cargar_dia(hoy), cargar_dia(fecha_anterior(hoy))
    print(f"Noticias guardadas: hoy ({hoy}) {len(dia['noticias'])} · ayer {len(anterior['noticias'])}")
    if args.forzar and dia["brief"] is not None:
        print("--forzar: se rehace el brief de hoy.")
    with httpx.Client(timeout=config["ia"]["timeout_seg"]) as cliente:
        hecho = actualizar_brief(dia, anterior, ahora, config, cliente, forzar=args.forzar)
    print(hecho.capitalize() + ".")
    if dia["noticias"] or dia["brief"] is not None:
        print(f"Guardado en {guardar_dia(dia, ahora, config).relative_to(RAIZ)}")
    print("\n" + texto_brief(dia, anterior))
    problemas = problemas_dia(dia, anterior, config)
    print("\nRevisión: " + ("OK (JSON válido, brief con ≤{} ítems, todos con link)".format(
        config["limites"]["max_brief"]) if not problemas else "PROBLEMAS"))
    for p in problemas:
        print(f"  ! {p}")
    return 1 if problemas else 0
