"""Kết nối SQLite + tạo bảng. Không Alembic — thêm cột mới thì ghi vào _ADDED_COLUMNS
(pattern kingstock/app/db.py)."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from common.config import ROOT

from .models import Base

DB_PATH = os.getenv("INGEST_DB", str(ROOT / "ingest.db"))
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# (bảng, cột, kiểu SQL) — ALTER TABLE ADD COLUMN cho DB cũ.
_ADDED_COLUMNS: list[tuple[str, str, str]] = []


def init_db() -> None:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, col, ddl in _ADDED_COLUMNS:
            if col not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def session() -> Session:
    return SessionLocal()
