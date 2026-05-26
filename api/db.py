"""SQLAlchemy engine + session management for the ShopStream DWH."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _build_db_url() -> str:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "shopstream_dwh")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    if not host or not user or not password:
        raise RuntimeError("DB_HOST, DB_USER and DB_PASSWORD must be set as environment variables.")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal  # noqa: PLW0603 — lazy singleton para Lambda warm starts
    if _engine is None:
        _engine = create_engine(
            _build_db_url(),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
            pool_recycle=1800,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


@contextmanager
def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
