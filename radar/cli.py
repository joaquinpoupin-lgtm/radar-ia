"""Comandos de Radar IA: `python -m radar <comando>`."""

import argparse
import sys

from radar.filtrar import comando_filtrar
from radar.fuentes import comando_fuentes
from radar.recolectar import comando_recolectar

# Comandos planeados: (nombre, descripción, paso del plan que lo implementa).
# Al implementar uno, reemplazar su función en COMANDOS.
PLANEADOS = [
    ("fuentes", "Prueba cada fuente de sources.yaml y muestra cuáles funcionan", 1),
    ("recolectar", "Trae noticias candidatas de todas las fuentes", 2),
    ("filtrar", "Muestra qué noticias nuevas se mandarían a la IA (sin usar la IA)", 4),
    ("probar-ia", "Comprueba que las claves de Gemini y Groq funcionan", 5),
    ("sitio", "Genera el sitio web estático en _site/ a partir de data/", 9),
    ("correr", "Corrida completa: recolectar, resumir, guardar y generar sitio", 10),
]


def _pendiente(paso: int):
    def comando(_args) -> int:
        print(f"Aún no implementado (Paso {paso} del plan).")
        return 1

    return comando


COMANDOS = {nombre: _pendiente(paso) for nombre, _, paso in PLANEADOS}
COMANDOS["fuentes"] = comando_fuentes
COMANDOS["recolectar"] = comando_recolectar
COMANDOS["filtrar"] = comando_filtrar


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Radar IA: noticias de inteligencia artificial resumidas en español simple.",
    )
    sub = parser.add_subparsers(dest="comando", metavar="<comando>")
    for nombre, descripcion, _ in PLANEADOS:
        sub.add_parser(nombre, help=descripcion, description=descripcion)
    sub.choices["recolectar"].add_argument(
        "--mostrar", type=int, default=0, metavar="N", help="muestra N candidatos de ejemplo")
    sub.choices["recolectar"].add_argument(
        "--grupos", action="store_true", help="muestra las noticias que juntan más de un link")
    sub.choices["filtrar"].add_argument(
        "--marcar", action="store_true",
        help="simula que la IA procesó las elegidas y las guarda en la caché (para probar sin IA)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not args.comando:
        parser.print_help()
        return 0
    return COMANDOS[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
