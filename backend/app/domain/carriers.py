"""¿De qué transportista habla la pregunta? Filtrar solo si es casi exacto; si es parecido,
preguntar «¿Quisiste decir…?» [D16]. Sin dependencias: difflib de la librería estándar.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

EXACT = 0.9
SUGGEST = 0.6
MAX_SUGGESTIONS = 3
MIN_VARIANT_CHARS = 5  # nombres muy cortos casan por azar con palabras normales

# Palabras de forma jurídica o de sector: el usuario suele omitirlas
_GENERIC = frozenset(
    {"transportes", "transporte", "logistica", "express", "cargo", "sa", "sl", "slu", "grupo"}
)
# Palabras de enlace: «Mareas Pacífico» debe casar con «Mareas del Pacífico»
_CONNECTORS = frozenset({"de", "del", "la", "las", "el", "los", "y"})


class Match(StrEnum):
    EXACT = "exact"  # filtrar automáticamente (y mostrarlo)
    SUGGESTION = "suggestion"  # preguntar «¿Quisiste decir…?»
    NONE = "none"  # sin filtro: pregunta general o comparativa


@dataclass(frozen=True)
class CarrierResolution:
    match: Match
    carriers: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin signos y sin palabras de enlace."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return " ".join(w for w in re.findall(r"\w+", plain) if w not in _CONNECTORS)


def _variant(carrier: str) -> str:
    """Nombre distintivo (sin palabras genéricas): «Transportes Cóndor Andino» -> «condor andino».

    Se compara solo el distintivo para que «envíos express» no se parezca a «… Express».
    Si queda demasiado corto, se usa el nombre completo.
    """
    full = normalize(carrier)
    distinctive = " ".join(w for w in full.split() if w not in _GENERIC)
    return distinctive if len(distinctive) >= MIN_VARIANT_CHARS else full


def _score(question_words: list[str], variant: str) -> float:
    """Mejor parecido entre el nombre y los tramos de la pregunta de n-1 a n+1 palabras,
    siendo n las palabras del nombre (el usuario puede omitir o añadir una)."""
    n = len(variant.split())
    windows = (
        " ".join(question_words[i : i + size])
        for size in range(max(1, n - 1), n + 2)
        for i in range(len(question_words) - size + 1)
    )
    return max((SequenceMatcher(None, w, variant).ratio() for w in windows), default=0.0)


def best_known_carrier(text: str, known_carriers: list[str]) -> tuple[str | None, float]:
    """Transportista registrado que mejor aparece en el texto y su puntuación (0-1)."""
    words = normalize(text).split()
    scored = [(_score(words, _variant(c)), c) for c in known_carriers]
    score, carrier = max(scored, default=(0.0, None))
    return carrier, score


def resolve_carrier(question: str, known_carriers: list[str]) -> CarrierResolution:
    words = normalize(question).split()
    scores = {carrier: _score(words, _variant(carrier)) for carrier in known_carriers}
    exact = [c for c, s in scores.items() if s >= EXACT]
    if len(exact) == 1:
        return CarrierResolution(Match.EXACT, exact)
    if len(exact) > 1:
        return CarrierResolution(Match.NONE)  # compara varios transportistas: no se filtra
    close = sorted((c for c, s in scores.items() if s >= SUGGEST), key=lambda c: -scores[c])
    if close:
        return CarrierResolution(Match.SUGGESTION, close[:MAX_SUGGESTIONS])
    return CarrierResolution(Match.NONE)
