"""Chunking [R4, D2]: estructura, fallback, tablas, procedencia y que no se pierda texto."""

import pytest

from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.domain.chunking import ChunkDraft, ClauseChunker, FixedChunker, build_embedding_text
from app.domain.chunking.headings import SUBCLAUSE
from app.domain.extraction import ExtractedDocument, ExtractedPage
from app.domain.models import ChunkKind
from scripts.generate_samples import ROOT

SAMPLES = ROOT / "samples"
READY_SAMPLES = [
    "condor_andino_v1.pdf",
    "condor_andino_v2.pdf",
    "rapido_austral_v1.pdf",
    "mareas_pacifico_v1.pdf",
    "vientos_sur_v1.pdf",
    "injection_test.pdf",
]


def extract(name: str) -> ExtractedDocument:
    return PdfplumberExtractor().extract((SAMPLES / name).read_bytes())


def doc(*pages: str) -> ExtractedDocument:
    return ExtractedDocument([ExtractedPage(i, text) for i, text in enumerate(pages, start=1)])


def by_section(chunks: list[ChunkDraft], section: str) -> list[ChunkDraft]:
    return [c for c in chunks if c.section == section]


# --- Invariantes sobre todos los PDFs: ningún texto se pierde y nada supera el presupuesto ---


@pytest.mark.parametrize("name", READY_SAMPLES)
def test_no_text_is_lost(name: str) -> None:
    document = extract(name)
    chunks = ClauseChunker().chunk(document)
    texts = [c.content for c in chunks] + [c.section or "" for c in chunks]
    for page in document.pages:
        for line in filter(None, map(str.strip, page.text.splitlines())):
            assert any(line in t for t in texts), f"línea perdida en {name}: {line!r}"
        for table in page.tables:
            for row in table:
                assert any(" | ".join(row) in c.content for c in chunks), f"fila perdida: {row}"


@pytest.mark.parametrize("name", READY_SAMPLES)
def test_text_chunks_respect_budget(name: str) -> None:
    chunker = ClauseChunker()
    for chunk in chunker.chunk(extract(name)):
        if chunk.kind is ChunkKind.TEXT:
            assert len(chunk.content) <= chunker.max_chars


# --- Plantilla numérica (Cóndor Andino) ---


def test_one_chunk_per_clause_with_all_its_subclauses() -> None:
    chunks = ClauseChunker().chunk(extract("condor_andino_v2.pdf"))
    [claims] = by_section(chunks, "6. Reclamaciones")
    assert "6.1 El plazo de reclamación" in claims.content
    assert "6.3 Toda reclamación" in claims.content
    assert chunks[0].section is None  # preámbulo


def test_clause_spanning_two_pages_cites_the_range() -> None:
    [payments] = by_section(
        ClauseChunker().chunk(extract("condor_andino_v1.pdf")), "8. Precio, pagos y facturación"
    )
    assert (payments.page_start, payments.page_end) == (1, 2)


def test_table_blocks_repeat_header_and_take_annex_section() -> None:
    chunks = ClauseChunker().chunk(extract("condor_andino_v1.pdf"))
    tables = [c for c in chunks if c.kind is ChunkKind.TABLE]
    assert len(tables) >= 2
    for t in tables:
        assert t.content.startswith("| Ruta | Tramo de peso | Tarifa base (EUR) |")
        assert t.section == "Anexo I. Tarifas"
    assert all(c.content != "Anexo I. Tarifas" for c in chunks)  # sin chunk de título suelto


# --- Plantilla fuera de lo esperado (Vientos del Sur) ---


def test_ordinal_headings_are_detected() -> None:
    sections = {c.section for c in ClauseChunker().chunk(extract("vientos_sur_v1.pdf"))}
    assert {"PRIMERA.- OBJETO", "SEXTA.- RESPONSABILIDAD Y RECLAMACIONES"} <= sections


def test_long_clause_falls_back_to_subclauses() -> None:
    chunks = ClauseChunker().chunk(extract("vientos_sur_v1.pdf"))
    pieces = by_section(chunks, "SEXTA.- RESPONSABILIDAD Y RECLAMACIONES")
    assert len(pieces) >= 2
    assert pieces[0].content.startswith("SEXTA.-")
    # Cada trozo siguiente empieza en un apartado: no se corta a mitad de frase
    assert all(SUBCLAUSE.match(p.content) for p in pieces[1:])


def test_table_continuing_on_next_page_reuses_header() -> None:
    chunks = ClauseChunker().chunk(extract("vientos_sur_v1.pdf"))
    later = [c for c in chunks if c.kind is ChunkKind.TABLE and c.page_start > 2]
    assert later, "la tabla debería continuar en páginas posteriores"
    for t in later:
        assert t.content.startswith("| Origen | Destino | Peso máximo (kg) | Precio (EUR) |")
        assert t.section == "ANEXO I - TARIFAS POR TRAYECTO"


# --- Fallback con entradas sintéticas ---


def test_document_without_headings_is_split_in_windows() -> None:
    lines = [f"Línea número {i} de un informe sin estructura reconocible." for i in range(60)]
    chunks = ClauseChunker(max_chars=500).chunk(doc("\n".join(lines)))
    assert len(chunks) > 1
    assert all(len(c.content) <= 500 and c.section is None for c in chunks)


def test_numbered_lines_inside_ordinal_document_are_subclauses() -> None:
    text = "PRIMERA.- OBJETO\n1. Servicio de transporte.\nSEGUNDA.- PRECIO\n1. Tarifa fija."
    chunks = ClauseChunker().chunk(doc(text))
    assert [c.section for c in chunks] == ["PRIMERA.- OBJETO", "SEGUNDA.- PRECIO"]


def test_single_huge_line_is_cut_by_characters() -> None:
    chunks = ClauseChunker(max_chars=100).chunk(doc("1. Objeto\n1. Uno\n" + "x" * 250))
    assert all(len(c.content) <= 100 for c in chunks)
    assert sum(c.content.count("x") for c in chunks) == 250


# --- FixedChunker (referencia B0) ---


def test_fixed_windows_overlap_and_cover_everything() -> None:
    chunker = FixedChunker(size=800, overlap=120)
    chunks = chunker.chunk(extract("condor_andino_v1.pdf"))
    assert all(len(c.content) <= 800 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.content[:120] == prev.content[-120:]
    assert "Madrid - Barcelona" in "".join(c.content for c in chunks)  # tablas como texto


def test_fixed_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        FixedChunker(size=100, overlap=100)


# --- Texto para el embedding ---


def test_embedding_text_adds_context_without_touching_content() -> None:
    draft = ChunkDraft(ChunkKind.TEXT, "6. Reclamaciones", 1, 1, "6.1 El plazo…")
    text = build_embedding_text(draft, carrier="Cóndor", contract_code="CA-2025", version=2)
    assert text == "Cóndor · CA-2025 v2 · 6. Reclamaciones\n6.1 El plazo…"
    assert draft.content == "6.1 El plazo…"
