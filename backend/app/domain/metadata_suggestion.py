"""Propuesta de metadatos a partir de la portada del PDF, para pre-rellenar el formulario.

Reglas, no LLM: deterministas, funcionan sin claves y se pueden probar. Son una ayuda: la persona
que sube el documento siempre confirma [D3]. Lo que no se detecta queda vacío, nunca se inventa.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.domain.carriers import EXACT, best_known_carrier

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}  # fmt: skip

_CODE = re.compile(
    r"(?:c[oó]digo|ref(?:erencia)?\.?|n[uú]m(?:ero)?\.? de contrato)\s*:?\s*([A-Z]{1,6}-\d{2,6})",
    re.IGNORECASE,
)
_VERSION = re.compile(r"(?:versi[oó]n|edici[oó]n|revisi[oó]n)\s*:?\s*(\d{1,3})\b", re.IGNORECASE)
_EFFECTIVE = re.compile(
    r"(?:vigente desde|en vigor desde|entra en vigor(?: el)?|efectivo desde)\s*(?:el\s*)?"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2} de [a-záéíóú]+ de \d{4})",
    re.IGNORECASE,
)
# «… que X (el Transportista) …», «Transportista: X», o el título «Contrato … · X»
_CARRIER_PATTERNS = (
    re.compile(r"que\s+(.{3,80}?)\s+\(el Transportista\)", re.IGNORECASE | re.DOTALL),
    re.compile(r"transportista\s*:\s*([^\n·|]{3,80})", re.IGNORECASE),
    re.compile(r"^contrato[^\n·]*·\s*([^\n]{3,80})$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^([^\n·]{3,80}?)\s*·\s*ref\.", re.IGNORECASE | re.MULTILINE),
)


@dataclass(frozen=True)
class MetadataSuggestion:
    carrier: str | None = None
    contract_code: str | None = None
    version: int | None = None
    effective_from: date | None = None
    known_carrier: bool = False  # True: es un transportista ya registrado (nombre canónico)


def suggest_metadata(text: str, known_carriers: list[str]) -> MetadataSuggestion:
    code = _CODE.search(text)
    version = _VERSION.search(text)
    effective = _EFFECTIVE.search(text)
    carrier, known = _carrier(text, known_carriers)
    return MetadataSuggestion(
        carrier=carrier,
        contract_code=code.group(1).upper() if code else None,
        version=int(version.group(1)) if version and int(version.group(1)) >= 1 else None,
        effective_from=_parse_date(effective.group(1)) if effective else None,
        known_carrier=known,
    )


def _carrier(text: str, known_carriers: list[str]) -> tuple[str | None, bool]:
    # 1. Un transportista ya registrado: se propone su nombre exacto (evita duplicados con
    #    nombres distintos, que romperían el filtro por transportista)
    carrier, score = best_known_carrier(text[:2000], known_carriers)
    if carrier and score >= EXACT:
        return carrier, True
    # 2. Patrones de portada
    for pattern in _CARRIER_PATTERNS:
        if match := pattern.search(text):
            name = " ".join(match.group(1).split()).strip(" .,:;")
            if name:
                return name, False
    return None, False


def _parse_date(raw: str) -> date | None:
    try:
        if "-" in raw:
            return date.fromisoformat(raw)
        if "/" in raw:
            day, month, year = (int(p) for p in raw.split("/"))
            return date(year, month, day)
        day_s, _, month_s, _, year_s = raw.lower().split()
        return date(int(year_s), _MONTHS[month_s], int(day_s))
    except (ValueError, KeyError):
        return None
