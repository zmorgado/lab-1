# [FEAT] Stage 2 (Hybrid Part 1): Implement Deterministic AST Seed Tag Extractor & Parallel Query Category Builder

## 1. Overview & Objectives

In the code-clone search and retrieval pipeline, **Stage 2 (Tag Extraction & Query Formulation)** relies on a hybrid architecture:
1. **Part 1 (Deterministic AST Extraction + Parallel Query Builder):** Parses Python source code into an Abstract Syntax Tree (AST) to extract ground-truth, noise-free structural anchors (`apis`, `structures`, `domain`, `data_structures`) with a regex fallback, and maps these seed tags into **three distinct parallel search query categories** for GitHub Search API dispatch.
2. **Part 2 (LLM Semantic Expansion):** Receives the seed tags and initial parallel queries from Part 1 to generate synonyms, paradigm alternatives, and natural language intent variations.

**This issue covers the implementation of Part 1:** a fast, zero-hallucination deterministic AST seed tag extractor (with regex fallback) and the builder logic for the 3-part parallel search query categories.

---

## 2. Scope & Technical Requirements

### A. Core Extractor Responsibilities
* **Primary Path (AST Traversal):** Operate strictly on a parsed `ast.AST` object (using Python's built-in `ast` module) via an `ast.NodeVisitor` subclass to inspect AST nodes deterministically without hallucination.
* **Fallback Path (Regex Extractor):** If `ast.parse()` raises a `SyntaxError` or `IndentationError` (e.g., incomplete code snippets, notebook cells, or syntax-heavy fragments), automatically route execution to a regex fallback parser (`_extract_regex_fallback_tags`) to salvage functional keywords.
* **Seed Tier Output:** Extract and categorize tokens into four explicit seed tiers:
  1. `apis`: Explicit function/method calls, attribute chains, and external module imports.
  2. `structures`: Top-level syntactic constructs (`def`, `class`) and higher-order function paradigms (`lambda`).
  3. `domain`: Keywords extracted strictly from official function docstrings or top-level comments, normalized and filtered against standard English stop-words.
  4. `data_structures`: Primary built-in container types (`dict`, `list`, `set`, `tuple`) when referenced as operational types.

### B. Parallel Query Category Builder Responsibilities
Categorize and map extracted seed tags into three structured search query payloads (each capped at 5–6 high-priority terms + `language:python`) to execute multi-query dispatch without triggering GitHub API `AND` over-filtering:

1. **Category 1 — Syntactic Query:** Combines exact function names, API invocations, and container types to catch near-literal implementations.
2. **Category 2 — Conceptual / Domain Query:** Combines docstring domain keywords, function signatures, and task intent to catch intent-matched code.
3. **Category 3 — Alternative API / Paradigm Query:** Focuses on structural paradigm markers (e.g., `lambda`, higher-order functions, functional transformers, or module calls) to catch alternative implementation styles.

---

## 3. Data Schema & Interface

### Data Models (`dataclass`)
```python
from dataclasses import dataclass, field
from typing import Set, List, Dict, Any

@dataclass
class ASTSeedTags:
    apis: Set[str] = field(default_factory=set)
    structures: Set[str] = field(default_factory=set)
    domain: Set[str] = field(default_factory=set)
    data_structures: Set[str] = field(default_factory=set)
    has_lambda: bool = False
    is_fallback: bool = False  # Set to True when Regex Fallback was triggered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "apis": sorted(list(self.apis)),
            "structures": sorted(list(self.structures)),
            "domain": sorted(list(self.domain)),
            "data_structures": sorted(list(self.data_structures)),
            "has_lambda": self.has_lambda,
            "is_fallback": self.is_fallback
        }

@dataclass
class ParallelQueries:
    syntactic_query: str      # Category 1: Exact symbol & API co-occurrence
    conceptual_query: str     # Category 2: Domain intent & docstring keywords
    paradigm_query: str       # Category 3: Paradigm & structural mechanism
    raw_tags: ASTSeedTags = field(default_factory=ASTSeedTags)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "syntactic_query": self.syntactic_query,
            "conceptual_query": self.conceptual_query,
            "paradigm_query": self.paradigm_query,
            "raw_tags": self.raw_tags.to_dict()
        }
```

### Module Interface & Pipeline Flow
```python
import ast
import logging

logger = logging.getLogger(__name__)

def extract_ast_seed_tags(code_snippet: str) -> ASTSeedTags:
    """
    Attempts to parse a Python code snippet string into an AST.
    If parsing succeeds, uses ASTVisitor for deterministic extraction.
    If ast.parse raises SyntaxError/IndentationError, routes to Regex Fallback.
    """
    try:
        parsed_tree = ast.parse(code_snippet)
        visitor = ASTSeedTagVisitor()
        visitor.visit(parsed_tree)
        return visitor.to_seed_tags()
    except (SyntaxError, IndentationError) as e:
        logger.warning(f"AST parsing failed ({e}). Falling back to Regex extraction.")
        return _extract_regex_fallback_tags(code_snippet)

def build_parallel_queries(seed_tags: ASTSeedTags, max_terms_per_query: int = 6) -> ParallelQueries:
    """
    Constructs the 3-part parallel GitHub search query strings from the AST seed tags.
    """
    ...
```

---

## 4. Node Extraction Rules & Parallel Query Construction Logic

### A. Node Extraction Rules
| Node Type | Target Element | Extraction Logic / Rules |
| :--- | :--- | :--- |
| `ast.FunctionDef` | Function Name & Docstring | Extract identifier into `structures`. Call `ast.get_docstring(node)`. Tokenize docstring, lower-case, and strip English stop-words into `domain`. |
| `ast.Call` | Invoked Functions / Methods | Recursively resolve `ast.Attribute` and `ast.Name` chains (e.g., `input_dict.items()` $\rightarrow$ `input_dict.items`, `sorted()` $\rightarrow$ `sorted`) into `apis`. |
| `ast.Lambda` | Anonymous Functions | Set `has_lambda = True` and add `"lambda"` to `structures`. |
| `ast.Name` | Container Types | Check `node.id` against `{"dict", "list", "set", "tuple"}` and add to `data_structures`. |
| `ast.Import` / `ast.ImportFrom` | External Dependencies | Extract imported module and alias names into `apis`. |

### B. Construction Logic for the 3 Parallel Query Categories

Each query string is assembled, deduplicated, capped at `max_terms_per_query` (default 6 terms), and appended with `language:python`:

1. **Category 1 (Syntactic Query Build):**
   * **Source Tiers:** Primary selection from `apis` + `structures` + `data_structures`.
   * **Assembly Rule:** `python <top_structures> <top_apis> <data_structures> language:python`
   * **Example Output:** `python rank_dictionary_by_value sorted items dict lambda language:python`

2. **Category 2 (Conceptual / Domain Query Build):**
   * **Source Tiers:** Primary selection from `domain` keywords + function signature identifiers (`def <name>`).
   * **Assembly Rule:** `def <primary_structure> <domain_term_1> <domain_term_2> <domain_term_3> language:python`
   * **Example Output:** `def rank sort dictionary values language:python`

3. **Category 3 (Alternative API / Paradigm Query Build):**
   * **Source Tiers:** Core paradigm markers (`lambda`, `map`, `filter`, `sorted`, `itemgetter`, import modules) combined with data structure types.
   * **Assembly Rule:** `python <paradigm_terms> <data_structures> <top_apis> language:python`
   * **Example Output:** `python lambda sorted dict items key language:python`

---

## 5. Acceptance Criteria (Definition of Done)

* [ ] **Implementation:** Create module `src/pipeline/ast_seed_extractor.py` containing `ASTSeedTagVisitor`, `_extract_regex_fallback_tags`, `extract_ast_seed_tags`, and `build_parallel_queries`.
* [ ] **Resilient Error Handling:** `extract_ast_seed_tags` must NEVER throw a `SyntaxError` or crash when fed unparsable/malformed snippets.
* [ ] **Parallel Query Construction:** `build_parallel_queries` must correctly generate all 3 distinct query strings (`syntactic_query`, `conceptual_query`, `paradigm_query`) from both standard AST seed tags and regex fallback tags.
* [ ] **Term Limit & Scoping:** Ensure each constructed query contains no more than 6 terms and includes `language:python`.
* [ ] **Unit Tests:** Add unit tests under `tests/test_ast_seed_extractor.py` verifying:
  * Extraction accuracy across AST and Regex fallback modes.
  * Validation of the 3 generated query strings for syntactical correctness, formatting, and term caps.
* [ ] **Performance Benchmark:** AST extraction + 3-query string assembly executes in under **6ms**.

---

## 6. Example Test Case

```python
# Valid snippet test
snippet_code = '''
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
'''

seed_tags = extract_ast_seed_tags(snippet_code)
parallel_queries = build_parallel_queries(seed_tags)

assert "rank_dictionary_by_value" in seed_tags.structures
assert "sorted" in seed_tags.apis
assert "dict" in seed_tags.data_structures

# Verify 3 Parallel Query Categories
assert "language:python" in parallel_queries.syntactic_query
assert "language:python" in parallel_queries.conceptual_query
assert "language:python" in parallel_queries.paradigm_query

assert "sorted" in parallel_queries.syntactic_query or "rank" in parallel_queries.syntactic_query
assert "sort" in parallel_queries.conceptual_query or "dictionary" in parallel_queries.conceptual_query
assert "lambda" in parallel_queries.paradigm_query or "dict" in parallel_queries.paradigm_query
```
