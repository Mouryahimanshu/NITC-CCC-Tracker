"""Database engine and SQLAlchemy session lifecycle.

Supports PostgreSQL (Neon or local) and SQLite (for local dev when
the campus network blocks port 5432). Set DATABASE_URL in backend/.env:
  - PostgreSQL:  postgresql://user:pass@host/dbname
  - SQLite:      sqlite:///./local.db
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from contextlib import contextmanager

from app.core.config import get_settings

_engine = None
_sessions = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def initialize_database():
    global _engine, _sessions
    url = get_settings().database_url
    if not url:
        return
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    if _is_sqlite(url):
        # SQLite: single-file, no pool needed, enable WAL + FK constraints
        _engine = create_engine(
            url, connect_args={"check_same_thread": False}, echo=False
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        _engine = create_engine(
            url, pool_pre_ping=True, pool_size=3, max_overflow=2,
            connect_args={"connect_timeout": 5},
        )
    _sessions = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def dispose_database():
    global _engine, _sessions
    if _engine:
        _engine.dispose()
    _engine = None
    _sessions = None


def get_session() -> Session:
    if _sessions is None:
        raise RuntimeError("PostgreSQL is not configured. Set DATABASE_URL in backend/.env.")
    session = _sessions()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope():
    if _sessions is None:
        raise RuntimeError("PostgreSQL is not configured. Set DATABASE_URL in backend/.env.")
    session = _sessions()
    try:
        yield session
    finally:
        session.close()


def create_schema():
    if _engine is None:
        raise RuntimeError("DATABASE_URL is required to create the database schema")
    from app.db.models import Base
    Base.metadata.create_all(_engine)
