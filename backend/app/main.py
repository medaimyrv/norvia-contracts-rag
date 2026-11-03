from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.adapters.providers import build_providers
from app.api import chat, documents
from app.domain.errors import DocumentConflictError
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Configuración incoherente (p. ej. EMBEDDING_DIM) -> la API no arranca [D6]
    app.state.providers = build_providers(get_settings())
    yield


app = FastAPI(title="Norvia RAG", lifespan=lifespan)
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
    """El proceso responde. La comprobación de BD y Redis vive en /health/ready (T18)."""
    return {"status": "ok"}
