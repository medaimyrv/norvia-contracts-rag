"""Orquestación del chat: transportista -> búsqueda -> umbral -> LLM en streaming -> citas.

Emite eventos de dominio; la API los traduce a SSE [R9, R11, D7, D8, D16, F3, F4].
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
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
from app.observability import link_to, text_attributes, tracer
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
    threshold: float  # pregunta que nombra un transportista [D8]
    general_threshold: float | None = None  # pregunta general o comparativa (None = threshold)
    capture_content: bool = False  # OTEL_CAPTURE_CONTENT: preguntas/respuestas en spans [S4]

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        # Span raíz explícito (no «current»): activar contexto a través de los yield de un
        # generador asíncrono rompe la pila de contextos de OpenTelemetry
        root = tracer.start_span(
            "rag.chat",
            attributes={
                "rag.k_requested": request.k,
                "rag.only_current": request.only_current,
                **text_attributes("rag.question", request.question, self.capture_content),
            },
        )
        try:
            async with aclosing(self._run(request, root)) as events:
                async for event in events:
                    yield event
        finally:
            root.end()

    async def _run(self, request: ChatRequest, root: trace.Span) -> AsyncIterator[ChatEvent]:
        context = trace.set_span_in_context(root)
        known = await _in_span(root, self.retriever.known_carriers, end=False)

        # 1. Transportista: el filtro explícito manda; si no, se resuelve en la pregunta [D16]
        resolution = resolve_carrier(request.question, known)
        # Umbral según si la pregunta NOMBRA un transportista (así se calibró), no según el filtro
        names_carrier = resolution.match is Match.EXACT
        threshold = (
            self.threshold
            if names_carrier or self.general_threshold is None
            else self.general_threshold
        )
        carrier = request.carrier
        if carrier is None:
            root.set_attribute("rag.carrier_resolution", resolution.match.value)
            if resolution.match is Match.SUGGESTION:
                root.set_attribute("rag.outcome", "clarification")
                yield Clarification(resolution.carriers)  # «¿Quisiste decir…?»: sin LLM
                return
            if resolution.match is Match.EXACT:
                carrier = resolution.carriers[0]
        root.set_attribute("rag.carrier_filter", carrier or "")

        # 2. Búsqueda (el embedder y la BD son síncronos: se ejecutan en un hilo)
        embed_span = tracer.start_span(
            "rag.embed_query", context, attributes={"embedding.model": self.embedder.model}
        )
        try:
            [vector] = await _in_span(embed_span, self.embedder.embed, [request.question])
        except EmbeddingProviderError:
            root.set_attribute("rag.outcome", "error")
            yield Failure("embedding_unavailable", "El servicio de búsqueda no está disponible.")
            return
        filters = SearchFilters(carrier=carrier, only_current=request.only_current)
        search_span = tracer.start_span("rag.retrieve", context)
        chunks = await _in_span(
            search_span, self.retriever.search, vector, request.k, filters, end=False
        )
        retrieval = Retrieval(carrier, chunks)
        search_span.set_attributes(
            {
                "rag.k": len(chunks),
                "rag.top_score": retrieval.top_score,
                "rag.threshold": threshold,
                "rag.threshold_kind": "named" if names_carrier else "general",
                "rag.scores": [round(c.score, 4) for c in chunks],
                "rag.documents": sorted({c.filename for c in chunks}),
            }
        )
        # Enlace a la traza de ingesta de cada documento recuperado [D10]
        for trace_id, span_id in {(c.ingest_trace_id, c.ingest_span_id) for c in chunks}:
            if link := link_to(trace_id, span_id):
                search_span.add_link(link.context)
        search_span.end()
        yield retrieval

        # 3. Capa 1 de D8: sin evidencia suficiente no se llama al LLM
        if retrieval.top_score < threshold:
            root.set_attributes({"rag.outcome": "no_evidence", "rag.evidence": False})
            yield Answer(no_evidence_answer(known))
            return

        # 4. LLM en streaming; capas 2 y 3 de D8 al terminar
        llm_span = tracer.start_span(
            "llm.stream", context, attributes={"llm.model": self.llm.model}
        )
        raw = ""
        try:
            # aclosing: si el cliente se desconecta, el cierre llega en cascada hasta el LLM [F7]
            llm_request = build_request(request.question, chunks)
            async with aclosing(self._stream_llm(llm_request, llm_span)) as pieces:
                async for piece in pieces:
                    raw += piece.full
                    if piece.visible:
                        yield Token(piece.visible)
        except LLMError as exc:
            llm_span.record_exception(exc)
            llm_span.set_status(Status(StatusCode.ERROR, exc.code))
            root.set_attributes({"rag.outcome": "error", "error.code": exc.code})
            yield Failure(exc.code, _ERROR_MESSAGES.get(exc.code, "Error del modelo de lenguaje."))
            return
        finally:
            llm_span.end()

        parsed = parse_llm_output(raw)
        final = finalize(parsed, chunks, retrieval.top_score, threshold, known)
        root.set_attributes(
            {
                "rag.outcome": "answer" if final.evidence else "no_evidence",
                "rag.evidence": final.evidence,
                "rag.confidence": final.confidence.value,
                "rag.citations": len(final.citations),
                "llm.structured_output_valid": parsed.structured is not None,
                **text_attributes("rag.answer", final.answer, self.capture_content),
            }
        )
        yield Answer(final)

    async def _stream_llm(self, llm_request, span: trace.Span) -> AsyncIterator["_Piece"]:
        started_at = time.perf_counter()
        for attempt in range(LLM_ATTEMPTS):
            span.set_attribute("llm.attempts", attempt + 1)
            started = False
            try:
                splitter = _MarkerSplitter()
                async with aclosing(self.llm.stream(llm_request)) as events:
                    async for event in events:
                        if isinstance(event, TextDelta):
                            if not started:
                                started = True
                                ttft = (time.perf_counter() - started_at) * 1000
                                span.set_attribute("llm.time_to_first_token_ms", round(ttft))
                            yield _Piece(event.text, splitter.feed(event.text))
                        elif isinstance(event, Usage):
                            span.set_attribute("llm.tokens.input", event.input_tokens)
                            span.set_attribute("llm.tokens.output", event.output_tokens)
                tail = splitter.flush()
                if tail:
                    yield _Piece("", tail)
                return
            except (LLMRateLimitError, LLMUnavailableError):
                if started or attempt == LLM_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(RETRY_BASE_S * 2**attempt)  # 1 s, 2 s


async def _in_span(span: trace.Span, fn, *args, end: bool = True):
    """Ejecuta `fn` en un hilo con `span` como contexto actual: sus consultas SQL cuelgan de él."""

    def run():
        token = otel_context.attach(trace.set_span_in_context(span))
        try:
            return fn(*args)
        finally:
            otel_context.detach(token)

    try:
        return await run_in_threadpool(run)
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR))
        raise
    finally:
        if end:
            span.end()


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
