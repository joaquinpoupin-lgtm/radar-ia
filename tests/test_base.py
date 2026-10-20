import os

from radar.cli import PLANEADOS, construir_parser, main
from radar.config import cargar_config, cargar_env


def test_config_tiene_lo_esencial():
    config = cargar_config()
    assert config["zona_horaria"] == "America/Santiago"
    assert config["limites"]["max_brief"] <= config["limites"]["max_por_dia"]
    assert config["ia"]["principal"]["proveedor"] == "gemini"
    assert config["ia"]["respaldo"]["proveedor"] == "groq"


def test_help_lista_todos_los_comandos():
    ayuda = construir_parser().format_help()
    for nombre, _, _ in PLANEADOS:
        assert nombre in ayuda


def test_sin_comando_muestra_ayuda(capsys):
    assert main([]) == 0
    assert "radar" in capsys.readouterr().out


def test_env_no_pisa_variables_existentes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comentario\nPRUEBA_A=desde_archivo\nPRUEBA_B=desde_archivo\nPRUEBA_VACIA=\n")
    monkeypatch.setenv("PRUEBA_A", "ya_definida")
    monkeypatch.delenv("PRUEBA_B", raising=False)
    monkeypatch.delenv("PRUEBA_VACIA", raising=False)
    cargar_env(env)
    assert os.environ["PRUEBA_A"] == "ya_definida"
    assert os.environ["PRUEBA_B"] == "desde_archivo"
    assert "PRUEBA_VACIA" not in os.environ
    monkeypatch.delenv("PRUEBA_B")
