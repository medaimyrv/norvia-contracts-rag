"""PDFs sintéticos [E5]: deterministas y sincronizados con lo que hay en el repo."""

import json
from pathlib import Path

from scripts.generate_samples import ROOT, generate

SAMPLES = ROOT / "samples"


def read_all(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_generation_is_deterministic(tmp_path: Path) -> None:
    # Mismos bytes -> mismo sha256: la idempotencia [R5] se puede demostrar regenerando
    generate(tmp_path / "a")
    generate(tmp_path / "b")
    assert read_all(tmp_path / "a") == read_all(tmp_path / "b")


def test_committed_samples_are_up_to_date(tmp_path: Path) -> None:
    # Si alguien cambia el generador y olvida regenerar samples/, falla aquí
    generate(tmp_path)
    assert read_all(tmp_path) == read_all(SAMPLES), "ejecuta `make samples`"


def test_manifest_lists_every_pdf() -> None:
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    pdfs = {p.name for p in SAMPLES.glob("*.pdf")}
    assert {item["file"] for item in manifest} == pdfs
    for item in manifest:
        assert (SAMPLES / item["file"]).read_bytes().startswith(b"%PDF-"), item["file"]
