"""Chat: orquestación, eventos SSE y casos de fallo [R9, R11, D7, D8, D16, F3, F4, F7, F9]."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake_providers import FakeEmbedder, FakeLLM
from app.api.chat import event_stream
from app.api.deps import get_chat_service
from app.domain.errors import LLMRateLimitError, LLMTimeoutError
from app.domain.llm import END_ANSWER, TextDelta
from app.domain.models import ChatRequest, ChunkKind
from app.domain.retrieval import RetrievedChunk
from app.main import app
from app.services import chat as chat_module
from app.services.chat import Answer, ChatService, Clarification, Failure, Retrieval, Token
from app.services.chat import _MarkerSplitter as MarkerSplitter

CONDOR = "Transportes Cóndor Andino"
CLAIMS = "6.1 El plazo de reclamación por mercancía dañada es de diez (10) días naturales."


class MemoryRetriever:
    def __init__(self, score: float = 0.8) -> None:
        self.score = score
        self.filters = None

    def known_carriers(self) -> list[str]:
        return [CONDOR, "Rápido Austral Logística"]

    def search(self, vector, k, filters):
        self.filters = filters
        return [
            RetrievedChunk(
                uuid4(),
                uuid4(),
                "condor_v2.pdf",
                CONDOR,
                "CA-2025",
                2,
                True,
                ChunkKind.TEXT,
                "6. Reclamaciones",
                1,
                1,
                CLAIMS,
                self.score,
            )
        ]


class ScriptedLLM:
    """Emite los textos dados; puede fallar en un intento concreto."""

    model = "scripted"

    def __init__(self, pieces: list[str], fail_with: Exception | None = None, fail_times: int = 0):
        self.pieces = pieces
        self.fail_with = fail_with
        self.fail_times = fail_times
        self.calls = 0
        self.closed = False

    async def stream(self, request):
        self.calls += 1
        if self.fail_with and self.calls <= self.fail_times:
            raise self.fail_with
        try:
            for piece in self.pieces:
                yield TextDelta(piece)
        finally:
            self.closed = True  # aclose() llega aquí si el cliente se desconecta


def service(llm=None, retriever=None, threshold: float = 0.5) -> ChatService:
    return ChatService(FakeEmbedder(), llm or FakeLLM(), retriever or MemoryRetriever(), threshold)


async def run(svc: ChatService, question: str = "¿Plazo de reclamación con Cóndor Andino?", **kw):
    return [e async for e in svc.stream(ChatRequest(question=question, **kw))]


VALID = [
    "El plazo es de diez días [c1].",
    f"\n{END_ANSWER}\n",
    '{"citations": [{"chunk_id": "c1"}], ',
    '"confidence": "high"}',
]


# --- Flujo normal ---


async def test_happy_path_streams_tokens_then_citations() -> None:
    events = await run(service(ScriptedLLM(VALID)))
    assert isinstance(events[0], Retrieval) and events[0].carrier_filter == CONDOR  # D16 exacto
    text = "".join(e.text for e in events if isinstance(e, Token))
    assert text == "El plazo es de diez días [c1].\n"
    assert END_ANSWER not in text and "citations" not in text
    final = events[-1].final
    assert final.evidence and final.citations[0].label == "c1"


async def test_marker_split_across_tokens_never_leaks() -> None:
    payload = '{"citations": [{"chunk_id": "c1"}], "confidence": "high"}'
    pieces = ["Diez días [c1].\n<<<END", "_ANS", "WER>>>\n", payload]
    events = await run(service(ScriptedLLM(pieces)))
    text = "".join(e.text for e in events if isinstance(e, Token))
    assert "<" not in text


async def test_explicit_carrier_has_priority() -> None:
    retriever = MemoryRetriever()
    svc = service(ScriptedLLM(VALID), retriever)
    await run(svc, question="¿Plazo?", carrier="Rápido Austral Logística")
    assert retriever.filters.carrier == "Rápido Austral Logística"


# --- Anti-alucinación [D8] ---


async def test_low_score_skips_llm_and_lists_carriers() -> None:
    llm = ScriptedLLM(VALID)
    events = await run(service(llm, MemoryRetriever(score=0.2), threshold=0.5))
    assert llm.calls == 0  # capa 1: ni se llama al LLM
    final = events[-1].final
    assert not final.evidence and CONDOR in final.answer


async def test_invalid_structured_output_degrades(monkeypatch) -> None:  # F9
    events = await run(service(ScriptedLLM(["Diez días [c1].", f"\n{END_ANSWER}\n", "{roto"])))
    assert events[-1].final.evidence is False


async def test_did_you_mean_skips_retrieval_and_llm() -> None:
    llm = ScriptedLLM(VALID)
    events = await run(service(llm), question="¿Plazo con Candor Andina?")
    assert events == [Clarification([CONDOR])]
    assert llm.calls == 0


# --- Fallos del proveedor [F3, F4] ---


async def test_timeout_emits_error_event() -> None:
    events = await run(service(ScriptedLLM(VALID, LLMTimeoutError("t"), fail_times=9)))
    assert isinstance(events[-1], Failure) and events[-1].code == "llm_timeout"


async def test_rate_limit_is_retried_before_first_token(monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "RETRY_BASE_S", 0)
    llm = ScriptedLLM(VALID, LLMRateLimitError("429"), fail_times=2)
    events = await run(service(llm))
    assert llm.calls == 3 and isinstance(events[-1], Answer)


async def test_rate_limit_gives_up_after_attempts(monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "RETRY_BASE_S", 0)
    events = await run(service(ScriptedLLM(VALID, LLMRateLimitError("429"), fail_times=99)))
    assert events[-1] == Failure(
        "llm_rate_limited", "El modelo está saturado (límite de uso). Inténtalo en unos segundos."
    )


# --- Desconexión del cliente [F7] ---


class DisconnectingRequest:
    def __init__(self, after: int) -> None:
        self.checks = 0
        self.after = after

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self.after


async def test_client_disconnect_closes_llm_stream() -> None:
    llm = ScriptedLLM([f"palabra{i} " for i in range(50)] + VALID[1:])
    request = ChatRequest(question="¿Plazo con Cóndor Andino?")
    stream = event_stream(DisconnectingRequest(after=3), service(llm), request)
    received = [chunk async for chunk in stream]
    assert len(received) == 3  # dejó de enviar al desconectarse
    assert llm.closed  # y cerró el stream del LLM: no se sigue gastando


# --- Separador partido ---


def test_marker_splitter_holds_back_partial_marker() -> None:
    splitter = MarkerSplitter()
    out = splitter.feed("Hola <<<END_") + splitter.feed("ANSWER>>>{json}")
    assert out == "Hola "
    assert splitter.flush() == ""


# --- Formato SSE de extremo a extremo ---


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def client():
    with TestClient(app) as c:
        app.dependency_overrides[get_chat_service] = lambda: service(ScriptedLLM(VALID))
        yield c
    app.dependency_overrides = {}


def test_sse_endpoint_event_sequence(client) -> None:
    response = client.post("/api/chat", json={"question": "¿Plazo con Cóndor Andino?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in parse_sse(response.text)]
    assert names[0] == "retrieval" and names[-2:] == ["citations", "done"]
    assert "token" in names
    citations = dict(parse_sse(response.text))["citations"]
    assert citations["evidence"] is True and citations["citations"][0]["label"] == "c1"


def test_sse_endpoint_validates_request(client) -> None:
    assert client.post("/api/chat", json={"question": "x"}).status_code == 422
    assert client.post("/api/chat", json={"question": "¿Plazo?", "extra": 1}).status_code == 422


# --- Trazas [Q2, D10, S4] ---


async def test_chat_trace_has_retrieval_and_llm_spans(spans) -> None:
    await run(service(ScriptedLLM(VALID)))
    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert {"rag.chat", "rag.embed_query", "rag.retrieve", "llm.stream"} <= set(by_name)
    root = by_name["rag.chat"]
    assert by_name["llm.stream"].parent.span_id == root.context.span_id
    retrieve = by_name["rag.retrieve"].attributes
    assert retrieve["rag.k"] == 1 and retrieve["rag.top_score"] == 0.8
    assert root.attributes["rag.outcome"] == "answer"
    assert root.attributes["rag.carrier_filter"] == CONDOR
    assert by_name["llm.stream"].attributes["llm.attempts"] == 1


async def test_question_text_is_not_in_spans_by_default(spans) -> None:
    await run(service(ScriptedLLM(VALID)), question="¿Plazo secreto con Cóndor Andino?")
    attrs = [str(v) for s in spans.get_finished_spans() for v in s.attributes.values()]
    assert not any("secreto" in a for a in attrs)
    root = next(s for s in spans.get_finished_spans() if s.name == "rag.chat")
    assert root.attributes["rag.question.length"] > 0  # solo longitud y huella


async def test_llm_error_is_recorded_in_span(spans) -> None:
    await run(service(ScriptedLLM(VALID, LLMTimeoutError("t"), fail_times=9)))
    llm = next(s for s in spans.get_finished_spans() if s.name == "llm.stream")
    assert llm.status.status_code.name == "ERROR"
    root = next(s for s in spans.get_finished_spans() if s.name == "rag.chat")
    assert root.attributes["error.code"] == "llm_timeout"
