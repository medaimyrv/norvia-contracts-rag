"""Búsqueda híbrida simple: similitud vectorial (HNSW) + filtros de metadatos [R8, D14]."""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.tables import Chunk, Document
from app.domain.models import DocumentStatus
from app.domain.retrieval import RetrievedChunk, SearchFilters


@dataclass(frozen=True)
class PgVectorRetriever:
    sessions: sessionmaker[Session]

    def search(
        self, query_vector: list[float], k: int, filters: SearchFilters
    ) -> list[RetrievedChunk]:
        distance = Chunk.embedding.cosine_distance(query_vector)
        query = (
            select(Chunk, Document, (1 - distance).label("score"))
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.status == DocumentStatus.READY)
            .order_by(distance)
            .limit(k)
        )
        if filters.carrier:
            query = query.where(Document.carrier == filters.carrier)
        if filters.only_current:
            query = query.where(Document.is_current)

        with self.sessions.begin() as session:
            # Con filtros, HNSW podría devolver menos de k filas (filtra después de buscar).
            # iterative_scan sigue explorando el grafo hasta completar k [D14]
            session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            rows = session.execute(query).all()
        results = [_to_result(chunk, doc, score) for chunk, doc, score in rows]
        # relaxed_order puede desordenar ligeramente: se reordena por puntuación
        return sorted(results, key=lambda r: -r.score)

    def known_carriers(self) -> list[str]:
        with self.sessions() as session:
            query = (
                select(Document.carrier)
                .where(Document.status == DocumentStatus.READY)
                .distinct()
                .order_by(Document.carrier)
            )
            return list(session.scalars(query))


def _to_result(chunk: Chunk, doc: Document, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=doc.id,
        filename=doc.filename,
        carrier=doc.carrier,
        contract_code=doc.contract_code,
        version=doc.version,
        is_current=doc.is_current,
        kind=chunk.kind,
        section=chunk.section,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        content=chunk.content,
        score=float(score),
    )
