"""Simulacros de fallas para `radar correr --simular ...` (Paso 13).

Sirven para comprobar, en el Mac o en GitHub Actions, que la corrida aguanta lo que puede pasar de verdad
sin tener que borrar claves ni esperar a que se agote la cuota. Solo afectan a la corrida en curso:
no tocan `.env`, los Secrets ni `sources.yaml`.

- `sin-clave-gemini`: se ignora la clave de Gemini → todo debe pasar por Groq.
- `cuota-gemini`: Gemini responde 429 (cuota agotada) → reintentos con espera y luego Groq.
- `cuota-todas`: Gemini y Groq responden 429 → lo elegido queda en `data/pendientes.json`.
- `fuente-caida`: se suma una fuente que no existe → se avisa y el resto sigue.
"""

import os
from urllib.parse import urlsplit

import httpx

from radar.fuentes import Fuente
from radar.ia import PROVEEDORES

SIMULACROS = {
    "sin-clave-gemini": "se ignora la clave de Gemini (todo debe ir por Groq)",
    "cuota-gemini": "Gemini responde 429 como si la cuota estuviera agotada",
    "cuota-todas": "Gemini y Groq responden 429 (lo elegido debe quedar pendiente)",
    "fuente-caida": "se suma una fuente que no existe",
}

# El dominio .invalid está reservado: nunca existe, así que la fuente siempre falla.
FUENTE_CAIDA = Fuente("Simulacro: fuente caída", "rss", "https://fuente-caida.invalid/feed.xml",
                      "modelos", "es", 1)


def leer_simulacros(texto: str | None) -> list[str]:
    """"cuota-todas, fuente-caida" → ["cuota-todas", "fuente-caida"]. Lanza ValueError si alguno no existe."""
    nombres = [n.strip() for n in (texto or "").split(",") if n.strip()]
    desconocidos = [n for n in nombres if n not in SIMULACROS]
    if desconocidos:
        raise ValueError(f"simulacro desconocido: {', '.join(desconocidos)} "
                         f"(opciones: {', '.join(SIMULACROS)})")
    return list(dict.fromkeys(nombres))


def _host(proveedor: str) -> str:
    return urlsplit(PROVEEDORES[proveedor][1]).hostname


class TransporteSinCuota(httpx.BaseTransport):
    """Responde 429 a los servicios de IA indicados; el resto de los pedidos sale de verdad."""

    def __init__(self, hosts: set[str], real: httpx.BaseTransport | None = None):
        self.hosts = hosts
        self.real = real or httpx.HTTPTransport()

    def handle_request(self, pedido: httpx.Request) -> httpx.Response:
        if pedido.url.host in self.hosts:
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED",
                                                       "message": "simulacro: cuota agotada"}})
        return self.real.handle_request(pedido)

    def close(self) -> None:
        self.real.close()


def cliente_ia(simulacros: list[str], config: dict) -> httpx.Client | None:
    """Cliente HTTP para la IA con la cuota "agotada", o None si no hay simulacro de cuota."""
    if "cuota-todas" in simulacros:
        hosts = {_host(p) for p in PROVEEDORES}
    elif "cuota-gemini" in simulacros:
        hosts = {_host("gemini")}
    else:
        return None
    return httpx.Client(timeout=config["ia"]["timeout_seg"], transport=TransporteSinCuota(hosts))


def aplicar(simulacros: list[str], fuentes: list[Fuente]) -> list[Fuente]:
    """Aplica los simulacros que no son de red y devuelve las fuentes con las que correr."""
    if "sin-clave-gemini" in simulacros:
        # Vacía (no borra) la variable: así el .env no la vuelve a cargar y `secreto()` la ve como faltante.
        os.environ[PROVEEDORES["gemini"][0]] = ""
    if "fuente-caida" in simulacros:
        fuentes = fuentes + [FUENTE_CAIDA]
    return fuentes
