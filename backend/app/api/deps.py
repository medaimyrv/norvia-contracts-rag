"""Dependencias de FastAPI. Los tests las sustituyen con app.dependency_overrides."""

from functools import lru_cache
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.retriever import PgVectorRetriever
from app.adapters.db.session import make_session_factory
from app.adapters.local_storage import LocalFileStorage
from app.adapters.providers import Providers
from app.services.chat import ChatService
from app.services.documents import DocumentService
from app.settings import Settings, get_settings
from app.worker.celery_app import celery_app


@lru_cache
def get_sessions() -> sessionmaker[Session]:
    return make_session_factory(get_settings().database_url.get_secret_value())


def enqueue_ingestion(document_id: UUID) -> None:
    # send_task por nombre: la API no importa el código del worker (extractor, chunker…)
    celery_app.send_task(
        "ingest_document",
        args=[str(document_id)],
        retry=True,
        retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5},
    )


def get_document_service() -> DocumentService:
    return DocumentService(
        sessions=get_sessions(),
        storage=LocalFileStorage(get_settings().upload_dir),
        enqueue=enqueue_ingestion,
    )


def get_app_settings() -> Settings:
    return get_settings()


def get_providers(request: Request) -> Providers:
    return request.app.state.providers  # construidos y validados al arrancar (main.lifespan)


def get_chat_service(request: Request) -> ChatService:
    providers = get_providers(request)
    return ChatService(
        embedder=providers.embedder,
        llm=providers.llm,
        retriever=PgVectorRetriever(get_sessions(), providers.embedder.model),
        threshold=get_settings().effective_relevance_threshold,
        capture_content=get_settings().otel_capture_content,
    )
