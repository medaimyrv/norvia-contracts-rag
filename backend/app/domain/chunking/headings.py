"""Detección de encabezados de cláusula con patrones habituales en documentos legales [D2]."""

import re

MAX_HEADING_CHARS = 100  # un encabezado es una línea corta; evita confundirlo con un párrafo

_NUMERIC = re.compile(r"^\d{1,2}\.\s+[A-ZÁÉÍÓÚÑ]")  # "6. Reclamaciones" (no "6.1 El plazo")
_NAMED = re.compile(r"^(cl[aá]usula|art[ií]culo)\s+\S+", re.IGNORECASE)
_ORDINAL = re.compile(
    r"^(primera|segunda|tercera|cuarta|quinta|sexta|s[eé]ptima|octava|novena|"
    r"d[eé]cima(\s+\w+)?|und[eé]cima|duod[eé]cima)\s*[.:\-–]",
    re.IGNORECASE,
)
_ANNEX = re.compile(r"^anexo\s+[ivxlc\d]+\b", re.IGNORECASE)

# Inicio de apartado dentro de una cláusula: "6.1", "1.", "a)"
SUBCLAUSE = re.compile(r"^(\d{1,2}(\.\d{1,2})+\.?|\d{1,2}\.|[a-z]\))\s")

# Orden de prioridad: si un documento usa ordinales, sus "1." internos son apartados
_SCHEMES = (_ORDINAL, _NAMED, _NUMERIC)


def detect_scheme(lines: list[str]) -> re.Pattern[str] | None:
    """Esquema de numeración dominante: el primero que aparece al menos dos veces."""
    for pattern in _SCHEMES:
        if sum(1 for line in lines if _matches(pattern, line)) >= 2:
            return pattern
    return None


def is_heading(line: str, scheme: re.Pattern[str] | None) -> bool:
    if scheme is not None and _matches(scheme, line):
        return True
    return _matches(_ANNEX, line)


def _matches(pattern: re.Pattern[str], line: str) -> bool:
    return len(line) <= MAX_HEADING_CHARS and pattern.match(line) is not None
