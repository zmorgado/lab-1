"""Etapa de AST (#20): parsea el snippet y los archivos candidatos, aisla los
subarboles que se pueden comparar y poda el resto.

Criterios de docs/research/multiple-snippet-sorting-solution.md, en el orden en
que se aplican (del mas barato al mas caro):

- A: la raiz del subarbol es de la misma categoria que el snippet (funcion o
  clase) y esta en el nivel de arriba. Las funciones anidadas quedan afuera.
- C: el subarbol es completo: nombre, parametros y un cuerpo que hace algo.
- B: el subarbol contiene al menos una de las anclas (tags de #4 y #7).
- Largo: ni mucho mas largo ni mucho mas corto que el snippet.

No calcula similitud estructural: eso lo mide #18 antes de construirlo.
"""

from __future__ import annotations

import keyword
import re
import textwrap
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Final

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from .grep_tags import GENERIC_NAMES, MIN_TAG_LENGTH

CATEGORY_FUNCTION: Final = "function"
CATEGORY_CLASS: Final = "class"

FUNCTION_NODE: Final = "function_definition"
CLASS_NODE: Final = "class_definition"

# Poda por largo, en lineas no vacias y relativa al snippet: con 4x, un snippet
# de 8 lineas deja pasar subarboles de 2 a 32 lineas
MIN_LENGTH_RATIO: Final = 0.25
MAX_LENGTH_RATIO: Final = 4.0

# Construcciones que un tag puede nombrar aunque no sean identificadores
# ('lambda' es tag de #4; 'comprehension' o 'generator', del LLM)
CONSTRUCT_WORDS: Final = {
    "lambda": "lambda",
    "list_comprehension": "comprehension",
    "dictionary_comprehension": "comprehension",
    "set_comprehension": "comprehension",
    "generator_expression": "generator",
    "yield": "generator",
    "await": "async",
    "decorator": "decorator",
}
RECURSION_WORDS: Final = ("recursion", "recursive")

# Palabras que no sirven de ancla: genericas o keywords que no nombran una construccion
STOP_WORDS: Final = GENERIC_NAMES | (
    frozenset(keyword.kwlist) - frozenset(CONSTRUCT_WORDS.values())
)

# 'sort_dictionary' -> sort, dictionary; 'HTTPServer' -> http, server
WORD_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

_PARSER = Parser(Language(tree_sitter_python.language()))


class UnparseableSource(Exception):
    """El archivo no es Python valido: se saltea entero, con el motivo."""


@dataclass(frozen=True)
class SnippetShape:
    """Lo que la etapa necesita saber del snippet pegado."""

    category: str
    # True si el snippet no tenia def ni class y se asumio funcion
    fallback: bool
    lines: int


@dataclass(frozen=True)
class Subtree:
    """Un candidato (b) para la etapa de embeddings.

    `code` es lo que se embebe. El resto ubica al subarbol en su archivo: lineas
    1-based e inclusivas, y la clase que lo contiene si es un metodo.
    """

    code: str
    kind: str
    name: str
    parent: str | None
    start_line: int
    end_line: int
    # Los tags que encontro el criterio B, en el orden en que llegaron
    anchors: tuple[str, ...]


@dataclass(frozen=True)
class Isolation:
    subtrees: tuple[Subtree, ...]
    # Cuantos subarboles descarto cada criterio
    rejected: dict[str, int] = field(default_factory=dict)


def analyze_snippet(source: str) -> SnippetShape:
    """Parsea el snippet y decide su categoria por la primera definicion de arriba."""
    code = textwrap.dedent(source)
    root = _PARSER.parse(code.encode("utf-8")).root_node
    lines = _count_lines(code)

    for node, enclosing in _definitions(root):
        if not enclosing:
            category = CATEGORY_CLASS if node.type == CLASS_NODE else CATEGORY_FUNCTION
            return SnippetShape(category=category, fallback=False, lines=lines)

    # Sentencias sueltas: viven dentro de alguna funcion del candidato, asi que
    # se compara contra funciones
    return SnippetShape(category=CATEGORY_FUNCTION, fallback=True, lines=lines)


