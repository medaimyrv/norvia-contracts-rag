"""Subida y consulta de documentos [R2, R3, S1]."""

from datetime import date
from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.tables import Chunk, Document
from app.api.deps import get_app_settings, get_document_service, get_sessions
from app.domain.models import ChunkOut, DocumentMetadata, DocumentOut
from app.services.documents import DocumentService
from app.settings import Settings

router = APIRouter(prefix="/api", tags=["documents"])

PDF_MAGIC = b"%PDF-"
MULTIPART_OVERHEAD = 64 * 1024  # campos del formulario y separadores


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def to_out(doc: Document, duplicate: bool = False) -> DocumentOut:
    out = DocumentOut.model_validate(doc, from_attributes=True)
    return out.model_copy(update={"duplicate": duplicate})


@router.post("/documents", status_code=202, response_model=DocumentOut)
async def upload_document(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    carrier: Annotated[str, Form()],
    contract_code: Annotated[str, Form()],
    version: Annotated[int, Form()],
    effective_from: Annotated[date, Form()],
    service: Annotated[DocumentService, Depends(get_document_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DocumentOut:
    limit = settings.max_upload_bytes
    # Primera barrera: rechazar por cabecera sin leer el cuerpo
    declared = int(request.headers.get("content-length") or 0)
    if declared > limit + MULTIPART_OVERHEAD:
        raise error(413, "file_too_large", f"Máximo {settings.max_upload_mb} MB")
    data = await file.read(limit + 1)  # segunda barrera: nunca más de limit + 1 bytes
    if len(data) > limit:
        raise error(413, "file_too_large", f"Máximo {settings.max_upload_mb} MB")
    if not data.startswith(PDF_MAGIC):
        # Se mira el contenido, no la extensión ni el content-type (los elige el cliente)
        raise error(415, "unsupported_type", "Solo se admiten archivos PDF")

    try:
        # Los campos del formulario ya llegan convertidos: el modelo estricto valida reglas
        meta = DocumentMetadata.model_validate(
            {
                "carrier": carrier,
                "contract_code": contract_code,
                "version": version,
                "effective_from": effective_from,
            }
        )
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_url=False, include_input=False)) from exc

    # El nombre solo se muestra: nunca se usa como ruta (se guarda por sha256)
    filename = PurePath(file.filename or "documento.pdf").name[:255]
    registration = service.register(filename, data, meta)
    if registration.duplicate:
        response.status_code = 200
    return to_out(registration.document, registration.duplicate)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    sessions: Annotated[sessionmaker[Session], Depends(get_sessions)],
) -> list[DocumentOut]:
    with sessions() as session:
        docs = session.scalars(select(Document).order_by(Document.created_at.desc())).all()
        return [to_out(d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: UUID, sessions: Annotated[sessionmaker[Session], Depends(get_sessions)]
) -> DocumentOut:
    with sessions() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise error(404, "not_found", "Documento no encontrado")
        return to_out(doc)


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(
    chunk_id: UUID, sessions: Annotated[sessionmaker[Session], Depends(get_sessions)]
) -> ChunkOut:
    """Fragmento original de una cita [R12]."""
    with sessions() as session:
        chunk = session.get(Chunk, chunk_id)
        if chunk is None:
            raise error(404, "not_found", "Fragmento no encontrado")
        return ChunkOut.model_validate(chunk, from_attributes=True)
