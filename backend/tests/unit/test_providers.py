"""Proveedores de modelos [R10, D6, D15]. Ningún test usa red ni claves [Q1]."""

import json
import math
from types import SimpleNamespace

import litellm
import pytest

from app.adapters import litellm_providers
from app.adapters.fake_providers import FakeEmbedder, FakeLLM
from app.adapters.litellm_providers import LiteLLMChat, LiteLLMEmbedder
from app.adapters.providers import build_providers
from app.domain.errors import (
    ConfigurationError,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.domain.llm import END_ANSWER, NO_EVIDENCE, EvidenceChunk, LLMRequest, TextDelta, Usage
from app.domain.models import LLMStructuredOutput
from app.settings import Settings

CLAIMS = (
    "6.1 El plazo de reclamación por mercancía dañada es de diez (10) días naturales desde la "
    "fecha de entrega. Transcurrido dicho plazo, la reclamación no será admitida."
)
INSURANCE = "7.1 El Transportista mantendrá un seguro con una cobertura mínima de 400.000 EUR."


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def collect(llm, request: LLMRequest) -> tuple[str, list[Usage]]:
    text, usage = "", []
    async for event in llm.stream(request):
        if isinstance(event, TextDelta):
            text += event.text
        else:
            usage.append(event)
    return text, usage


def request(question: str, *chunks: tuple[str, str]) -> LLMRequest:
    evidence = [EvidenceChunk(label, text) for label, text in chunks]
    return LLMRequest(system="sys", user=f"prompt {question}", question=question, evidence=evidence)


# --- FakeEmbedder ---


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    [a], [b] = FakeEmbedder().embed([CLAIMS]), FakeEmbedder().embed([CLAIMS])
    assert a == b
    assert len(a) == 768
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0)


def test_fake_embedder_ignores_case_and_accents() -> None:
    a, b = FakeEmbedder().embed(["Reclamación DAÑADA", "reclamacion danada"])
    assert a == b


def test_fake_embedder_ranks_lexical_overlap() -> None:
    q, claims, insurance = FakeEmbedder().embed(
        ["¿Plazo de reclamación por mercancía dañada?", CLAIMS, INSURANCE]
    )
    assert cosine(q, claims) > cosine(q, insurance)


def test_fake_embedder_never_returns_zero_vector() -> None:
    [v] = FakeEmbedder().embed(["de la el"])
    assert any(v)


# --- FakeLLM extractivo ---


async def test_fake_llm_extracts_best_sentence_with_citation() -> None:
    question = "¿Plazo de reclamación por mercancía dañada?"
    text, usage = await collect(FakeLLM(), request(question, ("c1", INSURANCE), ("c2", CLAIMS)))
    answer, payload = text.split(f"\n{END_ANSWER}\n")
    assert "diez (10) días naturales" in answer
    assert "[c2]" in answer
    structured = LLMStructuredOutput.model_validate_json(payload)
    assert [c.chunk_id for c in structured.citations] == ["c2"]
    assert usage and usage[0].output_tokens > 0


async def test_fake_llm_returns_at_most_two_sentences() -> None:
    text, _ = await collect(FakeLLM(), request("plazo reclamación", ("c1", CLAIMS * 3)))
    answer = text.split(END_ANSWER)[0]
    assert answer.count("[c1]") <= 2


async def test_fake_llm_without_evidence_says_so() -> None:
    text, _ = await collect(FakeLLM(), request("¿Plazo de reclamación?"))
    answer, payload = text.split(f"\n{END_ANSWER}\n")
    assert answer == NO_EVIDENCE
    assert json.loads(payload) == {"citations": [], "confidence": "low"}


# --- Adaptadores LiteLLM: se comprueba la llamada, sin red ---


def test_embedder_batches_and_requests_configured_dimension(monkeypatch) -> None:
    calls = []

    def fake_embedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.1] * 4} for _ in kwargs["input"]])

    monkeypatch.setattr(litellm_providers.litellm, "embedding", fake_embedding)
    embedder = LiteLLMEmbedder("gemini/x", dim=4, api_key="k", timeout_s=5, batch_size=2)
    assert len(embedder.embed(["a", "b", "c"])) == 3
    assert [len(c["input"]) for c in calls] == [2, 1]
    assert calls[0]["dimensions"] == 4 and calls[0]["timeout"] == 5


