"""Paso 8: guardar el día y armar el brief (sin red: la IA es una función falsa)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from radar.agrupar import agrupar
from radar.almacen import (RUTA_PROMPT_BRIEF, actualizar_brief, agregar_noticias, armar_prompt_brief,
                           candidatas_brief, cargar_dia, dia_vacio, elegir_brief, guardar_corrida, guardar_dia,
                           problemas_dia, texto_brief, toca_brief, validar_bullets)
from radar.config import cargar_config
from radar.filtrar import cargar_pendientes, cargar_procesados, publicadas_hoy
from radar.ia import IANoDisponible
from radar.recolectar import Candidato
from radar.resumir import Resultado

CONFIG = cargar_config()
CONFIG["brief"]["hora_desde"] = "06:00"  # fija la hora para probar el corte, aunque config.yaml use otra
# 06:31 en Chile (UTC-3 en octubre): hora de armar el brief.
MANANA = datetime(2026, 10, 21, 9, 31, tzinfo=timezone.utc)
MADRUGADA = datetime(2026, 10, 21, 3, 31, tzinfo=timezone.utc)  # 00:31 en Chile
HOY, AYER = "2026-10-21", "2026-10-20"


def noticia(id_, importancia="normal", confirmacion=1, fecha=HOY, url=None):
    return {"id": id_, "fecha": fecha, "titulo": f"Título {id_}", "que_paso": "Pasó algo.",
            "por_que_importa": "Importa.", "seccion": "modelos", "importancia": importancia,
            "terminos": [], "etiquetas": [],
            "fuentes": [{"nombre": "Blog", "url": url if url is not None else f"https://blog.com/{id_}"}],
            "confirmacion": confirmacion}


def dia_con(fecha, noticias, brief=None):
    return {**dia_vacio(fecha), "noticias": noticias, "brief": brief}


def falsa(respuestas, llamadas=None):
    """IA falsa: devuelve las respuestas en orden y valida como lo haría pedir_json."""
    def pedir(prompt, config, cliente, validar=None):
        if llamadas is not None:
            llamadas.append(prompt)
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        validar(r)
        return r
    return pedir


TRES = {"lo_mas_importante": ["Uno.", "Dos.", "Tres."]}


# --- Archivo del día ---

def test_guardar_y_cargar_el_dia(tmp_path):
    dia = cargar_dia(HOY, tmp_path)
    assert dia == dia_vacio(HOY)
    assert agregar_noticias(dia, [noticia("a"), noticia("b")]) == 2
    ruta = guardar_dia(dia, MANANA, CONFIG, tmp_path)
    assert ruta.name == f"{HOY}.json" and not list(tmp_path.glob("*.tmp"))
    datos = json.loads(ruta.read_text(encoding="utf-8"))  # JSON válido
    assert datos["actualizado"] == "2026-10-21T06:31:00-03:00"  # hora de Chile
    assert [n["id"] for n in cargar_dia(HOY, tmp_path)["noticias"]] == ["a", "b"]
    assert publicadas_hoy(HOY, tmp_path) == 2  # el pre-filtro cuenta lo publicado hoy


def test_no_repite_noticias_ni_guarda_sin_link():
    dia = dia_con(HOY, [noticia("a")])
    assert agregar_noticias(dia, [noticia("a"), noticia("b", url=""), noticia("c", url="ftp://x"),
                                  noticia("d")]) == 1
    assert [n["id"] for n in dia["noticias"]] == ["a", "d"]


def test_dia_danado_se_respalda_y_no_se_cae(tmp_path, capsys):
    (tmp_path / f"{HOY}.json").write_text("{roto", encoding="utf-8")
    assert cargar_dia(HOY, tmp_path) == dia_vacio(HOY)
    assert (tmp_path / f"{HOY}.danado.json").read_text(encoding="utf-8") == "{roto"
    assert "dañado" in capsys.readouterr().out


def test_guardar_corrida_actualiza_dia_cache_y_pendientes(tmp_path):
    ahora = MANANA
    def cand(i):
        return Candidato(titulo=f"News number {i}", url=f"https://s{i}.com/x", fuente=f"Fuente {i}", tipo="rss",
                         seccion="modelos", idioma="en", peso=2, fecha=ahora - timedelta(hours=1), extracto="x")
    g1, g2, g3 = agrupar([cand(1), cand(2), cand(3)], CONFIG["limites"]["similitud_titulos"])
    r = Resultado(noticias=[noticia(g1.id)], procesados=[g1, g2], fallidos=[g3])
    assert guardar_corrida(r, [], CONFIG, ahora, tmp_path) == 1
    assert [n["id"] for n in cargar_dia(HOY, tmp_path)["noticias"]] == [g1.id]
    procesados = cargar_procesados(tmp_path / "cache" / "procesados.json")
    assert g1.hashes | g2.hashes <= set(procesados) and not g3.hashes & set(procesados)
    assert [g.id for g in cargar_pendientes(tmp_path / "pendientes.json")] == [g3.id]


# --- Brief ---

def test_el_brief_toca_desde_la_hora_configurada_y_una_sola_vez():
    assert not toca_brief(dia_vacio(HOY), MADRUGADA, CONFIG)
    assert toca_brief(dia_vacio(HOY), MANANA, CONFIG)
    assert not toca_brief(dia_con(HOY, [], {"lo_mas_importante": [], "ids": ["a"]}), MANANA, CONFIG)


def test_con_config_yaml_la_primera_corrida_del_dia_arma_el_brief():
    # hora_desde 00:00: el cron de GitHub llega con horas de atraso (Paso 15)
    assert toca_brief(dia_vacio(HOY), MADRUGADA, cargar_config())


def test_candidatas_hoy_mas_las_de_ayer_que_no_entraron_en_el_brief_de_ayer():
    anterior = dia_con(AYER, [noticia("y1", fecha=AYER), noticia("y2", fecha=AYER)],
                       {"lo_mas_importante": [], "ids": ["y1"]})
    assert [n["id"] for n in candidatas_brief(dia_con(HOY, [noticia("h1")]), anterior)] == ["h1", "y2"]


def test_elige_maximo_10_con_las_alta_primero():
    candidatas = [noticia(f"n{i}") for i in range(12)] + [noticia("fuego", "alta"), noticia("tres", confirmacion=3)]
    elegidas = elegir_brief(candidatas, CONFIG["limites"]["max_brief"])
    assert len(elegidas) == 10 and [n["id"] for n in elegidas[:3]] == ["fuego", "tres", "n0"]


def test_arma_el_brief_con_bullets_y_pasa_la_revision():
    dia = dia_con(HOY, [noticia(f"n{i}") for i in range(14)] + [noticia("fuego", "alta")])
    anterior = dia_vacio(AYER)
    llamadas = []
    hecho = actualizar_brief(dia, anterior, MANANA, CONFIG, None, falsa([TRES], llamadas))
    assert "10 noticias + 3 bullets" in hecho
    assert dia["brief"]["ids"][0] == "fuego" and len(dia["brief"]["ids"]) == 10
    assert dia["brief"]["lo_mas_importante"] == ["Uno.", "Dos.", "Tres."]
    assert problemas_dia(dia, anterior, CONFIG) == []
    assert "https://" not in llamadas[0] and "Título fuego" in llamadas[0]  # la IA no ve links
    # Una vez armado no se rehace ni se vuelve a llamar a la IA.
    assert actualizar_brief(dia, anterior, MANANA, CONFIG, None, falsa([])) == "brief ya completo"
    assert "Lo más importante hoy" in texto_brief(dia, anterior) and "🔥" in texto_brief(dia, anterior)


def test_antes_de_la_hora_no_se_arma():
    dia = dia_con(HOY, [noticia("a")])
    assert actualizar_brief(dia, dia_vacio(AYER), MADRUGADA, CONFIG, None, falsa([])).startswith("todavía no")
    assert dia["brief"] is None


def test_sin_ia_queda_sin_bullets_y_se_completan_en_la_corrida_siguiente():
    dia = dia_con(HOY, [noticia("a"), noticia("b"), noticia("c")])
    anterior = dia_vacio(AYER)
    hecho = actualizar_brief(dia, anterior, MANANA, CONFIG, None, falsa([IANoDisponible(["gemini: cuota"])]))
    assert "sin bullets" in hecho and dia["brief"] == {"lo_mas_importante": [], "ids": ["a", "b", "c"]}
    assert problemas_dia(dia, anterior, CONFIG) == []  # sin bullets igual se puede publicar
    hecho = actualizar_brief(dia, anterior, MANANA, CONFIG, None, falsa([TRES]))
    assert "faltaban los bullets" in hecho and len(dia["brief"]["lo_mas_importante"]) == 3


def test_sin_noticias_no_se_arma_y_se_reintenta():
    dia = dia_vacio(HOY)
    assert "sin noticias" in actualizar_brief(dia, dia_vacio(AYER), MANANA, CONFIG, None, falsa([]))
    assert dia["brief"] is None


def test_con_menos_de_3_noticias_pide_menos_bullets():
    dia = dia_con(HOY, [noticia("a"), noticia("b")])
    llamadas = []
    actualizar_brief(dia, dia_vacio(AYER), MANANA, CONFIG, None,
                     falsa([{"lo_mas_importante": ["Uno.", "Dos."]}], llamadas))
    assert len(dia["brief"]["lo_mas_importante"]) == 2 and "exactamente **2 frases**" in llamadas[0]


@pytest.mark.parametrize("datos, error", [
    ({}, "lista de 3"),
    ({"lo_mas_importante": ["Uno.", "Dos."]}, "lista de 3"),
    ({"lo_mas_importante": ["Uno.", " ", "Tres."]}, "vacío"),
    ({"lo_mas_importante": ["Uno.", "Dos.", "x" * 301]}, "largo"),
])
def test_rechaza_bullets_mal_formados(datos, error):
    with pytest.raises(ValueError, match=error):
        validar_bullets(datos, 3)


def test_la_revision_detecta_problemas():
    dia = dia_con(HOY, [noticia("a", url=""), noticia("b")],
                  {"lo_mas_importante": [], "ids": [f"x{i}" for i in range(11)]})
    problemas = " | ".join(problemas_dia(dia, dia_vacio(AYER), CONFIG))
    assert "a no tiene link" in problemas and "más de 10" in problemas and "no existen" in problemas


def test_prompt_brief_trae_las_reglas():
    plantilla = RUTA_PROMPT_BRIEF.read_text(encoding="utf-8")
    for regla in ("Nunca inventes", "rumor", "lo_mas_importante", "{{CANTIDAD}}", "{{NOTICIAS}}"):
        assert regla in plantilla
    prompt = armar_prompt_brief([noticia("a")], plantilla)
    assert "{{" not in prompt and "Título a" in prompt
