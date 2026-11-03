"""Tipos del puerto LLM. Entre capas propias: dataclasses, no Pydantic."""

from dataclasses import dataclass

END_ANSWER = "<<<END_ANSWER>>>"  # separa el texto en streaming del JSON estructurado [D7]
NO_EVIDENCE = "SIN_EVIDENCIA"


@dataclass(frozen=True)
class EvidenceChunk:
    label: str  # identificador que el LLM usa al citar, p. ej. "c1"
    text: str
    carrier: str = ""  # el FakeLLM no cuenta el nombre del transportista como coincidencia


@dataclass(frozen=True)
class LLMRequest:
    """El adaptador real usa `system`/`user` (el prompt); el fake usa la pregunta y la evidencia."""

    system: str
    user: str
    question: str
    evidence: list[EvidenceChunk]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


LLMEvent = TextDelta | Usage
