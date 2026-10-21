"""Paso 14: fuentes en tendencia (GitHub, modelos de Hugging Face, arXiv vía Daily Papers, Product Hunt)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from radar.agrupar import agrupar
from radar.config import cargar_config
from radar.filtrar import prefiltrar
from radar.fuentes import ErrorFuentes, Fuente, cargar_fuentes, probar_fuente, topes_por_fuente, url_real
from radar.recolectar import (Candidato, candidatos_github, candidatos_hf_modelos, candidatos_papers,
                              limpiar_texto, parrafo_readme, recolectar)

CONFIG = cargar_config()
AHORA = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
DESDE = AHORA - timedelta(days=7)
GITHUB = Fuente("GitHub", "github", "https://api.github.com/search/repositories?q=created%3A%3E%3D{desde}",
                "herramientas", "en", 2, max_por_corrida=1)
HF = Fuente("HF", "huggingface", "https://huggingface.co/api/models?sort=trendingScore", "modelos", "en", 2)
PAPERS = Fuente("arXiv", "papers", "https://huggingface.co/api/daily_papers", "tendencias", "en", 1)

REPOS = {"total_count": 3, "items": [
    {"full_name": "lab/agente", "html_url": "https://github.com/lab/agente", "stargazers_count": 1984,
     "description": "An open source  agent\nfor spreadsheets", "language": "Python",
     "topics": ["ai-agents", "llm"], "created_at": "2026-10-18T10:00:00Z"},
    {"full_name": "otro/viejo", "html_url": "https://github.com/otro/viejo", "stargazers_count": 5000,
     "description": "Creado hace mucho", "created_at": "2026-09-01T10:00:00Z"},
    {"full_name": "sin/descripcion", "html_url": "https://github.com/sin/descripcion", "stargazers_count": 150,
     "description": None, "created_at": "2026-10-20T10:00:00Z"},
]}
MODELOS = [
    {"id": "lab/Modelo-7B", "likes": 1990, "downloads": 27737, "pipeline_tag": "text-generation",
     "tags": ["transformers", "license:mit"], "createdAt": "2026-10-17T02:40:38.000Z"},
    {"id": "copias/Modelo-7B-GGUF", "likes": 300, "downloads": 900, "createdAt": "2026-10-18T00:00:00.000Z",
     "tags": ["gguf", "base_model:quantized:lab/Modelo-7B"]},
    {"id": "lab/Viejo", "likes": 3000, "createdAt": "2026-08-01T00:00:00.000Z", "tags": []},
]
PAPERS_API = [
    {"paper": {"id": "2610.26825", "title": "MemT: Memory  Native", "upvotes": 146,
               "summary": "We introduce MemT, a model that remembers.",
               "submittedOnDailyAt": "2026-10-20T00:00:00.000Z"}, "publishedAt": "2026-10-19T20:00:00.000Z"},
    {"paper": {"id": "2610.11111", "title": "Poco votado", "upvotes": 3, "summary": "Algo."}},
]
README = """---
license: mit
---
<div align="center"><img src="logo.png"/></div>

# Modelo-7B

