"""Guardia: ninguna clave puede quedar en los archivos que se suben a GitHub.

Los mensajes de error nombran solo el archivo, nunca la clave.
"""

import os
import re
import subprocess

from radar.config import RAIZ

NOMBRES_CLAVES = ["GEMINI_API_KEY", "GROQ_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
PATRONES = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # forma de las claves de Google (Gemini)
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),  # forma de las claves de Groq
]


def _archivos_versionados() -> list[str]:
    salida = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return [a for a in salida.splitlines() if a]


def _valores_reales() -> list[str]:
    """Las claves de verdad, si están cargadas (del .env en local o de Secrets en Actions)."""
    valores = [os.environ.get(n, "") for n in NOMBRES_CLAVES]
    ruta_env = RAIZ / ".env"
    if ruta_env.exists():
        for linea in ruta_env.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                valores.append(linea.split("=", 1)[1].strip().strip('"').strip("'"))
    return [v for v in valores if len(v) >= 8]


def test_env_no_se_sube():
    assert ".env" not in _archivos_versionados()


def test_env_example_solo_tiene_nombres():
    for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.startswith("#"):
            assert linea.split("=", 1)[1].strip() == "", f".env.example trae un valor: {linea.split('=')[0]}"


def test_ninguna_clave_en_archivos_versionados():
    valores = _valores_reales()
    con_claves = []
    for archivo in _archivos_versionados():
        ruta = RAIZ / archivo
        if not ruta.is_file():
            continue
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        if any(p.search(texto) for p in PATRONES) or any(v in texto for v in valores):
            con_claves.append(archivo)
    assert con_claves == [], f"Posible clave en: {', '.join(con_claves)}"
