"""Orquestación del chat: transportista -> búsqueda -> umbral -> LLM en streaming -> citas.

Emite eventos de dominio; la API los traduce a SSE [R9, R11, D7, D8, D16, F3, F4].
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.domain.answer import (
    FinalAnswer,
    build_request,
    finalize,
    no_evidence_answer,
    parse_llm_output,
)
from app.domain.carriers import Match, resolve_carrier
from app.domain.errors import (
    EmbeddingProviderError,
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
)
from app.domain.llm import END_ANSWER, TextDelta, Usage
from app.domain.models import ChatRequest
from app.domain.retrieval import RetrievedChunk, SearchFilters
from app.ports.embedder import Embedder
from app.ports.llm import LLM
from app.ports.retriever import Retriever

log = logging.getLogger(__name__)

LLM_ATTEMPTS = 3  # reintentos solo antes del primer token: lo ya mostrado no se puede deshacer
RETRY_BASE_S = 1.0


@dataclass(frozen=True)
class Clarification:
    suggestions: list[str]


@dataclass(frozen=True)
class Retrieval:
    carrier_filter: str | None
    chunks: list[RetrievedChunk]

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class Answer:
    final: FinalAnswer


@dataclass(frozen=True)
class Failure:
    code: str
    message: str


ChatEvent = Clarification | Retrieval | Token | Answer | Failure


@dataclass(frozen=True)
class ChatService:
    embedder: Embedder
    llm: LLM
    retriever: Retriever
    threshold: float

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        known = await run_in_threadpool(self.retriever.known_carriers)

        # 1. Transportista: el filtro explícito manda; si no, se resuelve en la pregunta [D16]
        carrier = request.carrier
        if carrier is None:
            resolution = resolve_carrier(request.question, known)
            if resolution.match is Match.SUGGESTION:
                yield Clarification(resolution.carriers)  # «¿Quisiste decir…?»: sin LLM
                return
            if resolution.match is Match.EXACT:
                carrier = resolution.carriers[0]

        # 2. Búsqueda (el embedder y la BD son síncronos: se ejecutan en un hilo)
        try:
            [vector] = await run_in_threadpool(self.embedder.embed, [request.question])
        except EmbeddingProviderError:
            yield Failure("embedding_unavailable", "El servicio de búsqueda no está disponible.")
            return
        filters = SearchFilters(carrier=carrier, only_current=request.only_current)
        chunks = await run_in_threadpool(self.retriever.search, vector, request.k, filters)
        retrieval = Retrieval(carrier, chunks)
        yield retrieval

        # 3. Capa 1 de D8: sin evidencia suficiente no se llama al LLM
        if retrieval.top_score < self.threshold:
            yield Answer(no_evidence_answer(known))
            return

        # 4. LLM en streaming; capas 2 y 3 de D8 al terminar
        raw = ""
        try:
            # aclosing: si el cliente se desconecta, el cierre llega en cascada hasta el LLM [F7]
            llm_request = build_request(request.question, chunks)
            async with aclosing(self._stream_llm(llm_request)) as pieces:
                async for piece in pieces:
                    raw += piece.full
                    if piece.visible:
                        yield Token(piece.visible)
        except LLMError as exc:
            yield Failure(exc.code, _ERROR_MESSAGES.get(exc.code, "Error del modelo de lenguaje."))
            return
        final = finalize(parse_llm_output(raw), chunks, retrieval.top_score, self.threshold, known)
        yield Answer(final)

    async def _stream_llm(self, llm_request) -> AsyncIterator["_Piece"]:
        for attempt in range(LLM_ATTEMPTS):
            started = False
            try:
                splitter = _MarkerSplitter()
                async with aclosing(self.llm.stream(llm_request)) as events:
                    async for event in events:
                        if isinstance(event, TextDelta):
                            started = True
                            yield _Piece(event.text, splitter.feed(event.text))
                        elif isinstance(event, Usage):
                            log.info(
                                "llm usage",
                                extra={
                                    "input_tokens": event.input_tokens,
                                    "output_tokens": event.output_tokens,
                                },
                            )
                tail = splitter.flush()
                if tail:
                    yield _Piece("", tail)
                return
            except (LLMRateLimitError, LLMUnavailableError):
                if started or attempt == LLM_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(RETRY_BASE_S * 2**attempt)  # 1 s, 2 s


@dataclass(frozen=True)
class _Piece:
    full: str  # texto recibido del LLM
    visible: str  # parte que puede mostrarse ya (nunca el separador ni el JSON)


class _MarkerSplitter:
    """Deja pasar el texto anterior a END_ANSWER aunque el separador llegue partido."""

    def __init__(self) -> None:
        self.buffer = ""
        self.done = False

    def feed(self, text: str) -> str:
        if self.done:
            return ""
        self.buffer += text
        if END_ANSWER in self.buffer:
            self.done = True
            visible = self.buffer.split(END_ANSWER, 1)[0]
            self.buffer = ""
            return visible
        # Retener lo que podría ser el principio del separador
        safe = len(self.buffer) - (len(END_ANSWER) - 1)
        if safe <= 0:
            return ""
        visible, self.buffer = self.buffer[:safe], self.buffer[safe:]
        return visible

    def flush(self) -> str:
        if self.done:
            return ""
        visible, self.buffer = self.buffer, ""
        return visible


_ERROR_MESSAGES = {
    "llm_timeout": "El modelo tardó demasiado en responder. Inténtalo de nuevo.",
    "llm_rate_limited": "El modelo está saturado (límite de uso). Inténtalo en unos segundos.",
    "llm_unavailable": "El modelo de lenguaje no está disponible ahora mismo.",
    "llm_misconfigured": "El modelo de lenguaje está mal configurado.",
}
