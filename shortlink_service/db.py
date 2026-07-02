from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()

_engine = None
_session_factory = None


def init_engine(database_url: str) -> None:
    global _engine
    global _session_factory
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_tables() -> None:
    if _engine is None:
        raise RuntimeError("shortlink database is not initialized")
    Base.metadata.create_all(bind=_engine)


def get_session_factory():
    if _session_factory is None:
        raise RuntimeError("shortlink database is not initialized")
    return _session_factory
