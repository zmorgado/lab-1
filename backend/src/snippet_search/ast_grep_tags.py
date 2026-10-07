"""Extraccion de tags de un snippet, estilo grep (#4).

Etapa 1. Port de docs/research/generacion-de-tags-query.py: saca candidatos en
tres niveles (APIs, estructuras, palabras de dominio). Armar la query con ellos
es de query.py, que los toma en ese orden para que al truncar queden los mejores.

Los saca del AST cuando el snippet parsea: no ve 'sorted(' dentro de un string
ni de un comentario, y el docstring es el docstring. Un snippet que no parsea
(incompleto, sangrado) cae al regex sobre el texto suelto, que igual saca
tags: un snippet pegado suele llegar roto.
"""

from __future__ import annotations

import ast
import keyword
import re
import textwrap
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
DOCSTRING_PATTERN = re.compile('"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)
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
    """Los candidatos de un snippet de Python, separados por nivel.

    Prefiere el AST y cae al regex cuando el snippet no parsea.
    """
    try:
        tree = ast.parse(textwrap.dedent(snippet))
    except (SyntaxError, ValueError):
        return _extract_tags_regex(snippet)
    return _AstTagExtractor().extract(tree)


class _AstTagExtractor(ast.NodeVisitor):
    """Los mismos tres niveles, pero sobre el AST parseado."""

    def __init__(self) -> None:
        self.imports: list[str] = []
        self.calls: list[str] = []
        self.definitions: list[str] = []
        self.docstrings: list[str] = []
        self.has_lambda = False

    def extract(self, tree: ast.Module) -> Tiers:
        module_docstring = ast.get_docstring(tree)
        if module_docstring:
            self.docstrings.append(module_docstring)
        self.visit(tree)

        # Un nombre declarado en el snippet es estructura, no API, aunque se lo invoque
        apis = _keep_distinctive([*self.imports, *self.calls], exclude=set(self.definitions))
        # 'lambda' es keyword y la stop-list lo saca, pero como construccion dice algo
        lambdas = ("lambda",) if self.has_lambda else ()
        structures = (*_keep_distinctive(self.definitions), *lambdas)

        words: list[str] = []
        for doc in self.docstrings:
            found = DOMAIN_WORD_PATTERN.findall(doc)
            words.extend(word.lower() for word in found[:DOMAIN_WORDS_PER_DOCSTRING])
        domain = _keep_distinctive(words, exclude={*apis, *structures})

        return Tiers(apis=apis, structures=structures, domain=domain)

    # Importaciones: el modulo raiz, igual que el regex
    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(alias.name.split(".")[0] for alias in node.names)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Relativos ('from . import x') no nombran un modulo buscable
        if node.level == 0 and node.module:
            self.imports.append(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 'open(x).read()': el llamado de adentro aparece primero en el
        # fuente, asi que se lo visita antes de anotar este. Por lo
        # mismo, los argumentos se visitan a mano y no con generic_visit
        # (volveria a visitar el func)
        self.visit(node.func)
        callee = _callee_name(node.func)
        if callee:
            self.calls.append(callee)
        for argument in (*node.args, *node.keywords):
            self.visit(argument)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._definition(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._definition(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._definition(node)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.has_lambda = True
        self.generic_visit(node)

    def _definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        self.definitions.append(node.name)
        docstring = ast.get_docstring(node)
        if docstring:
            self.docstrings.append(docstring)


def _callee_name(func: ast.AST) -> str:
    """El nombre invocado: el ultimo componente de la cadena
    ('obj.method.items' -> 'items'), igual que veia el regex."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _extract_tags_regex(snippet: str) -> Tiers:
    """Fallback de texto suelto: el snippet no parsea y aun asi puede tener tags."""
    definitions = DEFINITION_PATTERN.findall(snippet)
    imports = [from_module or module for from_module, module in IMPORT_PATTERN.findall(snippet)]
    calls = [
        match.group(2)
        for match in CALL_PATTERN.finditer(snippet)
        if match.group(1) is None
    ]

    # Un nombre declarado en el snippet es estructura, no API, aunque se lo invoque
    apis = _keep_distinctive([*imports, *calls], exclude=set(definitions))
    # 'lambda' es keyword y la stop-list lo saca, pero como construccion dice algo
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