def isolate(source: str, snippet: SnippetShape, anchors: Iterable[str]) -> Isolation:
    """Los subarboles de un archivo candidato que pasan A, C, B y el largo.

    Un archivo sin sobrevivientes da un Isolation vacio; uno que no parsea
    levanta UnparseableSource.
    """
    root = _PARSER.parse(source.encode("utf-8")).root_node
    if root.has_error:
        line = _first_error_line(root)
        raise UnparseableSource(f"syntax error at line {line}: not valid Python")

    lines = source.split("\n")
    anchor_words = _anchor_words(anchors)

    subtrees: list[Subtree] = []
    rejected = {"A": 0, "C": 0, "B": 0, "length": 0}

    for node, enclosing, name, found, code in _pruning(
        root, lines, snippet, anchor_words, rejected
    ):
        parent = _name(enclosing[-1]) if enclosing else None
        subtrees.append(
            Subtree(
                code=code,
                kind=node.type,
                name=name,
                parent=parent,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                anchors=found,
            )
        )

    return Isolation(subtrees=tuple(subtrees), rejected=rejected)


def _pruning(
    root: Node,
    lines: list[str],
    snippet: SnippetShape,
    anchor_words: tuple[tuple[str, frozenset[str]], ...],
    rejected: dict[str, int],
) -> Iterator[tuple[Node, tuple[Node, ...], str, tuple[str, ...], str]]:
    """Las definiciones del archivo que sobreviven la poda, con su nombre, las
    anclas que encontro B y el codigo recortado.

    Cada descarte suma uno en `rejected`, bajo la clave del criterio que lo corto.
    """
    min_lines = snippet.lines * MIN_LENGTH_RATIO
    max_lines = snippet.lines * MAX_LENGTH_RATIO

    for node, enclosing in _definitions(root):
        # Contenedor: buscando funciones, una clase de arriba no se compara pero
        # sus metodos si. Se saltea sin contarla como descarte
        if _is_container(node, enclosing, snippet.category):
            continue

        # A: la raiz es de la misma categoria que el snippet y esta arriba
        # (funcion del modulo o metodo de una clase del modulo). Las anidadas
        # quedan afuera
        if not _is_candidate(node, enclosing, snippet.category):
            rejected["A"] += 1
            continue

        # C: esta completa, con nombre, parametros y un cuerpo que hace algo. Un
        # stub (pass, ..., solo docstring o NotImplementedError) no tiene
        # comportamiento que comparar
        if not _is_complete(node):
            rejected["C"] += 1
            continue

        # B: contiene todas las palabras de al menos un tag, buscadas en
        # identificadores, comentarios, docstring y construcciones. Si ningun
        # tag dejo palabras utiles, no se filtra por anclas
        name = _name(node)
        found = _matching_anchors(anchor_words, _vocabulary(node, name))
        if anchor_words and not found:
            rejected["B"] += 1
            continue

        # Largo: las lineas no vacias quedan entre MIN_LENGTH_RATIO y
        # MAX_LENGTH_RATIO veces las del snippet
        start, end = node.start_point.row, node.end_point.row
        code = textwrap.dedent("\n".join(lines[start : end + 1]))
        if not min_lines <= _count_lines(code) <= max_lines:
            rejected["length"] += 1
            continue

        yield node, enclosing, name, found, code


# --- interno -------------------------------------------------------------


def _definitions(root: Node) -> Iterator[tuple[Node, tuple[Node, ...]]]:
    """Cada def/class del arbol en orden, con las definiciones que la contienen.

    Los if/try del modulo no cuentan como nivel: un def adentro de un
    'if TYPE_CHECKING:' sigue siendo de arriba. Iterativo, como _walk.
    """
    stack: list[tuple[Node, tuple[Node, ...]]] = [(root, ())]
    while stack:
        node, enclosing = stack.pop()
        inner = enclosing
        if node.type == "decorated_definition":
            node = node.child_by_field_name("definition") or node
        if node.type in (FUNCTION_NODE, CLASS_NODE):
            yield node, enclosing
            inner = (*enclosing, node)
        stack.extend((child, inner) for child in reversed(node.named_children))


