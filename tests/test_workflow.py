"""Guardia del workflow de GitHub Actions: horario, sin corridas dobles y claves solo desde Secrets."""

import re

import yaml

from radar.config import RAIZ

RUTA = RAIZ / ".github" / "workflows" / "radar.yml"


def _workflow() -> dict:
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def _disparadores(wf: dict) -> dict:
    # PyYAML lee la clave `on:` como el booleano True.
    return wf.get("on") or wf[True]


def test_horario_en_hora_de_chile_y_boton_manual():
    disparadores = _disparadores(_workflow())
    assert disparadores["schedule"] == [{"cron": "30 0,6,12,18 * * *", "timezone": "America/Santiago"}]
    assert "workflow_dispatch" in disparadores


def test_nunca_dos_corridas_a_la_vez():
    concurrencia = _workflow()["concurrency"]
    assert concurrencia["group"]
    assert concurrencia["cancel-in-progress"] is False


def test_claves_solo_desde_secrets():
    pasos = _workflow()["jobs"]["correr"]["steps"]
    radar = next(p for p in pasos if p.get("id") == "radar")
    assert radar["run"].startswith("python -m radar correr")
    for nombre in ["GEMINI_API_KEY", "GROQ_API_KEY"]:
        assert radar["env"][nombre] == f"${{{{ secrets.{nombre} }}}}"
    # Ningún otro paso recibe las claves.
    texto = RUTA.read_text(encoding="utf-8")
    assert len(re.findall(r"secrets\.", texto)) == 2


def test_robot_usa_correo_noreply():
    texto = RUTA.read_text(encoding="utf-8")
    correos = re.findall(r'user\.email "([^"]+)"', texto)
    assert correos and all(c.endswith("@users.noreply.github.com") for c in correos)


def test_simulacro_solo_a_mano_y_por_variable():
    wf = _workflow()
    entrada = _disparadores(wf)["workflow_dispatch"]["inputs"]["simular"]
    assert entrada["default"] == "" and entrada["required"] is False  # el horario corre siempre normal
    radar = next(p for p in wf["jobs"]["correr"]["steps"] if p.get("id") == "radar")
    assert radar["env"]["SIMULAR"] == "${{ inputs.simular }}"
    assert "${{" not in radar["run"]  # el texto que escribe el usuario nunca se pega directo en el comando
