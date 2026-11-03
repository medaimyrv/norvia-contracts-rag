"""Utilidades compartidas por los tests de integración."""

import hashlib
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.tables import Document
from app.ports.storage import FileStorage
from scripts.generate_samples import ROOT

SAMPLES = ROOT / "samples"


def register_sample(
    sessions: sessionmaker[Session],
    storage: FileStorage,
    sample: str,
    *,
    carrier: str = "Transportes Cóndor Andino",
    contract_code: str = "CA-2025",
    version: int = 1,
    effective_from: date = date(2025, 1, 1),
) -> UUID:
    """Guarda el PDF y crea su fila PENDING, como haría la API."""
    data = (SAMPLES / sample).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    storage.save(sha, data)
    with sessions.begin() as session:
        doc = Document(
            sha256=sha,
            filename=sample,
            carrier=carrier,
            contract_code=contract_code,
            version=version,
            effective_from=effective_from,
        )
        session.add(doc)
        session.flush()
        return doc.id
