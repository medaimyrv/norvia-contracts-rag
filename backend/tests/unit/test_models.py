from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.models import (
    ChatRequest,
    Confidence,
    DocumentMetadata,
    LLMStructuredOutput,
)


def metadata(**overrides: object) -> dict[str, object]:
    base = {
        "carrier": "TransAndes",
        "contract_code": "TA-2025",
        "version": 2,
        "effective_from": date(2026, 1, 1),
    }
    return base | overrides


# --- Modo estricto [R1] ---


def test_strict_mode_rejects_coercible_types() -> None:
    with pytest.raises(ValidationError, match="int_type"):
        DocumentMetadata.model_validate(metadata(version="2"))


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DocumentMetadata.model_validate(metadata(is_admin=True))


def test_strings_are_stripped_and_must_not_be_empty() -> None:
    meta = DocumentMetadata.model_validate(metadata(carrier="  TransAndes "))
    assert meta.carrier == "TransAndes"
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(metadata(carrier="   "))


def test_version_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(metadata(version=0))


def test_json_input_accepts_iso_dates_in_strict_mode() -> None:
    # En JSON una fecha solo puede llegar como texto: el modo estricto lo admite
    raw = '{"carrier":"X","contract_code":"C","version":1,"effective_from":"2026-01-01"}'
    assert DocumentMetadata.model_validate_json(raw).effective_from == date(2026, 1, 1)


# --- Chat ---


def test_chat_request_defaults() -> None:
    req = ChatRequest.model_validate_json('{"question":"¿Plazo de reclamación?"}')
    assert req.only_current is True
    assert req.k == 6
    assert req.carrier is None


@pytest.mark.parametrize(
    "payload",
    ['{"question":"hi"}', '{"question":"ok?", "k": 50}', '{"question":"ok?", "k": "5"}'],
)
def test_chat_request_rejects_invalid_input(payload: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate_json(payload)


# --- Salida estructurada del LLM [D7, F9] ---


def test_llm_output_valid() -> None:
    out = LLMStructuredOutput.model_validate_json(
        '{"citations":[{"chunk_id":"c3"}],"confidence":"high"}'
    )
    assert out.confidence is Confidence.HIGH
    assert [c.chunk_id for c in out.citations] == ["c3"]


@pytest.mark.parametrize(
    "raw",
    [
        '{"citations":[],"confidence":"certain"}',  # confianza fuera del enum
        '{"citations":[{"chunk_id":"c1","text":"x"}],"confidence":"low"}',  # campo inventado
        '{"confidence":"low"}',  # falta citations
        '{"citations":[{"chunk_id":"c1"}],"confidence":"low"',  # JSON truncado
    ],
)
def test_llm_output_invalid_is_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        LLMStructuredOutput.model_validate_json(raw)
