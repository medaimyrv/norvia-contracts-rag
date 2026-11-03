from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.adapters.db.tables import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def _database_url() -> str:
    # Los tests inyectan la URL del contenedor; en el resto de casos manda el entorno
    if url := config.attributes.get("database_url"):
        return url
    from app.settings import get_settings

    return get_settings().database_url.get_secret_value()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
