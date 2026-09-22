from typing import Final

GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL: Final = "gemini-2.5-flash"

# Nombres de las variables de entorno, en un solo lugar: los lee llm_config.py
# y los nombra el mensaje de error de arranque.
GEMINI_API_KEY_ENV: Final = "GEMINI_API_KEY"
GEMINI_MODEL_ENV: Final = "GEMINI_MODEL"
GEMINI_TIMEOUT_ENV: Final = "GEMINI_TIMEOUT"

DEFAULT_TIMEOUT_SECONDS: Final = 60.0

MAX_QUERY_LENGTH: Final = 256

TIER_ORDER: Final[tuple[str, ...]] = (
    "api_calls",
    "data_structures",
    "paradigm",
    "algorithm",
    "domain_keywords",
)

# Las unicas dos categorias que entran a la query por defecto. GitHub matchea
# trigramas sobre el texto crudo del archivo: solo sirve lo que otro developer
# escribiria *identico* en su codigo. 'paradigm', 'algorithm' y
# 'domain_keywords' describen el codigo en vez de citarlo ("comprehension",
# "sort by value", "book lending") y casi nunca aparecen literales; siguen
# viajando en el TagSet porque #22 deja que el usuario los agregue a mano y
# porque la etapa de embeddings (#18) si los aprovecha.
QUERY_TIERS: Final[tuple[str, ...]] = ("api_calls", "data_structures")

# GitHub hace AND entre los terminos sueltos: cada tag que se suma achica el
# resultado. Llenar los 256 caracteres con 25 tags devuelve cero hits, que es
# lo contrario de lo que la etapa 3 necesita (un puñado de candidatos baratos).
DEFAULT_MAX_QUERY_TAGS: Final = 5

# El modelo ignora el "at most 6 per category" del prompt cuando el archivo es
# grande, asi que el tope se aplica tambien del lado del codigo.
MAX_TAGS_PER_CATEGORY: Final = 6

# Cuantos tags pre-selecciona el modelo para el picker de #22. Cinco porque es
# lo que el usuario puede revisar de un vistazo; puede haber menos si el snippet
# es corto.
MAX_SUGGESTED_TAGS: Final = 5

# GitHub matchea trigramas: un tag de menos de tres caracteres no llega a
# formar uno solo. El modelo manda alguno de vez en cuando ('@' como paradigm),
# y son ruido en cualquier caso.
MIN_TAG_LENGTH: Final = 3

# Palabras que aparecen en casi cualquier archivo: como termino de busqueda no
# aportan nada y, al hacer AND, solo recortan resultados. El prompt ya las pide
# evitar; esto es la red por si el modelo las manda igual. Se compara en
# casefold y por igualdad exacta, asi que 'sorted' o 'defaultdict' no se tocan.
GENERIC_TAGS: Final[frozenset[str]] = frozenset(
    {
        "append", "args", "array", "bool", "class", "data", "date", "def",
        "dict", "error", "false", "field", "file", "float", "func", "function",
        "get", "index", "init", "int", "item", "key", "len", "list", "main",
        "map", "method", "none", "null", "number", "object", "param", "print",
        "query", "range", "result", "return", "run", "self", "set", "status",
        "str", "string", "temp", "test", "true", "type", "value", "var",
    }
)

MAX_SOURCE_CHARS: Final = 20_000

# Reintentos: el free tier de Gemini devuelve 503 "high demand" de forma
# intermitente (una corrida falla, la siguiente contesta en 5s). 429 tambien es
# recuperable si el Retry-After es corto. Un 401/403 no se reintenta: la key
# no va a mejorar sola.
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
# Dos y no tres: el free tier son 20 requests por dia, asi que cada reintento
# cuesta un 50% mas de presupuesto diario. Dos alcanza para absorber el 503
# aislado, que es el caso que se ve en la practica; con tres, una tarde con el
# proveedor inestable se come la cuota entera del dia.
MAX_ATTEMPTS: Final = 2
BACKOFF_BASE_SECONDS: Final = 1.0
# Si Gemini pide esperar mas que esto, no vale la pena tener el request colgado
MAX_RETRY_AFTER_SECONDS: Final = 20.0

