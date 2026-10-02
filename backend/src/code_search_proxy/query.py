"""Armado de la query de search/code a partir de una lista de tags (#4).

Etapa 3. No sabe de donde vienen los tags: hoy de grep_tags, despues tambien del
LLM y de lo que edite el usuario (#22). Los filtros de owner y repo son #19.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

MAX_TAGS = 6
# Limite de GitHub, medido sobre el valor de 'q' y no sobre la URL
MAX_QUERY_LENGTH = 256

SINGLE_TOKEN_PATTERN = re.compile(r"\w+")


@dataclass(frozen=True)
class SearchQuery:
    """Los tags que entraron, en orden, y el valor 'q' que se manda."""

    tags: tuple[str, ...]
    q: str


@dataclass(frozen=True)
class NothingToSearch:
    """No quedo ningun tag usable: se informa en vez de buscar."""


def build_query(tags: Iterable[str], language: str) -> SearchQuery | NothingToSearch:
    """Llena la query en el orden dado hasta MAX_TAGS o hasta el limite de largo.

    Un tag que no entra se saltea y se sigue con el proximo: los niveles altos
    van primero, asi que quedan siempre que quepan.
    """
    qualifier = f"language:{language}"
    selected: list[str] = []
    terms: list[str] = []
    length = len(qualifier)

    for tag in tags:
        if len(selected) == MAX_TAGS:
            break
        term = _as_term(tag)
        if length + 1 + len(term) > MAX_QUERY_LENGTH:
            continue
        selected.append(tag)
        terms.append(term)
        length += 1 + len(term)

    if not selected:
        return NothingToSearch()
    return SearchQuery(tags=tuple(selected), q=" ".join([*terms, qualifier]))


def _as_term(tag: str) -> str:
    # Las comillas fuerzan frase exacta: sin ellas 'binary search' son dos terminos sueltos
    return tag if SINGLE_TOKEN_PATTERN.fullmatch(tag) else f'"{tag}"'
