"""Modelo de embeddings y span de ingesta por documento [D6, D10]

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Con qué modelo se vectorizó: los vectores de modelos distintos no son comparables
    op.add_column("documents", sa.Column("embedding_model", sa.String(100)))
    # span_id del span de ingesta: con trace_id permite span links desde el chat
    op.add_column("documents", sa.Column("ingest_span_id", sa.String(16)))


def downgrade() -> None:
    op.drop_column("documents", "ingest_span_id")
    op.drop_column("documents", "embedding_model")
