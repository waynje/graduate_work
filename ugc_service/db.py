from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


Base = declarative_base()

_engine = None
_session_factory = None


def init_engine(database_url: str) -> None:
    global _engine
    global _session_factory
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(
        database_url, future=True, pool_pre_ping=True, connect_args=connect_args
    )
    _session_factory = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


def get_session() -> Generator[Session, None, None]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized.")
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def create_tables() -> None:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized.")
    Base.metadata.create_all(bind=_engine)


def run_migrations(database_url: str) -> None:
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_config = AlembicConfig(str(alembic_ini))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized.")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
