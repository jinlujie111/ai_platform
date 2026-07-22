"""Data sync engines: sqoop (default), mysql (in-app), datax."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..models import DataSource
from . import datasource as ds_service

SYNC_ENGINES = ("sqoop", "mysql", "datax")


def normalize_sync_engine(value: str | None) -> str:
    engine = (value or "sqoop").strip().lower()
    if engine not in SYNC_ENGINES:
        raise ValueError(f"不支持的同步引擎：{value}，可选：{', '.join(SYNC_ENGINES)}")
    return engine


def _jdbc_url(ds: DataSource) -> str:
    kind = ds_service.dialect_name(ds.type)
    host = ds.host or "127.0.0.1"
    database = ds.database or ""
    if kind == "mysql":
        port = int(ds.port or 0) or 3306
        return f"jdbc:mysql://{host}:{port}/{database}?useUnicode=true&characterEncoding=utf8"
    if kind in ("postgres", "postgresql"):
        port = int(ds.port or 0) or 5432
        return f"jdbc:postgresql://{host}:{port}/{database}"
    raise ValueError(f"同步引擎暂不支持数据源类型：{ds.type}")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _sqoop_bin() -> str | None:
    home = (os.environ.get("SQOOP_HOME") or "").strip()
    if home:
        candidate = Path(home) / "bin" / ("sqoop.cmd" if os.name == "nt" else "sqoop")
        if candidate.exists():
            return str(candidate)
    return _which("sqoop") or _which("sqoop.cmd")


def _datax_launcher() -> list[str] | None:
    home = (os.environ.get("DATAX_HOME") or "").strip()
    if home:
        py = Path(home) / "bin" / "datax.py"
        if py.exists():
            return ["python", str(py)]
        bat = Path(home) / "bin" / "datax.bat"
        if bat.exists():
            return [str(bat)]
    script = _which("datax.py")
    if script:
        return ["python", script]
    return None


def _extract_table_hint(sql: str) -> str:
    match = re.search(
        r"\bfrom\s+([`\"\[]?)([A-Za-z0-9_\.]+)\1",
        sql or "",
        flags=re.IGNORECASE,
    )
    return match.group(2) if match else ""


def _run_command(cmd: list[str], *, cwd: str | None = None, timeout: int = 3600) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    stdout = (proc.stdout or "")[-4000:]
    stderr = (proc.stderr or "")[-4000:]
    if proc.returncode != 0:
        raise RuntimeError(
            f"命令执行失败（exit={proc.returncode}）：{' '.join(cmd)}\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )
    return {
        "ok": True,
        "command": " ".join(cmd),
        "stdout": stdout,
        "stderr": stderr,
        "row_count": 0,
    }


def run_mysql_sync(
    source: DataSource,
    sql: str,
    target: DataSource,
    target_table: str,
    *,
    write_mode: str = "append",
    max_rows: int = 5000,
) -> dict[str, Any]:
    """Application-level SQLAlchemy transfer (MySQL/PG)."""
    result = ds_service.transfer_query_to_table(
        source,
        sql,
        target,
        target_table,
        write_mode=write_mode,
        max_rows=max_rows,
    )
    result["sync_engine"] = "mysql"
    result["message"] = (result.get("message") or "完成") + " · 引擎=mysql(应用内)"
    return result


def run_sqoop_sync(
    source: DataSource,
    sql: str,
    target: DataSource,
    target_table: str,
    *,
    write_mode: str = "append",
) -> dict[str, Any]:
    """
    Prefer Sqoop CLI when available.
    For RDBMS→RDBMS without Hadoop staging, fall back to mysql in-app sync
    after recording the intended sqoop command.
    """
    ds_service.assert_writable(target, role="目标数据源")
    table = (target_table or "").strip()
    if not table:
        raise ValueError("目标表不能为空")
    query = (sql or "").strip().rstrip(";")
    if not query:
        raise ValueError("源 SQL 不能为空")
    if "$CONDITIONS" not in query.upper():
        # Sqoop import --query requires $CONDITIONS
        query_for_sqoop = f"{query} WHERE $CONDITIONS" if " where " not in query.lower() else f"({query}) AND $CONDITIONS"
    else:
        query_for_sqoop = query

    source_jdbc = _jdbc_url(source)
    target_jdbc = _jdbc_url(target)
    sqoop = _sqoop_bin()
    cmd = [
        sqoop or "sqoop",
        "import",
        "--connect",
        source_jdbc,
        "--username",
        source.username or "",
        "--password",
        source.password or "",
        "--query",
        query_for_sqoop,
        "--target-dir",
        f"/user/ai_platform/sqoop/{table}",
        "--delete-target-dir",
        "--num-mappers",
        "1",
    ]
    # Optional export hint for operators / logs
    export_hint = (
        f"sqoop export --connect {target_jdbc} --username {target.username or ''} "
        f"--table {table} --export-dir /user/ai_platform/sqoop/{table}"
        + (" --update-mode allowinsert" if (write_mode or "append").lower() == "append" else "")
    )

    if sqoop:
        try:
            result = _run_command(cmd)
            # Attempt export if Hadoop path succeeded
            export_cmd = [
                sqoop,
                "export",
                "--connect",
                target_jdbc,
                "--username",
                target.username or "",
                "--password",
                target.password or "",
                "--table",
                table,
                "--export-dir",
                f"/user/ai_platform/sqoop/{table}",
                "--num-mappers",
                "1",
            ]
            if (write_mode or "append").lower() == "replace":
                # Best-effort: clear via mysql engine first when possible
                try:
                    ds_service.run_execute_sql(target, f"DELETE FROM {table}")
                except Exception:
                    pass
            export_result = _run_command(export_cmd)
            return {
                "ok": True,
                "sync_engine": "sqoop",
                "sql": sql,
                "row_count": 0,
                "command": result.get("command"),
                "export_command": export_result.get("command"),
                "message": "Sqoop import/export 已执行（行数请以目标表为准）",
                "target_table": table,
                "write_mode": write_mode,
            }
        except Exception as exc:
            # Fall through to in-app with warning
            fallback = run_mysql_sync(
                source, sql, target, table, write_mode=write_mode, max_rows=50000
            )
            fallback["sync_engine"] = "sqoop"
            fallback["message"] = (
                f"Sqoop 执行失败，已回退 mysql 应用内同步：{exc}；"
                f"建议命令：{' '.join(cmd)} || {export_hint}"
            )
            fallback["command"] = " ".join(cmd)
            return fallback

    fallback = run_mysql_sync(
        source, sql, target, table, write_mode=write_mode, max_rows=50000
    )
    fallback["sync_engine"] = "sqoop"
    fallback["command"] = " ".join(cmd)
    fallback["message"] = (
        "未检测到 Sqoop 客户端（可配置 SQOOP_HOME 或 PATH），"
        f"已按默认策略回退 mysql 应用内同步。参考命令：{' '.join(cmd)}"
    )
    return fallback


def _datax_mysql_reader(source: DataSource, sql: str) -> dict[str, Any]:
    return {
        "name": "mysqlreader",
        "parameter": {
            "username": source.username or "",
            "password": source.password or "",
            "column": ["*"],
            "connection": [
                {
                    "jdbcUrl": [_jdbc_url(source)],
                    "querySql": [sql],
                }
            ],
        },
    }


def _datax_mysql_writer(target: DataSource, table: str, write_mode: str) -> dict[str, Any]:
    mode = "replace" if (write_mode or "append").lower() == "replace" else "insert"
    return {
        "name": "mysqlwriter",
        "parameter": {
            "writeMode": mode,
            "username": target.username or "",
            "password": target.password or "",
            "column": ["*"],
            "connection": [
                {
                    "jdbcUrl": _jdbc_url(target),
                    "table": [table],
                }
            ],
        },
    }


def run_datax_sync(
    source: DataSource,
    sql: str,
    target: DataSource,
    target_table: str,
    *,
    write_mode: str = "append",
) -> dict[str, Any]:
    ds_service.assert_writable(target, role="目标数据源")
    table = (target_table or "").strip()
    if not table:
        raise ValueError("目标表不能为空")
    query = (sql or "").strip().rstrip(";")
    if not query:
        raise ValueError("源 SQL 不能为空")

    job = {
        "job": {
            "setting": {"speed": {"channel": 2}},
            "content": [
                {
                    "reader": _datax_mysql_reader(source, query),
                    "writer": _datax_mysql_writer(target, table, write_mode),
                }
            ],
        }
    }
    launcher = _datax_launcher()
    with tempfile.TemporaryDirectory(prefix="ai_platform_datax_") as tmp:
        job_path = Path(tmp) / "job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        if launcher:
            result = _run_command([*launcher, str(job_path)])
            return {
                "ok": True,
                "sync_engine": "datax",
                "sql": sql,
                "row_count": 0,
                "command": result.get("command"),
                "message": "DataX 任务已执行（行数请以目标表为准）",
                "target_table": table,
                "write_mode": write_mode,
                "job": job,
            }

        fallback = run_mysql_sync(
            source, sql, target, table, write_mode=write_mode, max_rows=50000
        )
        fallback["sync_engine"] = "datax"
        fallback["message"] = (
            "未检测到 DataX（可配置 DATAX_HOME），已回退 mysql 应用内同步。"
            f"已生成 DataX 作业草稿（reader={_extract_table_hint(query) or 'query'} → {table}）。"
        )
        fallback["job"] = job
        return fallback


def run_sync(
    source: DataSource,
    sql: str,
    target: DataSource,
    target_table: str,
    *,
    write_mode: str = "append",
    sync_engine: str = "sqoop",
) -> dict[str, Any]:
    engine = normalize_sync_engine(sync_engine)
    if engine == "mysql":
        return run_mysql_sync(source, sql, target, target_table, write_mode=write_mode)
    if engine == "datax":
        return run_datax_sync(source, sql, target, target_table, write_mode=write_mode)
    return run_sqoop_sync(source, sql, target, target_table, write_mode=write_mode)
