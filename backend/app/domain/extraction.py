"""Resultado de extraer un PDF. Tipos internos entre capas: dataclasses, no Pydantic."""

from dataclasses import dataclass, field

Table = list[list[str]]  # filas x celdas; la primera fila es la cabecera


@dataclass(frozen=True)
class ExtractedPage:
    number: int  # 1-based, como se cita al usuario
    text: str  # texto de la página sin tablas ni cabeceras/pies repetidos
    tables: list[Table] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[ExtractedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)
