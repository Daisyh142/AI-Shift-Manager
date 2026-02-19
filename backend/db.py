from __future__ import annotations

import os
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text

DEFAULT_DATABASE_URL = "sqlite:///./workforyou.db"


def _database_url() -> str:
    # We use an env var so each developer can point to their own DB file
    # without changing code. If it's not set, we fall back to a local file.
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """
    Creates tables in the SQLite database if they don't exist yet.

    Connection to the rest of the app:
    - `backend/models.py` defines the tables.
    - `SQLModel.metadata.create_all(engine)` uses those definitions to create them.
    """
    # Important: importing models registers all table classes on SQLModel.metadata.
    # If we don't import them, `create_all()` can run with an empty metadata and
    # create zero tables.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)

    # Lightweight dev migration(s) for SQLite.
    # We don't run a full migration framework yet, but we can safely add columns
    # when we detect an older DB file.
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(timeoffrequest)")).fetchall()]
        if "decided_at" not in cols:
            conn.execute(text("ALTER TABLE timeoffrequest ADD COLUMN decided_at DATETIME"))
            conn.commit()


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a DB session per-request.

    Connection to the rest of the app:
    - Routers/services receive `session: Session = Depends(get_session)`
      so they can read/write SQLite safely.
    """
    with Session(engine) as session:
        yield session

