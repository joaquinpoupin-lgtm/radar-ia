"""Paso 9: sitio estático (sin red: los links se prueban con un transporte falso)."""

import json
from datetime import datetime, timezone

import httpx

from radar.config import cargar_config
from radar.sitio import (cargar_dias, datos_portada, espectro, fecha_larga, generar_sitio, links_externos,
                         links_internos_rotos, minutos_lectura, noticias_recientes, probar_link, revisar_links)

CONFIG = cargar_config()
MANANA = datetime(2026, 10, 21, 9, 31, tzinfo=timezone.utc)  # 06:31 en Chile
HOY, AYER = "2026-10-21", "2026-10-20"


def noticia(id_, fecha=HOY, importancia="normal", seccion="modelos", titulo=None, etiquetas=(), terminos=()):
    return {"id": id_, "fecha": fecha, "titulo": titulo or f"Título {id_}", "que_paso": f"Pasó algo con {id_}.",
            "por_que_importa": "Importa.", "seccion": seccion, "importancia": importancia,
            "terminos": [{"termino": t, "explicacion": f"Qué es {t}."} for t in terminos],
            "etiquetas": list(etiquetas), "fuentes": [{"nombre": "Blog", "url": f"https://blog.com/{id_}?a=1&b=2"}],
            "confirmacion": 1}


