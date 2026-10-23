"""Corrida completa: recolectar → agrupar → filtrar → IA → guardar el día → brief → sitio.

Es lo que correrá GitHub Actions cuatro veces al día (Paso 12). Reglas:
- Una fuente caída o la IA sin responder no son fallas: se registran, lo pendiente queda guardado y la
  corrida termina bien (código 0).
- Si una etapa falla por algo inesperado (un error del programa), se avisa y se sigue con las demás:
  el sitio se genera igual con lo que ya está guardado. En ese caso el código de salida es 1.
"""

import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import httpx

from radar.agrupar import agrupar, resumen_agrupacion
from radar.almacen import (actualizar_brief, cargar_dia, fecha_anterior, guardar_corrida, guardar_dia,
                           problemas_dia)
from radar.config import cargar_config
from radar.filtrar import (CARPETA_DATOS, cargar_pendientes, cargar_procesados, hoy_chile, prefiltrar,
                           publicadas_hoy, sumar_pendientes)
from radar.fuentes import ErrorFuentes, Fuente, cargar_fuentes, topes_por_fuente
from radar.ia import pedir_json
from radar.recolectar import recolectar
from radar.resumir import resumir
from radar.simulacro import SIMULACROS, aplicar, cliente_ia, leer_simulacros
from radar.sitio import CARPETA_SITIO, generar_sitio, links_internos_rotos


@dataclass
class Corrida:
    """Lo que pasó en la corrida, para el resumen final y para decidir el código de salida."""
    avisos: list[str] = field(default_factory=list)   # cosas esperables (fuente caída, IA sin cuota)
    errores: list[str] = field(default_factory=list)  # fallas del programa o datos con problemas → código 1
    nuevas: int = 0
    pendientes: int = 0
    sitio: bool = False

    @property
    def codigo(self) -> int:
        return 1 if self.errores else 0


def _etapa(corrida: Corrida, nombre: str, funcion):
    """Corre una etapa; si explota, lo anota (con el detalle técnico en el log) y devuelve None."""
    print(f"\n== {nombre} ==")
    inicio = monotonic()
    try:
        resultado = funcion()
    except Exception as e:
        traceback.print_exc()
        corrida.errores.append(f"{nombre}: error inesperado ({type(e).__name__}: {e})")
        print(f"!! {nombre} falló; se sigue con lo demás.")
        return None
    print(f"   ({monotonic() - inicio:.1f} s)")
    return resultado


