"""Proveedores deterministas: tests sin red y modo demostración sin claves [Q1, D6, D15].

Comparan palabras, no significados: «quejarme» no se parece a «reclamación».
"""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import AsyncIterator

from app.domain.llm import (
    END_ANSWER,
    NO_EVIDENCE,
    EvidenceChunk,
    LLMEvent,
    LLMRequest,
    TextDelta,
    Usage,
)

# Palabras vacías frecuentes: sin quitarlas, «de» o «la» dominarían la similitud
# Se escriben sin tildes porque tokens() las quita antes de comparar
_STOPWORDS = frozenset(
    {
        "a", "al", "como", "con", "cual", "de", "del", "el", "en", "es", "esta", "este",
        "la", "las", "le", "lo", "los", "mi", "para", "por", "que", "se", "si", "sobre",
        "su", "sus", "un", "una", "uno", "y", "o", "u", "ha", "hay", "tiene", "tengo",
    }
)  # fmt: skip


def tokens(text: str) -> list[str]:
    """Minúsculas, sin tildes y sin palabras vacías."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return [t for t in re.findall(r"\w+", plain) if t not in _STOPWORDS]


class FakeEmbedder:
    """Bolsa de palabras «hasheada» en `dim` posiciones y normalizada (coseno con sentido)."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokens(text):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            # Texto sin palabras útiles: vector fijo, nunca cero (el coseno con cero no existe)
            vector[-1] = 1.0
            return vector
        return [x / norm for x in vector]


class FakeLLM:
    """LLM extractivo: copia hasta 2 frases de la evidencia, con su cita. No puede alucinar."""

    model = "fake-extractive"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        picked = _best_sentences(request.question, request.evidence)
        if picked:
            body = " ".join(f"{sentence} [{label}]" for label, sentence in picked)
            labels = list(dict.fromkeys(label for label, _ in picked))
            confidence = "high" if len(picked) == 1 else "medium"
        else:
            body, labels, confidence = NO_EVIDENCE, [], "low"

        words = body.split(" ")
        for i, word in enumerate(words):
            yield TextDelta(word if i == 0 else " " + word)
        payload = {"citations": [{"chunk_id": label} for label in labels], "confidence": confidence}
        yield TextDelta(f"\n{END_ANSWER}\n{json.dumps(payload)}")
        yield Usage(input_tokens=len(request.user.split()), output_tokens=len(words))


def _best_sentences(question: str, evidence: list[EvidenceChunk]) -> list[tuple[str, str]]:
    wanted = set(tokens(question))
    scored: list[tuple[int, int, str, str]] = []  # (aciertos, orden, etiqueta, frase)
    for chunk in evidence:
        # Frases: fin de oración o inicio de apartado («6.1», «a)»), para no pegar el título
        text = re.sub(r"\n(?=\d+\.\d*\s|[a-z]\)\s)", "\n\n", chunk.text)
        for sentence in re.split(r"(?<=[.!?])\s+|\n\n", text):
            sentence = " ".join(sentence.split())
            score = len(wanted & set(tokens(sentence)))
            if score:
                scored.append((score, len(scored), chunk.label, sentence))
    if not scored:
        return []
    scored.sort(key=lambda s: (-s[0], s[1]))
    best = scored[0]
    picked = [best]
    # Segunda frase solo si aporta casi tanto como la primera
    if len(scored) > 1 and scored[1][0] * 2 >= best[0]:
        picked.append(scored[1])
    return [(label, sentence) for _, _, label, sentence in picked]
