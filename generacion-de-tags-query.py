import re
import urllib.parse
from typing import Dict, List, Set, Any

def extract_tags_and_build_github_query_regex(
    code_snippet: str, 
    language: str = "python", 
    max_tags: int = 6
) -> Dict[str, Any]:
    """
    Analiza un snippet de código utilizando expresiones regulares (enfoque grep),
    extrayendo palabras clave jerarquizadas para generar una query de GitHub.
    """
    tier_1_apis: Set[str] = set()
    tier_2_structures: Set[str] = set()
    tier_3_domain: Set[str] = set()

    # Identificadores genéricos a filtrar
    ignored_identifiers = {
        "self", "cls", "args", "kwargs", "True", "False", "None", 
        "int", "str", "float", "bool", "return", "def", "and", "or",
        "import", "from", "for", "in", "if", "else", "elif"
    }

    # --- SIMULACIÓN DE GREP MEDIANTE REGEX ---

    # Nivel 1: Imports (busca "import X" o "from X")
    imports = re.findall(r'^(?:import|from)\s+([a-zA-Z_]\w*)', code_snippet, re.MULTILINE)
    tier_1_apis.update(imports)

    # Nivel 1: Invocaciones (palabras seguidas de paréntesis, ignorando 'def')
    # Usa un "negative lookbehind" (? 2])

    # Nivel 3: Docstrings (contenido entre comillas triples simples o dobles)
    docstrings = re.findall(r'\"\"\"(.*?)\"\"\"|\'\'\'(.*?)\'\'\'', code_snippet, re.DOTALL)
    for doc_tuple in docstrings:
        # doc_tuple tendrá el valor en la posición 0 (""") o en la 1 (''')
        doc_text = doc_tuple[0] or doc_tuple[1]
        # Extraer palabras de más de 3 letras
        words = re.findall(r'\b[a-zA-Z]{4,}\b', doc_text)
        tier_3_domain.update([w.lower() for w in words[:3]])

    # --- LIMPIEZA Y PRIORIZACIÓN ---
    
    tier_1_apis -= ignored_identifiers
    tier_3_domain -= ignored_identifiers

    ordered_candidates = (
        list(tier_1_apis) + 
        list(tier_2_structures) + 
        list(tier_3_domain)
    )

    selected_tags: List[str] = []
    for tag in ordered_candidates:
        if tag not in selected_tags and len(selected_tags) < max_tags:
            selected_tags.append(tag)

    # --- CONSTRUCCIÓN DE LA QUERY ---
    
    raw_query = f"{' '.join(selected_tags)} language:{language}"
    encoded_q = urllib.parse.quote_plus(raw_query)
    github_url = f"https://api.github.com/search/code?q={encoded_q}"

    return {
        "selected_tags": selected_tags,
        "query_string": raw_query,
        "github_api_url": github_url,
        "tiers_breakdown": {
            "tier_1_apis": list(tier_1_apis),
            "tier_2_structures": list(tier_2_structures),
            "tier_3_domain": list(tier_3_domain)
        }
    }

# --- EJEMPLO DE USO ---
if __name__ == "__main__":
    snippet_a = '''
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
    '''
    
    result = extract_tags_and_build_github_query_regex(snippet_a, language="python")
    print("Tags Seleccionados:", result["selected_tags"])