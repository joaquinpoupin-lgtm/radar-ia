"""Llamadas a la IA (Gemini y Groq) con `httpx` + comando `probar-ia`.

`llamar()` hace una sola llamada (Paso 5); `pedir_json()` suma reintentos con espera creciente
y el cambio al proveedor de respaldo (Paso 6). Las claves van en una cabecera (nunca en la URL)
y jamás se imprimen.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from radar.config import cargar_config, secreto

# Proveedor → (variable con la clave, dirección base de su API)
PROVEEDORES = {
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
}

DONDE_SACAR_CLAVE = {
    "gemini": "https://aistudio.google.com/apikey",
    "groq": "https://console.groq.com/keys",
}

PROMPT_PRUEBA = 'Responde solo con este JSON, sin nada más: {"respuesta": "OK"}'


class ErrorIA(Exception):
    """La IA no respondió bien. `motivo` es una palabra corta: clave, modelo, cuota, red, respuesta."""

    def __init__(self, mensaje: str, motivo: str, status: int | None = None, espera: float | None = None):
        super().__init__(mensaje)
        self.motivo = motivo
        self.status = status
        self.espera = espera  # segundos que el servicio pidió esperar antes de reintentar (si lo dijo)


class IANoDisponible(Exception):
    """Ni el proveedor principal ni el de respaldo respondieron bien: lo pedido queda pendiente."""

    def __init__(self, fallos: list[str]):
        super().__init__("la IA no está disponible: " + "; ".join(fallos))
        self.fallos = fallos


def _cabeceras(proveedor: str, clave: str) -> dict:
    if proveedor == "gemini":
        return {"x-goog-api-key": clave}
    return {"Authorization": f"Bearer {clave}"}


def _espera_pedida(respuesta: httpx.Response) -> float | None:
    """Cuánto pide esperar el servicio: cabecera Retry-After o, en Gemini, "retryDelay": "34s" en el cuerpo."""
    try:
        return float(respuesta.headers["retry-after"])
    except (KeyError, ValueError):
        pass
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', respuesta.text)
    return float(m.group(1)) if m else None


def _codigo_error(respuesta: httpx.Response) -> str:
    """Solo el código corto del error (p. ej. "json_validate_failed"), nunca el mensaje completo."""
    try:
        error = respuesta.json().get("error", {})
        codigo = str(error.get("code") or error.get("status") or "")
    except (ValueError, AttributeError):
        return ""
    return f" ({codigo})" if re.fullmatch(r"[A-Za-z_]{3,40}", codigo) else ""


def _error_http(respuesta: httpx.Response, proveedor: str) -> ErrorIA:
    """Traduce un error HTTP a un motivo legible (sin copiar el cuerpo, por si trae datos sensibles)."""
    s = respuesta.status_code
    texto = respuesta.text.lower()
    if s in (401, 403) or "api_key_invalid" in texto or "api key not valid" in texto:
        return ErrorIA(f"HTTP {s}: la clave no es válida o no tiene permiso", "clave", s)
    if s == 404 or "model_not_found" in texto or "does not exist" in texto or "decommissioned" in texto:
        return ErrorIA(f"HTTP {s}: el modelo no existe o ya no está disponible", "modelo", s)
    if s == 429:
        return ErrorIA("HTTP 429: cuota del plan gratis agotada por ahora (probar más tarde)", "cuota", s,
                       _espera_pedida(respuesta))
    if s >= 500:
        return ErrorIA(f"HTTP {s}: el servicio de {proveedor} tiene problemas (probar más tarde)", "red", s,
                       _espera_pedida(respuesta))
    return ErrorIA(f"HTTP {s}: pedido rechazado{_codigo_error(respuesta)}", "respuesta", s)


def _post(cliente: httpx.Client, url: str, cabeceras: dict, cuerpo: dict, proveedor: str) -> dict:
    try:
        respuesta = cliente.post(url, headers=cabeceras, json=cuerpo)
    except httpx.TimeoutException:
        raise ErrorIA(f"{proveedor} no respondió a tiempo", "red")
    except httpx.HTTPError as e:
        raise ErrorIA(f"error de conexión con {proveedor} ({type(e).__name__})", "red")
    if respuesta.status_code != 200:
        raise _error_http(respuesta, proveedor)
    try:
        return respuesta.json()
    except json.JSONDecodeError:
        raise ErrorIA(f"{proveedor} devolvió algo que no es JSON", "respuesta")


def llamar(proveedor: str, modelo: str, prompt: str, clave: str, cliente: httpx.Client,
           opciones: dict | None = None) -> str:
    """Manda un prompt y devuelve el texto de la respuesta (se pide en formato JSON).

    `opciones` (de config.yaml) se suman al pedido: en Gemini dentro de `generationConfig`, en Groq arriba.
    """
    opciones = opciones or {}
    if proveedor not in PROVEEDORES:
        raise ErrorIA(f"proveedor '{proveedor}' no existe (usar: {', '.join(PROVEEDORES)})", "respuesta")
    base = PROVEEDORES[proveedor][1]
    cabeceras = _cabeceras(proveedor, clave)

    if proveedor == "gemini":
        datos = _post(cliente, f"{base}/models/{modelo}:generateContent", cabeceras, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", **opciones},
        }, proveedor)
        try:
            partes = datos["candidates"][0]["content"]["parts"]
            # Los modelos que "piensan" pueden devolver partes de razonamiento: se ignoran.
            texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            raise ErrorIA("gemini respondió sin texto (¿bloqueado o vacío?)", "respuesta")
    else:
        datos = _post(cliente, f"{base}/chat/completions", cabeceras, {
            "model": modelo,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            **opciones,
        }, proveedor)
        try:
            texto = datos["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ErrorIA("groq respondió sin texto", "respuesta")

    if not texto.strip():
        raise ErrorIA(f"{proveedor} respondió vacío", "respuesta")
    return texto


def pedir_json(prompt: str, config: dict, cliente: httpx.Client,
               validar: Callable[[dict], None] | None = None,
               dormir: Callable[[float], None] = time.sleep) -> dict:
    """La única puerta a la IA: devuelve la respuesta como dict o lanza `IANoDisponible`.

    - Cuota (429) o servicio caído/lento: espera `espera_inicial_seg`, luego el doble, etc. (o lo que pida
      el servicio, hasta `espera_max_seg`) y reintenta hasta `reintentos` veces.
    - Clave inválida o modelo inexistente: reintentar no sirve → pasa directo al respaldo.
    - Respuesta que no es JSON o que `validar` rechaza (lanza ValueError): se pide una vez más y luego
      pasa al respaldo.
    """
    ia = config["ia"]
    fallos = []
    for rol in ("principal", "respaldo"):
        proveedor, modelo = ia[rol]["proveedor"], ia[rol]["modelo"]
        variable = PROVEEDORES.get(proveedor, ("?",))[0]
        clave = secreto(variable)
        if not clave:
            fallos.append(f"{proveedor}: falta {variable}")
            if rol == "principal":
                print(f"  IA: falta {variable}; se usa el respaldo ({ia['respaldo']['proveedor']})")
            continue
        respuestas_malas = 0
        for intento in range(ia["reintentos"]):
            try:
                texto = llamar(proveedor, modelo, prompt, clave, cliente, ia[rol].get("opciones"))
                try:
                    datos = json.loads(texto)
                except json.JSONDecodeError:
                    raise ErrorIA(f"{proveedor} respondió algo que no es JSON válido", "respuesta")
                if not isinstance(datos, dict):
                    raise ErrorIA(f"{proveedor} respondió JSON, pero no un objeto", "respuesta")
                if validar:
                    try:
                        validar(datos)
                    except ValueError as e:
                        raise ErrorIA(f"{proveedor} respondió fuera del formato pedido ({e})", "respuesta")
                return datos
            except ErrorIA as e:
                motivo = str(e).replace(clave, "***")
                ultimo = intento + 1 >= ia["reintentos"]
                if e.motivo in ("clave", "modelo"):
                    fallos.append(f"{proveedor}: {motivo}")
                    break
                if e.motivo == "respuesta":
                    respuestas_malas += 1
                    if respuestas_malas >= 2 or ultimo:
                        fallos.append(f"{proveedor}: {motivo}")
                        break
                    print(f"  IA: {motivo}; se pide de nuevo")
                    continue
                if ultimo:
                    fallos.append(f"{proveedor}: {motivo} (tras {ia['reintentos']} intentos)")
                    break
                espera = min(e.espera or ia["espera_inicial_seg"] * 2 ** intento, ia["espera_max_seg"])
                print(f"  IA: {motivo}; reintento en {espera:g} s")
                dormir(espera)
        if rol == "principal":
            print(f"  IA: {proveedor} no respondió; se usa el respaldo ({ia['respaldo']['proveedor']})")
    raise IANoDisponible(fallos)


def modelos_disponibles(proveedor: str, clave: str, cliente: httpx.Client) -> list[str]:
    """Modelos de texto que esa clave puede usar (para sugerir uno si el de config.yaml no existe)."""
    base = PROVEEDORES[proveedor][1]
    try:
        respuesta = cliente.get(f"{base}/models", headers=_cabeceras(proveedor, clave),
                                params={"pageSize": 1000} if proveedor == "gemini" else None)
        respuesta.raise_for_status()
        datos = respuesta.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []
    if proveedor == "gemini":
        return sorted(m["name"].removeprefix("models/") for m in datos.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))
    return sorted(m["id"] for m in datos.get("data", []) if m.get("active", True))


@dataclass
class Prueba:
    rol: str          # principal | respaldo
    proveedor: str
    modelo: str
    estado: str       # OK | ERROR | FALTA CLAVE
    detalle: str = ""
    sugeridos: tuple[str, ...] = ()


def probar_proveedor(rol: str, proveedor: str, modelo: str, cliente: httpx.Client) -> Prueba:
    """Hace una llamada mínima. Nunca lanza excepciones y nunca incluye la clave en el resultado."""
    variable = PROVEEDORES.get(proveedor, ("?",))[0]
    clave = secreto(variable)
    if not clave:
        return Prueba(rol, proveedor, modelo, "FALTA CLAVE",
                      f"falta {variable} en .env (sacarla gratis en {DONDE_SACAR_CLAVE.get(proveedor, '?')})")
    inicio = time.monotonic()
    try:
        texto = llamar(proveedor, modelo, PROMPT_PRUEBA, clave, cliente)
        respuesta = json.loads(texto)
    except ErrorIA as e:
        sugeridos = ()
        if e.motivo == "modelo":
            sugeridos = tuple(modelos_disponibles(proveedor, clave, cliente))
        return Prueba(rol, proveedor, modelo, "ERROR", str(e).replace(clave, "***"), sugeridos)
    except json.JSONDecodeError:
        return Prueba(rol, proveedor, modelo, "ERROR", "respondió, pero no en JSON válido")
    segundos = time.monotonic() - inicio
    if not isinstance(respuesta, dict) or str(respuesta.get("respuesta", "")).strip().upper() != "OK":
        return Prueba(rol, proveedor, modelo, "ERROR", "respondió, pero no lo que se pidió")
    return Prueba(rol, proveedor, modelo, "OK", f"respondió en {segundos:.1f} s".replace(".", ","))


def tabla_pruebas(pruebas: list[Prueba]) -> str:
    filas = [("Estado", "Rol", "Proveedor", "Modelo", "Detalle")]
    filas += [(p.estado, p.rol, p.proveedor, p.modelo, p.detalle) for p in pruebas]
    anchos = [max(len(f[i]) for f in filas) for i in range(len(filas[0]) - 1)]
    lineas = ["  ".join(c.ljust(a) for c, a in zip(f, anchos)) + "  " + f[-1] for f in filas]
    lineas.insert(1, "-" * len(lineas[0]))
    for p in pruebas:
        if p.sugeridos:
            # Para elegir otro modelo: mostrar los livianos primero (Flash-Lite / modelos chicos).
            livianos = [m for m in p.sugeridos if "lite" in m or "flash" in m or "gpt-oss" in m or "qwen" in m]
            lista = (livianos or list(p.sugeridos))[:12]
            lineas.append("")
            lineas.append(f"Modelos que tu clave de {p.proveedor} sí puede usar (cambiar en config.yaml → ia):")
            lineas += [f"  - {m}" for m in lista]
    return "\n".join(l.rstrip() for l in lineas)


def comando_probar_ia(_args) -> int:
    config = cargar_config()
    ia = config["ia"]
    print("Probando la IA (las claves nunca se muestran)...\n")
    with httpx.Client(timeout=ia["timeout_seg"]) as cliente:
        pruebas = [probar_proveedor(rol, ia[rol]["proveedor"], ia[rol]["modelo"], cliente)
                   for rol in ("principal", "respaldo")]
    print(tabla_pruebas(pruebas))
    return 0 if all(p.estado == "OK" for p in pruebas) else 1
