"""Extraccion de tags de un snippet, estilo grep (#4).

Etapa 1. Port de docs/research/generacion-de-tags-query.py: saca candidatos en
tres niveles (APIs, estructuras, palabras de dominio). Armar la query con ellos
es de query.py, que los toma en ese orden para que al truncar queden los mejores.
"""

from __future__ import annotations

import keyword
import re
from collections.abc import Container, Iterable
from dataclasses import dataclass

# Los patrones de abajo son de Python: con otro lenguaje darian tags sin sentido
SUPPORTED_LANGUAGES = frozenset({"python"})

# Aparecen en cualquier snippet, asi que no ayudan a encontrar este. Los
# builtins con mas senal ('sorted', 'map', 'open') quedan afuera de la lista
GENERIC_NAMES = frozenset(
    {
        "self", "cls", "args", "kwargs",
        "print", "len", "range", "super", "isinstance", "type", "object",
        "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "enumerate", "zip",
    }
)
# Sin las soft keywords: 'match' o 'case' tambien son nombres validos ('re.match(')
IGNORED_IDENTIFIERS = GENERIC_NAMES | frozenset(keyword.kwlist)

# search/code matchea por trigramas: un nombre mas corto no filtra nada
MIN_TAG_LENGTH = 3

# Exige la forma completa del import: una linea de docstring que empieza con
# 'from' o 'import' es prosa, no un modulo
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from\s+([A-Za-z_]\w*)[\w.]*\s+import\b"
    r"|import\s+([A-Za-z_]\w*)[\w.]*(?:\s+as\s+\w+)?[ \t\r]*(?:[,;#]|$))",
    re.MULTILINE,
)
# El grupo opcional atrapa 'def'/'class' para descartar declaraciones:
# 'def rank(' declara, 'sorted(' invoca
CALL_PATTERN = re.compile(r"(\b(?:def|class)\s+)?\b([A-Za-z_]\w*)\s*\(")
DEFINITION_PATTERN = re.compile(
    r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE
)
LAMBDA_PATTERN = re.compile(r"\blambda\b")
DOCSTRING_PATTERN = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)
DOMAIN_WORD_PATTERN = re.compile(r"\b[A-Za-z]{4,}\b")
DOMAIN_WORDS_PER_DOCSTRING = 3


@dataclass(frozen=True)
class Tiers:
    """Candidatos por nivel, cada uno en orden de aparicion."""

    apis: tuple[str, ...]
    structures: tuple[str, ...]
    domain: tuple[str, ...]

    def ordered(self) -> tuple[str, ...]:
        """Todos los candidatos, nivel por nivel: el orden en que llenan la query."""
        return (*self.apis, *self.structures, *self.domain)


def extract_tags(snippet: str) -> Tiers:
    """Los candidatos de un snippet de Python, separados por nivel."""
    definitions = DEFINITION_PATTERN.findall(snippet)
    imports = [from_module or module for from_module, module in IMPORT_PATTERN.findall(snippet)]
    calls = [
        match.group(2)
        for match in CALL_PATTERN.finditer(snippet)
        if match.group(1) is None
    ]

    # Un nombre declarado en el snippet es estructura, no API, aunque se lo invoque
    apis = _keep_distinctive([*imports, *calls], exclude=set(definitions))
    # 'lambda' es keyword y la stop-list lo saca, pero como construccion si dice algo
    lambdas = ("lambda",) if LAMBDA_PATTERN.search(snippet) else ()
    structures = (*_keep_distinctive(definitions), *lambdas)

    words: list[str] = []
    for double, single in DOCSTRING_PATTERN.findall(snippet):
        found = DOMAIN_WORD_PATTERN.findall(double or single)
        words.extend(word.lower() for word in found[:DOMAIN_WORDS_PER_DOCSTRING])
    domain = _keep_distinctive(words, exclude={*apis, *structures})

    return Tiers(apis=apis, structures=structures, domain=domain)


def _keep_distinctive(names: Iterable[str], exclude: Container[str] = ()) -> tuple[str, ...]:
    """Sin repetidos ni genericos, conservando el orden de aparicion."""
    kept = (
        name
        for name in names
        if _is_distinctive(name) and name not in exclude
    )
    return tuple(dict.fromkeys(kept))


def _is_distinctive(name: str) -> bool:
    is_dunder = name.startswith("__") and name.endswith("__")
    return (
        len(name) >= MIN_TAG_LENGTH
        and not is_dunder
        and name not in IGNORED_IDENTIFIERS
    )
