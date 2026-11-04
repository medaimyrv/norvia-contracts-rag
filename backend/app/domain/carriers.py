"""¿De qué transportista habla la pregunta? Filtrar solo si es casi exacto; si es parecido,
preguntar «¿Quisiste decir…?» [D16]. Sin dependencias: difflib de la librería estándar.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

EXACT = 0.9
# Para sugerir, CADA palabra del nombre distintivo debe parecerse al menos esto a alguna palabra
# de la pregunta. Con una sola palabra no basta: «rápido», «mareas» o «sur» son palabras
# corrientes y provocaban «¿Quisiste decir…?» en preguntas generales
SUGGEST = 0.7
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


def _every_word_close(question_words: list[str], variant: str) -> float:
    """El parecido de la palabra del nombre peor representada en la pregunta."""
    return min(
        (
            max((SequenceMatcher(None, q, w).ratio() for q in question_words), default=0.0)
            for w in variant.split()
        ),
        default=0.0,
    )


def resolve_carrier(question: str, known_carriers: list[str]) -> CarrierResolution:
    words = normalize(question).split()
    scores = {carrier: _score(words, _variant(carrier)) for carrier in known_carriers}
    exact = [c for c, s in scores.items() if s >= EXACT]
    if len(exact) == 1:
        return CarrierResolution(Match.EXACT, exact)
    if len(exact) > 1:
        return CarrierResolution(Match.NONE)  # compara varios transportistas: no se filtra
    coverage = {c: _every_word_close(words, _variant(c)) for c in known_carriers}
    close = sorted((c for c, s in coverage.items() if s >= SUGGEST), key=lambda c: -coverage[c])
    if close:
        return CarrierResolution(Match.SUGGESTION, close[:MAX_SUGGESTIONS])
    return CarrierResolution(Match.NONE)


def replace_mention(question: str, carrier: str) -> str:
    """Sustituye en la pregunta la mención aproximada del transportista por su nombre exacto.

    Tras «¿Quisiste decir…?», la pregunta original aún dice «Kondor Andina»; el LLM ve un nombre
    que no coincide con la evidencia y, con razón, no responde. Se corrige el texto en su sitio.
    """
    variant = _variant(carrier)
    n = len(variant.split())
    tokens = [(m.start(), m.end(), normalize(m.group())) for m in re.finditer(r"\w+", question)]
    best_ratio, best_span = 0.0, None
    for size in range(max(1, n - 1), n + 3):
        for i in range(len(tokens) - size + 1):
            window = tokens[i : i + size]
            text = " ".join(t for _, _, t in window if t)  # las palabras de enlace quedan vacías
            ratio = SequenceMatcher(None, text, variant).ratio()
            if ratio > best_ratio:
                best_ratio, best_span = ratio, (window[0][0], window[-1][1])
    if best_span is None or best_ratio < SUGGEST:
        return question
    start, end = best_span
    return question[:start] + carrier + question[end:]