def correr(config: dict, ahora: datetime, fuentes: list[Fuente], datos: Path = CARPETA_DATOS,
           destino: Path = CARPETA_SITIO, cliente_red: httpx.Client | None = None,
           cliente_ia: httpx.Client | None = None, pedir=pedir_json, forzar_brief: bool = False) -> Corrida:
    corrida = Corrida()
    hoy = hoy_chile(ahora, config)
    ruta_pendientes = datos / "pendientes.json"

    def etapa_noticias():
        recoleccion = recolectar(fuentes, config, ahora, cliente_red)
        caidas = [i for i in recoleccion.informes if i.error]
        print(f"{len(recoleccion.candidatos)} candidatos de {len(fuentes)} fuentes · {len(caidas)} con error")
        for i in caidas:
            corrida.avisos.append(f"fuente {i.nombre}: {i.error}")
            print(f"   ! {i.nombre}: {i.error}")
        por_canal = [i.nombre for i in recoleccion.informes if i.desde_canal]
        if por_canal:
            print(f"   YouTube sin RSS, leído desde la página del canal: {', '.join(por_canal)}")
        if fuentes and len(caidas) == len(fuentes):
            corrida.errores.append("no se pudo leer ninguna fuente (¿sin internet?)")

        grupos = agrupar(recoleccion.candidatos, config["limites"]["similitud_titulos"])
        print(resumen_agrupacion(recoleccion.candidatos, grupos))
        pendientes = cargar_pendientes(ruta_pendientes)
        filtro = prefiltrar(sumar_pendientes(grupos, pendientes), cargar_procesados(datos / "cache" / "procesados.json"),
                            config, ahora, publicadas_hoy(hoy, datos), pendientes, topes_por_fuente(fuentes))
        elegidas = [g for g, _ in filtro.elegidas]
        print(f"Ya procesadas: {filtro.ya_procesadas} · nuevas: {filtro.nuevas}"
              + (f" (pendientes de antes: {filtro.pendientes})" if filtro.pendientes else "")
              + f" · para la IA: {len(elegidas)} (cupo {filtro.cupo})")
        if not elegidas:
            corrida.pendientes = len(pendientes)
            print("0 noticias nuevas para resumir.")
            return

        resultado = resumir(elegidas, config, ia, hoy, pedir)
        agregadas = guardar_corrida(resultado, pendientes, config, ahora, datos)
        corrida.nuevas = agregadas
        corrida.pendientes = len(cargar_pendientes(ruta_pendientes))
        print(f"IA: {len(resultado.noticias)} resumidas · {len(resultado.descartadas)} descartadas"
              f" · {resultado.unidas} unidas · {len(resultado.fallidos)} sin respuesta")
        print(f"Guardadas {agregadas} noticias en data/{hoy}.json · pendientes para la próxima: {corrida.pendientes}")
        for e in resultado.errores:
            corrida.avisos.append(f"IA: {e}")
            print(f"   ! la IA no respondió; quedan pendientes: {e}")

    def etapa_brief():
        dia, anterior = cargar_dia(hoy, datos), cargar_dia(fecha_anterior(hoy), datos)
        antes = repr(dia["brief"])
        hecho = actualizar_brief(dia, anterior, ahora, config, ia, pedir, forzar=forzar_brief)
        print(hecho.capitalize() + ".")
        if "sin bullets" in hecho:
            corrida.avisos.append("brief sin bullets: se completan en la próxima corrida")
        if repr(dia["brief"]) != antes:
            guardar_dia(dia, ahora, config, datos)
        for p in problemas_dia(dia, anterior, config):
            corrida.errores.append(f"revisión del día: {p}")
            print(f"   ! {p}")

    def etapa_sitio():
        generado = generar_sitio(config, ahora, datos, destino)
        p = generado.portada
        portada = (f"brief del {p['fecha']} ({len(p['brief']['noticias'])} noticias, ~{p['minutos']} min)"
                   if p["brief"] else "todavía sin brief")
        print(f"{len(generado.paginas)} páginas · {generado.noticias} noticias en total · portada: {portada}")
        for roto in links_internos_rotos(destino):
            corrida.errores.append(f"sitio: link roto {roto}")
        corrida.sitio = True

    with cliente_ia or httpx.Client(timeout=config["ia"]["timeout_seg"]) as ia:
        _etapa(corrida, "Noticias (recolectar, filtrar, resumir, guardar)", etapa_noticias)
        _etapa(corrida, "Brief del día", etapa_brief)
    _etapa(corrida, "Sitio", etapa_sitio)
    return corrida


def texto_final(corrida: Corrida, destino: Path) -> str:
    lineas = ["", "== Resumen ==",
              f"Noticias nuevas: {corrida.nuevas} · pendientes para la próxima corrida: {corrida.pendientes}"]
    if corrida.sitio:
        lineas.append(f"Sitio listo: {(destino / 'index.html').as_uri()}")
    if corrida.avisos:
        lineas.append(f"Avisos ({len(corrida.avisos)}, no detienen nada):")
        lineas += [f"  - {a}" for a in corrida.avisos]
    if corrida.errores:
        lineas.append(f"ERRORES ({len(corrida.errores)}):")
        lineas += [f"  ! {e}" for e in corrida.errores]
    lineas.append("Corrida terminada " + ("con errores." if corrida.errores else "bien."))
    return "\n".join(lineas)


def comando_correr(args) -> int:
    config = cargar_config()
    try:
        fuentes = cargar_fuentes()
    except ErrorFuentes as e:
        print(e)
        return 1
    try:
        simulacros = leer_simulacros(getattr(args, "simular", None))
    except ValueError as e:
        print(e)
        return 1
    fuentes = aplicar(simulacros, fuentes)
    ahora = datetime.now(timezone.utc)
    print(f"Radar IA · corrida del {hoy_chile(ahora, config)} · {len(fuentes)} fuentes")
    for s in simulacros:
        print(f"SIMULACRO {s}: {SIMULACROS[s]}")
    corrida = correr(config, ahora, fuentes, cliente_ia=cliente_ia(simulacros, config),
                     forzar_brief=args.forzar_brief)
    if simulacros:
        corrida.avisos.insert(0, f"simulacro activo: {', '.join(simulacros)}")
    print(texto_final(corrida, CARPETA_SITIO))
    return corrida.codigo

