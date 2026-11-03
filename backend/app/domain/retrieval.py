from dataclasses import dataclass
from uuid import UUID

from app.domain.models import ChunkKind


@dataclass(frozen=True)
class RetrievedChunk:
    """Un resultado de la búsqueda con lo necesario para el prompt y para citar [R8, R9]."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    carrier: str
    contract_code: str
    version: int
    is_current: bool
    kind: ChunkKind
    section: str | None
    page_start: int
    page_end: int
    content: str
    score: float  # similitud coseno: 1 = idéntico


@dataclass(frozen=True)
class SearchFilters:
    carrier: str | None = None
    only_current: bool = True
