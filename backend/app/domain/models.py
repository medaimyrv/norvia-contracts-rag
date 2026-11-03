"""Modelos de dominio y contratos de la API [R1]. Ver docs/SPEC.md §3 y §4.

Todos heredan de StrictModel: sin coerción de tipos ("3" no es 3) y sin campos extra.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class ChunkKind(StrEnum):
    TEXT = "text"
    TABLE = "table"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# --- Documentos ---


class DocumentMetadata(StrictModel):
    """Metadatos que operaciones introduce al subir el PDF [D3]."""

    carrier: NonEmptyStr
    contract_code: NonEmptyStr
    version: int = Field(ge=1)
    effective_from: date


class DocumentOut(StrictModel):
    id: UUID
    filename: str
    carrier: str
    contract_code: str
    version: int
    effective_from: date
    is_current: bool
    status: DocumentStatus
    error_code: str | None
    attempts: int
    chunk_count: int
    duplicate: bool = False
    created_at: datetime
    updated_at: datetime


class ChunkOut(StrictModel):
    """Fragmento original que muestra el frontend al pulsar una cita [R12]."""

    id: UUID
    document_id: UUID
    kind: ChunkKind
    section: str | None
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    content: str


# --- Chat ---


class ChatRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    carrier: NonEmptyStr | None = None
    only_current: bool = True
    k: int = Field(default=6, ge=1, le=20)


class CitationOut(StrictModel):
    label: str  # marcador usado en el texto de la respuesta, p. ej. "c2"
    chunk_id: UUID
    document_id: UUID
    filename: str
    carrier: str
    version: int
    page_start: int
    page_end: int
    snippet: str


# --- Salida estructurada del LLM [D7] ---


class LLMCitation(StrictModel):
    chunk_id: str = Field(min_length=1)


class LLMStructuredOutput(StrictModel):
    """JSON que el LLM emite tras <<<END_ANSWER>>>. Se valida con model_validate_json."""

    citations: list[LLMCitation]
    confidence: Confidence
