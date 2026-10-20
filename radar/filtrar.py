"""Caché de lo ya procesado + pre-filtro sin IA: elige las pocas noticias nuevas que vale la pena resumir."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from radar.agrupar import Grupo, agrupar, resumen_agrupacion
from radar.config import RAIZ, cargar_config
from radar.fuentes import ErrorFuentes, cargar_fuentes
from radar.recolectar import Candidato, patron_ia, recolectar

CARPETA_DATOS = RAIZ / "data"
RUTA_PROCESADOS = CARPETA_DATOS / "cache" / "procesados.json"
RUTA_PENDIENTES = CARPETA_DATOS / "pendientes.json"
MAX_BONUS_CONFIRMACION = 3


def hoy_chile(ahora: datetime, config: dict) -> str:
    """El "día" del radar siempre es el de Chile (AAAA-MM-DD)."""
    return ahora.astimezone(ZoneInfo(config["zona_horaria"])).date().isoformat()


# --- Caché: {"<hash de un link>": "AAAA-MM-DD en que se procesó"} ---

def cargar_procesados(ruta: Path = RUTA_PROCESADOS) -> dict[str, str]:
    """Si el archivo no existe o está dañado se parte de cero (como mucho se repite una corrida, nunca se cae)."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        print(f"Aviso: no se pudo leer {ruta.name} ({type(e).__name__}); se parte con la caché vacía.")
        return {}
    return datos if isinstance(datos, dict) else {}


def guardar_procesados(procesados: dict[str, str], hoy: str, dias: int, ruta: Path = RUTA_PROCESADOS) -> None:
    """Guarda la caché borrando lo de más de `dias` días: esas noticias ya no pueden volver a aparecer."""
    limite = (date.fromisoformat(hoy) - timedelta(days=dias)).isoformat()
    vigentes = {h: f for h, f in procesados.items() if f >= limite}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(dict(sorted(vigentes.items())), indent=1) + "\n", encoding="utf-8")


def ya_procesado(grupo: Grupo, procesados: dict[str, str]) -> bool:
    # Se revisan todos los links: si el principal cambió (p. ej. salió de la ventana de días), igual se reconoce.
    return any(h in procesados for h in grupo.hashes)


def marcar_procesados(procesados: dict[str, str], grupos: list[Grupo], hoy: str) -> None:
    """Lo resumido o descartado por la IA no se vuelve a mandar nunca."""
    for g in grupos:
        for h in g.hashes:
            procesados[h] = hoy


# --- Pendientes: lo que la IA no pudo procesar se reintenta primero en la corrida siguiente ---

