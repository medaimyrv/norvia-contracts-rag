"""API de documentos contra PostgreSQL real [R2, R3, S1, D5, F5, F6]."""

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete

from app.adapters.db.session import session_factory_for
from app.adapters.db.tables import Document
from app.adapters.local_storage import LocalFileStorage
from app.api.deps import get_app_settings, get_document_service, get_sessions
from app.main import app
from app.services.documents import DocumentService
from app.settings import Settings
from scripts.generate_samples import ROOT

pytestmark = pytest.mark.integration
PDF = (ROOT / "samples" / "condor_andino_v1.pdf").read_bytes()
META = {
    "carrier": "Transportes Cóndor Andino",
    "contract_code": "CA-2025",
    "version": "1",
    "effective_from": "2025-01-01",
}


class Queue:
    def __init__(self, fail: bool = False) -> None:
        self.ids: list[UUID] = []
        self.fail = fail

    def __call__(self, document_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("redis caído")
        self.ids.append(document_id)


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(migrated_engine: Engine, tmp_path: Path, queue: Queue):
    sessions = session_factory_for(migrated_engine)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url="postgresql+psycopg://x:y@h/d", max_upload_mb=1
    )
    app.dependency_overrides = {
        get_sessions: lambda: sessions,
        get_app_settings: lambda: settings,
        get_document_service: lambda: DocumentService(sessions, LocalFileStorage(tmp_path), queue),
    }
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}
    with sessions.begin() as s:
        s.execute(delete(Document))


def upload(client: TestClient, data: bytes = PDF, filename: str = "contrato.pdf", **meta: str):
    return client.post(
        "/api/documents",
        data=META | meta,
        files={"file": (filename, data, "application/pdf")},
    )


def test_upload_registers_and_enqueues(client, queue, tmp_path) -> None:
    response = upload(client)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING" and body["duplicate"] is False
    assert queue.ids == [UUID(body["id"])]
    assert len(list(tmp_path.glob("*.pdf"))) == 1


def test_same_file_same_metadata_is_idempotent(client, queue) -> None:
    first = upload(client).json()
    again = upload(client)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["duplicate"] is True
    assert len(queue.ids) == 1  # no se encola dos veces


def test_same_file_other_metadata_conflicts(client) -> None:
    upload(client)
    response = upload(client, carrier="Otro Transportista")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_file"


def test_existing_version_with_other_file_conflicts(client) -> None:
    upload(client)
    other = (ROOT / "samples" / "condor_andino_v2.pdf").read_bytes()
    response = upload(client, data=other)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_exists"


@pytest.mark.parametrize(
    "data,status,code",
    [
        (b"MZ\x90\x00 esto es un ejecutable", 415, "unsupported_type"),
        (b"", 415, "unsupported_type"),
        (b"%PDF-" + b"0" * (1024 * 1024), 413, "file_too_large"),
    ],
)
def test_file_validation(client, data: bytes, status: int, code: str) -> None:
    response = upload(client, data=data, filename="parece.pdf")
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    "field,value",
    [("version", "dos"), ("version", "0"), ("effective_from", "ayer"), ("carrier", " ")],
)
def test_invalid_metadata_is_rejected(client, field: str, value: str) -> None:
    assert upload(client, **{field: value}).status_code == 422


def test_filename_cannot_escape_storage(client, tmp_path) -> None:
    body = upload(client, filename="../../etc/passwd.pdf").json()
    assert body["filename"] == "passwd.pdf"
    assert not (tmp_path.parent.parent / "etc").exists()


def test_redis_down_still_accepts_upload(client, queue) -> None:
    queue.fail = True
    response = upload(client)
    assert response.status_code == 202  # queda PENDING; el sweeper lo reencolará [F5]
    assert response.json()["status"] == "PENDING"


def test_get_and_list_documents(client) -> None:
    created = upload(client).json()
    assert client.get(f"/api/documents/{created['id']}").json()["id"] == created["id"]
    assert [d["id"] for d in client.get("/api/documents").json()] == [created["id"]]


def test_unknown_document_and_chunk_return_404(client) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/documents/{missing}").status_code == 404
    assert client.get(f"/api/chunks/{missing}").status_code == 404
    assert client.get("/api/documents/no-es-uuid").status_code == 422


def test_database_down_returns_503(client) -> None:
    down = session_factory_for(create_engine("postgresql+psycopg://x:y@127.0.0.1:1/none"))
    app.dependency_overrides[get_sessions] = lambda: down
    response = client.get("/api/documents")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"


def test_config_reports_demo_mode_and_carriers(client) -> None:
    body = client.get("/api/config").json()
    assert body["demo_mode"] is True  # MODEL_PROVIDER por defecto: fake
    assert body["carriers"] == []  # aún no hay documentos READY


def test_ready_reports_each_dependency(client, monkeypatch) -> None:
    import redis

    monkeypatch.setattr(redis.Redis, "ping", lambda self: True)
    assert client.get("/health/ready").json() == {"database": "ok", "redis": "ok"}

    def down(self):
        raise redis.ConnectionError("caído")

    monkeypatch.setattr(redis.Redis, "ping", down)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"database": "ok", "redis": "unavailable"}


# --- Cambio de modelo de embeddings [D6] ---


def test_documents_from_other_model_are_flagged_and_reindexed(
    client, queue, migrated_engine
) -> None:
    from app.adapters.db.retriever import PgVectorRetriever

    created = upload(client).json()
    sessions = session_factory_for(migrated_engine)
    with sessions.begin() as s:  # simula un documento ingerido antes con otro modelo
        doc = s.get(Document, UUID(created["id"]))
        doc.status = "READY"
        doc.embedding_model = "gemini/gemini-embedding-001"
    # El modelo activo en los tests es el fake: ese documento no es comparable
    assert client.get("/api/config").json()["stale_documents"] == 1
    assert PgVectorRetriever(sessions, "fake/lexical-v1").known_carriers() == []

    queue.ids.clear()
    assert client.post("/api/documents/reindex").json() == {"requeued": 1}
    assert queue.ids == [UUID(created["id"])]
    assert client.get(f"/api/documents/{created['id']}").json()["status"] == "PENDING"
    assert client.get("/api/config").json()["stale_documents"] == 0


# --- Propuesta de metadatos para el formulario [D19] ---


def test_suggest_fills_form_from_cover_without_storing(client, tmp_path) -> None:
    files = {"file": ("x.pdf", PDF, "application/pdf")}
    response = client.post("/api/documents/suggest", files=files)
    body = response.json()
    assert (body["carrier"], body["contract_code"], body["version"], body["effective_from"]) == (
        "Transportes Cóndor Andino", "CA-2025", 1, "2025-01-01",
    )  # fmt: skip
    assert body["warning"] is None
    assert client.get("/api/documents").json() == []  # no guarda nada
    assert not list(tmp_path.glob("*.pdf"))


def test_suggest_warns_about_scanned_pdf_before_upload(client) -> None:
    scanned = (ROOT / "samples" / "scanned.pdf").read_bytes()
    body = client.post(
        "/api/documents/suggest", files={"file": ("s.pdf", scanned, "application/pdf")}
    ).json()
    assert "escaneado" in body["warning"]


def test_suggest_validates_file_type(client) -> None:
    files = {"file": ("a.pdf", b"hola", "text/plain")}
    response = client.post("/api/documents/suggest", files=files)
    assert response.status_code == 415
