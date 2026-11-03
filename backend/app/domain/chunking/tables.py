"""Tablas: bloques de filas completas con la cabecera repetida [D2]."""

from dataclasses import dataclass

from app.domain.chunking.types import ChunkDraft
from app.domain.extraction import ExtractedPage, Table
from app.domain.models import ChunkKind


@dataclass(frozen=True)
class _PreviousTable:
    header: list[str]
    page: int
    section: str | None


def table_chunks(
    pages: list[ExtractedPage], section_at_page: dict[int, str | None], max_chars: int
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    previous: _PreviousTable | None = None
    for page in pages:
        for position, table in enumerate(page.tables):
            rows = [row for row in table if any(row)]
            if not rows:
                continue
            if position == 0 and previous and _continues(rows, previous, page.number):
                header, body, section = previous.header, rows, previous.section
            else:
                header, body = rows[0], rows[1:]
                section = _section_for(page.number, section_at_page)
            drafts += _pack_rows(header, body, section, page.number, max_chars)
            previous = _PreviousTable(header, page.number, section)
    return drafts


def _continues(rows: Table, previous: _PreviousTable, page: int) -> bool:
    """Tabla partida entre páginas: misma forma, y la primera fila es un dato (tiene dígitos)."""
    first = rows[0]
    return (
        page == previous.page + 1
        and len(first) == len(previous.header)
        and first != previous.header
        and any(ch.isdigit() for cell in first for ch in cell)
    )


def _section_for(page: int, section_at_page: dict[int, str | None]) -> str | None:
    # Una página que solo tiene tabla hereda el último encabezado de páginas anteriores
    for p in range(page, 0, -1):
        if p in section_at_page:
            return section_at_page[p]
    return None


def _to_markdown(row: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "/") for cell in row) + " |"


def _pack_rows(
    header: list[str], body: Table, section: str | None, page: int, max_chars: int
) -> list[ChunkDraft]:
    head = _to_markdown(header) + "\n|" + "---|" * len(header)
    blocks: list[list[str]] = [[]]
    for row in map(_to_markdown, body):
        current = blocks[-1]
        if current and len(head) + sum(len(r) + 1 for r in current) + len(row) + 1 > max_chars:
            blocks.append([])
        blocks[-1].append(row)  # nunca se parte una fila, aunque supere el presupuesto
    return [
        ChunkDraft(ChunkKind.TABLE, section, page, page, "\n".join([head, *block]))
        for block in blocks
    ]