def escribir_dia(carpeta, fecha, noticias, brief=None):
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = {"fecha": fecha, "actualizado": f"{fecha}T06:31:00-03:00", "brief": brief, "noticias": noticias}
    (carpeta / f"{fecha}.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def generar(tmp_path, ahora=MANANA):
    return generar_sitio(CONFIG, ahora, datos=tmp_path / "data", destino=tmp_path / "_site")


def leer(tmp_path, ruta):
    return (tmp_path / "_site" / ruta).read_text(encoding="utf-8")


def test_genera_todas_las_paginas_con_links_internos_sanos(tmp_path):
    datos = tmp_path / "data"
    escribir_dia(datos, AYER, [noticia("ayer1", AYER), noticia("ayer2", AYER)],
                 brief={"lo_mas_importante": ["Algo de ayer."], "ids": ["ayer1"]})
    escribir_dia(datos, HOY, [noticia("hoy1", importancia="alta", etiquetas=["gratis"], terminos=["RAG"])],
                 brief={"lo_mas_importante": ["Uno.", "Dos."], "ids": ["hoy1", "ayer2"]})
    generado = generar(tmp_path)
    sitio = tmp_path / "_site"
    for ruta in ["index.html", "secciones.html", "estilo.css", "archivo.woff2", "archivo/index.html",
                 f"archivo/{HOY}.html", f"archivo/{AYER}.html"]:
        assert (sitio / ruta).exists(), ruta
    assert generado.noticias == 3
    assert links_internos_rotos(sitio) == []
    assert not (tmp_path / "_site.tmp").exists()


def test_portada_muestra_el_brief_de_hoy_con_la_noticia_de_ayer(tmp_path):
    datos = tmp_path / "data"
    escribir_dia(datos, AYER, [noticia("ayer2", AYER, titulo="Noticia de la noche")])
    escribir_dia(datos, HOY, [noticia("hoy1", importancia="alta", terminos=["RAG"]), noticia("hoy2")],
                 brief={"lo_mas_importante": ["Primer bullet.", "Segundo bullet."], "ids": ["hoy1", "ayer2"]})
    generar(tmp_path)
    portada = leer(tmp_path, "index.html")
    assert "miércoles 21 de octubre" in portada and "Brief del " in portada
    assert "Lo más importante hoy" in portada and "Primer bullet." in portada
    assert "Título hoy1" in portada and "Noticia de la noche" in portada and "de ayer" in portada
    assert 'class="dato-alta">Importante' in portada and "Qué es RAG." in portada
    # Espectro: una línea por noticia, doble si es importante y a media altura si es de ayer.
    assert 'class="linea doble" href="#n-hoy1"' in portada and 'class="linea ayer" href="#n-ayer2"' in portada
    assert "Hoy hay 1 noticia más fuera del brief" in portada  # hoy2
    assert 'href="https://blog.com/hoy1?a=1&amp;b=2" target="_blank" rel="noopener"' in portada
    assert "Título hoy2" not in portada


def test_antes_del_brief_de_hoy_la_portada_muestra_el_de_ayer(tmp_path):
    datos = tmp_path / "data"
    escribir_dia(datos, AYER, [noticia("ayer1", AYER)], brief={"lo_mas_importante": ["Ayer."], "ids": ["ayer1"]})
    escribir_dia(datos, HOY, [noticia("hoy1")])  # corrida de las 00:30: todavía sin brief
    generado = generar(tmp_path)
    assert generado.portada["fecha"] == AYER and not generado.portada["es_hoy"]
    portada = leer(tmp_path, "index.html")
    assert "El brief de hoy se arma" in portada and "Título ayer1" in portada


def test_sin_datos_igual_genera_el_sitio(tmp_path):
    generado = generar(tmp_path)
    assert generado.noticias == 0
    assert "Todavía no hay brief" in leer(tmp_path, "index.html")
    assert "Todavía no hay noticias" in leer(tmp_path, "secciones.html")
    assert links_internos_rotos(tmp_path / "_site") == []


def test_el_texto_de_la_ia_se_escapa(tmp_path):
    escribir_dia(tmp_path / "data", HOY, [noticia("x", titulo='<script>alert("hola")</script>')],
                 brief={"lo_mas_importante": ["<b>bullet</b>"], "ids": ["x"]})
    generar(tmp_path)
    portada = leer(tmp_path, "index.html")
    assert "<script>alert" not in portada and "&lt;script&gt;" in portada
    assert "<b>bullet</b>" not in portada


def test_secciones_tiene_filtros_y_solo_los_ultimos_dias(tmp_path):
    datos = tmp_path / "data"
    escribir_dia(datos, "2026-10-01", [noticia("vieja", "2026-10-01")])
    escribir_dia(datos, AYER, [noticia("a", AYER, seccion="dinero", etiquetas=["gratis", "video"])])
    escribir_dia(datos, HOY, [noticia("b", importancia="alta", etiquetas=["gratis"]), noticia("c")])
    generar(tmp_path)
    pagina = leer(tmp_path, "secciones.html")
    assert "Título vieja" not in pagina
    assert pagina.index("Título c") < pagina.index("Título b") < pagina.index("Título a")  # más nueva primero
    assert 'data-seccion="dinero" aria-pressed="false">Dinero con IA <small>1</small>' in pagina
    assert '<button type="button" data-seccion="tips"' not in pagina  # sin noticias, sin botón
    assert 'data-etiqueta="gratis" aria-pressed="false">#gratis <small>2</small>' in pagina
    assert 'data-alta="si" data-etiquetas="gratis"' in pagina
    assert "Solo importantes <small>1</small>" in pagina
    # El archivo sí guarda la vieja.
    assert "Título vieja" in leer(tmp_path, "archivo/2026-10-01.html")


def test_dia_danado_se_salta_sin_tocar_el_archivo(tmp_path, capsys):
    datos = tmp_path / "data"
    escribir_dia(datos, HOY, [noticia("hoy1")])
    (datos / f"{AYER}.json").write_text("{no es json", encoding="utf-8")
    (datos / "pendientes.json").write_text("[]", encoding="utf-8")
    assert list(cargar_dias(datos)) == [HOY]
    assert "no se pudo leer" in capsys.readouterr().out
    assert (datos / f"{AYER}.json").exists()


def test_noticias_recientes_y_lectura():
    dias = {AYER: {"noticias": [noticia("a1", AYER), noticia("a2", AYER)]}, HOY: {"noticias": [noticia("h1")]}}
    assert [n["id"] for n in noticias_recientes(dias, HOY, 7)] == ["h1", "a2", "a1"]
    assert [n["id"] for n in noticias_recientes(dias, HOY, 1)] == ["h1"]
    brief = {"bullets": ["uno " * 100], "noticias": [noticia("x")] * 10}
    assert minutos_lectura(brief, 200) == 1
    assert minutos_lectura({"bullets": ["palabra " * 600], "noticias": []}, 200) == 3
    assert minutos_lectura(None, 200) == 0


def test_datos_portada_sin_nada():
    p = datos_portada({}, HOY, CONFIG)
    assert p["brief"] is None and p["hoy_fuera"] == 0


def test_espectro_reparte_cada_seccion_en_su_franja():
    noticias = [noticia(f"m{i}") for i in range(5)] + [noticia("t", AYER, seccion="tips", importancia="alta")]
    lineas = espectro(noticias, HOY)
    modelos = [l["x"] for l in lineas if l["seccion"] == "modelos"]
    assert len(lineas) == 6 and all(0 < x < 100 / 6 for x in modelos) and len(set(modelos)) == 5
    tips = lineas[-1]
    assert 500 / 6 < tips["x"] < 100 and tips["alta"] and tips["de_ayer"]
    assert [l["i"] for l in lineas] == list(range(6))


def test_noticia_con_foto_y_sin_foto(tmp_path):
    con = {**noticia("con"), "imagen": "https://cdn.ej.com/foto.jpg?a=1&b=2"}
    escribir_dia(tmp_path / "data", HOY, [con, noticia("sin")], brief={"lo_mas_importante": ["Uno."], "ids": ["con", "sin"]})
    generar(tmp_path)
    portada = leer(tmp_path, "index.html")
    assert 'src="https://cdn.ej.com/foto.jpg?a=1&amp;b=2"' in portada and 'referrerpolicy="no-referrer"' in portada
    assert portada.count('class="foto__arte"') == 2  # la ilustración propia siempre está debajo
    assert portada.count("<img ") == 1
    assert 'class="noticia destacada" id="n-con"' in portada
    # La foto no es un link a una fuente: no se revisa con --revisar-links.
    assert "https://cdn.ej.com/foto.jpg?a=1&b=2" not in links_externos(tmp_path / "_site")


def test_fecha_larga():
    assert fecha_larga("2026-10-21") == "miércoles 21 de octubre de 2026"
    assert fecha_larga("2026-01-04") == "domingo 4 de enero de 2026"


def test_links_externos_sin_repetir(tmp_path):
    escribir_dia(tmp_path / "data", HOY, [noticia("a"), noticia("b")], brief={"lo_mas_importante": [], "ids": ["a"]})
    generar(tmp_path)
    urls = links_externos(tmp_path / "_site")
    assert sorted(urls) == ["https://blog.com/a?a=1&b=2", "https://blog.com/b?a=1&b=2"]


def cliente_falso():
    def responder(pedido):
        ruta = pedido.url.path
        if ruta == "/caido":
            raise httpx.ConnectError("sin conexión")
        codigo = {"/ok": 200, "/movido": 301, "/robots": 403, "/no-existe": 404, "/roto": 500}[ruta]
        cabeceras = {"location": "https://x.com/ok"} if codigo == 301 else {}
        return httpx.Response(codigo, headers=cabeceras)
    return httpx.Client(transport=httpx.MockTransport(responder), follow_redirects=True)


def test_probar_link_clasifica_las_respuestas():
    with cliente_falso() as c:
        estados = {ruta: probar_link(f"https://x.com{ruta}", c).estado
                   for ruta in ["/ok", "/movido", "/robots", "/no-existe", "/roto", "/caido"]}
    assert estados == {"/ok": "OK", "/movido": "OK", "/robots": "AVISO", "/no-existe": "ERROR",
                       "/roto": "ERROR", "/caido": "ERROR"}


def test_revisar_links_respeta_el_orden():
    urls = ["https://x.com/no-existe", "https://x.com/ok"]
    estados = revisar_links(urls, CONFIG, cliente_falso())
    assert [(e.url, e.estado) for e in estados] == [(urls[0], "ERROR"), (urls[1], "OK")]
