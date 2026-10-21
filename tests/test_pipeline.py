"""Paso 10: corrida completa de punta a punta (sin red: fuentes con transporte falso e IA falsa)."""

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx

from radar.config import cargar_config
from radar.fuentes import Fuente
from radar.ia import IANoDisponible
from radar.pipeline import correr, texto_final

CONFIG = cargar_config()
MANANA = datetime(2026, 10, 21, 9, 31, tzinfo=timezone.utc)  # 06:31 en Chile: toca el brief
MADRUGADA = datetime(2026, 10, 21, 3, 31, tzinfo=timezone.utc)  # 00:31 en Chile
HOY = "2026-10-21"
FUENTES = [Fuente("Blog A", "rss", "https://a.com/feed", "modelos", "en", 3),
           Fuente("Blog B", "rss", "https://b.com/feed", "herramientas", "en", 2)]


def feed(sitio, titulos, ahora):
    items = "".join(
        f"<item><title>{t}</title><link>https://{sitio}/{i}</link>"
        f"<pubDate>{format_datetime(ahora - timedelta(hours=i + 1))}</pubDate>"
        f"<description>Un extracto suficientemente largo sobre {t} para no buscar la página.</description></item>"
        for i, t in enumerate(titulos))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{sitio}</title>{items}</channel></rss>'


def red_falsa(ahora, caidas=()):
    feeds = {"a.com": feed("a.com", ["New open model released", "Agents get better"], ahora),
             "b.com": feed("b.com", ["A tool for prompts", "Another useful app"], ahora)}

    def responder(pedido):
        if pedido.url.host in caidas:
            return httpx.Response(503)
        return httpx.Response(200, text=feeds[pedido.url.host])
    return httpx.Client(transport=httpx.MockTransport(responder))


def ia_falsa(llamadas, falla=False):
    """Resume todo lo que le llega (o falla como si no hubiera cuota)."""
    def pedir(prompt, config, cliente, validar=None):
        llamadas.append(prompt)
        if falla:
            raise IANoDisponible(["gemini: cuota", "groq: cuota"])
        if "## Noticias" in prompt and "seccion_sugerida" in prompt:
            items = json.loads(prompt.split("## Noticias")[1])
            r = {"noticias": [{"n": d["n"], "titulo": f"Resumen de {d['titulo']}", "que_paso": "Pasó algo.",
                               "por_que_importa": "Importa.", "seccion": d["seccion_sugerida"],
                               "importancia": "alta" if d["n"] == 1 else "normal", "terminos": [],
                               "etiquetas": ["gratis"]} for d in items]}
        else:  # bullets: la cantidad la decide el código; se prueba hasta que valide
            for c in (3, 2, 1):
                r = {"lo_mas_importante": [f"Bullet {i}." for i in range(1, c + 1)]}
                try:
                    validar(r)
                    break
                except ValueError:
                    continue
        validar(r)
        return r
    return pedir


def ejecutar(tmp_path, ahora=MANANA, caidas=(), falla=False, llamadas=None, **extra):
    llamadas = [] if llamadas is None else llamadas
    return correr(CONFIG, ahora, FUENTES, datos=tmp_path / "data", destino=tmp_path / "_site",
                  cliente_red=red_falsa(ahora, caidas), cliente_ia=httpx.Client(),
                  pedir=ia_falsa(llamadas, falla), **extra)


def dia(tmp_path):
    return json.loads((tmp_path / "data" / f"{HOY}.json").read_text(encoding="utf-8"))


def test_desde_cero_deja_datos_brief_y_sitio(tmp_path):
    llamadas = []
    corrida = ejecutar(tmp_path, llamadas=llamadas)
    assert corrida.codigo == 0 and corrida.errores == []
    assert corrida.nuevas == 4 and corrida.sitio
    d = dia(tmp_path)
    assert len(d["noticias"]) == 4 and len(d["brief"]["ids"]) == 4
    assert d["brief"]["lo_mas_importante"] == ["Bullet 1.", "Bullet 2.", "Bullet 3."]
    assert len(llamadas) == 2  # un lote de resumen + los bullets
    procesados = json.loads((tmp_path / "data" / "cache" / "procesados.json").read_text())
    assert len(procesados) == 4
    portada = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "Resumen de New open model released" in portada and "Bullet 1." in portada
    assert (tmp_path / "_site" / "archivo" / f"{HOY}.html").exists()
    assert "Corrida terminada bien." in texto_final(corrida, tmp_path / "_site")


def test_segunda_corrida_no_resume_dos_veces(tmp_path):
    ejecutar(tmp_path)
    llamadas = []
    corrida = ejecutar(tmp_path, ahora=MANANA + timedelta(hours=6), llamadas=llamadas)
    assert corrida.codigo == 0 and corrida.nuevas == 0
    assert llamadas == []  # nada nuevo y el brief ya estaba completo
    assert len(dia(tmp_path)["noticias"]) == 4


def test_de_madrugada_no_arma_el_brief_salvo_que_se_fuerce(tmp_path):
    corrida = ejecutar(tmp_path, ahora=MADRUGADA)
    assert corrida.codigo == 0 and dia(tmp_path)["brief"] is None
    assert "Todavía no hay brief" in (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    ejecutar(tmp_path, ahora=MADRUGADA, forzar_brief=True)
    assert len(dia(tmp_path)["brief"]["ids"]) == 4


def test_sin_ia_queda_pendiente_y_termina_bien(tmp_path):
    corrida = ejecutar(tmp_path, falla=True)
    assert corrida.codigo == 0 and corrida.nuevas == 0 and corrida.pendientes == 4
    assert any("IA" in a for a in corrida.avisos)
    assert corrida.sitio
    # La siguiente corrida, con la IA de vuelta, las resume.
    corrida = ejecutar(tmp_path, ahora=MANANA + timedelta(hours=6))
    assert corrida.nuevas == 4 and corrida.pendientes == 0
    assert len(dia(tmp_path)["brief"]["lo_mas_importante"]) == 3


def test_una_fuente_caida_no_frena_la_corrida(tmp_path):
    corrida = ejecutar(tmp_path, caidas=("b.com",))
    assert corrida.codigo == 0 and corrida.nuevas == 2
    assert any("Blog B" in a for a in corrida.avisos)


def test_todas_las_fuentes_caidas_es_error_pero_igual_hay_sitio(tmp_path):
    corrida = ejecutar(tmp_path, caidas=("a.com", "b.com"))
    assert corrida.codigo == 1 and corrida.sitio
    assert "ninguna fuente" in corrida.errores[0]


def test_un_error_inesperado_no_impide_el_sitio(tmp_path, monkeypatch):
    def explota(*a, **k):
        raise RuntimeError("bug de prueba")
    monkeypatch.setattr("radar.pipeline.recolectar", explota)
    corrida = ejecutar(tmp_path)
    assert corrida.codigo == 1 and corrida.sitio
    assert "bug de prueba" in corrida.errores[0]
    assert (tmp_path / "_site" / "index.html").exists()
