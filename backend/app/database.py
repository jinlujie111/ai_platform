"""Database configuration and session helpers."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()  # also allow cwd override

DATA_DIR = Path(os.getenv("AI_PLATFORM_DATA_DIR", PROJECT_ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:jinlujie@127.0.0.1:3306/ai_platform?charset=utf8mb4",
)

CHROMA_DIR = DATA_DIR / "chroma"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

_engine_kwargs: dict = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif DATABASE_URL.startswith("mysql"):
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def _migrate_sqlite_vector_columns() -> None:
    """Rename legacy Qdrant columns to Chroma columns when present."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(knowledge_bases)").fetchall()
        columns = {row[1] for row in rows}
        if "qdrant_url" in columns and "chroma_path" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE knowledge_bases RENAME COLUMN qdrant_url TO chroma_path"
            )
        if "qdrant_collection" in columns and "chroma_collection" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE knowledge_bases RENAME COLUMN qdrant_collection TO chroma_collection"
            )


def _migrate_pipeline_schedule_columns() -> None:
    """Add schedule columns to pipelines when missing."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(pipelines)").fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        alters = [
            ("schedule_cron", "ALTER TABLE pipelines ADD COLUMN schedule_cron VARCHAR(120) DEFAULT ''"),
            ("schedule_enabled", "ALTER TABLE pipelines ADD COLUMN schedule_enabled INTEGER DEFAULT 0"),
            ("schedule_exec_date", "ALTER TABLE pipelines ADD COLUMN schedule_exec_date VARCHAR(32) DEFAULT ''"),
            ("schedule_note", "ALTER TABLE pipelines ADD COLUMN schedule_note VARCHAR(500) DEFAULT ''"),
        ]
        for name, sql in alters:
            if name not in columns:
                conn.exec_driver_sql(sql)


def _migrate_datasource_query_only_column() -> None:
    """Add query_only to existing data_sources (default 0 so old write pipelines keep working)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(data_sources)").fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        if "query_only" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE data_sources ADD COLUMN query_only INTEGER DEFAULT 0"
            )


def _migrate_pipeline_step_sync_engine() -> None:
    """Add sync_engine to pipeline_steps. Existing rows default to mysql (in-app)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(pipeline_steps)").fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        if "sync_engine" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE pipeline_steps ADD COLUMN sync_engine VARCHAR(32) DEFAULT 'mysql'"
            )


def init_db() -> None:
    from . import models  # noqa: F401
    from .auth_api import seed_default_admin

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_vector_columns()
    _migrate_pipeline_schedule_columns()
    _migrate_datasource_query_only_column()
    _migrate_pipeline_step_sync_engine()
    db = SessionLocal()
    try:
        seed_default_admin(db)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
