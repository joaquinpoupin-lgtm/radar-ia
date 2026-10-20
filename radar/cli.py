"""Comandos de Radar IA: `python -m radar <comando>`."""

import argparse
import sys

# Comandos planeados: (nombre, descripción, paso del plan que lo implementa).
# Al implementar uno, reemplazar su función en COMANDOS.
PLANEADOS = [
    ("fuentes", "Prueba cada fuente de sources.yaml y muestra cuáles funcionan", 1),
    ("recolectar", "Trae noticias candidatas de todas las fuentes", 2),
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


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Radar IA: noticias de inteligencia artificial resumidas en español simple.",
    )
    sub = parser.add_subparsers(dest="comando", metavar="<comando>")
    for nombre, descripcion, _ in PLANEADOS:
        sub.add_parser(nombre, help=descripcion, description=descripcion)
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
