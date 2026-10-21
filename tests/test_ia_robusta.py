"""Paso 6: reintentos, respaldo y pendientes con un proveedor falso (sin red ni claves reales)."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from radar.agrupar import agrupar
from radar.config import cargar_config
from radar.filtrar import (actualizar_pendientes, cargar_pendientes, guardar_pendientes, marcar_procesados,
                           prefiltrar, sumar_pendientes)
from radar.ia import IANoDisponible, pedir_json
from radar.recolectar import Candidato

CONFIG = cargar_config()
CLAVE = "clave-secreta-de-prueba-123"
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def ok_gemini(datos):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(datos)}]}}]})


def ok_groq(datos):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(datos)}}]})


class Falso:
    """Proveedor falso: cada servicio responde según una lista de respuestas (la última se repite)."""

    def __init__(self, gemini, groq):
        self.guion = {"generativelanguage.googleapis.com": list(gemini), "api.groq.com": list(groq)}
        self.pedidos = {"generativelanguage.googleapis.com": 0, "api.groq.com": 0}
        self.esperas = []

    def manejar(self, pedido):
        host = pedido.url.host
        self.pedidos[host] += 1
        lista = self.guion[host]
        respuesta = lista.pop(0) if len(lista) > 1 else lista[0]
        return respuesta(pedido) if callable(respuesta) else respuesta

    def pedir(self, prompt="dame JSON", validar=None, config=CONFIG):
        cliente = httpx.Client(transport=httpx.MockTransport(self.manejar))
        return pedir_json(prompt, config, cliente, validar, dormir=self.esperas.append)

    @property
    def gemini(self):
        return self.pedidos["generativelanguage.googleapis.com"]

    @property
    def groq(self):
        return self.pedidos["api.groq.com"]


@pytest.fixture(autouse=True)
def claves(monkeypatch):
    # Nunca se leen las claves reales del .env.
    valores = {"GEMINI_API_KEY": CLAVE, "GROQ_API_KEY": CLAVE}
    monkeypatch.setattr("radar.ia.secreto", lambda nombre: valores.get(nombre))
    return valores


CUOTA = httpx.Response(429, json={"error": {"message": "quota"}})
CAIDO = httpx.Response(503)


def test_429_reintenta_con_espera_creciente():
    falso = Falso([CUOTA, CUOTA, ok_gemini({"a": 1})], [ok_groq({"b": 2})])
    assert falso.pedir() == {"a": 1}
    assert falso.esperas == [5, 10]  # espera_inicial_seg, luego el doble
    assert falso.groq == 0


def test_respeta_la_espera_que_pide_el_servicio_con_tope():
    pide_3 = httpx.Response(429, headers={"Retry-After": "3"})
    gemini_pide_mucho = httpx.Response(429, text='{"error": {"details": [{"retryDelay": "500s"}]}}')
    falso = Falso([pide_3, gemini_pide_mucho, ok_gemini({"a": 1})], [CAIDO])
    falso.pedir()
    assert falso.esperas == [3, CONFIG["ia"]["espera_max_seg"]]


def test_gemini_agotado_pasa_a_groq():
    falso = Falso([CUOTA], [ok_groq({"b": 2})])
    assert falso.pedir() == {"b": 2}
    assert falso.gemini == CONFIG["ia"]["reintentos"]


def test_clave_invalida_no_reintenta_y_pasa_al_respaldo():
    falso = Falso([httpx.Response(401)], [ok_groq({"b": 2})])
    assert falso.pedir() == {"b": 2}
    assert falso.gemini == 1 and falso.esperas == []


def test_sin_clave_de_gemini_usa_groq(claves):
    del claves["GEMINI_API_KEY"]
    falso = Falso([ok_gemini({"a": 1})], [ok_groq({"b": 2})])
    assert falso.pedir() == {"b": 2}
    assert falso.gemini == 0


def test_sin_conexion_cuenta_como_caida():
    def sin_red(pedido):
        raise httpx.ConnectError("sin red", request=pedido)

    falso = Falso([sin_red, ok_gemini({"a": 1})], [CAIDO])
    assert falso.pedir() == {"a": 1}
    assert falso.esperas == [5]


def test_respuesta_rara_se_pide_otra_vez_sin_esperar():
    falso = Falso([httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hola"}]}}]}),
                   ok_gemini({"a": 1})], [CAIDO])
    assert falso.pedir() == {"a": 1}
    assert falso.gemini == 2 and falso.esperas == []


def test_formato_invalido_dos_veces_pasa_al_respaldo():
    def validar(datos):
        if "b" not in datos:
            raise ValueError("falta b")

    falso = Falso([ok_gemini({"a": 1})], [ok_groq({"b": 2})])
    assert falso.pedir(validar=validar) == {"b": 2}
    assert falso.gemini == 2


def test_ambos_caidos_lanza_ia_no_disponible_sin_mostrar_la_clave(capsys):
    falso = Falso([httpx.Response(429, text=CLAVE)], [CAIDO])
    with pytest.raises(IANoDisponible) as e:
        falso.pedir()
    assert len(e.value.fallos) == 2
    assert CLAVE not in str(e.value) and CLAVE not in capsys.readouterr().out
    assert falso.esperas == [5, 10, 5, 10]


# --- Pendientes ---

def cand(titulo, url, fuente="Blog", horas=1, peso=2):
    return Candidato(titulo=titulo, url=url, fuente=fuente, tipo="rss", seccion="modelos", idioma="en",
                     peso=peso, fecha=AHORA - timedelta(hours=horas), extracto="extracto corto")


def grupos(*candidatos):
    return agrupar(list(candidatos), CONFIG["limites"]["similitud_titulos"])


def test_lo_pendiente_se_reintenta_en_la_corrida_siguiente(tmp_path):
    ruta = tmp_path / "pendientes.json"
    procesados = {}

    # Corrida 1: la IA está caída → lo elegido queda pendiente y no se marca como procesado.
    frescos = grupos(cand("Small model release", "https://a.com/chico", peso=1))
    elegidas = [g for g, _ in prefiltrar(frescos, procesados, CONFIG, AHORA).elegidas]
    with pytest.raises(IANoDisponible):
        Falso([CUOTA], [CAIDO]).pedir()
    guardar_pendientes(actualizar_pendientes(cargar_pendientes(ruta), elegidas, procesados, CONFIG, AHORA),
                       AHORA, ruta)
    assert procesados == {}

    # Corrida 2: la noticia ya no sale en el feed y hay otras con más puntaje, igual va primero.
    pendientes = cargar_pendientes(ruta)
    assert [g.titulo for g in pendientes] == ["Small model release"]
    assert pendientes[0].principal.extracto == "extracto corto"
    frescos = grupos(*(cand(f"Big news number {i}", f"https://b{i}.com/x", f"Fuente {i}", peso=3)
                       for i in range(12)))
    r = prefiltrar(sumar_pendientes(frescos, pendientes), procesados, CONFIG, AHORA + timedelta(hours=6),
                   pendientes=pendientes)
    assert r.elegidas[0][0].titulo == "Small model release" and r.pendientes == 1
    elegidas = [g for g, _ in r.elegidas]
    assert Falso([ok_gemini({"ok": True})], [CAIDO]).pedir() == {"ok": True}
    marcar_procesados(procesados, elegidas, "2026-10-20")
    guardar_pendientes(actualizar_pendientes(pendientes, [], procesados, CONFIG, AHORA), AHORA, ruta)
    assert cargar_pendientes(ruta) == []


def test_pendiente_que_vuelve_a_aparecer_no_se_duplica():
    [pendiente] = grupos(cand("Tool launch", "https://a.com/t"))
    frescos = grupos(cand("Tool launch", "https://a.com/t"), cand("Tool launch", "https://a.com/t", "HN"))
    juntos = sumar_pendientes(frescos, [pendiente])
    assert len(juntos) == 1 and juntos[0].confirmacion == 2


def test_pendientes_viejos_se_olvidan():
    viejo = grupos(cand("Old news", "https://a.com/v", horas=24 * 5))
    assert actualizar_pendientes(viejo, [], {}, CONFIG, AHORA) == []


def test_pendientes_dañado_no_rompe(tmp_path, capsys):
    ruta = tmp_path / "pendientes.json"
    ruta.write_text("{no es json", encoding="utf-8")
    assert cargar_pendientes(ruta) == []
    assert "Aviso" in capsys.readouterr().out


def test_opciones_de_config_van_en_el_pedido_y_el_400_muestra_el_codigo():
    import copy
    config = copy.deepcopy(CONFIG)
    config["ia"]["respaldo"]["opciones"] = {"reasoning_effort": "low"}
    cuerpos = []

    def groq(pedido):
        cuerpos.append(json.loads(pedido.content))
        return ok_groq({"b": 2})

    rechazo = httpx.Response(400, json={"error": {"code": "json_validate_failed", "message": "texto largo"}})
    falso = Falso([rechazo], [groq])
    assert falso.pedir(config=config) == {"b": 2}
    assert cuerpos[0]["reasoning_effort"] == "low"
    with pytest.raises(IANoDisponible, match=r"pedido rechazado \(json_validate_failed\)"):
        Falso([rechazo], [CAIDO]).pedir()
