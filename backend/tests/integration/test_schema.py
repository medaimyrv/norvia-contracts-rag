"""Esquema y migraciones contra pgvector real [R7]."""

import uuid
from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.db.tables import EMBEDDING_DIM, Base, Chunk, Document
from app.domain.models import ChunkKind, DocumentStatus
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


def make_document(**overrides: object) -> Document:
    fields: dict[str, object] = {
        "sha256": uuid.uuid4().hex * 2,
        "filename": "contrato.pdf",
        "carrier": "TransAndes",
        "contract_code": "TA-1",
        "version": 1,
        "effective_from": date(2026, 1, 1),
    }
    return Document(**(fields | overrides))


def one_hot(position: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[position] = 1.0
    return vec


@pytest.fixture
def session(migrated_engine: Engine):
    with Session(migrated_engine) as s:
        yield s
        s.rollback()
        s.execute(delete(Document))
        s.commit()


def test_orm_models_match_migration(migrated_engine: Engine) -> None:
    # Si alguien cambia tables.py sin escribir migración, este test falla
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_hnsw_index_uses_cosine_ops(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        indexdef = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'")
        ).scalar_one()
    assert "USING hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef


def test_defaults_on_insert(session: Session) -> None:
    doc = make_document()
    session.add(doc)
    session.commit()
    session.refresh(doc)
    assert doc.status is DocumentStatus.PENDING
    assert (doc.attempts, doc.chunk_count, doc.is_current) == (0, 0, False)


def test_sha256_is_unique(session: Session) -> None:
    session.add_all([make_document(sha256="a" * 64), make_document(sha256="a" * 64, version=2)])
    with pytest.raises(IntegrityError):
        session.commit()


def test_only_one_current_version_per_contract(session: Session) -> None:
    session.add_all(
        [
            make_document(version=1, is_current=True),
            make_document(version=2, is_current=True),
        ]
    )
    with pytest.raises(IntegrityError, match="uq_documents_one_current"):
        session.commit()


def test_cosine_search_orders_by_similarity_and_cascades(session: Session) -> None:
    doc = make_document()
    doc.chunks = [
        Chunk(
            chunk_index=i,
            kind=ChunkKind.TEXT,
            page_start=1,
            page_end=1,
            content=f"chunk {i}",
            embedding=one_hot(i),
        )
        for i in range(3)
    ]
    session.add(doc)
    session.commit()

    nearest = session.scalars(
        select(Chunk.content).order_by(Chunk.embedding.cosine_distance(one_hot(2))).limit(1)
    ).one()
    assert nearest == "chunk 2"

    session.delete(doc)
    session.commit()
    assert session.scalar(select(func.count()).select_from(Chunk)) == 0


def test_downgrade_and_upgrade_again(pg_url: str, migrated_engine: Engine) -> None:
    cfg = alembic_config(pg_url)
    command.downgrade(cfg, "base")
    assert "documents" not in inspect(migrated_engine).get_table_names()
    command.upgrade(cfg, "head")
    assert {"documents", "chunks"} <= set(inspect(migrated_engine).get_table_names())
