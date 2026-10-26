"""Fotos de vista previa de las noticias (sin red: páginas falsas)."""

import httpx

from radar.imagenes import id_video_youtube, imagen_noticia, poner_imagenes


def pagina(meta: str) -> str:
    return f"<html><head><title>x</title>{meta}</head><body>hola</body></html>"


PAGINAS = {
    "/con-foto": pagina('<meta property="og:image" content="https://cdn.ej.com/foto.jpg">'),
    "/relativa": pagina('<meta name="twitter:image" content="/img/portada.png">'),
    "/logo": pagina('<meta property="og:image" content="https://ej.com/static/logo.png">'),
    "/sin-foto": pagina('<meta property="og:description" content="Algo">'),
}


def red_falsa():
    def responder(pedido):
        if pedido.url.path == "/caida":
            return httpx.Response(503)
        return httpx.Response(200, html=PAGINAS.get(pedido.url.path, pagina("")))
    return httpx.Client(transport=httpx.MockTransport(responder))


def noticia(*urls):
    return {"id": "x", "fuentes": [{"nombre": "Fuente", "url": u} for u in urls]}


def test_toma_la_foto_de_la_primera_fuente_que_tenga_una():
    with red_falsa() as red:
        assert imagen_noticia(noticia("https://ej.com/caida", "https://ej.com/con-foto"), red) == "https://cdn.ej.com/foto.jpg"
        assert imagen_noticia(noticia("https://ej.com/relativa"), red) == "https://ej.com/img/portada.png"


def test_descarta_logos_y_paginas_sin_foto():
    with red_falsa() as red:
        assert imagen_noticia(noticia("https://ej.com/logo", "https://ej.com/sin-foto"), red) is None


def test_youtube_usa_la_miniatura_del_video_sin_leer_la_pagina():
    assert id_video_youtube("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert id_video_youtube("https://www.youtube.com/shorts/xyz789") == "xyz789"
    assert id_video_youtube("https://ej.com/watch?v=abc") is None
    with red_falsa() as red:
        assert imagen_noticia(noticia("https://www.youtube.com/watch?v=abc123"), red) == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


def test_poner_imagenes_solo_completa_las_que_faltan():
    noticias = [noticia("https://ej.com/con-foto"), noticia("https://ej.com/sin-foto"),
                {**noticia("https://ej.com/con-foto"), "imagen": None}]
    with red_falsa() as red:
        assert poner_imagenes(noticias, red, hilos=2) == 1
    assert [n["imagen"] for n in noticias] == ["https://cdn.ej.com/foto.jpg", None, None]