def cargar_pendientes(ruta: Path = RUTA_PENDIENTES) -> list[Grupo]:
    """Se guardan los candidatos completos (título, link, extracto corto): así se reintentan aunque ya no
    salgan en el feed. Si el archivo está dañado se avisa y se parte sin pendientes."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        grupos = []
        for g in datos["grupos"]:
            candidatos = [Candidato(**{**c, "fecha": datetime.fromisoformat(c["fecha"]) if c["fecha"] else None})
                          for c in g["candidatos"]]
            grupos.append(Grupo(g["id"], candidatos))
        return grupos
    except FileNotFoundError:
        return []
    except (ValueError, OSError, KeyError, TypeError) as e:
        print(f"Aviso: no se pudo leer {ruta.name} ({type(e).__name__}); se parte sin pendientes.")
        return []


def guardar_pendientes(grupos: list[Grupo], ahora: datetime, ruta: Path = RUTA_PENDIENTES) -> None:
    """Un candidato sin fecha queda con la de esta corrida, para que igual expire con la ventana de días."""
    datos = {"grupos": [{"id": g.id, "titulo": g.titulo,
                         "candidatos": [{**c.a_dict(), "fecha": (c.fecha or ahora).isoformat()}
                                        for c in g.candidatos]} for g in grupos]}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sumar_pendientes(grupos: list[Grupo], pendientes: list[Grupo]) -> list[Grupo]:
    """Junta lo recién recolectado con los pendientes. Si una noticia pendiente volvió a aparecer, se usa
    la versión nueva (puede traer más fuentes) y no se repite."""
    hashes_frescos = set().union(*(g.hashes for g in grupos)) if grupos else set()
    return grupos + [p for p in pendientes if not (p.hashes & hashes_frescos)]


def actualizar_pendientes(anteriores: list[Grupo], fallidos: list[Grupo], procesados: dict[str, str],
                          config: dict, ahora: datetime) -> list[Grupo]:
    """Pendientes para la próxima corrida: los que fallaron ahora + los anteriores que siguen sin procesar.
    Se olvidan los ya procesados y los que salieron de la ventana de días (ya no son noticia)."""
    desde = ahora - timedelta(days=config["limites"]["dias_antiguedad_max"])
    salida, vistos = [], set()
    for g in fallidos + anteriores:
        if g.hashes & vistos or ya_procesado(g, procesados) or (g.principal.fecha and g.principal.fecha < desde):
            continue
        vistos |= g.hashes
        salida.append(g)
    return salida


def publicadas_hoy(hoy: str, carpeta: Path = CARPETA_DATOS) -> int:
    """Noticias ya publicadas hoy (data/AAAA-MM-DD.json lo escribe el Paso 8)."""
    try:
        return len(json.loads((carpeta / f"{hoy}.json").read_text(encoding="utf-8"))["noticias"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return 0


# --- Pre-filtro ---

@lru_cache
def _patron_clave(palabras: tuple[str, ...]):
    return patron_ia(list(palabras))


def puntaje(grupo: Grupo, config: dict, ahora: datetime) -> float:
    """Peso de la fuente + bonus (más fuentes, HN, palabras clave) − castigo por antigüedad. Sin IA."""
    p = config["prefiltro"]
    total = max(c.peso for c in grupo.candidatos)
    total += min(grupo.confirmacion - 1, MAX_BONUS_CONFIRMACION) * p["bonus_por_fuente_extra"]
    puntos_hn = max((c.puntaje or 0 for c in grupo.candidatos), default=0)
    total += max((b for minimo, b in p["bonus_hn"].items() if puntos_hn >= minimo), default=0)
    if any(_patron_clave(tuple(p["palabras_clave"])).search(c.titulo) for c in grupo.candidatos):
        total += p["bonus_palabra_clave"]
    fecha = grupo.principal.fecha
    dias = (ahora - fecha).total_seconds() / 86400 if fecha else config["limites"]["dias_antiguedad_max"]
    return round(total - max(dias, 0) * p["castigo_por_dia"], 2)


@dataclass
class Prefiltro:
    elegidas: list[tuple[Grupo, float]] = field(default_factory=list)  # (grupo, puntaje), mejor primero
    ya_procesadas: int = 0
    viejas: int = 0
    nuevas: int = 0  # sin procesar y dentro de la ventana de días
    cupo: int = 0    # cuántas se podían mandar a la IA en esta corrida
    pendientes: int = 0  # de las nuevas, cuántas quedaron pendientes en una corrida anterior (van primero)


def prefiltrar(grupos: list[Grupo], procesados: dict[str, str], config: dict, ahora: datetime,
               publicadas: int = 0, pendientes: list[Grupo] = ()) -> Prefiltro:
    """Quita lo ya procesado y lo viejo, ordena por puntaje y respeta los topes por corrida, por día y por fuente.

    Lo que quedó pendiente en corridas anteriores (`pendientes`) va primero, antes que todo lo demás.
    """
    hashes_pendientes = set().union(*(p.hashes for p in pendientes)) if pendientes else set()
    limites = config["limites"]
    desde = ahora - timedelta(days=limites["dias_antiguedad_max"])
    r = Prefiltro(cupo=max(0, min(limites["max_nuevas_por_corrida"], limites["max_por_dia"] - publicadas)))
    candidatas = []
    for g in grupos:
        if ya_procesado(g, procesados):
            r.ya_procesadas += 1
        elif g.principal.fecha and g.principal.fecha < desde:
            r.viejas += 1
        else:
            candidatas.append((g, puntaje(g, config, ahora)))
    r.nuevas = len(candidatas)

    # Pendientes primero; después por puntaje (estable: a igual puntaje, el orden de llegada).
    candidatas.sort(key=lambda x: (not (x[0].hashes & hashes_pendientes), -x[1]))
    r.pendientes = sum(bool(g.hashes & hashes_pendientes) for g, _ in candidatas)
    por_fuente: dict[str, int] = {}
    for g, p in candidatas:
        if len(r.elegidas) >= r.cupo:
            break
        fuente = g.principal.fuente
        if por_fuente.get(fuente, 0) < config["prefiltro"]["max_por_fuente"]:
            por_fuente[fuente] = por_fuente.get(fuente, 0) + 1
            r.elegidas.append((g, p))
    return r


def informe(r: Prefiltro) -> str:
    lineas = [f"Ya procesadas antes: {r.ya_procesadas} · más viejas que la ventana: {r.viejas}"
              f" · nuevas: {r.nuevas}" + (f" (pendientes de antes: {r.pendientes})" if r.pendientes else "")]
    if not r.nuevas:
        lineas.append("0 noticias nuevas: no hay nada que mandar a la IA.")
    elif not r.cupo:
        lineas.append("Ya se llegó al tope de noticias publicadas hoy: no se manda nada a la IA.")
    else:
        lineas.append(f"Para la IA en esta corrida: {len(r.elegidas)} (cupo {r.cupo})\n")
        for g, p in r.elegidas:
            extra = f" (+{g.confirmacion - 1} fuente{'s' if g.confirmacion > 2 else ''})" if g.confirmacion > 1 else ""
            lineas.append(f"  {p:5.2f}  {g.principal.fuente[:16]:16}  {g.titulo[:80]}{extra}")
    return "\n".join(lineas)


def comando_filtrar(args) -> int:
    config = cargar_config()
    try:
        fuentes = cargar_fuentes()
    except ErrorFuentes as e:
        print(e)
        return 1
    ahora = datetime.now(timezone.utc)
    hoy = hoy_chile(ahora, config)
    print(f"Recolectando de {len(fuentes)} fuentes...")
    recoleccion = recolectar(fuentes, config, ahora)
    for i in recoleccion.informes:
        if i.error:
            print(f"  {i.nombre}: ERROR {i.error}")
    grupos = agrupar(recoleccion.candidatos, config["limites"]["similitud_titulos"])
    print(resumen_agrupacion(recoleccion.candidatos, grupos))

    procesados = cargar_procesados()
    pendientes = cargar_pendientes()
    publicadas = publicadas_hoy(hoy)
    print(f"Publicadas hoy ({hoy}): {publicadas} de {config['limites']['max_por_dia']}")
    resultado = prefiltrar(sumar_pendientes(grupos, pendientes), procesados, config, ahora, publicadas, pendientes)
    print(informe(resultado))

    if args.marcar and resultado.elegidas:
        marcar_procesados(procesados, [g for g, _ in resultado.elegidas], hoy)
        guardar_procesados(procesados, hoy, config["cache"]["dias"])
        print(f"\nSimulación: {len(resultado.elegidas)} marcadas como procesadas en "
              f"{RUTA_PROCESADOS.relative_to(RAIZ)} (como si la IA ya las hubiera resumido).")
    return 0 if any(not i.error for i in recoleccion.informes) else 1
