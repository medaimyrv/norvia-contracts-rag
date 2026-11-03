"""Registro de documentos subidos: idempotencia por hash y conflictos explícitos [R2, R5, D5]."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.tables import Document
from app.domain.errors import DocumentConflictError
from app.domain.models import DocumentMetadata, DocumentStatus
from app.ports.storage import FileStorage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Registration:
    document: Document
    duplicate: bool


@dataclass(frozen=True)
class DocumentService:
    sessions: sessionmaker[Session]
    storage: FileStorage
    enqueue: Callable[[UUID], None]

    def register(self, filename: str, data: bytes, meta: DocumentMetadata) -> Registration:
        sha = hashlib.sha256(data).hexdigest()
        with self.sessions() as session:
            existing = session.scalar(select(Document).where(Document.sha256 == sha))
        if existing is not None:
            return self._duplicate(existing, meta)

        self.storage.save(sha, data)  # antes que la fila: el worker nunca ve un PDF inexistente
        try:
            with self.sessions.begin() as session:
                doc = Document(sha256=sha, filename=filename, **meta.model_dump())
                session.add(doc)
                session.flush()
        except IntegrityError as exc:
            # Carrera o versión repetida: se resuelve consultando qué choca
            raise self._conflict(sha, meta) from exc

        self._try_enqueue(doc.id)
        return Registration(doc, duplicate=False)

    def _duplicate(self, existing: Document, meta: DocumentMetadata) -> Registration:
        same = (
            existing.carrier,
            existing.contract_code,
            existing.version,
            existing.effective_from,
        ) == (meta.carrier, meta.contract_code, meta.version, meta.effective_from)
        if not same:
            raise DocumentConflictError(
                "duplicate_file",
                "Este archivo ya está registrado con otros metadatos "
                f"({existing.carrier} · {existing.contract_code} v{existing.version}).",
                str(existing.id),
            )
        if existing.status is DocumentStatus.FAILED:
            self._try_enqueue(existing.id)  # volver a subirlo = volver a intentarlo
        return Registration(existing, duplicate=True)

    def _conflict(self, sha: str, meta: DocumentMetadata) -> DocumentConflictError:
        with self.sessions() as session:
            same_file = session.scalar(select(Document).where(Document.sha256 == sha))
            if same_file is not None:
                return DocumentConflictError(
                    "duplicate_file", "Este archivo ya está registrado.", str(same_file.id)
                )
            same_version = session.scalar(
                select(Document).where(
                    Document.carrier == meta.carrier,
                    Document.contract_code == meta.contract_code,
                    Document.version == meta.version,
                )
            )
        existing_id = str(same_version.id) if same_version else ""
        return DocumentConflictError(
            "version_exists",
            f"Ya existe la versión {meta.version} de {meta.contract_code} para {meta.carrier}. "
            "Sube una versión nueva o corrige el código.",
            existing_id,
        )

    def _try_enqueue(self, document_id: UUID) -> None:
        try:
            self.enqueue(document_id)
        except Exception:
            # Redis caído [F5]: el documento queda PENDING y el sweeper lo reencolará
            log.warning(
                "enqueue failed; document stays PENDING",
                extra={"document_id": str(document_id)},
            )
