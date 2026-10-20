import json

import httpx
import pytest

from radar.ia import ErrorIA, llamar, probar_proveedor, tabla_pruebas

CLAVE = "clave-secreta-de-prueba-123"


def respuesta_gemini(texto):
    return {"candidates": [{"content": {"parts": [{"text": texto}]}}]}


def respuesta_groq(texto):
    return {"choices": [{"message": {"content": texto}}]}


def cliente_falso(responder, pedidos=None):
    def manejar(pedido):
        if pedidos is not None:
            pedidos.append(pedido)
        return responder(pedido)

    return httpx.Client(transport=httpx.MockTransport(manejar))


@pytest.fixture
def con_claves(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", CLAVE)
    monkeypatch.setenv("GROQ_API_KEY", CLAVE)


def test_gemini_clave_va_en_cabecera_y_no_en_url():
    pedidos = []
    cliente = cliente_falso(lambda _: httpx.Response(200, json=respuesta_gemini('{"respuesta": "OK"}')), pedidos)
    texto = llamar("gemini", "gemini-x", "hola JSON", CLAVE, cliente)
    assert json.loads(texto) == {"respuesta": "OK"}
    pedido = pedidos[0]
    assert pedido.url.path.endswith("/models/gemini-x:generateContent")
    assert CLAVE not in str(pedido.url)
    assert pedido.headers["x-goog-api-key"] == CLAVE
    assert json.loads(pedido.content)["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_ignora_partes_de_razonamiento():
    datos = {"candidates": [{"content": {"parts": [
        {"text": "pensando...", "thought": True}, {"text": '{"respuesta": "OK"}'}]}}]}
    cliente = cliente_falso(lambda _: httpx.Response(200, json=datos))
    assert llamar("gemini", "m", "p", CLAVE, cliente) == '{"respuesta": "OK"}'


def test_groq_formato_openai_con_modo_json():
    pedidos = []
    cliente = cliente_falso(lambda _: httpx.Response(200, json=respuesta_groq('{"respuesta": "OK"}')), pedidos)
    llamar("groq", "openai/gpt-oss-120b", "hola JSON", CLAVE, cliente)
    cuerpo = json.loads(pedidos[0].content)
    assert pedidos[0].url.path.endswith("/chat/completions")
    assert pedidos[0].headers["authorization"] == f"Bearer {CLAVE}"
    assert cuerpo["model"] == "openai/gpt-oss-120b"
    assert cuerpo["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("status, cuerpo, motivo", [
    (400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid."}}, "clave"),
    (401, {"error": {"message": "Invalid API Key"}}, "clave"),
    (404, {"error": {"message": "models/x is not found"}}, "modelo"),
    (400, {"error": {"code": "model_decommissioned", "message": "decommissioned"}}, "modelo"),
    (429, {"error": {"message": "quota"}}, "cuota"),
    (503, {}, "red"),
])
def test_errores_http_se_traducen(status, cuerpo, motivo):
    cliente = cliente_falso(lambda _: httpx.Response(status, json=cuerpo))
    with pytest.raises(ErrorIA) as e:
        llamar("groq", "m", "p", CLAVE, cliente)
    assert e.value.motivo == motivo


def test_sin_conexion_es_error_de_red():
    def caido(pedido):
        raise httpx.ConnectError("sin red", request=pedido)

    with pytest.raises(ErrorIA) as e:
        llamar("gemini", "m", "p", CLAVE, cliente_falso(caido))
    assert e.value.motivo == "red"


def test_probar_ok(con_claves):
    cliente = cliente_falso(lambda _: httpx.Response(200, json=respuesta_groq('{"respuesta": "ok"}')))
    prueba = probar_proveedor("respaldo", "groq", "m", cliente)
    assert prueba.estado == "OK"
    assert "respondió en" in prueba.detalle


def test_probar_sin_clave_dice_donde_sacarla(monkeypatch):
    monkeypatch.setattr("radar.ia.secreto", lambda nombre: None)
    prueba = probar_proveedor("principal", "gemini", "m", cliente_falso(lambda _: httpx.Response(500)))
    assert prueba.estado == "FALTA CLAVE"
    assert "GEMINI_API_KEY" in prueba.detalle and "aistudio.google.com" in prueba.detalle


def test_modelo_inexistente_sugiere_otros(con_claves):
    def responder(pedido):
        if pedido.method == "GET":
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]})
        return httpx.Response(404, json={"error": {"message": "not found"}})

    prueba = probar_proveedor("principal", "gemini", "gemini-viejo", cliente_falso(responder))
    assert prueba.estado == "ERROR"
    assert prueba.sugeridos == ("gemini-3.5-flash-lite",)
    assert "gemini-3.5-flash-lite" in tabla_pruebas([prueba])


def test_respuesta_rara_es_error(con_claves):
    cliente = cliente_falso(lambda _: httpx.Response(200, json=respuesta_gemini("no es json")))
    assert probar_proveedor("principal", "gemini", "m", cliente).estado == "ERROR"


def test_la_clave_nunca_aparece_en_la_salida(con_claves):
    casos = [
        lambda _: httpx.Response(200, json=respuesta_groq('{"respuesta": "OK"}')),
        lambda _: httpx.Response(401, json={"error": {"message": f"bad key {CLAVE}"}}),
        lambda _: httpx.Response(429, text=CLAVE),
    ]
    pruebas = [probar_proveedor("respaldo", "groq", "m", cliente_falso(r)) for r in casos]
    assert CLAVE not in tabla_pruebas(pruebas)
