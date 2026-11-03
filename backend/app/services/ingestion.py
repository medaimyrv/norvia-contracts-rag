"""Servicio de ingesta: PDF -> chunks con embeddings en PostgreSQL [R4, R5, F8, D4, D5].

No conoce Celery: la tarea solo decide reintentos. Así se prueba sin broker.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.tables import Chunk, Document
from app.domain.chunking import build_embedding_text
from app.domain.errors import IngestionError
from app.domain.models import ChunkKind, DocumentStatus
from app.observability import current_span_ids, tracer
from app.ports.chunker import Chunker
from app.ports.embedder import Embedder
from app.ports.extractor import Extractor
from app.ports.storage import FileStorage

log = logging.getLogger(__name__)


class Outcome(StrEnum):
    READY = "ready"
    ALREADY_READY = "already_ready"  # idempotencia [R5]
    FAILED = "failed"  # error permanente: no reintentar
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class IngestionService:
    sessions: sessionmaker[Session]
    storage: FileStorage
    extractor: Extractor
    chunker: Chunker
    embedder: Embedder

    def ingest(self, document_id: UUID) -> Outcome:
        """Errores transitorios (proveedor, BD) se propagan para que la tarea reintente."""
        with tracer.start_as_current_span("ingest.document") as span:
            span.set_attribute("document.id", str(document_id))
            outcome = self._ingest(document_id, span)
            span.set_attribute("ingest.outcome", outcome.value)
            return outcome

    def _ingest(self, document_id: UUID, span: trace.Span) -> Outcome:
        doc = self._start(document_id)
        if doc is None:
            return Outcome.NOT_FOUND
        if doc.status is DocumentStatus.READY:
            return Outcome.ALREADY_READY
        span.set_attribute("ingest.attempt", doc.attempts)

        try:
            with tracer.start_as_current_span("ingest.extract") as s:
                extracted = self.extractor.extract(self.storage.read(doc.sha256))
                s.set_attribute("pdf.pages", extracted.page_count)
            with tracer.start_as_current_span("ingest.chunk") as s:
                drafts = self.chunker.chunk(extracted)
                s.set_attribute("chunk.count", len(drafts))
                s.set_attribute("chunk.tables", sum(d.kind is ChunkKind.TABLE for d in drafts))
            with tracer.start_as_current_span("ingest.embed") as s:
                s.set_attribute("embedding.texts", len(drafts))
                vectors = self.embedder.embed(
                    [
                        build_embedding_text(
                            d,
                            carrier=doc.carrier,
                            contract_code=doc.contract_code,
                            version=doc.version,
                        )
                        for d in drafts
                    ]
                )
        except IngestionError as exc:
            span.set_attribute("error.code", exc.code)
            if not exc.permanent:
                raise
            self.mark_failed(document_id, exc.code)
            return Outcome.FAILED

        with tracer.start_as_current_span("ingest.store"), self.sessions.begin() as session:
            # Bloqueo de fila: si otro worker procesa el mismo documento, espera aquí
            locked = session.get(Document, document_id, with_for_update=True)
            if locked is None:
                return Outcome.NOT_FOUND
            if locked.status is DocumentStatus.READY:
                return Outcome.ALREADY_READY
            # Todo o nada [F8]: si el proceso muere antes del commit, no quedan chunks a medias
            session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            session.add_all(
                Chunk(
                    document_id=document_id,
                    chunk_index=i,
                    kind=d.kind,
                    section=d.section,
                    page_start=d.page_start,
                    page_end=d.page_end,
                    content=d.content,
                    embedding=vector,
                )
                for i, (d, vector) in enumerate(zip(drafts, vectors, strict=True))
            )
            locked.status = DocumentStatus.READY
            locked.error_code = None
            locked.chunk_count = len(drafts)
            locked.page_count = extracted.page_count
            locked.embedding_model = self.embedder.model  # vectores comparables solo entre sí [D6]
            session.flush()
            refresh_current_version(session, locked.carrier, locked.contract_code)
        log.info(
            "document ingested",
            extra={"document_id": str(document_id), "chunks": len(drafts)},
        )
        return Outcome.READY

    def mark_failed(self, document_id: UUID, error_code: str) -> None:
        with self.sessions.begin() as session:
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.FAILED, error_code=error_code)
            )
        log.warning("document failed", extra={"document_id": str(document_id), "code": error_code})

    def _start(self, document_id: UUID) -> Document | None:
        """Tx corta y confirmada: la UI ve PROCESSING y el número de intento."""
        with self.sessions.begin() as session:
            doc = session.get(Document, document_id)
            if doc is None or doc.status is DocumentStatus.READY:
                return doc
            doc.status = DocumentStatus.PROCESSING
            doc.attempts += 1
            doc.error_code = None
            doc.processing_started_at = datetime.now(UTC)
            # La traza de la ingesta queda en el documento: el chat enlaza con ella [D10]
            doc.trace_id, doc.ingest_span_id = current_span_ids()
            return doc


# Umbrales del sweeper [F5, F8]. PROCESSING debe superar task_time_limit (300 s) con margen
PENDING_GRACE = timedelta(minutes=1)
PROCESSING_TIMEOUT = timedelta(minutes=10)


def find_stuck_documents(sessions: sessionmaker[Session], now: datetime) -> list[UUID]:
    """PENDING que nadie recogió (Redis caído al subir) o PROCESSING cuyo worker murió."""
    with sessions() as session:
        query = select(Document.id).where(
            (
                (Document.status == DocumentStatus.PENDING)
                & (Document.updated_at < now - PENDING_GRACE)
            )
            | (
                (Document.status == DocumentStatus.PROCESSING)
                & (Document.processing_started_at < now - PROCESSING_TIMEOUT)
            )
        )
        return list(session.scalars(query))


def refresh_current_version(session: Session, carrier: str, contract_code: str) -> None:
    """Vigente = versión READY con mayor número cuya fecha de vigencia ya llegó [D3].

    Dos workers pueden terminar a la vez dos versiones del mismo contrato: cada uno bloquea
    solo su documento y ninguno ve aún el otro como READY, así que ambos se elegirían como
    vigentes. El advisory lock serializa el recálculo por contrato: el segundo espera al commit
    del primero y entonces ya lo ve (READ COMMITTED lee lo confirmado en cada sentencia).
    """
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"{carrier}|{contract_code}"))))
    winner = session.scalar(
        select(Document.id)
        .where(
            Document.carrier == carrier,
            Document.contract_code == contract_code,
            Document.status == DocumentStatus.READY,
            Document.effective_from <= date.today(),
        )
        .order_by(Document.version.desc())
        .limit(1)
    )
    group = (Document.carrier == carrier) & (Document.contract_code == contract_code)
    # Dos sentencias: apagar y luego encender. Con una sola, el índice único parcial podría
    # ver dos versiones vigentes a la vez a mitad de la actualización
    session.execute(update(Document).where(group, Document.is_current).values(is_current=False))
    if winner is not None:
        session.execute(update(Document).where(Document.id == winner).values(is_current=True))
