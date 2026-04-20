from __future__ import annotations

import os
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text

DEFAULT_DATABASE_URL = "sqlite:///./workforyou.db"


def _database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)

    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(timeoffrequest)")).fetchall()]
        if "decided_at" not in cols:
            conn.execute(text("ALTER TABLE timeoffrequest ADD COLUMN decided_at DATETIME"))
            conn.commit()
        assignment_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(assignment)")).fetchall()]
        if "override" not in assignment_cols:
            conn.execute(text("ALTER TABLE assignment ADD COLUMN override BOOLEAN DEFAULT 0"))
            conn.commit()
        if "override_reason" not in assignment_cols:
            conn.execute(text("ALTER TABLE assignment ADD COLUMN override_reason TEXT"))
            conn.commit()
        employee_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(employee)")).fetchall()]
        if "active" not in employee_cols:
            conn.execute(text("ALTER TABLE employee ADD COLUMN active BOOLEAN DEFAULT 1"))
            conn.commit()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

