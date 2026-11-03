from typing import Protocol

from app.domain.chunking import ChunkDraft
from app.domain.extraction import ExtractedDocument


class Chunker(Protocol):
    """Estrategia de chunking intercambiable: el eval compara implementaciones [D17]."""

    def chunk(self, doc: ExtractedDocument) -> list[ChunkDraft]: ...
