"""Chunking estructural: cláusula -> apartado -> ventana [D2]."""

from dataclasses import dataclass

from app.domain.chunking.headings import SUBCLAUSE, detect_scheme, is_heading
from app.domain.chunking.tables import table_chunks
from app.domain.chunking.types import ChunkDraft
from app.domain.extraction import ExtractedDocument
from app.domain.models import ChunkKind


@dataclass(frozen=True)
class _Line:
    page: int
    text: str


class ClauseChunker:
    def __init__(self, max_chars: int = 1500, table_max_chars: int = 600) -> None:
        self.max_chars = max_chars
        self.table_max_chars = table_max_chars

    def chunk(self, doc: ExtractedDocument) -> list[ChunkDraft]:
        lines = [
            _Line(page.number, text.strip())
            for page in doc.pages
            for text in page.text.splitlines()
            if text.strip()
        ]
        scheme = detect_scheme([line.text for line in lines])

        # Agrupa líneas por cláusula. Lo anterior al primer encabezado es el preámbulo (sin sección)
        sections: list[tuple[str | None, list[_Line]]] = []
        section_at_page: dict[int, str | None] = {}
        heading: str | None = None
        body: list[_Line] = []
        for line in lines:
            if is_heading(line.text, scheme):
                if body:
                    sections.append((heading, body))
                heading, body = line.text, [line]
            else:
                body.append(line)
            section_at_page[line.page] = heading
        if body:
            sections.append((heading, body))

        # Un encabezado sin cuerpo (p. ej. el título de un anexo que solo tiene tabla) no es
        # evidencia: se omite como chunk y llega a sus tablas como `section`
        drafts = [
            d
            for title, group in sections
            if not (len(group) == 1 and group[0].text == title)
            for d in self._split(title, group)
        ]
        drafts += table_chunks(doc.pages, section_at_page, self.table_max_chars)
        # Orden de lectura: por página; en la misma página, el texto antes que sus tablas
        return sorted(drafts, key=lambda d: (d.page_start, d.kind is ChunkKind.TABLE))

    def _split(self, section: str | None, body: list[_Line]) -> list[ChunkDraft]:
        if _size(body) <= self.max_chars:
            return [_draft(section, body)]
        groups: list[list[_Line]] = []
        for line in body:
            if groups and SUBCLAUSE.match(line.text):
                groups.append([line])
            elif groups:
                groups[-1].append(line)
            else:
                groups.append([line])
        units = groups if len(groups) > 1 else [[line] for line in body]
        # El título de la cláusula viaja en `section`, no se duplica en el contenido
        return [_draft(section, piece) for piece in _pack(units, self.max_chars)]


def _size(lines: list[_Line]) -> int:
    return len("\n".join(line.text for line in lines))


def _pack(units: list[list[_Line]], max_chars: int) -> list[list[_Line]]:
    """Agrupa unidades (apartados o líneas) sin superar max_chars; parte lo que no quepa."""
    out: list[list[_Line]] = []
    current: list[_Line] = []
    for unit in units:
        if current and _size(current + unit) > max_chars:
            out.append(current)
            current = []
        if _size(unit) <= max_chars:
            current += unit
        elif len(unit) > 1:
            out += _pack([[line] for line in unit], max_chars)
        else:  # una sola línea gigante: ventana dura por caracteres
            line = unit[0]
            out += [
                [_Line(line.page, line.text[i : i + max_chars])]
                for i in range(0, len(line.text), max_chars)
            ]
    if current:
        out.append(current)
    return out


def _draft(section: str | None, lines: list[_Line]) -> ChunkDraft:
    pages = [line.page for line in lines]
    return ChunkDraft(
        kind=ChunkKind.TEXT,
        section=section,
        page_start=min(pages),
        page_end=max(pages),
        content="\n".join(line.text for line in lines),
    )
