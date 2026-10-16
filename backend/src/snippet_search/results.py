"""Etapa de resultados (#8): de los archivos y los scores a la lista que ve el
usuario.

Dos funciones puras. `merge_files` junta lo que devolvieron las queries de
search/code, un archivo por contenido (sha), sin repos privados. `to_results`
ordena los candidatos con score, los numera y los corta.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .ast_subtrees import Subtree

# Cuantos resultados ve el usuario si no pide otra cantidad
DEFAULT_MAX_RESULTS: Final = 10


@dataclass(frozen=True)
class Location:
    """Un repo publico donde esta el contenido."""

    repo: str
    path: str
    html_url: str | None


@dataclass(frozen=True)
class MergedFile:
    """Un contenido (sha) encontrado por una o mas queries."""

    sha: str
    # La copia publica que se baja
    item: dict[str, Any]
    # Los tipos de query que lo encontraron
    queries: tuple[str, ...]
    # Todos los repos publicos donde aparece
    locations: tuple[Location, ...]


@dataclass(frozen=True)
class Candidate:
    """Un subarbol que llego a los embeddings, con el archivo del que salio."""

    file: MergedFile
    subtree: Subtree
    # Coseno de UniXcoder contra el snippet
    score: float


@dataclass(frozen=True)
class ResultQuery:
    kind: str
    q: str


@dataclass(frozen=True)
class Result:
    """Lo que ve el usuario: un subarbol, donde esta y que tan parecido es."""

    rank: int
    score: float
    sha: str
    locations: tuple[Location, ...]
    queries: tuple[ResultQuery, ...]
    name: str
    # El tipo de subarbol: function_definition o class_definition
    node: str
    parent: str | None
    start_line: int
    end_line: int
    code: str


def merge_files(
    bodies: Sequence[tuple[str, Any]], limit: int
) -> tuple[list[MergedFile], int]:
    """(tipo de query, body de search/code) -> archivos por sha, y cuantos
    contenidos se descartaron por estar solo en repos privados.

    Van primero los que encontraron mas queries (#19); a igualdad, el mejor
    puesto que les dio GitHub. Se corta en `limit`, el techo de archivos que
    se bajan.
    """
    items: dict[str, dict[str, Any]] = {}
    kinds: dict[str, list[str]] = {}
    best: dict[str, int] = {}
    locations: dict[str, list[Location]] = {}
    private: set[str] = set()
    for kind, body in bodies:
        for position, item in enumerate((body or {}).get("items", [])):
            key = _key(item)
            # La query encontro este contenido aunque sea en una copia privada:
            # cuenta para el orden, sin nombrar el repo
            best[key] = min(best.get(key, position), position)
            if kind not in (found := kinds.setdefault(key, [])):
                found.append(kind)
            # Un solo token para todos: el codigo privado no sale de aca (#1)
            if _is_private(item):
                private.add(key)
                continue
            items.setdefault(key, item)
            if (location := _location(item)) not in (seen := locations.setdefault(key, [])):
                seen.append(location)

    order = sorted(items, key=lambda key: (-len(kinds[key]), best[key]))[:limit]
    files = [
        MergedFile(key, items[key], tuple(kinds[key]), tuple(locations[key])) for key in order
    ]
    # Solo cuenta lo que no tiene copia publica: lo demas si se usa
    return files, len(private - items.keys())


def to_results(
    candidates: Sequence[Candidate], query_text: Mapping[str, str], max_results: int
) -> tuple[Result, ...]:
    """Candidatos con score -> resultados ordenados y numerados.

    Por score de mayor a menor. A igualdad, por repo, path y linea, para que dos
    corridas iguales den siempre el mismo orden.
    """
    ordered = sorted(candidates, key=_order)[:max_results]
    return tuple(_result(rank, c, query_text) for rank, c in enumerate(ordered, start=1))


def _order(candidate: Candidate) -> tuple[float, str, str, int]:
    # La menor ubicacion y no la primera: el orden de GitHub no tiene que decidir
    first = min(candidate.file.locations, key=lambda loc: (loc.repo, loc.path))
    return (-candidate.score, first.repo, first.path, candidate.subtree.start_line)


def _result(rank: int, candidate: Candidate, query_text: Mapping[str, str]) -> Result:
    subtree = candidate.subtree
    return Result(
        rank=rank,
        score=candidate.score,
        sha=candidate.file.sha,
        locations=candidate.file.locations,
        queries=tuple(ResultQuery(kind, query_text.get(kind, "")) for kind in candidate.file.queries),
        name=subtree.name,
        node=subtree.kind,
        parent=subtree.parent,
        start_line=subtree.start_line,
        end_line=subtree.end_line,
        code=subtree.code,
    )


def without_private(body: Any) -> Any:
    """Un body de search/code sin sus items privados, para devolverlo crudo sin
    filtrar repos ni paths privados (#8)."""
    if not isinstance(body, dict):
        return body
    return {**body, "items": [i for i in body.get("items", []) if not _is_private(i)]}


def _key(item: dict[str, Any]) -> str:
    # El sha identifica el contenido: el mismo archivo en dos repos es uno solo
    return item.get("sha") or f"{repo_of(item)}/{item.get('path', '')}"


def _location(item: dict[str, Any]) -> Location:
    return Location(repo_of(item), item.get("path", ""), item.get("html_url"))


def _is_private(item: dict[str, Any]) -> bool:
    return bool(item.get("repository", {}).get("private"))


def repo_of(item: dict[str, Any]) -> str:
    return item.get("repository", {}).get("full_name", "")
