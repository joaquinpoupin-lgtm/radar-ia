"""Resumir con IA: lotes de noticias → prompt → respuesta validada contra el esquema del brief (sección 7).

La IA solo escribe el texto. El id, la fecha, los links (`fuentes`) y `confirmacion` los pone este código
a partir de los grupos, para que ningún link sea inventado.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

import httpx

from radar.agrupar import Grupo, agrupar, resumen_agrupacion
from radar.almacen import guardar_corrida
from radar.config import RAIZ, cargar_config
from radar.filtrar import cargar_pendientes, cargar_procesados, hoy_chile, prefiltrar, publicadas_hoy, sumar_pendientes
from radar.fuentes import ErrorFuentes, cargar_fuentes
from radar.ia import IANoDisponible, pedir_json
from radar.recolectar import recolectar

RUTA_PROMPT = RAIZ / "prompts" / "resumen.md"
SECCIONES = ("modelos", "herramientas", "tendencias", "creadores", "dinero", "tips")
IMPORTANCIAS = ("alta", "normal")
CAMPOS_TEXTO = ("titulo", "que_paso", "por_que_importa")
MAX_ETIQUETAS = 4


def entrada_ia(n: int, grupo: Grupo) -> dict:
    """Lo que ve la IA de cada noticia: solo título, extracto corto y de dónde viene (sin links)."""
    p = grupo.principal
    datos = {"n": n, "titulo": p.titulo, "fuente": p.fuente, "tipo": p.tipo, "sitio": urlparse(p.url).netloc,
             "seccion_sugerida": p.seccion, "idioma": p.idioma, "extracto": p.extracto}
    # Lo que cuentan las otras fuentes de la misma noticia (a veces traen datos que la principal no tiene).
    otras = [{"fuente": c.fuente, "titulo": c.titulo, "extracto": c.extracto}
             for c in grupo.candidatos[1:] if c.extracto and c.extracto != p.extracto]
    if otras:
        datos["otras_fuentes"] = otras
    if grupo.confirmacion > 1:
        datos["fuentes_que_la_cuentan"] = grupo.confirmacion
    return datos


def armar_prompt(grupos: list[Grupo], plantilla: str) -> str:
    noticias = [entrada_ia(n, g) for n, g in enumerate(grupos, 1)]
    return plantilla.replace("{{NOTICIAS}}", json.dumps(noticias, ensure_ascii=False, indent=1))


def _texto(valor) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def validar_respuesta(datos: dict, cantidad: int) -> None:
    """Revisa que la IA respondió una entrada válida por cada noticia del lote. Lanza ValueError si no."""
    items = datos.get("noticias")
    if not isinstance(items, list):
        raise ValueError("falta la lista 'noticias'")
    por_n = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("n"), int) or not 1 <= item["n"] <= cantidad:
            raise ValueError("una entrada no tiene un 'n' válido")
        if item["n"] in por_n:
            raise ValueError(f"la noticia {item['n']} viene dos veces")
        por_n[item["n"]] = item
    faltan = sorted(set(range(1, cantidad + 1)) - set(por_n))
    if faltan:
        raise ValueError(f"faltan las noticias {faltan}")

    for n, item in por_n.items():
        if item.get("descartar") is True:
            continue
        if "misma_que" in item:
            otra = por_n.get(item["misma_que"])
            if otra is None or item["misma_que"] == n or otra.get("descartar") is True or "misma_que" in otra:
                raise ValueError(f"la noticia {n} se une a una que no está resumida")
            continue
        for campo in CAMPOS_TEXTO:
            if not _texto(item.get(campo)):
                raise ValueError(f"a la noticia {n} le falta '{campo}'")
        if item.get("seccion") not in SECCIONES:
            raise ValueError(f"la noticia {n} tiene una sección inválida")
        if item.get("importancia") not in IMPORTANCIAS:
            raise ValueError(f"la noticia {n} tiene una importancia inválida")
        terminos = item.get("terminos", [])
        if not isinstance(terminos, list) or not all(
                isinstance(t, dict) and _texto(t.get("termino")) and _texto(t.get("explicacion")) for t in terminos):
            raise ValueError(f"la noticia {n} tiene 'terminos' mal formados")
        etiquetas = item.get("etiquetas", [])
        if not isinstance(etiquetas, list) or not all(_texto(e) for e in etiquetas):
            raise ValueError(f"la noticia {n} tiene 'etiquetas' mal formadas")


def noticia(grupo: Grupo, item: dict, hoy: str) -> dict:
    """Esquema de la sección 7 del brief. Texto de la IA; id, fecha, fuentes y confirmación del código."""
    etiquetas = []
    for e in item.get("etiquetas", []):
        e = e.strip().lower()
        if e not in etiquetas:
            etiquetas.append(e)
    return {
        "id": grupo.id,
        "fecha": hoy,
        "titulo": item["titulo"].strip(),
        "que_paso": item["que_paso"].strip(),
        "por_que_importa": item["por_que_importa"].strip(),
        "seccion": item["seccion"],
        "importancia": item["importancia"],
        "terminos": [{"termino": t["termino"].strip(), "explicacion": t["explicacion"].strip()}
                     for t in item.get("terminos", [])],
        "etiquetas": etiquetas[:MAX_ETIQUETAS],
        "fuentes": grupo.fuentes,
        "confirmacion": grupo.confirmacion,
    }


@dataclass
class Resultado:
    noticias: list[dict] = field(default_factory=list)
    descartadas: list[tuple[Grupo, str]] = field(default_factory=list)  # (grupo, motivo)
    unidas: int = 0                                  # noticias que la IA juntó con otra del mismo lote
    procesados: list[Grupo] = field(default_factory=list)  # todo lo que la IA ya vio (para la caché)
    fallidos: list[Grupo] = field(default_factory=list)    # la IA no respondió: quedan pendientes
    errores: list[str] = field(default_factory=list)


def procesar_lote(grupos: list[Grupo], datos: dict, hoy: str, r: Resultado) -> None:
    por_n = {item["n"]: item for item in datos["noticias"]}
    # Los que la IA marcó como "la misma noticia" suman sus links al grupo que sí se resume.
    combinados = {n: list(g.candidatos) for n, g in enumerate(grupos, 1)}
    for n, item in por_n.items():
        if "misma_que" in item and item.get("descartar") is not True:
            combinados[item["misma_que"]] += grupos[n - 1].candidatos
            r.unidas += 1
    for n, grupo in enumerate(grupos, 1):
        item = por_n[n]
        if item.get("descartar") is True:
            r.descartadas.append((grupo, str(item.get("motivo") or "sin motivo")))
        elif "misma_que" not in item:
            r.noticias.append(noticia(Grupo(grupo.id, combinados[n]), item, hoy))
    r.procesados += grupos


def resumir(grupos: list[Grupo], config: dict, cliente: httpx.Client, hoy: str,
            pedir: Callable = pedir_json, plantilla: str | None = None) -> Resultado:
    """Manda los grupos en lotes de `tamano_lote`. Si la IA no está disponible, ese lote y los que
    siguen quedan en `fallidos` (no se gastan más intentos en esta corrida)."""
    plantilla = plantilla or RUTA_PROMPT.read_text(encoding="utf-8")
    tamano = config["limites"]["tamano_lote"]
    r = Resultado()
    for i in range(0, len(grupos), tamano):
        lote = grupos[i:i + tamano]
        if r.errores:
            r.fallidos += lote
            continue
        try:
            datos = pedir(armar_prompt(lote, plantilla), config, cliente,
                          validar=lambda d, n=len(lote): validar_respuesta(d, n))
        except IANoDisponible as e:
            r.errores.append(str(e))
            r.fallidos += lote
            continue
        procesar_lote(lote, datos, hoy, r)
    return r


def texto_resultado(r: Resultado) -> str:
    """Los resúmenes como se leerían, para revisarlos en la terminal."""
    lineas = []
    for i, n in enumerate(r.noticias, 1):
        fuego = "🔥 " if n["importancia"] == "alta" else ""
        lineas.append(f"{i}. {fuego}[{n['seccion']}] {n['titulo']}")
        lineas.append(f"   Qué pasó: {n['que_paso']}")
        lineas.append(f"   Por qué importa: {n['por_que_importa']}")
        for t in n["terminos"]:
            lineas.append(f"   · {t['termino']}: {t['explicacion']}")
        if n["etiquetas"]:
            lineas.append(f"   Etiquetas: {', '.join(n['etiquetas'])}")
        for f in n["fuentes"]:
            lineas.append(f"   → {f['nombre']}: {f['url']}")
        lineas.append("")
    if r.descartadas:
        lineas.append(f"Descartadas por la IA ({len(r.descartadas)}):")
        lineas += [f"  - {g.titulo[:80]} — {motivo}" for g, motivo in r.descartadas]
    if r.unidas:
        lineas.append(f"Unidas con otra del mismo lote: {r.unidas}")
    if r.fallidos:
        lineas.append(f"Quedaron pendientes (la IA no respondió): {len(r.fallidos)}")
        lineas += [f"  ! {e}" for e in r.errores]
    return "\n".join(lineas).rstrip()


def comando_resumir(args) -> int:
    """Recolecta, elige como en una corrida y resume. Sin --guardar es una prueba del prompt (no toca nada);
    con --guardar suma las noticias a data/AAAA-MM-DD.json y actualiza la caché y los pendientes."""
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
    grupos = agrupar(recoleccion.candidatos, config["limites"]["similitud_titulos"])
    print(resumen_agrupacion(recoleccion.candidatos, grupos))
    pendientes = cargar_pendientes()
    elegidas = prefiltrar(sumar_pendientes(grupos, pendientes), cargar_procesados(), config, ahora,
                          publicadas_hoy(hoy), pendientes).elegidas
    if not elegidas:
        print("0 noticias nuevas: no hay nada que resumir.")
        return 0
    aviso = "se guardan en data/" if args.guardar else "no se guarda nada; es una prueba"
    print(f"Resumiendo {len(elegidas)} noticias con la IA ({aviso})...\n")
    with httpx.Client(timeout=config["ia"]["timeout_seg"]) as cliente:
        resultado = resumir([g for g, _ in elegidas], config, cliente, hoy)
    print(texto_resultado(resultado))
    if args.json:
        print("\n" + json.dumps(resultado.noticias, ensure_ascii=False, indent=1))
    if args.guardar:
        agregadas = guardar_corrida(resultado, pendientes, config, ahora)
        print(f"\nGuardado: {agregadas} noticias en data/{hoy}.json · {len(resultado.procesados)} a la caché"
              f" · {len(resultado.fallidos)} pendientes nuevas")
    return 1 if resultado.fallidos else 0
