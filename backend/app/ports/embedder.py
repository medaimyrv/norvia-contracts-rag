from typing import Protocol


class Embedder(Protocol):
    """Síncrono: lo usa la tarea Celery. En el chat se llama con run_in_threadpool."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Raises: EmbeddingProviderError si el proveedor falla (transitorio)."""
        ...
