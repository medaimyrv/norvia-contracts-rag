"""Tarea Celery: capa delgada sobre IngestionService; solo decide reintentos [R6, D4]."""

import logging
from functools import lru_cache
from uuid import UUID

from celery import Task
from celery.signals import worker_init
from sqlalchemy.exc import OperationalError

from app.adapters.db.session import make_session_factory
from app.adapters.local_storage import LocalFileStorage
from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.adapters.providers import build_providers
from app.domain.chunking import ClauseChunker
from app.domain.errors import IngestionError
from app.services.ingestion import IngestionService
from app.settings import get_settings
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

MAX_RETRIES = 5


@lru_cache
def get_ingestion_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        sessions=make_session_factory(settings.database_url.get_secret_value()),
        storage=LocalFileStorage(settings.upload_dir),
        extractor=PdfplumberExtractor(),
        chunker=ClauseChunker(),  # estrategia B2 hasta que el eval decida [D2, D17]
        embedder=build_providers(settings).embedder,
    )


@worker_init.connect
def _validate_configuration(**_: object) -> None:
    # Configuración incoherente (p. ej. EMBEDDING_DIM) -> el worker no arranca
    build_providers(get_settings())


class IngestTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:  # type: ignore[override]
        # Reintentos agotados en un error transitorio: queda FAILED con su código
        if isinstance(exc, IngestionError):
            code = exc.code
        elif isinstance(exc, OperationalError):
            code = "database_unavailable"
        else:
            code = "internal_error"
        try:
            get_ingestion_service().mark_failed(UUID(args[0]), code)
        except OperationalError:
            log.exception("no se pudo marcar FAILED (BD caída); lo recogerá el sweeper")


@celery_app.task(
    base=IngestTask,
    name="ingest_document",
    autoretry_for=(IngestionError, OperationalError),  # solo llegan aquí los transitorios
    max_retries=MAX_RETRIES,
    retry_backoff=5,  # 5 s, 10 s, 20 s… con jitter, hasta 5 min
    retry_backoff_max=300,
    retry_jitter=True,
)
def ingest_document(document_id: str) -> str:
    return get_ingestion_service().ingest(UUID(document_id)).value
