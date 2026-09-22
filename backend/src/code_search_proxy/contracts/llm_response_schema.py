
from typing import Any, Final

from code_search_proxy.constants.app_constants import TIER_ORDER

_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
  # Schema OpenAPI que Gemini respeta al generar. Con `responseMimeType` en JSON
  # la respuesta viene garantizada con esta forma, asi que no hace falta parsear
  # markdown ni pedirle al modelo "devolveme JSON y nada mas"
  "type": "OBJECT",
  "properties": {
      "api_calls": {"type": "ARRAY", "items": {"type": "STRING"}},
      "data_structures": {"type": "ARRAY", "items": {"type": "STRING"}},
      "paradigm": {"type": "ARRAY", "items": {"type": "STRING"}},
      "algorithm": {"type": "ARRAY", "items": {"type": "STRING"}},
      "domain_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
      "language": {"type": "STRING"},
      "suggested": {"type": "ARRAY", "items": {"type": "STRING"}},
  },
  "required": [*TIER_ORDER, "language", "suggested"],
  # 'suggested' va ultimo a proposito: el modelo genera en este orden, asi que
  # cuando le toca elegir ya tiene las cinco categorias escritas delante y
  # elige entre ellas en vez de inventar sobre la marcha.
  "propertyOrdering": [*TIER_ORDER, "language", "suggested"],
}
