"""Database engine and SQLAlchemy session lifecycle.

Supports PostgreSQL (Neon or local) and SQLite (for local dev when
the campus network blocks port 5432). Set DATABASE_URL in backend/.env:
  - PostgreSQL:  postgresql://user:pass@host/dbname
  - SQLite:      sqlite:///./local.db
"""

import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger("nitc.db")

_engine = None
_sessions = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def initialize_database():
    global _engine, _sessions
    url = get_settings().database_url or os.environ.get("DATABASE_URL", "")
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
            url, pool_pre_ping=True, pool_size=5, max_overflow=5,
            connect_args={"connect_timeout": 10},
        )
    _sessions = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    # Ensure schema and rooms T1–T6 exist
    try:
        from app.db.models import Base, Room, User
        from app.services.auth import hash_password

        Base.metadata.create_all(_engine)
        with _sessions() as db:
            for code in ("T1", "T2", "T3", "T4", "T5", "T6"):
                if db.scalar(select(Room).where(Room.code == code)) is None:
                    db.add(Room(code=code, active=True))
            admin = db.scalar(select(User).where(User.username == "admin"))
            if admin is None:
                db.add(User(username="admin", display_name="CCC Administrator",
                            password_hash=hash_password("admin1234567"), role="ADMIN", active=True))
            faculty = db.scalar(select(User).where(User.username == "faculty"))
            if faculty is None:
                db.add(User(username="faculty", display_name="CCC Faculty",
                            password_hash=hash_password("faculty12345"), role="FACULTY", active=True))
            db.commit()
    except Exception as err:
        logger.warning("Database bootstrap notice: %s", err)


def dispose_database():
    global _engine, _sessions
    if _engine:
        _engine.dispose()
    _engine = None
    _sessions = None


def get_session() -> Session:
    global _sessions
    if _sessions is None:
        if get_settings().database_url or os.environ.get("DATABASE_URL"):
            initialize_database()
        if _sessions is None:
            raise RuntimeError("Database connection is not configured. Set DATABASE_URL in project environment variables.")
    session = _sessions()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope():
    global _sessions
    if _sessions is None:
        if get_settings().database_url or os.environ.get("DATABASE_URL"):
            initialize_database()
        if _sessions is None:
            raise RuntimeError("Database connection is not configured. Set DATABASE_URL in project environment variables.")
    session = _sessions()
    try:
        yield session
    finally:
        session.close()


def create_schema():
    if _engine is None:
        initialize_database()
    if _engine is None:
        raise RuntimeError("DATABASE_URL is required to create the database schema")
    from app.db.models import Base
    Base.metadata.create_all(_engine)