[![badge](https://img.shields.io/x)](https://lab.ai)

| Benchmark | Score |
| --- | --- |

**Modelo-7B** is a small [open model](https://lab.ai) by Lab that writes code and answers questions in many languages.

## Quickstart

Install the package with pip and run the example below to start chatting with the model right away.
"""


def test_url_real_pone_la_fecha_de_hace_dias_tendencias():
    assert url_real(GITHUB, AHORA, CONFIG).endswith("created%3A%3E%3D2026-10-14")
    assert url_real(HF, AHORA, CONFIG) == HF.url  # sin {desde} no cambia


def test_max_por_corrida_se_valida_y_se_usa_como_tope(tmp_path):
    ruta = tmp_path / "sources.yaml"
    ruta.write_text("""fuentes:
  - {nombre: A, tipo: github, url: https://a.com, seccion: herramientas, idioma: en, peso: 2, max_por_corrida: 1}
  - {nombre: B, tipo: rss, url: https://b.com, seccion: modelos, idioma: en, peso: 3}
""", encoding="utf-8")
    fuentes = cargar_fuentes(ruta)
    assert topes_por_fuente(fuentes) == {"A": 1}
    ruta.write_text("""fuentes:
  - {nombre: A, tipo: papers, url: https://a.com, seccion: tendencias, idioma: en, peso: 1, max_por_corrida: 0}
""", encoding="utf-8")
    with pytest.raises(ErrorFuentes, match="max_por_corrida"):
        cargar_fuentes(ruta)


def test_sources_yaml_trae_las_fuentes_nuevas_con_tope():
    fuentes = {f.nombre: f for f in cargar_fuentes()}
    nuevas = [f for f in fuentes.values() if f.tipo in ("github", "huggingface", "papers")]
    nuevas.append(fuentes["Product Hunt (IA)"])
    assert {f.tipo for f in nuevas} == {"github", "huggingface", "papers", "rss"}
    assert all(f.max_por_corrida == 1 for f in nuevas)  # para que no inunden
    assert "{desde}" in next(f for f in nuevas if f.tipo == "github").url


def test_prefiltro_respeta_el_tope_propio_de_la_fuente():
    lista = agrupar([Candidato(f"repo {n}: tool number {n}", f"https://github.com/r/{n}", "GitHub", "github",
                               "herramientas", "en", 3, AHORA) for n in range(5)], 0.8)
    assert len(prefiltrar(lista, {}, CONFIG, AHORA).elegidas) == CONFIG["prefiltro"]["max_por_fuente"]
    assert len(prefiltrar(lista, {}, CONFIG, AHORA, topes={"GitHub": 1}).elegidas) == 1


def test_github_repos_recientes_con_datos_en_el_extracto():
    repo, sin = candidatos_github(GITHUB, REPOS["items"], AHORA, DESDE, 500)  # el viejo queda fuera
    assert repo.titulo == "lab/agente: An open source agent for spreadsheets"
    assert repo.url == "https://github.com/lab/agente" and repo.fecha == AHORA  # visto en alza hoy
    assert repo.extracto == ("An open source agent for spreadsheets · 1.984 estrellas en GitHub · lenguaje Python"
                             " · temas: ai-agents, llm")
    assert sin.titulo == "sin/descripcion" and sin.extracto == "150 estrellas en GitHub"


def test_hf_modelos_recientes_sin_copias_cuantizadas():
    [modelo] = candidatos_hf_modelos(HF, MODELOS, AHORA, DESDE, 500)
    assert modelo.titulo == "lab/Modelo-7B" and modelo.url == "https://huggingface.co/lab/Modelo-7B"
    assert modelo.extracto == ("tipo: text-generation · licencia mit · 1.990 me gusta y 27.737 descargas"
                               " en Hugging Face")


def test_papers_solo_los_muy_votados_con_link_a_arxiv():
    [paper] = candidatos_papers(PAPERS, PAPERS_API, 50, 500)
    assert paper.titulo == "MemT: Memory Native" and paper.url == "https://arxiv.org/abs/2610.26825"
    assert paper.fecha == datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert paper.extracto == "We introduce MemT, a model that remembers. · 146 votos en Hugging Face"


def test_parrafo_readme_toma_la_presentacion_y_no_las_instrucciones():
    assert parrafo_readme(README, 500) == ("Modelo-7B is a small open model by Lab that writes code and answers"
                                           " questions in many languages.")
    solo_uso = "# X\n\n## Quickstart\n\n" + "Install the package with pip and run this example to start now. " * 2
    assert parrafo_readme(solo_uso, 500) == ""
    assert parrafo_readme("", 500) == ""


def test_product_hunt_sin_relleno():
    assert limpiar_texto("<p> Open models, built for agents. </p> <p><a>Discussion</a> | <a>Link</a></p>",
                         500) == "Open models, built for agents."


def responder(pedido):
    host, ruta = pedido.url.host, pedido.url.path
    if host == "api.github.com":
        assert "2026-10-14" in str(pedido.url)  # {desde} reemplazado
        return httpx.Response(200, json=REPOS)
    if ruta == "/api/models":
        return httpx.Response(200, json=MODELOS)
    if ruta == "/api/daily_papers":
        return httpx.Response(200, json=PAPERS_API)
    if ruta == "/lab/Modelo-7B/raw/main/README.md":
        return httpx.Response(200, text=README)
    return httpx.Response(404)


def test_recolectar_lee_las_tres_apis_y_completa_el_readme():
    r = recolectar([GITHUB, HF, PAPERS], CONFIG, AHORA, httpx.Client(transport=httpx.MockTransport(responder)))
    assert {i.nombre: i.candidatos for i in r.informes} == {"GitHub": 2, "HF": 1, "arXiv": 1}
    assert not any(i.error for i in r.informes)
    modelo = next(c for c in r.candidatos if c.fuente == "HF")
    assert modelo.extracto.startswith("Modelo-7B is a small open model by Lab")
    assert modelo.extracto.endswith("27.737 descargas en Hugging Face") and len(modelo.extracto) <= 500


def test_api_con_otra_forma_es_error_de_la_fuente_sin_frenar_al_resto():
    def raro(pedido):
        if pedido.url.host == "api.github.com":
            return httpx.Response(200, json={"message": "API rate limit exceeded"})
        return responder(pedido)
    r = recolectar([GITHUB, PAPERS], CONFIG, AHORA, httpx.Client(transport=httpx.MockTransport(raro)))
    informes = {i.nombre: i for i in r.informes}
    assert "API de GitHub" in informes["GitHub"].error and informes["arXiv"].candidatos == 1


@pytest.mark.parametrize("fuente,datos", [(GITHUB, REPOS), (HF, MODELOS), (PAPERS, PAPERS_API)])
def test_radar_fuentes_prueba_las_apis(fuente, datos):
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, json=datos)))
    r = probar_fuente(fuente, cliente, AHORA, 90)
    assert r.estado == "OK" and r.items == len(datos["items"] if isinstance(datos, dict) else datos)
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"x": 1})))
    assert probar_fuente(fuente, cliente, AHORA, 90).estado == "ERROR"