def _is_container(node: Node, enclosing: tuple[Node, ...], category: str) -> bool:
    # Buscando funciones, una clase de arriba no es candidata pero sus metodos si
    return category == CATEGORY_FUNCTION and node.type == CLASS_NODE and not enclosing


def _is_candidate(node: Node, enclosing: tuple[Node, ...], category: str) -> bool:
    """Criterio A."""
    if category == CATEGORY_CLASS:
        return node.type == CLASS_NODE and not enclosing
    if node.type != FUNCTION_NODE:
        return False
    # Funcion de arriba, o metodo de una clase de arriba
    return not enclosing or (len(enclosing) == 1 and enclosing[0].type == CLASS_NODE)


def _is_complete(node: Node) -> bool:
    """Criterio C. Un stub (docstring, pass, ... o NotImplementedError) no tiene
    comportamiento que comparar."""
    body = node.child_by_field_name("body")
    if body is None or node.child_by_field_name("name") is None:
        return False
    if node.type == FUNCTION_NODE and node.child_by_field_name("parameters") is None:
        return False
    return any(not _is_placeholder(statement) for statement in body.named_children)


def _is_placeholder(statement: Node) -> bool:
    if statement.type in ("comment", "pass_statement"):
        return True
    if statement.type == "expression_statement" and statement.named_child_count == 1:
        return statement.named_children[0].type in ("string", "ellipsis")
    if statement.type == "raise_statement":
        return b"NotImplementedError" in (statement.text or b"")
    return False


def _vocabulary(node: Node, name: str) -> frozenset[str]:
    """Las palabras contra las que se buscan las anclas: identificadores,
    comentarios, el docstring y las construcciones que aparecen."""
    words = set(_split(_docstring(node)))
    for current in _walk(node):
        if current.type in ("identifier", "comment"):
            words.update(_split(_text(current)))
        elif current.type in CONSTRUCT_WORDS:
            words.add(CONSTRUCT_WORDS[current.type])
        elif current.type == "call" and _callee(current) == name:
            words.update(RECURSION_WORDS)
    return frozenset(words)


def _anchor_words(anchors: Iterable[str]) -> tuple[tuple[str, frozenset[str]], ...]:
    """Cada tag con las palabras que tiene que encontrar. Un tag sin palabras utiles se descarta."""
    result: dict[str, frozenset[str]] = {}
    for tag in anchors:
        words = frozenset(
            word for word in _split(tag) if len(word) >= MIN_TAG_LENGTH and word not in STOP_WORDS
        )
        if words and tag not in result:
            result[tag] = words
    return tuple(result.items())


def _matching_anchors(
    anchors: tuple[tuple[str, frozenset[str]], ...], vocabulary: frozenset[str]
) -> tuple[str, ...]:
    # Un tag de varias palabras ('binary search') matchea si estan todas
    return tuple(tag for tag, words in anchors if words <= vocabulary)


def _callee(call: Node) -> str | None:
    function = call.child_by_field_name("function")
    if function is not None and function.type == "attribute":
        function = function.child_by_field_name("attribute")
    return _text(function) if function is not None and function.type == "identifier" else None


def _first_error_line(root: Node) -> int:
    for current in _walk(root):
        if current.is_error or current.is_missing:
            return current.start_point.row + 1
    return root.start_point.row + 1


def _docstring(node: Node) -> str:
    body = node.child_by_field_name("body")
    first = body.named_children[0] if body is not None and body.named_children else None
    if first is not None and first.type == "expression_statement" and first.named_child_count == 1:
        if first.named_children[0].type == "string":
            return _text(first)
    return ""


def _walk(node: Node) -> Iterator[Node]:
    # Iterativo: una cadena larga de 'a + b + ...' arma un arbol mas hondo que
    # el limite de recursion de Python
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _name(node: Node) -> str:
    name = node.child_by_field_name("name")
    return _text(name) if name is not None else ""


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def _split(text: str) -> list[str]:
    return [word.lower() for word in WORD_PATTERN.findall(text)]


def _count_lines(code: str) -> int:
    return sum(1 for line in code.split("\n") if line.strip())
