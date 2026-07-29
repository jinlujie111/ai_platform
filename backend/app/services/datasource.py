"""Datasource connectivity and read-only SQL execution."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..models import DataSource

SUPPORTED_SQL_TYPES = {"mysql", "postgres", "postgresql"}
READONLY_PREFIXES = ("select", "with", "show", "describe", "desc", "explain")
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|replace|grant|revoke|"
    r"merge|call|exec|execute|load|copy|attach|detach|into)\b",
    re.IGNORECASE,
)


def dialect_name(ds_type: str) -> str:
    value = (ds_type or "").lower().strip()
    if value == "postgresql":
        return "postgres"
    return value


def is_sql_datasource(ds_type: str) -> bool:
    return dialect_name(ds_type) in SUPPORTED_SQL_TYPES or dialect_name(ds_type) == "postgresql"


def build_sqlalchemy_url(ds: DataSource) -> str:
    kind = dialect_name(ds.type)
    user = quote_plus(ds.username or "")
    try:
        from .secret_box import decrypt_secret

        plain_password = decrypt_secret(ds.password)
    except Exception:
        plain_password = ds.password or ""
    password = quote_plus(plain_password or "")
    host = ds.host or "127.0.0.1"
    port = int(ds.port or 0) or None
    database = ds.database or ""
    extra = (ds.extra or "").lstrip("?&")
    auth = f"{user}:{password}@" if (ds.username or plain_password) else ""

    if kind == "mysql":
        port = port or 3306
        url = f"mysql+pymysql://{auth}{host}:{port}/{database}"
    elif kind in ("postgres", "postgresql"):
        port = port or 5432
        url = f"postgresql+psycopg://{auth}{host}:{port}/{database}"
    else:
        raise ValueError(
            f"暂不支持通过 SQL 查询的数据源类型：{ds.type}。"
            "当前支持 MySQL / PostgreSQL。"
        )
    if extra:
        url += ("&" if "?" in url else "?") + extra
    return url


def create_datasource_engine(ds: DataSource) -> Engine:
    return create_engine(
        build_sqlalchemy_url(ds),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        future=True,
    )


def assert_readonly_sql(sql: str, *, default_limit: int = 100) -> str:
    cleaned = (sql or "").strip()
    if not cleaned:
        raise ValueError("SQL 不能为空")
    # strip block/line comments for safety checks
    no_block = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.S)
    no_line = re.sub(r"--.*?$", " ", no_block, flags=re.M)
    compact = " ".join(no_line.split())
    if ";" in compact.rstrip(";"):
        raise ValueError("仅允许单条只读 SQL，不能包含多语句")
    compact = compact.rstrip(";").strip()
    lower = compact.lower()
    if not lower.startswith(READONLY_PREFIXES):
        raise ValueError("仅允许 SELECT / WITH / SHOW / DESCRIBE / EXPLAIN 只读语句")
    if lower.startswith(("select", "with")) and FORBIDDEN.search(lower):
        raise ValueError("检测到非只读关键字，已拒绝执行")
    if lower.startswith(("select", "with")) and " limit " not in f" {lower} ":
        compact = f"{compact} LIMIT {max(1, int(default_limit))}"
    return compact


def test_connection(ds: DataSource) -> dict[str, Any]:
    if not is_sql_datasource(ds.type):
        raise ValueError(
            f"类型 {ds.type} 暂不支持连通测试，请改用 MySQL / PostgreSQL"
        )
    engine = create_datasource_engine(ds)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "message": "连接成功"}
    finally:
        engine.dispose()


def run_readonly_query(ds: DataSource, sql: str, *, max_rows: int = 100) -> dict[str, Any]:
    safe_sql = assert_readonly_sql(sql, default_limit=max_rows)
    engine = create_datasource_engine(ds)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            if result.returns_rows:
                columns = list(result.keys())
                rows = []
                for index, row in enumerate(result):
                    if index >= max_rows:
                        break
                    item = {}
                    for key, value in zip(columns, row):
                        if hasattr(value, "isoformat"):
                            item[key] = value.isoformat()
                        else:
                            try:
                                json.dumps(value)
                                item[key] = value
                            except TypeError:
                                item[key] = str(value)
                    rows.append(item)
                return {
                    "ok": True,
                    "sql": safe_sql,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": len(rows) >= max_rows,
                }
            return {
                "ok": True,
                "sql": safe_sql,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "message": "语句已执行（无结果集）",
            }
    finally:
        engine.dispose()


def assert_write_sql(sql: str) -> str:
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("SQL 不能为空")
    if ";" in cleaned:
        raise ValueError("仅允许单条 SQL")
    lower = cleaned.lower()
    blocked = re.compile(
        r"\b(drop\s+database|drop\s+schema|truncate\s+database|grant|revoke|shutdown)\b",
        re.IGNORECASE,
    )
    if blocked.search(lower):
        raise ValueError("禁止执行高危语句（DROP DATABASE / GRANT 等）")
    return cleaned


def is_query_only(ds: DataSource) -> bool:
    return bool(getattr(ds, "query_only", 0))


def assert_writable(ds: DataSource, *, role: str = "该数据源") -> None:
    if is_query_only(ds):
        raise ValueError(
            f"{role}「{ds.name}」已开启仅查询权限，禁止写入/装载操作。"
            "请在数据源配置中关闭「仅查询」后再试。"
        )


def run_execute_sql(ds: DataSource, sql: str) -> dict[str, Any]:
    assert_writable(ds, role="目标数据源")
    safe_sql = assert_write_sql(sql)
    engine = create_datasource_engine(ds)
    try:
        with engine.begin() as conn:
            result = conn.execute(text(safe_sql))
            rowcount = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
            count = int(rowcount)
            return {
                "ok": True,
                "sql": safe_sql,
                "row_count": count,
                "message": (
                    f"SQL 已执行，影响 {count} 行"
                    if count > 0
                    else "SQL 已执行，影响 0 行（请检查 WHERE 条件或源数据）"
                ),
            }
    finally:
        engine.dispose()


def transfer_query_to_table(
    source: DataSource,
    sql: str,
    target: DataSource,
    target_table: str,
    *,
    write_mode: str = "append",
    max_rows: int = 5000,
) -> dict[str, Any]:
    assert_writable(target, role="目标数据源")
    table = (target_table or "").strip()
    if not table or not re.match(r"^[A-Za-z0-9_\.]+$", table):
        raise ValueError("目标表名不合法")
    extracted = run_readonly_query(source, sql, max_rows=max_rows)
    columns = extracted.get("columns") or []
    rows = extracted.get("rows") or []
    if not columns:
        return {
            "ok": True,
            "sql": extracted.get("sql"),
            "row_count": 0,
            "message": "源查询无列，跳过写入",
        }
    if not rows:
        return {
            "ok": True,
            "sql": extracted.get("sql"),
            "row_count": 0,
            "target_table": table,
            "write_mode": write_mode,
            "message": (
                f"源查询 0 行，未写入目标表 {table}"
                + ("（已跳过 replace 清空，避免误删目标数据）" if (write_mode or "append").lower() == "replace" else "")
            ),
        }

    kind = dialect_name(target.type)
    quoted_cols = []
    for col in columns:
        name = str(col)
        if not re.match(r"^[A-Za-z0-9_]+$", name):
            raise ValueError(f"列名不合法：{name}")
        quoted_cols.append(f'`{name}`' if kind == "mysql" else f'"{name}"')

    placeholders = ", ".join([f":c{i}" for i in range(len(columns))])
    col_sql = ", ".join(quoted_cols)
    insert_sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"

    engine = create_datasource_engine(target)
    try:
        with engine.begin() as conn:
            mode = (write_mode or "append").lower()
            # Only clear target when we actually have rows to load.
            if mode == "replace" and rows:
                conn.execute(text(f"DELETE FROM {table}"))
            payload = []
            for row in rows:
                item = {}
                for index, col in enumerate(columns):
                    item[f"c{index}"] = row.get(col)
                payload.append(item)
            if payload:
                conn.execute(text(insert_sql), payload)
        truncated = bool(extracted.get("truncated"))
        return {
            "ok": True,
            "sql": extracted.get("sql"),
            "insert_sql": insert_sql,
            "row_count": len(rows),
            "truncated": truncated,
            "target_table": table,
            "write_mode": write_mode,
            "message": (
                f"已写入 {len(rows)} 行到 {table}"
                + ("（已达单次上限，结果可能被截断）" if truncated else "")
            ),
        }
    finally:
        engine.dispose()


def list_tables(ds: DataSource, *, limit: int = 100) -> dict[str, Any]:
    kind = dialect_name(ds.type)
    if kind == "mysql":
        sql = (
            "SELECT table_schema AS table_schema, table_name AS table_name "
            "FROM information_schema.tables "
            f"WHERE table_schema = DATABASE() ORDER BY table_name LIMIT {int(limit)}"
        )
    elif kind in ("postgres", "postgresql"):
        sql = (
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            f"ORDER BY table_schema, table_name LIMIT {int(limit)}"
        )
    else:
        raise ValueError(f"不支持的数据源类型：{ds.type}")
    return run_readonly_query(ds, sql, max_rows=limit)


def describe_table(ds: DataSource, table_name: str, schema: str | None = None) -> dict[str, Any]:
    table = (table_name or "").strip()
    if not table or not re.match(r"^[A-Za-z0-9_\.]+$", table):
        raise ValueError("表名不合法")
    kind = dialect_name(ds.type)
    if "." in table and not schema:
        schema, table = table.split(".", 1)
    if kind == "mysql":
        sql = (
            "SELECT column_name, data_type, is_nullable, column_key, column_comment "
            "FROM information_schema.columns "
            f"WHERE table_schema = DATABASE() AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        )
    elif kind in ("postgres", "postgresql"):
        schema_name = schema or "public"
        sql = (
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        )
    else:
        raise ValueError(f"不支持的数据源类型：{ds.type}")
    return run_readonly_query(ds, sql, max_rows=500)
