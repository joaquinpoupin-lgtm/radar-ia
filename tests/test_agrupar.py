from datetime import datetime, timedelta, timezone

from radar.agrupar import agrupar, hash_url, resumen_agrupacion, titulos_parecidos, palabras_titulo, url_canonica
from radar.recolectar import Candidato

AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
UMBRAL = 0.8


def cand(titulo, url, fuente="Blog", horas=0, peso=2):
    return Candidato(titulo=titulo, url=url, fuente=fuente, tipo="rss", seccion="modelos", idioma="en",
                     peso=peso, fecha=AHORA - timedelta(hours=horas))


def test_url_canonica_quita_lo_que_no_cambia_la_pagina():
    base = "https://ejemplo.com/blog/nuevo-modelo"
    for variante in ["http://www.Ejemplo.com/blog/nuevo-modelo/",
                     "https://ejemplo.com/blog/nuevo-modelo?utm_source=reddit&utm_medium=rss",
                     "https://ejemplo.com/blog/nuevo-modelo#comentarios",
                     "https://ejemplo.com/blog/nuevo-modelo?ref=hn&fbclid=abc"]:
        assert url_canonica(variante) == base
    # Los parámetros que sí importan se conservan (y en orden fijo).
    assert url_canonica("https://www.youtube.com/watch?v=abc&utm_source=x") == "https://youtube.com/watch?v=abc"
    assert url_canonica("https://x.com/a?b=2&a=1") == url_canonica("https://x.com/a?a=1&b=2")
    assert url_canonica("https://x.com/a?id=1") != url_canonica("https://x.com/a?id=2")


def test_id_estable():
    id_ = hash_url("https://ejemplo.com/a?utm_source=x")
    assert id_ == hash_url("http://www.ejemplo.com/a/") and len(id_) == 12
    assert all(c in "0123456789abcdef" for c in id_)
    assert id_ != hash_url("https://ejemplo.com/b")


def test_misma_url_en_varias_fuentes_es_una_noticia():
    blog = cand("Introducing Model X", "https://ejemplo.com/model-x", "Blog oficial", horas=5, peso=3)
    hn = cand("Model X is out", "https://www.ejemplo.com/model-x?utm_source=hn", "Hacker News", horas=2)
    reddit = cand("Model X just dropped!!", "https://ejemplo.com/model-x/", "Reddit", horas=1)
    [grupo] = agrupar([hn, reddit, blog], UMBRAL)
    assert grupo.principal is blog  # el más antiguo es el original
    assert grupo.id == hash_url(blog.url)
    assert grupo.confirmacion == 3
    assert grupo.fuentes == [{"nombre": "Blog oficial", "url": "https://ejemplo.com/model-x"}]  # un solo link
    assert grupo.hashes == {hash_url(blog.url)}


def test_titulos_parecidos_de_distintas_fuentes_se_agrupan():
    a = cand("OpenAI launches GPT-6 for everyone", "https://openai.com/gpt-6", "Blog de OpenAI", horas=6)
    b = cand("Show HN: OpenAI launches GPT-6", "https://news.site/gpt6", "Hacker News", horas=3)
    c = cand("Introducing a new coding agent", "https://otra.com/agente", "Otro blog", horas=1)
    grupos = agrupar([a, b, c], UMBRAL)
    assert [len(g.candidatos) for g in grupos] == [2, 1]
    assert grupos[0].principal is a and grupos[0].confirmacion == 2
    assert [f["url"] for f in grupos[0].fuentes] == ["https://openai.com/gpt-6", "https://news.site/gpt6"]
    assert grupos[0].hashes == {hash_url(a.url), hash_url(b.url)}
    assert resumen_agrupacion([a, b, c], grupos) == "3 candidatos → 2 noticias (1 contadas por más de una fuente)"


def test_no_se_agrupan_noticias_distintas():
    p = lambda t: palabras_titulo(t)
    # Mismas palabras, distinto número: son cosas distintas.
    assert not titulos_parecidos(p("Anthropic releases Claude Opus 4.5 with better coding"),
                                 p("Anthropic releases Claude Opus 4.6 with better coding"), UMBRAL)
    # Títulos cortos que comparten letras pero no la noticia.
    assert not titulos_parecidos(p("Introducing Codex"), p("Introducing Sora"), UMBRAL)
    # Título corto contenido entero en otro largo: misma noticia (pero no con 3 palabras o menos).
    assert titulos_parecidos(p("OpenAI acquires Orchestra Bio"),
                             p("OpenAI acquires startup Orchestra Bio\u2060 to beef up its biotech business"), UMBRAL)
    assert not titulos_parecidos(p("Introducing GPT agents"), p("Introducing GPT agents for teams and more"), UMBRAL)
    assert not titulos_parecidos(p("OpenAI acquires Orchestra Bio"), p("OpenAI acquires a rival of Orchestra"), UMBRAL)
    # Tildes, mayúsculas y puntuación no importan.
    assert titulos_parecidos(p("¡Lanzan el modelo Árbol!"), p("lanzan el modelo arbol"), UMBRAL)


def test_misma_fuente_con_titulos_casi_iguales_no_se_agrupa():
    uno = cand("Las noticias de IA de esta semana en resumen", "https://yt.com/watch?v=1", "Canal", horas=48)
    dos = cand("Las noticias de IA de esta semana, en resumen", "https://yt.com/watch?v=2", "Canal", horas=1)
    assert len(agrupar([uno, dos], UMBRAL)) == 2


def test_el_id_no_cambia_cuando_llegan_mas_fuentes():
    original = cand("New open model beats the rest", "https://lab.ai/modelo", "Lab", horas=10)
    id_antes = agrupar([original], UMBRAL)[0].id
    tardia = cand("New open model beats the rest", "https://medio.com/nota", "Medio", horas=1, peso=3)
    sin_fecha = cand("New open model beats the rest", "https://otro.com/nota", "Otro")
    sin_fecha.fecha = None
    [grupo] = agrupar([tardia, sin_fecha, original], UMBRAL)
    assert grupo.id == id_antes
    assert [c.fuente for c in grupo.candidatos] == ["Lab", "Medio", "Otro"]  # sin fecha al final
