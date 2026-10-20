"""Carga de configuración (config.yaml) y de secretos (variables de entorno / .env)."""

import os
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.yaml"
RUTA_ENV = RAIZ / ".env"


def cargar_config(ruta: Path = RUTA_CONFIG) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_env(ruta: Path = RUTA_ENV) -> None:
    """Lee un .env simple (CLAVE=valor) sin pisar variables ya definidas.

    En GitHub Actions no hay .env: las claves llegan como variables de entorno (Secrets).
    """
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        if valor:
            os.environ.setdefault(clave.strip(), valor)


def secreto(nombre: str) -> str | None:
    """Devuelve una clave (o None). Nunca imprimir el valor."""
    cargar_env()
    return os.environ.get(nombre) or None
