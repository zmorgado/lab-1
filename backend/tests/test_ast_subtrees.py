from pathlib import Path

import pytest

from snippet_search.ast_subtrees import (
    CATEGORY_CLASS,
    CATEGORY_FUNCTION,
    Isolation,
    UnparseableSource,
    analyze_snippet,
    isolate,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Una busqueda binaria de 10 lineas: del largo de las funciones de bisect.py
BINARY_SEARCH = '''
def insert_sorted(items, value):
    """Insert value into items keeping them sorted."""
    low, high = 0, len(items)
    while low < high:
        mid = (low + high) // 2
        if value < items[mid]:
            high = mid
        else:
            low = mid + 1
    items.insert(low, value)
'''


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.py.txt").read_text(encoding="utf-8")


def names(isolation: Isolation) -> list[str]:
    return [subtree.name for subtree in isolation.subtrees]


# --- el snippet --------------------------------------------------------------


def test_a_pasted_function_is_a_function() -> None:
    shape = analyze_snippet(BINARY_SEARCH)

    assert shape.category == CATEGORY_FUNCTION
    assert not shape.fallback
    assert shape.lines == 10


def test_a_pasted_class_is_a_class() -> None:
    shape = analyze_snippet("class Stack:\n    def push(self, x):\n        self.items.append(x)\n")

    assert shape.category == CATEGORY_CLASS


def test_a_method_pasted_with_its_indentation_is_a_function() -> None:
    shape = analyze_snippet("    def area(self):\n        return self.width * self.height\n")

    assert shape.category == CATEGORY_FUNCTION
    assert not shape.fallback


def test_a_decorated_function_is_a_function() -> None:
    shape = analyze_snippet("@cache\ndef fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n")

    assert shape.category == CATEGORY_FUNCTION
    assert not shape.fallback


def test_loose_statements_fall_back_to_function() -> None:
    shape = analyze_snippet("import heapq\nheap = []\nheapq.heappush(heap, 3)\n")

    # Sin def ni class se compara contra funciones, y queda dicho
    assert shape.category == CATEGORY_FUNCTION
    assert shape.fallback


# --- criterios sobre archivos reales -----------------------------------------


def test_a_keeps_top_level_functions_and_methods_but_drops_nested_ones() -> None:
    isolation = isolate(fixture("cpython_textwrap"), analyze_snippet(BINARY_SEARCH), ["text"])

    # textwrap.indent define 'predicate' y 'prefixed_lines' adentro
    assert "indent" in names(isolation)
    assert "predicate" not in names(isolation)
    assert "prefixed_lines" not in names(isolation)
    assert isolation.rejected["A"] == 2


def test_a_with_a_class_snippet_keeps_classes_only() -> None:
    snippet = analyze_snippet(
        "class Counter:\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        "    def increment(self):\n"
        "        self.count += 1\n"
        "        return self.count\n"
    )

    isolation = isolate(fixture("cpython_numbers"), snippet, ["number"])

    assert {subtree.kind for subtree in isolation.subtrees} == {"class_definition"}
    assert "Number" in names(isolation)
    assert isolation.rejected["A"] > 0


def test_c_drops_abstract_stubs_and_keeps_concrete_methods() -> None:
    isolation = isolate(fixture("cpython_numbers"), analyze_snippet(BINARY_SEARCH), ["complex"])

    # Complex.__complex__ es abstracto (solo docstring); Real.__complex__ hace algo
    survivors = [(subtree.parent, subtree.name) for subtree in isolation.subtrees]
    assert ("Real", "__complex__") in survivors
    assert ("Complex", "__complex__") not in survivors
    assert isolation.rejected["C"] > 0


def test_b_drops_subtrees_without_any_anchor() -> None:
    isolation = isolate(fixture("cpython_bisect"), analyze_snippet(BINARY_SEARCH), ["insort"])

    assert names(isolation) == ["insort_right", "insort_left"]
    assert isolation.rejected["B"] == 2


def test_b_matches_a_multi_word_tag_against_the_docstring() -> None:
    # Un tag conceptual del LLM: 'keep' y 'sorted' estan en el docstring de insort_*
    isolation = isolate(
        fixture("cpython_bisect"), analyze_snippet(BINARY_SEARCH), ["keep sorted"]
    )

    assert names(isolation) == ["insort_right", "insort_left"]


def test_b_matches_a_construct_the_code_never_names() -> None:
    # 'generator' no aparece escrito: lo ponen el 'yield' de indent y el
    # 'any(c != '-' for c in ...)' de _handle_long_word
    isolation = isolate(fixture("cpython_textwrap"), analyze_snippet(BINARY_SEARCH), ["generator"])

    assert names(isolation) == ["_handle_long_word", "indent"]
    assert all(subtree.anchors == ("generator",) for subtree in isolation.subtrees)


def test_length_drops_subtrees_far_longer_than_the_snippet() -> None:
    isolation = isolate(fixture("cpython_textwrap"), analyze_snippet(BINARY_SEARCH), ["chunks"])

    # _wrap_chunks tiene unas 70 lineas contra las 10 del snippet
    assert "_wrap_chunks" not in names(isolation)
    assert isolation.rejected["length"] > 0


def test_a_file_where_nothing_survives_is_an_empty_set() -> None:
    isolation = isolate(fixture("cpython_numbers"), analyze_snippet(BINARY_SEARCH), ["insort"])

    assert isolation.subtrees == ()


def test_a_file_that_does_not_parse_is_reported_with_its_line() -> None:
    # Un template de Jinja: GitHub lo indexa como Python, pero no lo es
    with pytest.raises(UnparseableSource, match="line 1"):
        isolate(fixture("cookiecutter_users_models"), analyze_snippet(BINARY_SEARCH), ["user"])


# --- la forma de salida ------------------------------------------------------


def test_a_subtree_carries_its_code_range_and_parent() -> None:
    isolation = isolate(fixture("cpython_textwrap"), analyze_snippet(BINARY_SEARCH), ["text"])
    method = next(s for s in isolation.subtrees if s.name == "_munge_whitespace")
    lines = fixture("cpython_textwrap").split("\n")

    assert method.parent == "TextWrapper"
    assert method.kind == "function_definition"
    assert lines[method.start_line - 1].strip().startswith("def _munge_whitespace")
    # El codigo se dedenta: el metodo arranca en la columna 0, como un snippet pegado
    assert method.code.startswith("def _munge_whitespace(self, text):")
    assert method.code.count("\n") == method.end_line - method.start_line