def test_embedder_maps_rate_limit_to_transient_error(monkeypatch) -> None:
    def boom(**_):
        raise litellm.RateLimitError("429", llm_provider="gemini", model="x")

    monkeypatch.setattr(litellm_providers.litellm, "embedding", boom)
    with pytest.raises(EmbeddingProviderError) as exc_info:
        LiteLLMEmbedder("gemini/x", 4, "k", 5).embed(["a"])
    assert exc_info.value.permanent is False  # la tarea Celery reintentará


def test_embedder_maps_auth_error_to_permanent_error(monkeypatch) -> None:
    def boom(**_):
        raise litellm.AuthenticationError("401", llm_provider="gemini", model="x")

    monkeypatch.setattr(litellm_providers.litellm, "embedding", boom)
    with pytest.raises(EmbeddingConfigurationError) as exc_info:
        LiteLLMEmbedder("gemini/x", 4, "k", 5).embed(["a"])
    assert exc_info.value.permanent is True  # la tarea marcará FAILED sin reintentar


def test_embedder_rejects_wrong_dimension(monkeypatch) -> None:
    monkeypatch.setattr(
        litellm_providers.litellm,
        "embedding",
        lambda **kw: SimpleNamespace(data=[{"embedding": [0.1] * 3}]),
    )
    with pytest.raises(EmbeddingProviderError):
        LiteLLMEmbedder("gemini/x", 4, "k", 5).embed(["a"])


def chunk(text: str | None = None, usage: SimpleNamespace | None = None) -> SimpleNamespace:
    choices = [SimpleNamespace(delta=SimpleNamespace(content=text))] if text is not None else []
    return SimpleNamespace(choices=choices, usage=usage)


async def test_chat_streams_text_and_usage(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        assert kwargs["stream"] is True and kwargs["temperature"] == 0

        async def gen():
            yield chunk("Hola")
            yield chunk(" mundo")
            yield chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))

        return gen()

    monkeypatch.setattr(litellm_providers.litellm, "acompletion", fake_acompletion)
    text, usage = await collect(LiteLLMChat("gemini/x", "k", 5), request("q"))
    assert text == "Hola mundo"
    assert usage == [Usage(10, 2)]


@pytest.mark.parametrize(
    "exc,expected",
    [
        (litellm.Timeout("t", model="x", llm_provider="gemini"), LLMTimeoutError),
        (litellm.RateLimitError("r", llm_provider="gemini", model="x"), LLMRateLimitError),
        (litellm.NotFoundError("404", model="x", llm_provider="gemini"), LLMConfigurationError),
    ],
)
async def test_chat_maps_provider_errors(monkeypatch, exc, expected) -> None:
    async def boom(**_):
        raise exc

    monkeypatch.setattr(litellm_providers.litellm, "acompletion", boom)
    with pytest.raises(expected):
        await collect(LiteLLMChat("gemini/x", "k", 5), request("q"))


# --- Selección de proveedores y validación al arrancar ---

DB = "postgresql+psycopg://u:p@localhost/db"


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, database_url=DB, **overrides)  # type: ignore[arg-type]


def test_fake_provider_is_default() -> None:
    providers = build_providers(settings())
    assert isinstance(providers.embedder, FakeEmbedder) and providers.is_fake


def test_gemini_provider_uses_litellm() -> None:
    providers = build_providers(settings(model_provider="gemini", gemini_api_key="k"))
    assert isinstance(providers.embedder, LiteLLMEmbedder)
    assert isinstance(providers.llm, LiteLLMChat) and not providers.is_fake


def test_dimension_mismatch_prevents_startup() -> None:
    with pytest.raises(ConfigurationError, match="EMBEDDING_DIM=1024"):
        build_providers(settings(embedding_dim=1024))
