from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.providers import build_providers
from app.api import chat, documents
from app.api.deps import get_app_settings, get_sessions
from app.domain.errors import DocumentConflictError
from app.logging_config import configure_logging
from app.observability import setup_tracing
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    setup_tracing(settings, "api")
    # Configuración incoherente (p. ej. EMBEDDING_DIM) -> la API no arranca [D6]
    app.state.providers = build_providers(settings)
    yield


app = FastAPI(title="Norvia RAG", lifespan=lifespan)
# Span por petición HTTP. Sin health checks ni un span por cada token enviado (ruido)
FastAPIInstrumentor.instrument_app(app, excluded_urls="health", exclude_spans=["receive", "send"])
app.include_router(documents.router)
app.include_router(chat.router)


@app.exception_handler(DocumentConflictError)
async def conflict_handler(_: Request, exc: DocumentConflictError) -> JSONResponse:
    detail = {"code": exc.code, "message": exc.message, "existing_id": exc.existing_id}
    return JSONResponse(status_code=409, content={"detail": detail})


@app.exception_handler(OperationalError)
async def database_down_handler(_: Request, __: OperationalError) -> JSONResponse:
    # BD caída [F6]: error tipado en vez de un 500 con traza
    detail = {"code": "database_unavailable", "message": "Base de datos no disponible"}
    return JSONResponse(status_code=503, content={"detail": detail})


@app.get("/health/live")
def live() -> dict[str, str]:
    """El proceso responde (healthcheck de Docker). No depende de BD ni Redis."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready(
    sessions: Annotated[sessionmaker[Session], Depends(get_sessions)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> JSONResponse:
    """¿Puede atender? Comprueba PostgreSQL y Redis por separado [F5, F6]."""
    checks: dict[str, str] = {}
    try:
        with sessions() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        redis.Redis.from_url(settings.redis_url, socket_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if healthy else 503, content=checks)
