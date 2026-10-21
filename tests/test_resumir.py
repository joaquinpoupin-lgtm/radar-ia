"""Paso 7: prompt de resumen y validación de la respuesta (sin red: la IA es una función falsa)."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from radar.agrupar import agrupar
from radar.config import cargar_config
from radar.ia import IANoDisponible
from radar.recolectar import Candidato
from radar.resumir import RUTA_PROMPT, armar_prompt, resumir, texto_resultado, validar_respuesta

CONFIG = cargar_config()
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
HOY = "2026-10-20"


def cand(titulo, url, fuente="Blog", extracto="Un extracto corto."):
    return Candidato(titulo=titulo, url=url, fuente=fuente, tipo="rss", seccion="modelos", idioma="en",
                     peso=2, fecha=AHORA - timedelta(hours=1), extracto=extracto)


def grupos(n):
    return agrupar([cand(f"News number {i}", f"https://s{i}.com/x", f"Fuente {i}") for i in range(1, n + 1)],
                   CONFIG["limites"]["similitud_titulos"])


def resumida(n, **extra):
    return {"n": n, "titulo": f"Título {n}", "que_paso": "Pasó algo.", "por_que_importa": "Importa.",
            "seccion": "modelos", "importancia": "normal", "terminos": [], "etiquetas": [], **extra}


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


def test_prompt_trae_las_reglas_y_las_noticias_sin_links():
    plantilla = RUTA_PROMPT.read_text(encoding="utf-8")
    for regla in ("Nunca inventes", "No copies", "rumor", "sin confirmar", "misma_que", "descartar"):
        assert regla in plantilla
    prompt = armar_prompt(grupos(2), plantilla)
    assert "{{NOTICIAS}}" not in prompt
    datos = json.loads(prompt.split("## Noticias")[1])
    assert [d["n"] for d in datos] == [1, 2] and datos[0]["sitio"] == "s1.com"
    assert "https://" not in prompt.split("## Noticias")[1]  # la IA no ve links: no puede inventarlos


def test_valida_una_respuesta_correcta():
    validar_respuesta({"noticias": [resumida(1), {"n": 2, "descartar": True, "motivo": "x"},
                                    {"n": 3, "misma_que": 1}]}, 3)


@pytest.mark.parametrize("cambio, error", [
    (lambda d: d.pop("noticias"), "falta la lista"),
    (lambda d: d["noticias"].pop(), "faltan las noticias [2]"),
    (lambda d: d["noticias"].append(resumida(1)), "dos veces"),
    (lambda d: d["noticias"][0].update(n=9), "'n' válido"),
    (lambda d: d["noticias"][0].pop("que_paso"), "le falta 'que_paso'"),
    (lambda d: d["noticias"][0].update(titulo="  "), "le falta 'titulo'"),
    (lambda d: d["noticias"][0].update(seccion="deportes"), "sección inválida"),
    (lambda d: d["noticias"][0].update(importancia="urgente"), "importancia inválida"),
    (lambda d: d["noticias"][0].update(terminos=[{"termino": "RAG"}]), "'terminos'"),
    (lambda d: d["noticias"][0].update(etiquetas="gratis"), "'etiquetas'"),
    (lambda d: d["noticias"][1].update(misma_que=2), "no está resumida"),
])
def test_rechaza_respuestas_fuera_del_esquema(cambio, error):
    datos = {"noticias": [resumida(1), resumida(2)]}
    cambio(datos)
    with pytest.raises(ValueError, match=error.replace("[", r"\[").replace("]", r"\]")):
        validar_respuesta(datos, 2)


def test_resume_descarta_y_une_poniendo_links_desde_el_codigo():
    g = grupos(3)
    respuesta = {"noticias": [
        resumida(1, importancia="alta", etiquetas=["Gratis", "gratis", "open source"],
                 terminos=[{"termino": "RAG", "explicacion": "Consultar documentos."}],
                 fuentes=[{"nombre": "inventada", "url": "https://inventado.com"}]),
        {"n": 2, "descartar": True, "motivo": "no es de IA"},
        {"n": 3, "misma_que": 1}]}
    r = resumir(g, CONFIG, None, HOY, pedir=falsa([respuesta]))
    [n] = r.noticias
    assert n["id"] == g[0].id and n["fecha"] == HOY and n["importancia"] == "alta"
    assert n["etiquetas"] == ["gratis", "open source"]
    assert [f["url"] for f in n["fuentes"]] == ["https://s1.com/x", "https://s3.com/x"]  # nunca la inventada
    assert n["confirmacion"] == 2
    assert set(n) == {"id", "fecha", "titulo", "que_paso", "por_que_importa", "seccion", "importancia",
                      "terminos", "etiquetas", "fuentes", "confirmacion"}
    assert [motivo for _, motivo in r.descartadas] == ["no es de IA"]
    assert r.unidas == 1 and len(r.procesados) == 3 and not r.fallidos
    assert "🔥 [modelos] Título 1" in texto_resultado(r)


def test_manda_en_lotes_y_si_la_ia_cae_lo_demas_queda_pendiente():
    config = copy.deepcopy(CONFIG)
    config["limites"]["tamano_lote"] = 2
    llamadas = []
    respuestas = [{"noticias": [resumida(1), resumida(2)]}, IANoDisponible(["gemini: 429", "groq: 503"])]
    r = resumir(grupos(5), config, None, HOY, pedir=falsa(respuestas, llamadas))
    assert len(llamadas) == 2  # el 3.er lote ni se intenta: la IA ya estaba caída
    assert len(r.noticias) == 2 and len(r.procesados) == 2
    assert len(r.fallidos) == 3 and r.errores
    assert "Quedaron pendientes" in texto_resultado(r)
