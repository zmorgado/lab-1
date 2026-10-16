"""Seleccion de tags (#22): el nodo entre las dos fuentes de tags y la busqueda.

Junta los seeds del AST (#4) y los tags del LLM (#7) en un pool sin repetidos,
ordenado por peso y de hasta POOL_SIZE tags. Cada tag dice que query alimenta y
si va seleccionado de entrada; el usuario edita sobre esto antes de buscar.

El pool no depende de `Tiers.is_fallback`: el flag solo dice que camino de
extraccion corrio, no cambia ni el orden ni quien entra.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .ast_grep_tags import Tiers
from .llm_tags import KIND_CONCEPTUAL, KIND_PARADIGM, KIND_SYNTACTIC, KINDS, SOURCE_SEED, TagSet
from .query import SearchQuery, build_query

# La unica query cuando el LLM no esta: sale de los tiers del AST (#1)
QUERY_TIERS: Final = "tiers"

# Lo que se le ofrece al usuario. Mas grande que una query (6 tags) a proposito:
# cortar al armar el pool dejaba afuera 'cosine' y adentro un 'math' sin usar
POOL_SIZE: Final = 20

# Pesos de #22, el menor primero. El orden decide que entra en una query
# cuando no entra todo: los nombres y el dominio antes que las APIs, y los
# imports genericos al final
WEIGHT_DOMAIN: Final = 1
WEIGHT_API: Final = 2
WEIGHT_IMPORT: Final = 3

# Sin un seed del AST que lo pese, un tag del LLM pesa por su tipo
_KIND_WEIGHTS: Final = {
    KIND_CONCEPTUAL: WEIGHT_DOMAIN,
    KIND_SYNTACTIC: WEIGHT_API,
    KIND_PARADIGM: WEIGHT_API,
}


@dataclass(frozen=True)
class PoolTag:
    """Un tag que se le ofrece al usuario, y si va seleccionado de entrada."""

    text: str
    kind: str
    source: str
    selected: bool


@dataclass(frozen=True)
class _Seed:
    text: str
    weight: int
    # La query a la que va si el LLM lo dejo afuera
    kind: str


def select(tiers: Tiers, llm_tags: TagSet | None, language: str) -> tuple[PoolTag, ...]:
    """El pool, ordenado por peso, con la seleccion de entrada.

    Con el LLM, sus tags van seleccionados, cada uno a la query de su tipo, y
    los seeds que descarto se ofrecen sin seleccionar: un modulo interno como
    'ringr_agents' no entra si el usuario no lo elige.

    Sin el LLM, o si no dejo nada buscable, los seeds van a la query de tiers,
    seleccionados los que entran en ella.
    """
    seeds = _weighted_seeds(tiers)
    if llm_tags is not None and _searchable(llm_tags, language):
        return _with_model(seeds, llm_tags)

    pooled = seeds[:POOL_SIZE]
    query = build_query([seed.text for seed in pooled], language)
    fitted = set(query.tags) if isinstance(query, SearchQuery) else set()
    return tuple(PoolTag(s.text, QUERY_TIERS, SOURCE_SEED, s.text in fitted) for s in pooled)


def _with_model(seeds: list[_Seed], llm_tags: TagSet) -> tuple[PoolTag, ...]:
    by_text = {seed.text.lower(): seed for seed in seeds}
    weighted = [
        (_llm_weight(tag.text, tag.kind, by_text), PoolTag(tag.text, tag.kind, tag.source, True))
        for tag in llm_tags.tags
    ]
    # Los del LLM entran todos; los seeds que descarto, hasta llenar el pool
    taken = {tag.text.lower() for tag in llm_tags.tags}
    room = max(0, POOL_SIZE - len(weighted))
    dropped = [seed for seed in seeds if seed.text.lower() not in taken][:room]
    weighted += [(s.weight, PoolTag(s.text, s.kind, SOURCE_SEED, False)) for s in dropped]
    # Estable: a igual peso, primero el orden del LLM y despues el de los seeds
    return tuple(tag for _, tag in sorted(weighted, key=lambda pair: pair[0]))


def _llm_weight(text: str, kind: str, seeds: dict[str, _Seed]) -> int:
    seed = seeds.get(text.lower())
    return seed.weight if seed else _KIND_WEIGHTS.get(kind, WEIGHT_API)


def _weighted_seeds(tiers: Tiers) -> list[_Seed]:
    """Los seeds por peso y, adentro de cada peso, en orden de aparicion.

    El AST los separa sin adivinar: un import es un nodo Import, un llamado un
    Call, `lambda` una construccion y una palabra de dominio sale de un docstring.
    """
    imports = set(tiers.imports)
    definitions = [name for name in tiers.structures if name != "lambda"]
    seeds = [
        *(_Seed(name, WEIGHT_DOMAIN, KIND_SYNTACTIC) for name in definitions),
        *(_Seed(word, WEIGHT_DOMAIN, KIND_CONCEPTUAL) for word in tiers.domain),
        *(_Seed(name, WEIGHT_API, KIND_SYNTACTIC) for name in tiers.apis if name not in imports),
        *([_Seed("lambda", WEIGHT_API, KIND_PARADIGM)] if "lambda" in tiers.structures else []),
        *(_Seed(name, WEIGHT_IMPORT, KIND_PARADIGM) for name in tiers.imports),
    ]
    # 'Rank' y 'rank' son el mismo tag: queda el de mas peso
    unique: dict[str, _Seed] = {}
    for seed in seeds:
        unique.setdefault(seed.text.lower(), seed)
    return list(unique.values())


def _searchable(llm_tags: TagSet, language: str) -> bool:
    return any(
        isinstance(build_query([t.text for t in llm_tags.tags if t.kind == kind], language), SearchQuery)
        for kind in KINDS
    )
