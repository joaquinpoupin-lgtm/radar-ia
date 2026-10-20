"""Deduplicar y agrupar: la misma noticia contada por varias fuentes es UN grupo con varios links."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if TYPE_CHECKING:  # solo para los tipos: recolectar.py importa este módulo
    from radar.recolectar import Candidato

# Parámetros de seguimiento que no cambian el contenido de la página.
PARAMETROS_BASURA = {"ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}
# Prefijos de Hacker News que no son parte del título de la noticia.
PREFIJO_HN = re.compile(r"^(show|launch|ask|tell) hn\s*:?\s*", re.I)
# Un título corto contenido en otro largo solo cuenta si tiene al menos estas palabras.
MIN_PALABRAS_CONTENIDO = 4
SIN_FECHA = datetime.max.replace(tzinfo=timezone.utc)


def url_canonica(url: str) -> str:
    """Misma página = mismo texto: https, dominio en minúsculas y sin www, sin utm_/ref/fbclid, sin # ni / final."""
    partes = urlsplit(url.strip())
    dominio = partes.netloc.lower().removeprefix("www.")
    parametros = sorted((k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
                        if not k.lower().startswith("utm_") and k.lower() not in PARAMETROS_BASURA)
    ruta = partes.path.rstrip("/")
    return urlunsplit(("https", dominio, ruta, urlencode(parametros), ""))


def hash_url(url: str) -> str:
    """id estable: primeros 12 caracteres del SHA-1 de la URL canónica."""
    return hashlib.sha1(url_canonica(url).encode("utf-8")).hexdigest()[:12]


def palabras_titulo(titulo: str) -> list[str]:
    """Título → palabras comparables: sin prefijo HN, sin tildes, sin puntuación, en minúsculas."""
    titulo = PREFIJO_HN.sub("", titulo)
    titulo = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", titulo.lower()).split()


def titulos_parecidos(a: list[str], b: list[str], umbral: float) -> bool:
    """Compara palabra por palabra (no letra por letra: "Introducing Codex" ≠ "Introducing Sora").

    Si los números no coinciden son noticias distintas aunque el resto sea igual ("Claude 4.5" ≠ "Claude 4.6").
    Si el título corto (de MIN_PALABRAS_CONTENIDO o más) cabe entero y en orden en el largo, también es la misma:
    "OpenAI acquires Orchestra Bio" = "OpenAI acquires startup Orchestra Bio to beef up its biotech business".
    """
    if not a or not b or {p for p in a if p.isdigit()} != {p for p in b if p.isdigit()}:
        return False
    comparador = SequenceMatcher(None, a, b, autojunk=False)
    if comparador.quick_ratio() >= umbral and comparador.ratio() >= umbral:
        return True
    corto = min(len(a), len(b))
    return (corto >= MIN_PALABRAS_CONTENIDO
            and sum(m.size for m in comparador.get_matching_blocks()) == corto)


@dataclass
class Grupo:
    """Una noticia: uno o más candidatos de distintas fuentes. El primero es el principal."""
    id: str
    candidatos: list[Candidato]

    @property
    def principal(self) -> Candidato:
        return self.candidatos[0]

    @property
    def titulo(self) -> str:
        return self.principal.titulo

    @property
    def confirmacion(self) -> int:
        """Cuántas fuentes distintas cuentan esta noticia."""
        return len({c.fuente for c in self.candidatos})

    @property
    def fuentes(self) -> list[dict]:
        """Links a mostrar (sin repetir la misma página). Salen del recolector, nunca de la IA."""
        vistos, salida = set(), []
        for c in self.candidatos:
            canonica = url_canonica(c.url)
            if canonica not in vistos:
                vistos.add(canonica)
                salida.append({"nombre": c.fuente, "url": c.url})
        return salida

    @property
    def hashes(self) -> set[str]:
        """Hash de cada link del grupo: la caché (Paso 4) los revisa todos por si el principal cambió."""
        return {hash_url(c.url) for c in self.candidatos}


def _orden_principal(c: Candidato) -> tuple:
    # El más antiguo es el original: así el id no cambia cuando otras fuentes la repiten después.
    return (c.fecha or SIN_FECHA, -c.peso, url_canonica(c.url))


def agrupar(candidatos: list[Candidato], umbral: float) -> list[Grupo]:
    """Une candidatos con la misma URL canónica o con títulos parecidos de fuentes distintas."""
    padre = list(range(len(candidatos)))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unir(i: int, j: int) -> None:
        padre[raiz(j)] = raiz(i)

    por_url: dict[str, int] = {}
    for i, c in enumerate(candidatos):
        canonica = url_canonica(c.url)
        if canonica in por_url:
            unir(por_url[canonica], i)
        else:
            por_url[canonica] = i

    # Por título solo entre fuentes distintas: una misma fuente no publica dos veces la misma noticia,
    # pero sí títulos casi iguales para cosas distintas ("Noticias IA semana 12" / "semana 13").
    palabras = [palabras_titulo(c.titulo) for c in candidatos]
    for i in range(len(candidatos)):
        for j in range(i + 1, len(candidatos)):
            if (candidatos[i].fuente != candidatos[j].fuente and raiz(i) != raiz(j)
                    and titulos_parecidos(palabras[i], palabras[j], umbral)):
                unir(i, j)

    miembros: dict[int, list[Candidato]] = {}
    for i, c in enumerate(candidatos):
        miembros.setdefault(raiz(i), []).append(c)
    grupos = []
    for lista in miembros.values():  # en el orden en que aparecieron
        lista.sort(key=_orden_principal)
        grupos.append(Grupo(hash_url(lista[0].url), lista))
    return grupos


def resumen_agrupacion(candidatos: list[Candidato], grupos: list[Grupo]) -> str:
    varias = sum(g.confirmacion > 1 for g in grupos)
    return (f"{len(candidatos)} candidatos → {len(grupos)} noticias"
            f" ({varias} contadas por más de una fuente)")
