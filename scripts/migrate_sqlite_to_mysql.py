"""One-shot copy of existing SQLite business tables into MySQL ai_platform."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text

from backend.app.database import DATA_DIR, DATABASE_URL, Base, engine
from backend.app import models  # noqa: F401
from backend.app.auth_api import seed_default_admin
from backend.app.database import SessionLocal


TABLES = [
    "users",
    "knowledge_bases",
    "documents",
    "chunks",
    "data_sources",
    "pipelines",
    "pipeline_steps",
    "pipeline_runs",
    "pipeline_step_runs",
]


def table_count(eng, table: str) -> int:
    with eng.connect() as conn:
        try:
            return int(conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0)
        except Exception:
            return 0


def copy_table(sqlite_conn: sqlite3.Connection, eng, table: str) -> int:
    cur = sqlite_conn.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    if not rows:
        return 0
    cols = [d[0] for d in cur.description]
    col_sql = ", ".join(f"`{c}`" for c in cols)
    placeholders = ", ".join([f":{c}" for c in cols])
    sql = text(f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})")
    payload = [dict(zip(cols, row)) for row in rows]
    with eng.begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


def main() -> None:
    if not str(DATABASE_URL).startswith("mysql"):
        print("DATABASE_URL is not MySQL, skip.")
        return

    src = Path(os.getenv("AI_PLATFORM_DATA_DIR", DATA_DIR)) / "ai_platform.db"
    print("create schema…")
    Base.metadata.create_all(bind=engine)

    has_business = (
        table_count(engine, "data_sources") > 0
        or table_count(engine, "knowledge_bases") > 0
        or table_count(engine, "pipelines") > 0
    )
    if has_business:
        print("MySQL already has business data, skip copy.")
    elif not src.exists():
        print(f"No SQLite at {src}")
    else:
        print(f"Copying from {src}")
        sqlite_conn = sqlite3.connect(src)
        try:
            existing = {
                r[0]
                for r in sqlite_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            with engine.begin() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                for table in TABLES:
                    if table in existing:
                        conn.execute(text(f"DELETE FROM `{table}`"))
            total = 0
            for table in TABLES:
                if table not in existing:
                    print(f"skip missing {table}")
                    continue
                n = copy_table(sqlite_conn, engine, table)
                total += n
                print(f"copied {table}: {n}")
            with engine.begin() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            print(f"copy done, rows={total}")
        finally:
            sqlite_conn.close()

    db = SessionLocal()
    try:
        seed_default_admin(db)
        print("admin seed ensured")
    finally:
        db.close()


if __name__ == "__main__":
    main()
