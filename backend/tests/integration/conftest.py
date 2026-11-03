"""PostgreSQL + pgvector real en un contenedor desechable [Q1]. Requiere Docker."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

# Ryuk (el limpiador de testcontainers) falla de forma intermitente en Docker Desktop + WSL
# al publicar su puerto. Los contenedores se paran igualmente al salir del `with`.
# testcontainers lee esta variable en el primer uso, no al importar.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

PG_IMAGE = "pgvector/pgvector:pg17"  # la misma imagen que docker-compose.yml
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False  # no pisar el logging de pytest
    return cfg


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer(PG_IMAGE, driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_engine(pg_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(pg_url), "head")
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()
