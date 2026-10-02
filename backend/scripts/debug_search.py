"""
debug_search.py — one run of pipeline.search, without the server
-----------------------------------------------------------------
Calls the same function POST /api/search calls, with the real GitHub client, the
real LLM service and UniXcoder, so it can be stepped through in a debugger. Put a
breakpoint in pipeline.search and launch this file.

Credentials come from the environment or backend/.env, like the service:
GITHUB_TOKEN (or a logged-in 'gh') and GEMINI_API_KEY. Without the Gemini key the
run still works, and the LLM reports llm_unavailable.

Usage (from backend/):
    PYTHONPATH=src uv run python scripts/debug_search.py [snippet_file.py]
"""

import asyncio
import sys
from pathlib import Path

from snippet_search.config import load_settings
from snippet_search.github import GitHubClient
from snippet_search.llm_tags import GeminiTagService
from snippet_search.pipeline import search, unixcoder_rank

# El ejemplo de docs/research/solution-schematics-v2.md
DEFAULT_SNIPPET = '''
"""Agente base: define el flujo fijo de un turno (Template Method)."""

from abc import ABC, abstractmethod
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from ringr_agents.http import HttpClient, HttpRequest
from ringr_agents.models import ConversationModel, Message, ParserModel
from ringr_agents.turn import ActionStatus, TurnResult


class AgentData(BaseModel):
    """Base de los schemas de agente: salida del parser validada y normalizada.

    Los campos deben ser escalares: cada uno se envía también como header HTTP.
    """

    # extra="ignore": claves inventadas por el LLM nunca llegan a los headers
    # frozen=True: seguro para guardar como último envío y comparar por igualdad
    model_config = ConfigDict(extra="ignore", frozen=True)


class Agent[T: AgentData](ABC):
    """Las subclases solo declaran schema, endpoint y la regla should_act."""

    schema: type[T]
    endpoint: ClassVar[str]

    def __init__(
        self,
        conversation_model: ConversationModel,
        parser_model: ParserModel,
        http_client: HttpClient,
        token: str,
    ) -> None:
        self._conversation_model = conversation_model
        self._parser_model = parser_model
        self._http_client = http_client
        self._token = token
        self._history: list[Message] = []
        # Último envío exitoso: el parser lee toda la conversación y repite datos
        self._last_sent: T | None = None

    def handle_turn(self, user_message: str) -> TurnResult[T]:
        self._history.append(Message(role="user", content=user_message))

        reply = self._conversation_model.answer_user(self._history)
        self._history.append(Message(role="assistant", content=reply))

        data = self.schema.model_validate(self._parser_model.parse_data(self._history))

        return TurnResult(reply=reply, data=data, action=self._execute_action(data))

    def _execute_action(self, data: T) -> ActionStatus:
        if not self.should_act(data):
            return ActionStatus.SKIPPED

        # Igualdad del schema normalizado: "150" y 150 son el mismo compromiso
        if data == self._last_sent:
            return ActionStatus.DUPLICATE

        response = self._http_client.send(self._build_request(data))
        if response.status_code != 200:
            # No se marca como enviado: el próximo turno puede reintentar
            return ActionStatus.FAILED

        self._last_sent = data
        return ActionStatus.SENT

    def _build_request(self, data: T) -> HttpRequest:
        # Body y headers salen del mismo schema normalizado: nunca pueden divergir
        body = data.model_dump(mode="json")
        # quote: evita inyección de headers (\r\n) y caracteres no ASCII. Agrega igualmente una complejidad dado que el receptor deberia usar unquote
        data_headers = {key: quote(str(value), safe="") for key, value in body.items()}
        return HttpRequest(
            method="POST",
            url=self.endpoint,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                **data_headers,
            },
            body=body,
        )

    @abstractmethod
    def should_act(self, data: T) -> bool:
        """Regla de negocio: decide si los datos habilitan la acción externa."""

'''

TOP_CANDIDATES = 10


async def main(source: str) -> None:
    settings = load_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set: the run goes on with grep tags only.\n")

    async with GitHubClient(settings) as github, GeminiTagService(settings) as llm:
        outcome = await search(github, source, "python", llm=llm, rank=unixcoder_rank)

    print(f"query:    {outcome.query.q}")
    print(f"llm:      {outcome.llm_tags.as_dict() if outcome.llm_tags else outcome.llm_error}")
    print(f"snippet:  {outcome.snippet}")
    print(f"anchors:  {list(outcome.anchors)}")
    print(f"rejected: {outcome.rejected}")
    for skipped in outcome.skipped:
        print(f"skipped:  {skipped.repo}/{skipped.path}: {skipped.reason}")

    print(f"\n{len(outcome.candidates)} candidates, top {TOP_CANDIDATES}:")
    for candidate in outcome.candidates[:TOP_CANDIDATES]:
        subtree = candidate.subtree
        print(
            f"  {candidate.score:.3f}  {candidate.repo}/{candidate.path}"
            f":{subtree.start_line}-{subtree.end_line}  {subtree.name}  {list(subtree.anchors)}"
        )


if __name__ == "__main__":
    snippet = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else DEFAULT_SNIPPET
    asyncio.run(main(snippet))
