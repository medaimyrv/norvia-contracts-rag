"""Esquema inicial: documents, chunks e índice HNSW [R7]

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768  # copia literal: una migración no debe cambiar si cambia el código


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("carrier", sa.String(100), nullable=False),
        sa.Column("contract_code", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "READY",
                "FAILED",
                native_enum=False,
                length=20,
                name="document_status",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error_code", sa.String(50)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer()),
        sa.Column("trace_id", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("carrier", "contract_code", "version", name="uq_documents_version"),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index(
        "uq_documents_one_current",
        "documents",
        ["carrier", "contract_code"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("text", "table", native_enum=False, length=10, name="chunk_kind"),
            nullable=False,
        ),
        sa.Column("section", sa.Text()),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_position"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # HNSW frente a IVFFlat: no necesita datos previos para entrenarse y da mejor recall [R7]
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    # La extensión se conserva: puede usarla otra base de datos del clúster
