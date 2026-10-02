from code_search_proxy.grep_tags import Tiers, extract_tags

RANK_BY_VALUE = '''
from operator import itemgetter

def rank_by_value(scores):
    """Sort the scores dictionary by value."""
    ordered = sorted(scores.items(), key=itemgetter(1), reverse=True)
    return dict(ordered)
'''


def test_candidates_are_split_by_tier_in_order_of_appearance() -> None:
    assert extract_tags(RANK_BY_VALUE) == Tiers(
        apis=("operator", "sorted", "items", "itemgetter"),
        structures=("rank_by_value",),
        domain=("sort", "scores", "dictionary"),
    )


def test_ordered_puts_apis_first_then_structures_then_domain_words() -> None:
    # AC: los niveles dan el orden en que se llena la query
    assert extract_tags(RANK_BY_VALUE).ordered() == (
        "operator",
        "sorted",
        "items",
        "itemgetter",
        "rank_by_value",
        "sort",
        "scores",
        "dictionary",
    )


def test_keywords_and_generic_names_are_left_out() -> None:
    snippet = '''
class WordCounter(Base):
    def __init__(self, path):
        super().__init__()
        self.path = path

    def tally(self):
        total = 0
        while (total < len(self.path)):
            assert isinstance(self.path, str)
            print(fn(total))
            total += 1
        return (total)
'''

    # AC: ni keywords ('while', 'return'), ni builtins genericos, ni dunders,
    # ni nombres de menos de tres caracteres
    assert extract_tags(snippet).ordered() == ("WordCounter", "tally")


def test_a_lambda_counts_as_a_structure() -> None:
    snippet = '''
def sort_dictionary(d):
    return dict(sorted(d.items(), key=lambda item: item[1]))
'''

    assert extract_tags(snippet).structures == ("sort_dictionary", "lambda")


def test_a_snippet_with_nothing_distinctive_yields_no_candidates() -> None:
    assert extract_tags("x = 1\ny = x + 2\nprint(len(str(y)))\n").ordered() == ()


def test_prose_in_a_docstring_is_not_read_as_an_import() -> None:
    snippet = '''
def load_rows(path):
    """Load the rows
    from the given file."""
    return open(path).readlines()
'''

    assert extract_tags(snippet).ordered() == (
        "open",
        "readlines",
        "load_rows",
        "load",
        "rows",
    )


def test_a_soft_keyword_used_as_a_name_is_kept() -> None:
    # 'match' es keyword solo en un 'match' statement; 're.match(' es una API
    assert extract_tags("import re\nfound = re.match(pattern, line)\n").apis == ("match",)


def test_an_import_with_windows_line_endings_is_kept() -> None:
    # Un archivo con CRLF que llega por curl o 'jq -Rs' trae '\r' antes del salto
    snippet = "import numpy\r\nzeros = numpy.zeros(3)\r\n"

    assert extract_tags(snippet).apis == ("numpy", "zeros")