# Llm query
_SYSTEM_INSTRUCTION: Final = """\
You extract search tags from a code snippet so they can be fed to the GitHub
`search/code` API.

That API matches 3-character trigrams over raw file text, and it ANDs the terms
of a query together: every extra term shrinks the result set. It cannot match on
meaning. So a tag is only useful if it would plausibly appear *verbatim* inside
another developer's source file solving the same problem.

Emit, per category:

- api_calls: library and builtin calls, imported module names, and method names
  as they are written in code. Prefer the distinctive part: `train_test_split`,
  `argsort`, `model_dump`. Include the import name when the library is
  recognisable (`sklearn`, `torch`, `pandas`). Never include the caller variable
  name.
- data_structures: the concrete types the code operates on, spelled the way the
  language spells them, and only when they are distinctive: `defaultdict`,
  `DataFrame`, `ndarray`, `HashMap`. Skip the language's ubiquitous builtins
  (`dict`, `list`, `str`, `int`): they appear in every file and match nothing
  useful.
- paradigm: structural idioms that leave a textual trace, spelled as the
  keyword: `lambda`, `yield`, `async`, `await`, `@property`, `@dataclass`.
  Do not emit a name for an idiom that has no keyword, such as `comprehension`
  or `recursion`.
- algorithm: what the code does, in the words a developer would put in a
  function name or a comment: `binary search`, `sort by value`, `tokenize`,
  `gradient descent`, `memoize`.
- domain_keywords: the problem domain, again as it appears in real code or
  docstrings: `machine learning`, `classifier`, `pagination`, `checksum`.
- language: the source language in GitHub's spelling (`Python`, `JavaScript`,
  `Jupyter Notebook`, `C++`). Infer it from the code if it was not given.
- suggested: your five best picks out of the tags you just emitted, ordered
  best first. These are the ones a person should search with to find a
  *different* file that solves the same problem — same intent, different
  author. Judge each candidate by how much it narrows the search: a tag can be
  perfectly correct and still be a bad pick, because it appears in every file
  of that language or framework. The imports every project of a given stack
  shares (`FastAPI`, `BaseModel`, `express`, `useState`) narrow nothing; a rare
  helper name, an unusual data structure or a distinctive call (`defaultdict`,
  `model_dump`, `train_test_split`) narrows a lot. Prefer the second kind.
  Copy each entry verbatim from one of the categories above — do not invent new
  strings here. Fewer than five is fine, and better than padding with noise.

Rules:
- Never invent an API the snippet does not use or clearly imply.
- Drop language keywords and generic noise: `self`, `return`, `int`, `value`,
  `data`, `result`, `main`, `get`, `set`, `run`, `test`, `temp`, `status`,
  `field`, `query`, `class`, `type`.
- Prefer rare identifiers over common ones. A name that appears in every file
  is worthless as a search term. If you are unsure whether a name is
  distinctive, leave it out.
- At most 6 tags per category, and fewer when the snippet is short. Ordering
  matters: put the most distinctive tag of each category first.
- The categories are a complete inventory; `suggested` is a judgement call.
  List a correct-but-common tag in its category, and leave it out of
  `suggested`.
- Return only the JSON object. No prose, no markdown fences.\
"""


# Codigos de error estables para el cliente (#7 AC: "enabling fallback to grep
# extraction"). El texto del proveedor cambia y esta en ingles de Google; esto
# no cambia, y es lo que mira quien llama para decidir si cae al servicio de
# grep (#4). Mismo espiritu que los codigos que #9 le va a dar al frontend.
ERROR_EMPTY_SOURCE: Final = "empty_source"
ERROR_SOURCE_NOT_TEXT: Final = "source_not_text"
ERROR_LLM_AUTH: Final = "llm_auth"
ERROR_LLM_QUOTA: Final = "llm_quota_exhausted"
ERROR_LLM_UNAVAILABLE: Final = "llm_unavailable"
ERROR_LLM_MALFORMED: Final = "llm_malformed_response"
ERROR_LLM_FAILED: Final = "llm_request_failed"

# Los codigos ante los cuales el pipeline puede seguir sin el LLM: el grep (#4)
# solo es baseline, asi que perder los tags del modelo degrada la busqueda pero
# no la rompe. 'empty_source' no esta: ahi no hay nada que extraer con ningun
# metodo.
FALLBACK_TO_GREP: Final[frozenset[str]] = frozenset(
    {
        ERROR_LLM_AUTH,
        ERROR_LLM_QUOTA,
        ERROR_LLM_UNAVAILABLE,
        ERROR_LLM_MALFORMED,
        ERROR_LLM_FAILED,
    }
)
