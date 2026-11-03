"""Extractor sobre los PDFs sintéticos reales de samples/ [R4, F1, F2]."""

import pytest

from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.domain.errors import IngestionError, InvalidPdfError, NoTextLayerError
from scripts.generate_samples import ROOT

SAMPLES = ROOT / "samples"


@pytest.fixture(scope="module")
def condor_v2():
    return PdfplumberExtractor().extract((SAMPLES / "condor_andino_v2.pdf").read_bytes())


def test_clause_is_found_on_its_page(condor_v2) -> None:
    pages_with_clause = [
        p.number for p in condor_v2.pages if "6.1 El plazo de reclamación" in p.text
    ]
    assert pages_with_clause == [1]
    assert "diez (10) días naturales" in condor_v2.pages[0].text


def test_tariff_table_is_extracted_as_table(condor_v2) -> None:
    tables = [t for p in condor_v2.pages for t in p.tables]
    assert len(tables) == 1
    header = ["Ruta", "Tramo de peso", "Tarifa base (EUR)", "Recargo refrigerado (EUR)"]
    assert tables[0][0] == header
    assert len(tables[0]) == 16  # cabecera + 5 rutas x 3 tramos de peso


def test_table_content_is_not_duplicated_in_text(condor_v2) -> None:
    assert all("Madrid - Barcelona" not in p.text for p in condor_v2.pages)


def test_repeated_footer_is_removed(condor_v2) -> None:
    assert condor_v2.page_count == 2
    assert all("Página" not in p.text for p in condor_v2.pages)


def test_corrupt_pdf_raises_permanent_invalid_pdf() -> None:
    with pytest.raises(InvalidPdfError) as exc_info:
        PdfplumberExtractor().extract((SAMPLES / "corrupt.pdf").read_bytes())
    assert exc_info.value.code == "invalid_pdf"
    assert exc_info.value.permanent


def test_scanned_pdf_raises_no_text_layer() -> None:
    with pytest.raises(NoTextLayerError) as exc_info:
        PdfplumberExtractor().extract((SAMPLES / "scanned.pdf").read_bytes())
    assert exc_info.value.code == "no_text_layer"
    assert exc_info.value.permanent


@pytest.mark.parametrize("data", [b"", b"%PDF-1.7 basura", b"no es un pdf"])
def test_garbage_bytes_are_invalid_pdf(data: bytes) -> None:
    with pytest.raises(InvalidPdfError):
        PdfplumberExtractor().extract(data)


def test_ingestion_errors_share_a_base_class() -> None:
    # La tarea Celery captura IngestionError y decide reintentar según `permanent`
    assert issubclass(InvalidPdfError, IngestionError)
    assert issubclass(NoTextLayerError, IngestionError)
