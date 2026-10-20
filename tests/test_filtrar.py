import json
from datetime import datetime, timedelta, timezone

from radar.agrupar import agrupar, hash_url
from radar.config import cargar_config
from radar.filtrar import (cargar_procesados, guardar_procesados, hoy_chile, informe, marcar_procesados,
                           prefiltrar, publicadas_hoy, puntaje)
from radar.recolectar import Candidato

CONFIG = cargar_config()
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def cand(titulo, url, fuente="Blog", horas=1, peso=2, puntos=None):
    return Candidato(titulo=titulo, url=url, fuente=fuente, tipo="rss", seccion="modelos", idioma="en",
                     peso=peso, fecha=AHORA - timedelta(hours=horas), puntaje=puntos)


def grupos(*candidatos):
    return agrupar(list(candidatos), CONFIG["limites"]["similitud_titulos"])


def config_con(**limites):
    return {**CONFIG, "limites": {**CONFIG["limites"], **limites}}


def test_dia_en_hora_de_chile():
    # 01:30 UTC del 21 todavía es el 20 en Chile.
    assert hoy_chile(datetime(2026, 10, 21, 1, 30, tzinfo=timezone.utc), CONFIG) == "2026-10-20"


def test_puntaje_premia_fuente_confirmacion_hn_y_palabras_clave():
    [simple] = grupos(cand("Some thoughts on chips", "https://a.com/1", horas=0))
    assert puntaje(simple, CONFIG, AHORA) == 2
    [completo] = grupos(cand("OpenAI launches a coding agent", "https://openai.com/x", "OpenAI", peso=3, horas=0),
                        cand("OpenAI launches a coding agent", "https://openai.com/x", "Hacker News", puntos=350,
                             horas=0))
    assert puntaje(completo, CONFIG, AHORA) == 3 + 1 + 2 + 0.5  # peso + 1 fuente extra + HN ≥300 + palabra clave
    [viejo] = grupos(cand("Some thoughts on chips", "https://a.com/1", horas=48))
    assert puntaje(viejo, CONFIG, AHORA) == 2 - 2 * 0.5  # 2 días de antigüedad


def test_elige_los_mejores_respetando_topes():
    lista = grupos(
        *[cand(f"Medio nota {n}", f"https://medio.com/{n}", "Medio", horas=n) for n in range(1, 6)],
        cand("Oficial anuncio", "https://lab.ai/x", "Lab", peso=3),
        cand("Ruido", "https://reddit.com/r/x/1", "Reddit", peso=1),
    )
    r = prefiltrar(lista, {}, config_con(max_nuevas_por_corrida=4), AHORA)
    assert r.nuevas == 7 and r.cupo == 4
    fuentes = [g.principal.fuente for g, _ in r.elegidas]
    assert fuentes[0] == "Lab"  # mejor puntaje primero
    assert fuentes.count("Medio") == CONFIG["prefiltro"]["max_por_fuente"]  # no más de 3 de la misma fuente
    assert fuentes == ["Lab", "Medio", "Medio", "Medio"]


def test_respeta_el_tope_diario():
    lista = grupos(*[cand(f"Nota {n}", f"https://x{n}.com", f"F{n}") for n in range(10)])
    assert prefiltrar(lista, {}, CONFIG, AHORA, publicadas=20).cupo == 5
    r = prefiltrar(lista, {}, CONFIG, AHORA, publicadas=25)
    assert r.cupo == 0 and r.elegidas == [] and "tope" in informe(r)


def test_descarta_lo_viejo_y_lo_ya_procesado():
    lista = grupos(cand("Nueva", "https://a.com/nueva"), cand("Vieja", "https://a.com/vieja", horas=24 * 5),
                   cand("Ya vista", "https://a.com/vista?utm_source=rss"))
    r = prefiltrar(lista, {hash_url("https://a.com/vista"): "2026-10-19"}, CONFIG, AHORA)
    assert (r.nuevas, r.viejas, r.ya_procesadas) == (1, 1, 1)
    assert [g.titulo for g, _ in r.elegidas] == ["Nueva"]


def test_se_reconoce_aunque_cambie_el_principal():
    # Se procesó cuando solo existía el link de Hacker News; ahora apareció el original (más antiguo).
    hn = cand("New open model beats the rest", "https://medio.com/nota", "Hacker News", horas=2)
    [solo] = grupos(hn)
    procesados = {}
    marcar_procesados(procesados, [solo], "2026-10-20")
    original = cand("New open model beats the rest", "https://lab.ai/modelo", "Lab", horas=10)
    [ahora_con_dos] = grupos(hn, original)
    assert ahora_con_dos.principal is original
    assert prefiltrar([ahora_con_dos], procesados, CONFIG, AHORA).ya_procesadas == 1


def test_dos_corridas_seguidas_no_repiten_nada(tmp_path):
    ruta = tmp_path / "procesados.json"
    lista = grupos(*[cand(f"Nota {n}", f"https://x{n}.com", f"F{n}") for n in range(15)])

    primera = prefiltrar(lista, cargar_procesados(ruta), CONFIG, AHORA)
    procesados = cargar_procesados(ruta)
    marcar_procesados(procesados, [g for g, _ in primera.elegidas], "2026-10-20")
    guardar_procesados(procesados, "2026-10-20", 30, ruta)

    segunda = prefiltrar(lista, cargar_procesados(ruta), CONFIG, AHORA)
    assert len(primera.elegidas) == 10 and len(segunda.elegidas) == 5
    assert not {g.id for g, _ in primera.elegidas} & {g.id for g, _ in segunda.elegidas}

    procesados = cargar_procesados(ruta)
    marcar_procesados(procesados, [g for g, _ in segunda.elegidas], "2026-10-20")
    tercera = prefiltrar(lista, procesados, CONFIG, AHORA)
    assert tercera.nuevas == 0 and "0 noticias nuevas" in informe(tercera)


def test_cache_poda_lo_viejo_y_tolera_archivo_danado(tmp_path, capsys):
    ruta = tmp_path / "cache" / "procesados.json"
    guardar_procesados({"aaa": "2026-09-01", "bbb": "2026-10-01"}, "2026-10-20", 30, ruta)
    assert json.loads(ruta.read_text()) == {"bbb": "2026-10-01"}
    ruta.write_text("{esto no es json")
    assert cargar_procesados(ruta) == {}
    assert "Aviso" in capsys.readouterr().out
    assert cargar_procesados(tmp_path / "no-existe.json") == {}


def test_publicadas_hoy(tmp_path):
    assert publicadas_hoy("2026-10-20", tmp_path) == 0
    (tmp_path / "2026-10-20.json").write_text(json.dumps({"noticias": [{}, {}, {}]}))
    assert publicadas_hoy("2026-10-20", tmp_path) == 3
