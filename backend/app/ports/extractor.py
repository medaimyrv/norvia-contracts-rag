from typing import Protocol

from app.domain.extraction import ExtractedDocument


class Extractor(Protocol):
    def extract(self, data: bytes) -> ExtractedDocument:
        """Extrae texto y tablas por página.

        Raises:
            InvalidPdfError: el archivo no se puede parsear.
            NoTextLayerError: no hay texto extraíble (p. ej. un escaneo).
        """
        ...
