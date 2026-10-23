from datetime import datetime, timezone
from pathlib import Path

import httpx

from radar.config import cargar_config
from radar.fuentes import Fuente
from radar.recolectar import (candidatos_feed, candidatos_hn, descripcion_pagina, limpiar_texto, patron_ia,
                              recolectar, tabla)

FIXTURES = Path(__file__).parent / "fixtures"
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
CONFIG = cargar_config()
PATRON = patron_ia(CONFIG["recolector"]["palabras_ia"])


def fuente(nombre="Blog", tipo="rss", url="https://ejemplo.com/feed", seccion="modelos"):
    return Fuente(nombre, tipo, url, seccion, "en", 2)


def pagina(descripcion):
    return (f'<html><head><meta property="og:description" content="{descripcion}">'
            '<meta name="description" content="otra"></head><body>...</body></html>')


HITS = {"hits": [
    {"title": "Show HN: An open source AI agent for spreadsheets", "url": "https://agente.dev",
     "points": 150, "created_at_i": 1792940400, "objectID": "1"},
    {"title": "Ask HN: Which LLM do you use for coding?", "url": None, "story_text": "<p>Curious what people use.</p>",
     "points": 80, "created_at_i": 1792936800, "objectID": "2"},
    {"title": "The history of the bicycle", "url": "https://bici.org", "points": 300,
     "created_at_i": 1792940400, "objectID": "3"},
    {"title": "Fixing my email client", "url": "https://mail.org", "points": 90,  # "email" contiene "ai"
     "created_at_i": 1792940400, "objectID": "4"},
]}


def test_limpiar_texto():
    texto = "<p>Hola &amp; chao: mira https://x.com/a   aquí.</p><p>The post X appeared first on Blog.</p>"
    assert limpiar_texto(texto, 500) == "Hola & chao: mira aquí."
    largo = limpiar_texto("palabra " * 100, 50)
    assert len(largo) <= 50 and largo.endswith("…") and "palab…" not in largo


def test_rss_convierte_al_formato_comun():
    c = candidatos_feed(fuente(), (FIXTURES / "feed_ejemplo.xml").read_bytes(), 500)[0]
    assert c.a_dict() == {
        "titulo": "Nuevo modelo de ejemplo", "url": "https://ejemplo.com/nuevo-modelo", "fuente": "Blog",
        "tipo": "rss", "seccion": "modelos", "idioma": "en", "peso": 2,
        "fecha": "2026-10-19T15:00:00+00:00", "extracto": "Extracto corto de prueba."}


def test_youtube_usa_la_descripcion_sin_links():
    c = candidatos_feed(fuente(tipo="youtube"), (FIXTURES / "youtube_ejemplo.xml").read_bytes(), 500)[0]
    assert c.url == "https://www.youtube.com/watch?v=abc123"
    assert "lo comparo con el anterior" in c.extracto and "https://" not in c.extracto


def test_youtube_sin_rss_lee_el_canal_y_la_descripcion_de_cada_video():
    canal = fuente("Canal", "youtube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc", "creadores")
    pedidos = []

    def responder(pedido):
        url = str(pedido.url)
        pedidos.append(url)
        if "feeds/videos.xml" in url:
            return httpx.Response(500)
        if "/channel/UCabc/videos" in url:
            return httpx.Response(200, content=(FIXTURES / "youtube_canal.html").read_bytes())
        if url.startswith("https://www.youtube.com/watch?v=nuevo1"):
            return httpx.Response(200, text='{"shortDescription":"Pruebo el modelo \\"nuevo\\" paso a paso.'
                                            '\\nLink: https://promo.com/x"}')
        return httpx.Response(404)

    r = recolectar([canal], CONFIG, AHORA, httpx.Client(transport=httpx.MockTransport(responder)))
    assert [(c.titulo, c.url) for c in r.candidatos] == [("Probé el nuevo modelo de video",
                                                          "https://www.youtube.com/watch?v=nuevo1")]  # el viejo no
    assert r.candidatos[0].extracto == 'Pruebo el modelo "nuevo" paso a paso. Link:'
    assert r.informes[0].desde_canal and not r.informes[0].error
    assert "https://www.youtube.com/watch?v=viejo2&hl=en" not in pedidos  # del video viejo no se pide nada
    assert "RSS caído: leído desde la página del canal" in tabla(r)


def test_reddit_usa_el_link_externo_y_el_texto_del_post():
    externo, propio, video = candidatos_feed(fuente(), (FIXTURES / "reddit_ejemplo.xml").read_bytes(), 500)
    assert externo.url == "https://blog.ejemplo.com/modelo-abierto?utm_source=reddit"
    assert externo.extracto == ""  # sin el relleno "submitted by /u/..."
    assert propio.url == "https://www.reddit.com/r/ChatGPT/comments/2b/automated_report/"
    assert propio.extracto.startswith("I connected my spreadsheet")
    assert video.url == "https://www.reddit.com/r/aivideo/comments/3c/look/"  # v.redd.it no es un artículo


