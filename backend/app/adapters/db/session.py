from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    return session_factory_for(create_engine(database_url, pool_pre_ping=True))


def session_factory_for(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: los objetos siguen legibles después del commit
    return sessionmaker(engine, expire_on_commit=False)
