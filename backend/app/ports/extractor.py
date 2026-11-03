from typing import Protocol

from app.domain.extraction import ExtractedDocument


class Extractor(Protocol):
    def extract(self, data: bytes, max_pages: int | None = None) -> ExtractedDocument:
        """Extrae texto y tablas por página (solo las primeras `max_pages` si se indica).

        Raises:
            InvalidPdfError: el archivo no se puede parsear.
            NoTextLayerError: no hay texto extraíble (p. ej. un escaneo).
        """
        ...
