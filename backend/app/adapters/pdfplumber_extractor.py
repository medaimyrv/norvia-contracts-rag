"""Extractor con pdfplumber [D1]."""

import io
import re
from collections import Counter

import pdfplumber
from pdfplumber.page import Page

from app.domain.errors import InvalidPdfError, NoTextLayerError
from app.domain.extraction import ExtractedDocument, ExtractedPage, Table

# Por debajo de este número de caracteres se considera que no hay capa de texto: un escaneo
# puede traer algo mínimo (un número de página) sin contenido real
MIN_TEXT_CHARS = 20


class PdfplumberExtractor:
    def extract(self, data: bytes, max_pages: int | None = None) -> ExtractedDocument:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                raw = [_extract_page(page) for page in pdf.pages[:max_pages]]
        except Exception as exc:
            # Archivo no confiable: cualquier fallo del parser es culpa de la entrada
            raise InvalidPdfError(str(exc)) from exc

        if not raw:
            raise InvalidPdfError("el PDF no tiene páginas")

        pages = _drop_repeated_lines(raw)
        if sum(len(p.text) for p in pages) < MIN_TEXT_CHARS and not any(p.tables for p in pages):
            raise NoTextLayerError(f"{len(pages)} páginas sin texto extraíble")
        return ExtractedDocument(pages=pages)


def _extract_page(page: Page) -> ExtractedPage:
    found = page.find_tables()
    tables: list[Table] = [
        [[(cell or "").strip() for cell in row] for row in t.extract()] for t in found
    ]
    # Se quita la zona de cada tabla del texto: si no, la tarifa aparecería dos veces
    text_area = page
    for t in found:
        text_area = text_area.outside_bbox(t.bbox)
    text = (text_area.extract_text() or "").strip()
    return ExtractedPage(number=page.page_number, text=text, tables=tables)


def _drop_repeated_lines(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    """Elimina cabeceras y pies: líneas presentes en todas las páginas (ignorando dígitos)."""
    if len(pages) < 2:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip())

    counts = Counter(k for p in pages for k in {key(line) for line in p.text.splitlines()})
    repeated = {k for k, n in counts.items() if n == len(pages) and k}
    return [
        ExtractedPage(
            number=p.number,
            text="\n".join(ln for ln in p.text.splitlines() if key(ln) not in repeated).strip(),
            tables=p.tables,
        )
        for p in pages
    ]