def test_hacker_news_filtra_ia():
    candidatos = candidatos_hn(fuente("HN", "hackernews"), HITS, PATRON, 500)
    assert [c.titulo[:8] for c in candidatos] == ["Show HN:", "Ask HN: "]
    assert candidatos[0].puntaje == 150 and candidatos[0].url == "https://agente.dev"
    assert candidatos[1].url == "https://news.ycombinator.com/item?id=2"
    assert candidatos[1].extracto == "Curious what people use."


def test_descripcion_pagina():
    def responder(pedido):
        if "pdf" in str(pedido.url):
            return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
        return httpx.Response(200, text=pagina("Lo que dice &quot;la página&quot;."),
                              headers={"content-type": "text/html; charset=utf-8"})

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    assert descripcion_pagina("https://x.com/a", cliente) == 'Lo que dice "la página".'
    assert descripcion_pagina("https://x.com/a.pdf", cliente) is None


def test_recoleccion_completa_sigue_aunque_una_fuente_falle():
    fuentes = [fuente("Blog"), fuente("Caída", url="https://caida.com/feed"),
               fuente("Sin extracto", url="https://sinextracto.com/feed"),
               fuente("HN", "hackernews", "https://hn.algolia.com/api"),
               fuente("Rota", url="https://rota.com/feed")]
    paginas_vistas = []

    def responder(pedido):
        url = str(pedido.url)
        html = {"content-type": "text/html"}
        if url == "https://ejemplo.com/feed":
            return httpx.Response(200, content=(FIXTURES / "feed_ejemplo.xml").read_bytes())
        if "caida" in url:
            raise httpx.ConnectError("sin red", request=pedido)
        if url == "https://sinextracto.com/feed":
            return httpx.Response(200, content=(FIXTURES / "feed_sin_extracto.xml").read_bytes())
        if "algolia" in url:
            return httpx.Response(200, json=HITS)
        if "rota" in url:
            return httpx.Response(200, content=b"esto no es un feed")
        paginas_vistas.append(url)
        if url in ("https://sinextracto.com/uno", "https://sinextracto.com/dos"):
            return httpx.Response(200, text=pagina(f"Descripción propia de {url[-3:]} con suficiente largo."),
                                  headers=html)
        if url.startswith("https://sinextracto.com/"):  # tres y cuatro: la genérica del sitio
            return httpx.Response(200, text=pagina("Bienvenido a nuestro blog sobre tecnología."), headers=html)
        return httpx.Response(404)

    r = recolectar(fuentes, CONFIG, AHORA, httpx.Client(transport=httpx.MockTransport(responder)))
    informes = {i.nombre: i for i in r.informes}
    assert [i.nombre for i in r.informes] == [f.nombre for f in fuentes]
    assert informes["Blog"].candidatos == 1  # la noticia del 15-10 es más vieja que 3 días
    assert "conexión" in informes["Caída"].error
    assert "RSS" in informes["Rota"].error
    assert informes["HN"].candidatos == 2

    extractos = {c.url: c.extracto for c in r.candidatos if c.fuente == "Sin extracto"}
    assert extractos["https://sinextracto.com/uno"] == "Descripción propia de uno con suficiente largo."
    assert extractos["https://sinextracto.com/dos"] == "Descripción propia de dos con suficiente largo."
    assert extractos["https://sinextracto.com/tres"] == ""  # la genérica repetida se descarta
    assert informes["Sin extracto"].con_descripcion_pagina == 2
    # Extracto corto: se intenta la página (404 aquí) y se conserva el que venía en el RSS.
    assert "https://ejemplo.com/nuevo-modelo" in paginas_vistas
    assert next(c for c in r.candidatos if c.fuente == "Blog").extracto == "Extracto corto de prueba."

    texto = tabla(r)
    assert "ERROR: error de conexión" in texto
    assert "Total: 7 candidatos de 5 fuentes · 2 fuentes con error" in texto


def test_tope_por_fuente():
    config = {**CONFIG, "recolector": {**CONFIG["recolector"], "max_por_fuente": 2}}
    contenido = (FIXTURES / "feed_sin_extracto.xml").read_bytes()
    cliente = httpx.Client(transport=httpx.MockTransport(
        lambda p: httpx.Response(200, content=contenido) if p.url.path == "/feed" else httpx.Response(404)))
    r = recolectar([fuente(url="https://sinextracto.com/feed")], config, AHORA, cliente)
    assert [c.titulo for c in r.candidatos] == ["Post uno", "Post dos"]  # los más nuevos
