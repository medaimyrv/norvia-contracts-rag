from typing import Protocol

from app.domain.retrieval import RetrievedChunk, SearchFilters


class Retriever(Protocol):
    def search(
        self, query_vector: list[float], k: int, filters: SearchFilters
    ) -> list[RetrievedChunk]: ...

    def known_carriers(self) -> list[str]:
        """Transportistas con algún documento READY (para resolve_carrier y el desplegable)."""
        ...
