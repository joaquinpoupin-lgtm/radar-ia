from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from radar.config import cargar_config
from radar.fuentes import ErrorFuentes, Fuente, cargar_fuentes, probar_fuente, probar_todas, tabla

FIXTURES = Path(__file__).parent / "fixtures"
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
RSS = Fuente("Blog", "rss", "https://ejemplo.com/feed", "modelos", "en", 3)
HN = Fuente("HN", "hackernews", "https://hn.algolia.com/api/v1/x", "tendencias", "en", 2)


def cliente_falso(status=200, contenido=b"", json=None):
    def responder(_pedido):
        if json is not None:
            return httpx.Response(status, json=json)
        return httpx.Response(status, content=contenido)

    return httpx.Client(transport=httpx.MockTransport(responder))


def escribir(tmp_path, texto):
    ruta = tmp_path / "sources.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_sources_yaml_real_es_valido():
    fuentes = cargar_fuentes()
    assert len(fuentes) >= 20
    assert len({f.nombre for f in fuentes}) == len(fuentes)
    assert sum(f.tipo == "youtube" for f in fuentes) >= 8
    assert any(f.tipo == "hackernews" for f in fuentes)


def test_errores_se_juntan_en_un_mensaje(tmp_path):
    ruta = escribir(tmp_path, """
fuentes:
  - {nombre: A, tipo: twitter, url: https://a.com, seccion: modelos, idioma: en, peso: 3}
  - {nombre: B, tipo: rss, url: https://b.com, seccion: chismes, idioma: fr, peso: 7}
  - {nombre: A, tipo: rss, url: ftp://a.com, seccion: tips, idioma: es, peso: 1}
  - {nombre: C, tipo: rss}
""")
    with pytest.raises(ErrorFuentes) as e:
        cargar_fuentes(ruta)
    mensaje = str(e.value)
    for esperado in ("tipo 'twitter'", "sección 'chismes'", "idioma 'fr'", "peso", "https://",
                     "nombre repetido", "faltan campos: url, seccion, idioma, peso"):
        assert esperado in mensaje


def test_fuentes_inactivas_se_omiten(tmp_path):
    ruta = escribir(tmp_path, """
fuentes:
  - {nombre: A, tipo: rss, url: https://a.com, seccion: modelos, idioma: en, peso: 3}
  - {nombre: B, tipo: rss, url: https://b.com, seccion: modelos, idioma: en, peso: 3, activa: false}
""")
    assert [f.nombre for f in cargar_fuentes(ruta)] == ["A"]
    assert len(cargar_fuentes(ruta, solo_activas=False)) == 2


def test_rss_ok_cuenta_items_y_fecha():
    contenido = (FIXTURES / "feed_ejemplo.xml").read_bytes()
    r = probar_fuente(RSS, cliente_falso(contenido=contenido), AHORA, 90)
    assert (r.estado, r.items) == ("OK", 2)
    assert r.ultima == datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def test_rss_viejo_da_aviso():
    contenido = (FIXTURES / "feed_ejemplo.xml").read_bytes()
    r = probar_fuente(RSS, cliente_falso(contenido=contenido), datetime(2026, 10, 24, 16, tzinfo=timezone.utc), 3)
    assert r.estado == "AVISO" and "hace 5 días" in r.detalle


@pytest.mark.parametrize("status, esperado", [(404, "ya no existe"), (429, "demasiados pedidos"), (500, "HTTP 500")])
def test_errores_http(status, esperado):
    r = probar_fuente(RSS, cliente_falso(status=status), AHORA, 90)
    assert r.estado == "ERROR" and esperado in r.detalle


def test_contenido_que_no_es_rss():
    r = probar_fuente(RSS, cliente_falso(contenido=b"<html><body>hola</body"), AHORA, 90)
    assert r.estado == "ERROR"


def test_sin_conexion_no_lanza_excepcion():
    def caida(pedido):
        raise httpx.ConnectError("sin red", request=pedido)

    r = probar_fuente(RSS, httpx.Client(transport=httpx.MockTransport(caida)), AHORA, 90)
    assert r.estado == "ERROR" and "conexión" in r.detalle


def test_hacker_news():
    hits = [{"title": "x", "created_at_i": 1792940400}, {"title": "y", "created_at_i": 1792926000}]
    r = probar_fuente(HN, cliente_falso(json={"hits": hits}), AHORA, 90)
    assert (r.estado, r.items) == ("OK", 2)
    assert r.ultima == datetime.fromtimestamp(1792940400, timezone.utc)
    assert probar_fuente(HN, cliente_falso(json={"otra": 1}), AHORA, 90).estado == "ERROR"


def test_tabla_mantiene_orden_y_resume():
    contenido = (FIXTURES / "feed_ejemplo.xml").read_bytes()
    caida = Fuente("Caída", "rss", "https://caida.com", "tips", "es", 1)

    def responder(pedido):
        if "caida" in str(pedido.url):
            return httpx.Response(404)
        return httpx.Response(200, content=contenido)

    resultados = probar_todas([RSS, caida], cargar_config(), AHORA,
                              httpx.Client(transport=httpx.MockTransport(responder)))
    assert [r.fuente.nombre for r in resultados] == ["Blog", "Caída"]
    texto = tabla(resultados, AHORA)
    assert "ayer" in texto
    assert "2 fuentes: 1 OK · 0 con aviso · 1 con error" in texto
