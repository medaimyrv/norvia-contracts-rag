"""Propuesta de metadatos desde la portada del PDF [D3, D19]."""

from datetime import date

import pytest

from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.domain.metadata_suggestion import suggest_metadata
from scripts.generate_samples import ROOT

KNOWN = ["Transportes Cóndor Andino", "Rápido Austral Logística"]


def cover(name: str) -> str:
    doc = PdfplumberExtractor().extract((ROOT / "samples" / name).read_bytes(), max_pages=2)
    return "\n".join(p.text for p in doc.pages)


@pytest.mark.parametrize(
    "sample,carrier,code,version,effective",
    [
        ("condor_andino_v2.pdf", "Transportes Cóndor Andino", "CA-2025", 2, date(2026, 3, 1)),
        # Plantilla distinta: «Ref.», «Edición» y fecha escrita en castellano
        ("vientos_sur_v1.pdf", "Vientos del Sur Express", "VS-2026", 1, date(2026, 1, 15)),
    ],
)
def test_reads_cover_of_both_templates(sample, carrier, code, version, effective) -> None:
    s = suggest_metadata(cover(sample), KNOWN)
    assert (s.carrier, s.contract_code, s.version, s.effective_from) == (
        carrier, code, version, effective,
    )  # fmt: skip


def test_known_carrier_gets_its_registered_name() -> None:
    # El texto dice «Cóndor Andino»: se propone el nombre ya registrado (sin duplicados)
    s = suggest_metadata("Contrato con Cóndor Andino. Código CA-9 Versión 1", KNOWN)
    assert s.carrier == "Transportes Cóndor Andino" and s.known_carrier


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Vigente desde 05/02/2026", date(2026, 2, 5)),
        ("Entra en vigor el 1 de marzo de 2027", date(2027, 3, 1)),
        ("Vigente desde 31/02/2026", None),  # fecha imposible: no se inventa
    ],
)
def test_date_formats(text: str, expected: date | None) -> None:
    assert suggest_metadata(text, []).effective_from == expected


def test_nothing_detected_leaves_everything_empty() -> None:
    s = suggest_metadata("Informe trimestral de incidencias en almacén.", KNOWN)
    assert (s.carrier, s.contract_code, s.version, s.effective_from) == (None, None, None, None)
