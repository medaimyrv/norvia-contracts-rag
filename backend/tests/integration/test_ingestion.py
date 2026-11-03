"""Ingesta y tarea Celery contra PostgreSQL+pgvector real [R4, R5, R6, F1, F2, F8, D3, D4]."""

from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, func, select

from app.adapters.db.session import session_factory_for
from app.adapters.db.tables import Chunk, Document
from app.adapters.fake_providers import FakeEmbedder
from app.adapters.local_storage import LocalFileStorage
from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.domain.chunking import ClauseChunker
from app.domain.errors import EmbeddingProviderError
from app.domain.models import DocumentStatus
from app.services.ingestion import IngestionService, Outcome
from app.worker import tasks
from app.worker.celery_app import celery_app
from scripts.generate_samples import ROOT
from tests.integration.helpers import register_sample

pytestmark = pytest.mark.integration
SAMPLES = ROOT / "samples"


class FlakyEmbedder(FakeEmbedder):
    """Falla las primeras `failures` llamadas, como un proveedor con rate limit."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.failures:
            raise EmbeddingProviderError("429")
        return super().embed(texts)


@pytest.fixture
def sessions(migrated_engine: Engine):
    factory = session_factory_for(migrated_engine)
    yield factory
    with factory.begin() as s:
        s.execute(delete(Document))


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path)


def make_service(sessions, storage, embedder=None) -> IngestionService:
    return IngestionService(
        sessions=sessions,
        storage=storage,
        extractor=PdfplumberExtractor(),
        chunker=ClauseChunker(),
        embedder=embedder or FakeEmbedder(),
    )


def register(sessions, storage, sample: str, **meta) -> UUID:
    return register_sample(sessions, storage, sample, **meta)


def get(sessions, doc_id: UUID) -> Document:
    with sessions() as s:
        return s.get(Document, doc_id)


def chunk_count(sessions, doc_id: UUID) -> int:
    with sessions() as s:
        return s.scalar(select(func.count()).where(Chunk.document_id == doc_id))


# --- Servicio ---


def test_ingest_stores_chunks_with_embeddings(sessions, storage) -> None:
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    assert make_service(sessions, storage).ingest(doc_id) is Outcome.READY

    doc = get(sessions, doc_id)
    assert doc.status is DocumentStatus.READY and doc.is_current
    assert doc.chunk_count == chunk_count(sessions, doc_id) > 10
    assert (doc.attempts, doc.page_count) == (1, 2)
    with sessions() as s:
        multipage = s.scalars(select(Chunk).where(Chunk.page_start != Chunk.page_end)).all()
        assert multipage and all(len(c.embedding) == 768 for c in multipage)


def test_ingest_is_idempotent(sessions, storage) -> None:
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    service = make_service(sessions, storage)
    service.ingest(doc_id)
    first = chunk_count(sessions, doc_id)
    assert service.ingest(doc_id) is Outcome.ALREADY_READY
    assert chunk_count(sessions, doc_id) == first


def test_rerun_after_crash_leaves_no_partial_chunks(sessions, storage) -> None:
    # Simula un worker que murió: documento en PROCESSING con chunks viejos a medias [F8]
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    with sessions.begin() as s:
        s.get(Document, doc_id).status = DocumentStatus.PROCESSING
        s.add(
            Chunk(
                document_id=doc_id,
                chunk_index=0,
                kind="text",
                page_start=1,
                page_end=1,
                content="basura de un intento anterior",
                embedding=[0.1] * 768,
            )
        )
    make_service(sessions, storage).ingest(doc_id)
    with sessions() as s:
        contents = s.scalars(select(Chunk.content).where(Chunk.document_id == doc_id)).all()
    assert "basura de un intento anterior" not in contents
    assert len(contents) == get(sessions, doc_id).chunk_count


@pytest.mark.parametrize(
    "sample,code", [("corrupt.pdf", "invalid_pdf"), ("scanned.pdf", "no_text_layer")]
)
def test_permanent_errors_mark_failed(sessions, storage, sample: str, code: str) -> None:
    doc_id = register(sessions, storage, sample)
    assert make_service(sessions, storage).ingest(doc_id) is Outcome.FAILED
    doc = get(sessions, doc_id)
    assert (doc.status, doc.error_code, doc.attempts) == (DocumentStatus.FAILED, code, 1)
    assert chunk_count(sessions, doc_id) == 0


def test_transient_error_propagates_and_keeps_no_chunks(sessions, storage) -> None:
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    with pytest.raises(EmbeddingProviderError):
        make_service(sessions, storage, FlakyEmbedder(failures=1)).ingest(doc_id)
    assert get(sessions, doc_id).status is DocumentStatus.PROCESSING
    assert chunk_count(sessions, doc_id) == 0


# --- Versiones vigentes [D3] ---


def test_newer_version_becomes_current_regardless_of_order(sessions, storage) -> None:
    service = make_service(sessions, storage)
    v2 = register(
        sessions, storage, "condor_andino_v2.pdf", version=2, effective_from=date(2026, 3, 1)
    )
    v1 = register(sessions, storage, "condor_andino_v1.pdf", version=1)
    service.ingest(v2)
    service.ingest(v1)  # la versión antigua llega después: no debe quitarle la vigencia a v2
    assert get(sessions, v2).is_current and not get(sessions, v1).is_current


def test_future_version_is_not_current_yet(sessions, storage) -> None:
    service = make_service(sessions, storage)
    v1 = register(sessions, storage, "condor_andino_v1.pdf", version=1)
    v2 = register(
        sessions,
        storage,
        "condor_andino_v2.pdf",
        version=2,
        effective_from=date.today() + timedelta(days=30),
    )
    service.ingest(v1)
    service.ingest(v2)
    assert get(sessions, v1).is_current and not get(sessions, v2).is_current


# --- Tarea Celery (eager: síncrona, sin broker) ---


@pytest.fixture
def eager():
    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = previous


def test_task_retries_transient_errors_then_succeeds(sessions, storage, eager, monkeypatch) -> None:
    embedder = FlakyEmbedder(failures=2)
    monkeypatch.setattr(
        tasks, "get_ingestion_service", lambda: make_service(sessions, storage, embedder)
    )
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    tasks.ingest_document.delay(str(doc_id))
    doc = get(sessions, doc_id)
    assert doc.status is DocumentStatus.READY
    assert doc.attempts == 3  # 2 fallos + 1 éxito


def test_task_marks_failed_when_retries_are_exhausted(
    sessions, storage, eager, monkeypatch
) -> None:
    monkeypatch.setattr(
        tasks,
        "get_ingestion_service",
        lambda: make_service(sessions, storage, FlakyEmbedder(failures=99)),
    )
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    tasks.ingest_document.delay(str(doc_id))
    doc = get(sessions, doc_id)
    assert (doc.status, doc.error_code) == (DocumentStatus.FAILED, "embedding_provider_error")
    assert doc.attempts == tasks.MAX_RETRIES + 1


def test_task_does_not_retry_permanent_errors(sessions, storage, eager, monkeypatch) -> None:
    monkeypatch.setattr(tasks, "get_ingestion_service", lambda: make_service(sessions, storage))
    doc_id = register(sessions, storage, "corrupt.pdf")
    assert tasks.ingest_document.delay(str(doc_id)).get() == "failed"
    assert get(sessions, doc_id).attempts == 1


def test_concurrent_versions_never_end_up_both_current(sessions, storage) -> None:
    """Dos workers terminan v1 y v2 a la vez: el advisory lock serializa el recálculo."""
    import threading

    from app.services.ingestion import refresh_current_version

    v1 = register(sessions, storage, "condor_andino_v1.pdf", version=1)
    v2 = register(
        sessions, storage, "condor_andino_v2.pdf", version=2, effective_from=date(2026, 3, 1)
    )
    errors: list[Exception] = []

    def finish_v1() -> None:
        try:
            with sessions.begin() as s:
                s.get(Document, v1).status = DocumentStatus.READY
                s.flush()
                refresh_current_version(s, "Transportes Cóndor Andino", "CA-2025")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with sessions.begin() as s:
        s.get(Document, v2).status = DocumentStatus.READY
        s.flush()
        refresh_current_version(s, "Transportes Cóndor Andino", "CA-2025")  # toma el lock
        other = threading.Thread(target=finish_v1)
        other.start()
        other.join(timeout=0.5)
        assert other.is_alive()  # v1 espera al lock mientras v2 no confirma
    other.join(timeout=10)

    assert errors == []
    assert get(sessions, v2).is_current and not get(sessions, v1).is_current


def test_ingestion_trace_and_link_ids_are_stored(sessions, storage, spans) -> None:
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    make_service(sessions, storage).ingest(doc_id)
    names = [s.name for s in spans.get_finished_spans()]
    expected = {"ingest.document", "ingest.extract", "ingest.chunk", "ingest.embed", "ingest.store"}
    assert expected <= set(names)
    root = next(s for s in spans.get_finished_spans() if s.name == "ingest.document")
    doc = get(sessions, doc_id)
    # El chat podrá enlazar con esta traza exacta [D10]
    assert doc.trace_id == format(root.context.trace_id, "032x")
    assert doc.ingest_span_id == format(root.context.span_id, "016x")
    chunk_span = next(s for s in spans.get_finished_spans() if s.name == "ingest.chunk")
    assert chunk_span.attributes["chunk.count"] == doc.chunk_count


# --- Sweeper [F5, F8] ---


def test_sweeper_finds_forgotten_pending_and_dead_processing(sessions, storage) -> None:
    from datetime import UTC, datetime
    from datetime import timedelta as td

    from app.services.ingestion import find_stuck_documents

    forgotten = register(sessions, storage, "condor_andino_v1.pdf", version=1)
    dead = register(sessions, storage, "condor_andino_v2.pdf", version=2)
    fresh = register(sessions, storage, "rapido_austral_v1.pdf", contract_code="RA-2025")
    now = datetime.now(UTC)
    with sessions.begin() as s:
        s.get(Document, dead).status = DocumentStatus.PROCESSING
        s.get(Document, dead).processing_started_at = now - td(minutes=30)
    later = now + td(minutes=5)  # PENDING de hace 5 min: nadie lo recogió
    assert set(find_stuck_documents(sessions, later)) == {forgotten, fresh, dead}
    assert find_stuck_documents(sessions, now) == [dead]  # recién subidos: aún no


def test_sweeper_task_requeues(sessions, storage, monkeypatch) -> None:
    from datetime import UTC, datetime
    from datetime import timedelta as td

    queued: list[str] = []
    monkeypatch.setattr(tasks, "get_ingestion_service", lambda: make_service(sessions, storage))
    monkeypatch.setattr(tasks.ingest_document, "delay", queued.append)
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    with sessions.begin() as s:
        s.get(Document, doc_id).status = DocumentStatus.PROCESSING
        s.get(Document, doc_id).processing_started_at = datetime.now(UTC) - td(hours=1)
    assert tasks.sweep_stuck_documents() == 1
    assert queued == [str(doc_id)]


def test_ingestion_records_embedding_model(sessions, storage) -> None:
    doc_id = register(sessions, storage, "condor_andino_v1.pdf")
    make_service(sessions, storage).ingest(doc_id)
    assert get(sessions, doc_id).embedding_model == "fake/lexical-v1"
