# [FEAT] Stage 2 (Hybrid Part 1): Implement Deterministic AST Seed Tag Extractor (with Regex Fallback)

## 1. Overview & Objectives

In the code-clone search and retrieval pipeline, **Stage 2 (Tag Extraction)** relies on a hybrid architecture:
1. **Part 1 (Deterministic AST Extraction + Regex Fallback):** Parses Python source code into an Abstract Syntax Tree (AST) to extract ground-truth, noise-free structural anchors (`apis`, `structures`, `domain`, `data_structures`). If a snippet contains invalid syntax or incomplete code, it gracefully falls back to a regex-based extractor.
2. **Part 2 (LLM Semantic Expansion):** Receives the seed tags from Part 1 to generate synonyms, paradigm alternatives, and natural language intent variations.

**This issue covers the implementation of Part 1:** a fast, zero-hallucination deterministic AST seed tag extractor with a resilient regex fallback mechanism for unparsable code fragments.

---

## 2. Scope & Technical Requirements

### A. Core Responsibilities
* **Primary Path (AST Traversal):** Operate strictly on a parsed `ast.AST` object (using Python's built-in `ast` module) via an `ast.NodeVisitor` subclass to inspect AST nodes deterministically without hallucination.
* **Fallback Path (Regex Extractor):** If `ast.parse()` raises a `SyntaxError` or `IndentationError` (e.g., incomplete code snippets, notebook cells, or syntax-heavy fragments), automatically route execution to a regex fallback parser (`_extract_regex_fallback_tags`) to salvage functional keywords.
* **Seed Tier Output:** Extract and categorize tokens into four explicit seed tiers:
  1. `apis`: Explicit function/method calls, attribute chains, and external module imports.
  2. `structures`: Top-level syntactic constructs (`def`, `class`) and higher-order function paradigms (`lambda`).
  3. `domain`: Keywords extracted strictly from official function docstrings or top-level comments, normalized and filtered against standard English stop-words.
  4. `data_structures`: Primary built-in container types (`dict`, `list`, `set`, `tuple`) when referenced as operational types.

---

## 3. Data Schema & Interface

### Data Model (`dataclass`)
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
```

### Module Interface & Fallback Flow
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
```

---

## 4. Node Extraction Rules & Fallback Specification

### A. Primary AST Traversal Rules (`ASTSeedTagVisitor`)
| Node Type | Target Element | Extraction Logic / Rules |
| :--- | :--- | :--- |
| `ast.FunctionDef` | Function Name & Docstring | Extract identifier into `structures`. Call `ast.get_docstring(node)` (ensuring position 0 verification). Tokenize docstring, lower-case, and strip English stop-words into `domain`. |
| `ast.Call` | Invoked Functions / Methods | Recursively resolve `ast.Attribute` and `ast.Name` chains (e.g., `input_dict.items()` $\rightarrow$ `input_dict.items`, `sorted()` $\rightarrow$ `sorted`) into `apis`. |
| `ast.Lambda` | Anonymous Functions | Set `has_lambda = True` and add `"lambda"` to `structures`. |
| `ast.Name` | Container Types | Check `node.id` against `{"dict", "list", "set", "tuple"}` and add to `data_structures`. |
| `ast.Import` / `ast.ImportFrom` | External Dependencies | Extract imported module and alias names into `apis`. |

### B. Regex Fallback Parser Rules (`_extract_regex_fallback_tags`)
When `ast.parse()` fails, regex patterns target basic Python grammar primitives:
1. **Function & Class Names:** `r'def\s+([a-zA-Z_]\w*)'` and `r'class\s+([a-zA-Z_]\w*)'` $\rightarrow$ `structures`.
2. **Lambda Constructs:** `r'\blambda\b'` $\rightarrow$ set `has_lambda = True` and add `"lambda"` to `structures`.
3. **Common API Calls:** `r'([a-zA-Z_]\w*)\s*\('` $\rightarrow$ filter against common keywords/built-ins and add to `apis`.
4. **Data Structures:** `r'\b(dict|list|set|tuple)\b'` $\rightarrow$ `data_structures`.
5. **Comments & Incomplete Docstrings:** `r'#\s*(.+)'` or triple-quote blocks `r'"""(.*?)"""'` $\rightarrow$ tokenize and strip stop-words into `domain`.
6. **Metadata:** Set `is_fallback = True`.

---

## 5. Acceptance Criteria (Definition of Done)

* [ ] **Implementation:** Create module `src/pipeline/ast_seed_extractor.py` containing `ASTSeedTagVisitor`, `_extract_regex_fallback_tags`, and `extract_ast_seed_tags`.
* [ ] **Resilient Error Handling:** `extract_ast_seed_tags` must NEVER throw a `SyntaxError` or crash the pipeline when fed unparsable/malformed snippets.
* [ ] **Fallback Flagging:** Ensure `is_fallback` is correctly set to `True` when regex fallback is invoked.
* [ ] **Unit Tests:** Add comprehensive unit tests under `tests/test_ast_seed_extractor.py` covering:
  * Standard valid Python function definitions with docstrings.
  * Async functions, class methods, and lambda expressions.
  * **Unparsable / Malformed Snippets:** e.g., missing colons (`def foo()`), unclosed brackets, or isolated lines of code.
  * Verification that regex fallback successfully extracts basic `structures`, `apis`, and `data_structures` from malformed snippets.
* [ ] **Performance Benchmark:** Valid AST parsing executes in under **5ms**; Regex fallback executes in under **2ms**.

---

## 6. Example Test Case for Fallback

```python
# Malformed snippet (missing colon after def, unclosed parenthesis)
malformed_code = '''
def rank_dictionary_by_value(input_dict, reverse_order=True
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1]
    return dict(sorted_pairs)
'''

seed_tags = extract_ast_seed_tags(malformed_code)

assert seed_tags.is_fallback is True
assert "rank_dictionary_by_value" in seed_tags.structures
assert "sorted" in seed_tags.apis
assert "dict" in seed_tags.data_structures
assert seed_tags.has_lambda is True
```
