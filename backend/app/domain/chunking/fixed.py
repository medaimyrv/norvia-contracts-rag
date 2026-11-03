"""Referencia ingenua para el eval (B0): ventanas fijas sin mirar la estructura [D2, D17]."""

from app.domain.chunking.types import ChunkDraft
from app.domain.extraction import ExtractedDocument
from app.domain.models import ChunkKind


class FixedChunker:
    def __init__(self, size: int = 800, overlap: int = 120) -> None:
        if not 0 <= overlap < size:
            raise ValueError("overlap debe estar entre 0 y size")
        self.size = size
        self.overlap = overlap

    def chunk(self, doc: ExtractedDocument) -> list[ChunkDraft]:
        # Un único flujo de texto; las tablas entran como texto plano. Se recuerda la página
        # de cada tramo para poder citar el rango de páginas de cada ventana.
        parts: list[str] = []
        spans: list[tuple[int, int, int]] = []  # (inicio, fin, página)
        position = 0
        for page in doc.pages:
            pieces = [page.text] + ["\n".join(" | ".join(row) for row in t) for t in page.tables]
            for piece in filter(None, pieces):
                if parts:
                    parts.append("\n")
                    position += 1
                spans.append((position, position + len(piece), page.number))
                parts.append(piece)
                position += len(piece)
        text = "".join(parts)

        drafts: list[ChunkDraft] = []
        start = 0
        while start < len(text):
            end = min(start + self.size, len(text))
            pages = [p for s, e, p in spans if s < end and e > start]
            drafts.append(ChunkDraft(ChunkKind.TEXT, None, min(pages), max(pages), text[start:end]))
            if end == len(text):
                break
            start += self.size - self.overlap
        return drafts
