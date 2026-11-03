from dataclasses import dataclass

from app.domain.models import ChunkKind


@dataclass(frozen=True)
class ChunkDraft:
    """Chunk antes de tener embedding e id. `content` es el texto fuente que se cita [D2]."""

    kind: ChunkKind
    section: str | None
    page_start: int
    page_end: int
    content: str


def build_embedding_text(
    draft: ChunkDraft, *, carrier: str, contract_code: str, version: int
) -> str:
    """Texto que se convierte en vector: cabecera de contexto + contenido. No se guarda [D2].

    Lo usan la ingesta y el eval: si cambia, hay que reingestar.
    """
    header = f"{carrier} · {contract_code} v{version}"
    if draft.section:
        header += f" · {draft.section}"
    return f"{header}\n{draft.content}"
