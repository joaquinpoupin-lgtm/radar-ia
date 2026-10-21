"""Paso 13: simulacros de fallas (`radar correr --simular ...`), sin red ni claves reales."""

import json
from datetime import timedelta
from functools import partial

import httpx
import pytest

from radar.config import secreto
from radar.ia import IANoDisponible, pedir_json
from radar.pipeline import correr
from radar.simulacro import FUENTE_CAIDA, TransporteSinCuota, aplicar, cliente_ia, leer_simulacros
from test_pipeline import CONFIG, FUENTES, MANANA, dia, ejecutar, feed

GEMINI, GROQ = "generativelanguage.googleapis.com", "api.groq.com"


@pytest.fixture
def claves(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-falsa-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "clave-falsa-groq")


def groq_ok(pedido):
    """Groq de mentira que siempre contesta {"respuesta": "OK"}; cualquier otro servicio no debería llamarse."""
    assert pedido.url.host == GROQ
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"respuesta": "OK"}'}}]})


def test_leer_simulacros():
    assert leer_simulacros(None) == [] and leer_simulacros("") == []
    assert leer_simulacros(" cuota-todas , fuente-caida,cuota-todas") == ["cuota-todas", "fuente-caida"]
    with pytest.raises(ValueError, match="desconocido: inventado"):
        leer_simulacros("fuente-caida,inventado")


def test_cliente_ia_solo_con_simulacro_de_cuota():
    assert cliente_ia([], CONFIG) is None and cliente_ia(["fuente-caida"], CONFIG) is None
    assert cliente_ia(["cuota-gemini"], CONFIG)._transport.hosts == {GEMINI}
    assert cliente_ia(["cuota-todas"], CONFIG)._transport.hosts == {GEMINI, GROQ}


def test_sin_clave_gemini_la_ignora_y_usa_groq(claves):
    aplicar(["sin-clave-gemini"], FUENTES)
    assert secreto("GEMINI_API_KEY") is None and secreto("GROQ_API_KEY")
    esperas = []
    with httpx.Client(transport=httpx.MockTransport(groq_ok)) as cliente:
        assert pedir_json("hola", CONFIG, cliente, dormir=esperas.append) == {"respuesta": "OK"}
    assert esperas == []  # sin clave no se reintenta: va directo al respaldo


def test_cuota_gemini_reintenta_con_espera_y_pasa_a_groq(claves):
    esperas = []
    transporte = TransporteSinCuota({GEMINI}, real=httpx.MockTransport(groq_ok))
    with httpx.Client(transport=transporte) as cliente:
        assert pedir_json("hola", CONFIG, cliente, dormir=esperas.append) == {"respuesta": "OK"}
    assert esperas == [5, 10]  # 3 intentos con Gemini (espera creciente) y luego Groq


def test_cuota_todas_termina_sin_ia(claves):
    esperas = []
    transporte = TransporteSinCuota({GEMINI, GROQ}, real=httpx.MockTransport(groq_ok))
    with httpx.Client(transport=transporte) as cliente, pytest.raises(IANoDisponible) as e:
        pedir_json("hola", CONFIG, cliente, dormir=esperas.append)
    assert esperas == [5, 10, 5, 10]
    assert all("429" in f for f in e.value.fallos) and "clave-falsa" not in str(e.value.fallos)


def test_fuente_caida_se_suma_sin_tocar_las_demas():
    assert aplicar(["fuente-caida"], FUENTES) == FUENTES + [FUENTE_CAIDA]
    assert aplicar([], FUENTES) == FUENTES
    assert FUENTE_CAIDA.url.split("/")[2].endswith(".invalid")  # dominio reservado: nunca existe


def red_con_fuente_caida(ahora):
    feeds = {"a.com": feed("a.com", ["New open model released", "Agents get better"], ahora),
             "b.com": feed("b.com", ["A tool for prompts", "Another useful app"], ahora)}

    def responder(pedido):
        if pedido.url.host not in feeds:
            raise httpx.ConnectError("no existe el dominio", request=pedido)
        return httpx.Response(200, text=feeds[pedido.url.host])
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_simulacro_completo_queda_pendiente_y_se_resume_despues(tmp_path, claves):
    """Fuente caída + cuota agotada en las dos IA (pasando por las llamadas HTTP de verdad del código)."""
    esperas = []
    ia = httpx.Client(transport=TransporteSinCuota({GEMINI, GROQ}, real=httpx.MockTransport(groq_ok)))
    corrida = correr(CONFIG, MANANA, aplicar(["fuente-caida"], FUENTES), datos=tmp_path / "data",
                     destino=tmp_path / "_site", cliente_red=red_con_fuente_caida(MANANA), cliente_ia=ia,
                     pedir=partial(pedir_json, dormir=esperas.append))
    assert corrida.codigo == 0 and corrida.errores == []  # "en verde"
    assert corrida.nuevas == 0 and corrida.pendientes == 4 and corrida.sitio
    assert any("Simulacro: fuente caída" in a for a in corrida.avisos)
    assert any(a.startswith("IA:") for a in corrida.avisos)
    pendientes = json.loads((tmp_path / "data" / "pendientes.json").read_text(encoding="utf-8"))
    assert len(pendientes["grupos"]) == 4
    procesados = tmp_path / "data" / "cache" / "procesados.json"
    assert not procesados.exists() or json.loads(procesados.read_text()) == {}  # nada se marcó como resumido
    assert esperas  # sí hubo reintentos con espera

    # La corrida siguiente, ya sin simulacro, resume lo pendiente sin repetir nada.
    corrida = ejecutar(tmp_path, ahora=MANANA + timedelta(hours=6))
    assert corrida.codigo == 0 and corrida.nuevas == 4 and corrida.pendientes == 0
    assert len(dia(tmp_path)["noticias"]) == 4
