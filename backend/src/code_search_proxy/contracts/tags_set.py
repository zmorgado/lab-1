from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from code_search_proxy.constants.app_constants import (
    DEFAULT_MAX_QUERY_TAGS,
    MAX_QUERY_LENGTH,
    QUERY_TIERS,
    TIER_ORDER,
)


def _quote_if_needed(value: str) -> str:
    """Entrecomilla solo si hay whitespace, como en language:"Jupyter Notebook"."""
    return '"' + value + '"' if any(c.isspace() for c in value) else value


@dataclass(frozen=True)
class TagSet:
    """Las cinco categorias de la Etapa 2, ya normalizadas y deduplicadas."""

    api_calls: tuple[str, ...] = ()
    data_structures: tuple[str, ...] = ()
    paradigm: tuple[str, ...] = ()
    algorithm: tuple[str, ...] = ()
    domain_keywords: tuple[str, ...] = ()
    language: str | None = None
    # Los que el modelo pre-selecciona para el picker de #22. No es una sexta
    # categoria: siempre es un subconjunto de las cinco de arriba, ordenado de
    # mas a menos distintivo.
    suggested: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, list[str]]:
        """Las categorias en orden de tier, para serializar sin perder el orden."""
        return {category: list(getattr(self, category)) for category in TIER_ORDER}

    def ordered_tags(
        self,
        max_tags: int | None = None,
        tiers: Sequence[str] = TIER_ORDER,
    ) -> list[str]:
        """Aplana las categorias a una lista unica ordenada por tier.

        Dedupe case-insensitive pero conservando la grafia original: `items` e
        `Items` son el mismo trigrama para GitHub, y la primera aparicion viene
        del tier mas alto, que es la que queremos conservar.
        """
        seen: set[str] = set()
        flat: list[str] = []
        for category in tiers:
            for tag in getattr(self, category):
                key = tag.casefold()
                if key in seen:
                    continue
                seen.add(key)
                flat.append(tag)
                if max_tags is not None and len(flat) >= max_tags:
                    return flat
        return flat

    def query_tags(
        self,
        max_tags: int | None = DEFAULT_MAX_QUERY_TAGS,
        tiers: Sequence[str] = QUERY_TIERS,
    ) -> list[str]:
        """Los tags que realmente entran a `q`, en orden.

        Por defecto solo las categorias literales y pocas: GitHub hace AND
        entre los terminos, asi que el limite real no son los 256 caracteres
        sino cuantas condiciones simultaneas puede cumplir un archivo. Llenar
        la query hasta el borde devuelve cero resultados; la etapa 3 solo
        necesita recortar GitHub a un puñado de candidatos, y de afinar se
        encargan el AST (#20) y los embeddings (#21).

        Quien llama puede pedir otra cosa: #22 deja que el usuario elija los
        tags a mano, y ahi entran las categorias que aca se dejan afuera.
        """
        return self.ordered_tags(max_tags=max_tags, tiers=tiers)

    def to_query(
        self,
        max_tags: int | None = DEFAULT_MAX_QUERY_TAGS,
        tiers: Sequence[str] = QUERY_TIERS,
    ) -> str:
        """Arma el valor de `q` para `search/code`, recortando a 256 chars.

        Los tags con espacios van entre comillas dobles, que en GitHub fuerzan
        match exacto de frase. El idioma viaja como qualifier `language:`, que
        no es texto libre y por lo tanto no admite el operador OR.

        Se agregan tags de a uno mientras entren enteros: truncar la query al
        caracter 256 dejaria un identificador partido, que matchea cualquier
        cosa o directamente nada.
        """
        suffix = f" language:{_quote_if_needed(self.language)}" if self.language else ""
        query = ""
        for tag in self.query_tags(max_tags=max_tags, tiers=tiers):
            candidate = f"{query} {_quote_if_needed(tag)}".strip()
            if len(candidate) + len(suffix) > MAX_QUERY_LENGTH:
                break
            query = candidate
        return f"{query}{suffix}".strip()
