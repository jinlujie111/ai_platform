"""Chat orchestration: RAG + datasource SQL + knowledge + pipeline + MCP tools."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..llm import SYSTEM_PROMPT, call_openai_compatible_messages
from ..models import DataSource, KnowledgeBase, Pipeline, PipelineRun, PipelineStep, utcnow
from . import datasource as ds_service
from .knowledge import retrieve
from .mcp_client import call_mcp_tool, list_mcp_tools
from .pipeline_runner import run_pipeline as execute_pipeline

MAX_TOOL_ROUNDS = 6

SQL_TOOL_NAMES = {"list_tables", "describe_table", "run_readonly_sql"}
KB_TOOL_NAMES = {"search_knowledge"}
PIPELINE_TOOL_NAMES = {
    "list_pipelines",
    "run_pipeline",
    "get_pipeline_run",
    "create_pipeline",
    "create_data_sync",
    "create_data_process",
    "schedule_task",
    "list_schedules",
    "query_pipeline_logs",
}

BUILTIN_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "列出指定数据源中的表（只读）。在不确定表名时先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer", "description": "数据源 ID"},
                },
                "required": ["datasource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "查看指定表的字段结构（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer"},
                    "table_name": {
                        "type": "string",
                        "description": "表名，可带 schema，如 public.orders",
                    },
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_readonly_sql",
            "description": (
                "在指定数据源执行只读 SQL（SELECT/WITH/SHOW/DESCRIBE/EXPLAIN）。"
                "禁止写操作。大表请加时间和 LIMIT。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer"},
                    "sql": {"type": "string", "description": "只读 SQL"},
                },
                "required": ["datasource_id", "sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "在已选知识库中检索相关文档片段。回答制度、文档、FAQ 类问题时应调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题或关键词"},
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "可选，限定单个知识库 ID；不传则检索全部已选知识库",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回条数，默认 5，最大 20",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pipelines",
            "description": "列出可用数据处理流水线及其最近运行状态。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pipeline",
            "description": "同步执行指定流水线，返回运行结果摘要。仅在用户明确要求执行/跑数时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "integer", "description": "流水线 ID"},
                },
                "required": ["pipeline_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_run",
            "description": "查询流水线某次运行详情；不传 run_id 时返回该流水线最近一次运行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "integer"},
                    "run_id": {"type": "integer", "description": "可选，运行记录 ID"},
                },
                "required": ["pipeline_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pipeline",
            "description": "创建一条数据处理流水线（可先空步骤，后续再补同步/加工步骤）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "流水线名称，需唯一"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "description": "draft 或 active，默认 active",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_data_sync",
            "description": (
                "创建数据同步任务：从源表/SQL 同步到目标表。"
                "支持同步引擎 sqoop（默认）/ mysql（应用内）/ datax；"
                "同步方式 append/replace；run_now=true 时立即执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务/流水线名称"},
                    "source_datasource_id": {"type": "integer", "description": "源数据源 ID"},
                    "target_datasource_id": {"type": "integer", "description": "目标数据源 ID"},
                    "source_table": {"type": "string", "description": "源表名"},
                    "target_table": {"type": "string", "description": "目标表名"},
                    "sync_mode": {
                        "type": "string",
                        "description": "同步方式：append(追加) 或 replace(全量覆盖)，默认 append",
                    },
                    "sync_engine": {
                        "type": "string",
                        "description": "同步引擎：sqoop（默认）/ mysql / datax",
                    },
                    "exec_date": {
                        "type": "string",
                        "description": "执行日期 YYYY-MM-DD；SQL 中可用 {exec_date} 占位",
                    },
                    "source_sql": {
                        "type": "string",
                        "description": "可选自定义源 SQL；不传则 SELECT * FROM 源表",
                    },
                    "date_column": {
                        "type": "string",
                        "description": "可选，按执行日期过滤的日期字段名",
                    },
                    "run_now": {
                        "type": "boolean",
                        "description": "是否立即执行，默认 false",
                    },
                },
                "required": [
                    "name",
                    "source_datasource_id",
                    "target_datasource_id",
                    "target_table",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_data_process",
            "description": (
                "创建数据处理任务：在指定数据源执行加工 SQL（execute 步骤）。"
                "适合清洗、汇总、建临时表等；run_now=true 时立即执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "datasource_id": {"type": "integer"},
                    "sql_text": {"type": "string", "description": "加工 SQL，可用 {exec_date}"},
                    "exec_date": {"type": "string", "description": "执行日期 YYYY-MM-DD"},
                    "run_now": {"type": "boolean"},
                },
                "required": ["name", "datasource_id", "sql_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": (
                "为流水线配置定时任务。cron 示例：0 2 * * *（每天 2 点）；"
                "也可只设 exec_date 表示按日任务备注。enabled=false 可停用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "integer"},
                    "cron": {"type": "string", "description": "cron 表达式，5 段"},
                    "exec_date": {"type": "string", "description": "可选执行日期 YYYY-MM-DD"},
                    "enabled": {"type": "boolean", "description": "是否启用，默认 true"},
                    "note": {"type": "string", "description": "备注"},
                },
                "required": ["pipeline_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_schedules",
            "description": "列出已配置定时任务的流水线（含 cron、启用状态、执行日期）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "enabled_only": {
                        "type": "boolean",
                        "description": "仅看已启用，默认 false",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pipeline_logs",
            "description": "查询流水线运行日志：可按流水线、状态、关键字、日期过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "description": "success / failed / running / pending",
                    },
                    "keyword": {"type": "string", "description": "在日志或错误信息中搜索"},
                    "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    "limit": {"type": "integer", "description": "返回条数，默认 20，最大 50"},
                },
            },
        },
    },
]

# Backward-compatible alias
TOOL_DEFINITIONS = BUILTIN_TOOL_DEFINITIONS


@dataclass
class KnowledgeToolRef:
    id: int
    embedding_api_key: str = ""
    chroma_api_key: str = ""


@dataclass
class McpToolRef:
    name: str
    config: dict[str, Any]


@dataclass
class ToolRuntime:
    db: Session | None = None
    datasources: list[DataSource] = field(default_factory=list)
    knowledge_refs: list[KnowledgeToolRef] = field(default_factory=list)
    mcp_servers: list[McpToolRef] = field(default_factory=list)
    allow_pipeline: bool = False
    allow_mcp: bool = False
    mcp_tool_meta: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_datasource_context(datasources: list[DataSource]) -> str:
    if not datasources:
        return ""
    lines = ["可用数据源（可通过工具查询真实数据）："]
    for ds in datasources:
        perm = "仅查询" if bool(getattr(ds, "query_only", 0)) else "可写入"
        lines.append(
            f"- id={ds.id} | 名称={ds.name} | 类型={ds.type} | 权限={perm} | "
            f"host={ds.host}:{ds.port or '-'} | database={ds.database or '-'}"
        )
    lines.append(
        "工作方式：优先结合知识库中的表/字段含义；需要真实数据时调用工具。"
        "没有工具返回前，不得声称已查询成功。"
        "标记为「仅查询」的数据源不得作为同步/加工写入目标。"
    )
    return "\n".join(lines)


def build_knowledge_context(refs: list[KnowledgeToolRef], db: Session | None) -> str:
    if not refs or db is None:
        return ""
    lines = ["可用知识库（可通过 search_knowledge 检索）："]
    for ref in refs:
        kb = db.get(KnowledgeBase, ref.id)
        if not kb:
            continue
        lines.append(f"- id={kb.id} | 名称={kb.name}")
    if len(lines) == 1:
        return ""
    lines.append("需要文档事实时调用 search_knowledge，不要编造未检索到的内容。")
    return "\n".join(lines)


def build_pipeline_context(db: Session | None) -> str:
    if db is None:
        return ""
    pipelines = db.scalars(
        select(Pipeline).order_by(Pipeline.updated_at.desc()).limit(30)
    ).all()
    if not pipelines:
        return "暂无流水线。可用 list_pipelines 确认。"
    lines = ["可用数据处理流水线："]
    for item in pipelines:
        lines.append(f"- id={item.id} | 名称={item.name} | 状态={item.status or 'draft'}")
    lines.append("可用工具：create_pipeline / create_data_sync / create_data_process / schedule_task / list_schedules / query_pipeline_logs / run_pipeline。")
    lines.append("会话中新建的流水线默认为待审批(pending_approval)，需管理员审批为 active 后才可执行。")
    lines.append("仅在用户明确要求执行时调用 run_pipeline 或 run_now=true。")
    return "\n".join(lines)


def _allowed_ids(datasources: list[DataSource]) -> set[int]:
    return {int(ds.id) for ds in datasources}


def _get_ds(datasources: list[DataSource], datasource_id: int) -> DataSource:
    for ds in datasources:
        if int(ds.id) == int(datasource_id):
            return ds
    raise ValueError(f"数据源 {datasource_id} 未授权或不存在")


def _run_summary(run: PipelineRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "pipeline_id": run.pipeline_id,
        "status": run.status,
        "trigger": run.trigger,
        "error": run.error or "",
        "log_text": (run.log_text or "")[:4000],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "step_runs": [
            {
                "step_name": item.step_name,
                "step_type": item.step_type,
                "status": item.status,
                "message": (item.message or "")[:500],
                "row_count": item.row_count,
            }
            for item in (run.step_runs or [])
        ],
    }


def execute_sql_tool(
    name: str,
    arguments: dict[str, Any],
    datasources: list[DataSource],
) -> dict[str, Any]:
    allowed = _allowed_ids(datasources)
    datasource_id = int(arguments.get("datasource_id"))
    if datasource_id not in allowed:
        raise ValueError(f"数据源 {datasource_id} 未在本次对话中启用")
    ds = _get_ds(datasources, datasource_id)
    if name == "list_tables":
        return ds_service.list_tables(ds)
    if name == "describe_table":
        return ds_service.describe_table(
            ds,
            str(arguments.get("table_name") or ""),
            schema=None,
        )
    if name == "run_readonly_sql":
        return ds_service.run_readonly_query(ds, str(arguments.get("sql") or ""))
    raise ValueError(f"未知工具：{name}")


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    datasources: list[DataSource],
) -> dict[str, Any]:
    """Backward-compatible sync SQL tool executor."""
    return execute_sql_tool(name, arguments, datasources)


def _search_knowledge(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("知识库检索不可用")
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("请提供检索 query")
    top_k = arguments.get("top_k")
    try:
        top_k_n = int(top_k) if top_k is not None else 5
    except Exception:
        top_k_n = 5
    top_k_n = max(1, min(20, top_k_n))
    kb_filter = arguments.get("knowledge_base_id")
    refs = list(runtime.knowledge_refs)
    if kb_filter is not None:
        kb_id = int(kb_filter)
        refs = [item for item in refs if int(item.id) == kb_id]
        if not refs:
            raise ValueError(f"知识库 {kb_id} 未在本次对话中启用")
    if not refs:
        raise ValueError("本次对话未选择知识库")

    results: list[dict[str, Any]] = []
    for ref in refs:
        kb = runtime.db.get(KnowledgeBase, ref.id)
        if not kb:
            continue
        hits = retrieve(
            kb,
            query,
            embedding_api_key=ref.embedding_api_key or "",
            chroma_api_key=ref.chroma_api_key or "",
            top_k=top_k_n,
        )
        results.extend(hits)
    results.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    clipped = results[:top_k_n]
    return {
        "query": query,
        "count": len(clipped),
        "results": [
            {
                "knowledge_base_id": item.get("knowledge_base_id"),
                "knowledge_base_name": item.get("knowledge_base_name"),
                "document": item.get("document"),
                "chunk_id": item.get("chunk_id"),
                "score": item.get("score"),
                "content": (item.get("content") or "")[:1200],
            }
            for item in clipped
        ],
    }


def _list_pipelines(runtime: ToolRuntime) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    pipelines = runtime.db.scalars(
        select(Pipeline).order_by(Pipeline.updated_at.desc()).limit(50)
    ).all()
    items = []
    for pipe in pipelines:
        last = runtime.db.scalars(
            select(PipelineRun)
            .where(PipelineRun.pipeline_id == pipe.id)
            .order_by(PipelineRun.id.desc())
            .limit(1)
        ).first()
        items.append(
            {
                "id": pipe.id,
                "name": pipe.name,
                "description": pipe.description or "",
                "status": pipe.status,
                "schedule_cron": getattr(pipe, "schedule_cron", None) or "",
                "schedule_enabled": bool(getattr(pipe, "schedule_enabled", 0) or 0),
                "schedule_exec_date": getattr(pipe, "schedule_exec_date", None) or "",
                "last_run_id": last.id if last else None,
                "last_run_status": last.status if last else None,
            }
        )
    return {"pipelines": items, "count": len(items)}


def _run_pipeline_tool(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    pipeline_id = int(arguments.get("pipeline_id"))
    pipe = runtime.db.get(Pipeline, pipeline_id)
    if not pipe:
        raise ValueError(f"流水线 {pipeline_id} 不存在")
    run = execute_pipeline(runtime.db, pipeline_id, trigger="chat")
    runtime.db.refresh(run)
    run = runtime.db.scalars(
        select(PipelineRun)
        .where(PipelineRun.id == run.id)
        .options(selectinload(PipelineRun.step_runs))
    ).first()
    return {"pipeline_name": pipe.name, **_run_summary(run)}


def _get_pipeline_run(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    pipeline_id = int(arguments.get("pipeline_id"))
    run_id = arguments.get("run_id")
    pipe = runtime.db.get(Pipeline, pipeline_id)
    if not pipe:
        raise ValueError(f"流水线 {pipeline_id} 不存在")
    if run_id is not None:
        run = runtime.db.scalars(
            select(PipelineRun)
            .where(PipelineRun.id == int(run_id))
            .options(selectinload(PipelineRun.step_runs))
        ).first()
        if not run or int(run.pipeline_id) != pipeline_id:
            raise ValueError(f"运行记录 {run_id} 不存在或不属于该流水线")
    else:
        run = runtime.db.scalars(
            select(PipelineRun)
            .where(PipelineRun.pipeline_id == pipeline_id)
            .options(selectinload(PipelineRun.step_runs))
            .order_by(PipelineRun.id.desc())
            .limit(1)
        ).first()
        if not run:
            return {"pipeline_id": pipeline_id, "pipeline_name": pipe.name, "run": None}
    return {"pipeline_name": pipe.name, **_run_summary(run)}


def _safe_ident(value: str, label: str) -> str:
    name = (value or "").strip()
    if not name or not all(ch.isalnum() or ch in "._" for ch in name):
        raise ValueError(f"{label}不合法：{value}")
    return name


def _pipeline_brief(pipe: Pipeline) -> dict[str, Any]:
    return {
        "id": pipe.id,
        "name": pipe.name,
        "description": pipe.description or "",
        "status": pipe.status,
        "schedule_cron": getattr(pipe, "schedule_cron", None) or "",
        "schedule_enabled": bool(getattr(pipe, "schedule_enabled", 0) or 0),
        "schedule_exec_date": getattr(pipe, "schedule_exec_date", None) or "",
        "schedule_note": getattr(pipe, "schedule_note", None) or "",
    }


def _create_pipeline(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ValueError("请提供流水线名称")
    exists = runtime.db.scalars(select(Pipeline).where(Pipeline.name == name).limit(1)).first()
    if exists:
        raise ValueError(f"流水线名称已存在：{name}")
    # Chat-created pipelines always require admin approval before becoming executable.
    pipe = Pipeline(
        name=name,
        description=str(arguments.get("description") or "").strip(),
        status="pending_approval",
        schedule_note="created_from=chat",
    )
    runtime.db.add(pipe)
    runtime.db.commit()
    runtime.db.refresh(pipe)
    return {
        "ok": True,
        "pipeline": _pipeline_brief(pipe),
        "message": "已创建流水线，状态为待审批；管理员在「权限与审计 → 任务审批」通过后才会生效。",
    }


def _maybe_run(runtime: ToolRuntime, pipeline_id: int, run_now: bool) -> dict[str, Any] | None:
    if not run_now:
        return None
    pipe = runtime.db.get(Pipeline, pipeline_id) if runtime.db is not None else None
    if pipe and (pipe.status or "").strip().lower() != "active":
        return {
            "ok": False,
            "skipped": True,
            "reason": "pending_approval",
            "message": (
                f"流水线「{pipe.name}」待管理员审批，已跳过立即执行。"
                "请在配置中心审批通过后再运行。"
            ),
        }
    run = execute_pipeline(runtime.db, pipeline_id, trigger="chat")
    runtime.db.refresh(run)
    run = runtime.db.scalars(
        select(PipelineRun)
        .where(PipelineRun.id == run.id)
        .options(selectinload(PipelineRun.step_runs))
    ).first()
    return _run_summary(run)


def _create_data_sync(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ValueError("请提供同步任务名称")
    source_id = int(arguments.get("source_datasource_id"))
    target_id = int(arguments.get("target_datasource_id"))
    source_ds = runtime.db.get(DataSource, source_id)
    target_ds = runtime.db.get(DataSource, target_id)
    if source_ds is None:
        raise ValueError(f"源数据源不存在：{source_id}")
    if target_ds is None:
        raise ValueError(f"目标数据源不存在：{target_id}")
    ds_service.assert_writable(target_ds, role="目标数据源")
    target_table = _safe_ident(str(arguments.get("target_table") or ""), "目标表")
    source_table = str(arguments.get("source_table") or "").strip()
    source_sql = str(arguments.get("source_sql") or "").strip()
    sync_mode = str(arguments.get("sync_mode") or "append").strip().lower() or "append"
    if sync_mode not in ("append", "replace"):
        raise ValueError("sync_mode 仅支持 append 或 replace")
    sync_engine = str(arguments.get("sync_engine") or "sqoop").strip().lower() or "sqoop"
    if sync_engine not in ("sqoop", "mysql", "datax"):
        raise ValueError("sync_engine 仅支持 sqoop / mysql / datax")
    exec_date = str(arguments.get("exec_date") or "").strip()
    date_column = str(arguments.get("date_column") or "").strip()
    run_now = bool(arguments.get("run_now"))

    if not source_sql:
        if not source_table:
            raise ValueError("请提供 source_table 或 source_sql")
        source_table = _safe_ident(source_table, "源表")
        source_sql = f"SELECT * FROM {source_table}"
        if exec_date and date_column:
            col = _safe_ident(date_column, "日期字段")
            source_sql += f" WHERE DATE({col}) = '{{exec_date}}'"
        elif exec_date:
            source_sql += " -- exec_date={exec_date}"

    exists = runtime.db.scalars(select(Pipeline).where(Pipeline.name == name).limit(1)).first()
    if exists:
        raise ValueError(f"流水线名称已存在：{name}")

    desc = (
        f"数据同步：源={source_id}/{source_table or 'SQL'} → 目标={target_id}/{target_table}；"
        f"引擎={sync_engine}；方式={sync_mode}；执行日期={exec_date or '-'}"
    )
    pipe = Pipeline(
        name=name,
        description=desc,
        status="pending_approval",
        schedule_exec_date=exec_date,
        schedule_note=f"created_from=chat;sync_mode={sync_mode};sync_engine={sync_engine}",
    )
    runtime.db.add(pipe)
    runtime.db.flush()
    runtime.db.add(
        PipelineStep(
            pipeline_id=pipe.id,
            position=0,
            name="数据同步",
            step_type="transfer",
            datasource_id=source_id,
            target_datasource_id=target_id,
            target_table=target_table,
            sql_text=source_sql,
            write_mode=sync_mode,
            sync_engine=sync_engine,
            enabled=1,
        )
    )
    runtime.db.commit()
    pipe = runtime.db.scalars(
        select(Pipeline).where(Pipeline.id == pipe.id).options(selectinload(Pipeline.steps))
    ).first()
    result = {
        "ok": True,
        "pipeline": _pipeline_brief(pipe),
        "sync": {
            "source_datasource_id": source_id,
            "source_table": source_table,
            "target_datasource_id": target_id,
            "target_table": target_table,
            "sync_mode": sync_mode,
            "sync_engine": sync_engine,
            "exec_date": exec_date,
            "source_sql": source_sql,
        },
        "message": "已创建数据同步任务，待管理员审批通过后生效。",
    }
    run_info = _maybe_run(runtime, pipe.id, run_now)
    if run_info:
        result["run"] = run_info
    return result


def _create_data_process(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    name = str(arguments.get("name") or "").strip()
    sql_text = str(arguments.get("sql_text") or "").strip()
    if not name or not sql_text:
        raise ValueError("请提供 name 和 sql_text")
    datasource_id = int(arguments.get("datasource_id"))
    ds = runtime.db.get(DataSource, datasource_id)
    if ds is None:
        raise ValueError(f"数据源不存在：{datasource_id}")
    ds_service.assert_writable(ds, role="数据源")
    exec_date = str(arguments.get("exec_date") or "").strip()
    run_now = bool(arguments.get("run_now"))
    exists = runtime.db.scalars(select(Pipeline).where(Pipeline.name == name).limit(1)).first()
    if exists:
        raise ValueError(f"流水线名称已存在：{name}")
    pipe = Pipeline(
        name=name,
        description=f"数据处理 · datasource={datasource_id}",
        status="pending_approval",
        schedule_exec_date=exec_date,
        schedule_note="created_from=chat",
    )
    runtime.db.add(pipe)
    runtime.db.flush()
    runtime.db.add(
        PipelineStep(
            pipeline_id=pipe.id,
            position=0,
            name="数据处理",
            step_type="execute",
            datasource_id=datasource_id,
            sql_text=sql_text,
            enabled=1,
        )
    )
    runtime.db.commit()
    pipe = runtime.db.get(Pipeline, pipe.id)
    result = {
        "ok": True,
        "pipeline": _pipeline_brief(pipe),
        "message": "已创建数据处理任务，待管理员审批通过后生效。",
    }
    run_info = _maybe_run(runtime, pipe.id, run_now)
    if run_info:
        result["run"] = run_info
    return result


def _schedule_task(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    pipeline_id = int(arguments.get("pipeline_id"))
    pipe = runtime.db.get(Pipeline, pipeline_id)
    if not pipe:
        raise ValueError(f"流水线 {pipeline_id} 不存在")
    if "cron" in arguments and arguments.get("cron") is not None:
        pipe.schedule_cron = str(arguments.get("cron") or "").strip()
    if "exec_date" in arguments and arguments.get("exec_date") is not None:
        pipe.schedule_exec_date = str(arguments.get("exec_date") or "").strip()
    if "note" in arguments and arguments.get("note") is not None:
        pipe.schedule_note = str(arguments.get("note") or "").strip()[:500]
    enabled = arguments.get("enabled")
    if enabled is None:
        enabled = True
    pipe.schedule_enabled = 1 if enabled else 0
    pipe.updated_at = utcnow()
    runtime.db.add(pipe)
    runtime.db.commit()
    runtime.db.refresh(pipe)
    return {
        "ok": True,
        "message": "定时任务已更新（当前版本保存调度配置；到点执行可配合外部调度或手动 run_pipeline）",
        "pipeline": _pipeline_brief(pipe),
    }


def _list_schedules(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    enabled_only = bool(arguments.get("enabled_only"))
    pipelines = runtime.db.scalars(select(Pipeline).order_by(Pipeline.updated_at.desc())).all()
    items = []
    for pipe in pipelines:
        cron = getattr(pipe, "schedule_cron", None) or ""
        enabled = bool(getattr(pipe, "schedule_enabled", 0) or 0)
        exec_date = getattr(pipe, "schedule_exec_date", None) or ""
        if not cron and not exec_date and not enabled:
            continue
        if enabled_only and not enabled:
            continue
        items.append(_pipeline_brief(pipe))
    return {"schedules": items, "count": len(items)}


def _query_pipeline_logs(runtime: ToolRuntime, arguments: dict[str, Any]) -> dict[str, Any]:
    if runtime.db is None:
        raise ValueError("流水线服务不可用")
    limit = arguments.get("limit")
    try:
        limit_n = int(limit) if limit is not None else 20
    except Exception:
        limit_n = 20
    limit_n = max(1, min(50, limit_n))

    stmt = select(PipelineRun).options(selectinload(PipelineRun.step_runs)).order_by(PipelineRun.id.desc())
    if arguments.get("pipeline_id") is not None:
        stmt = stmt.where(PipelineRun.pipeline_id == int(arguments["pipeline_id"]))
    if arguments.get("status"):
        stmt = stmt.where(PipelineRun.status == str(arguments["status"]).strip())
    runs = list(runtime.db.scalars(stmt.limit(200)).all())

    date_from = str(arguments.get("date_from") or "").strip()
    date_to = str(arguments.get("date_to") or "").strip()
    keyword = str(arguments.get("keyword") or "").strip().lower()

    def _in_range(run: PipelineRun) -> bool:
        stamp = run.started_at or run.created_at
        if not stamp:
            return True
        day = stamp.strftime("%Y-%m-%d")
        if date_from and day < date_from:
            return False
        if date_to and day > date_to:
            return False
        return True

    filtered = []
    for run in runs:
        if not _in_range(run):
            continue
        blob = f"{run.log_text or ''}\n{run.error or ''}".lower()
        if keyword and keyword not in blob:
            continue
        pipe = runtime.db.get(Pipeline, run.pipeline_id)
        filtered.append(
            {
                "pipeline_id": run.pipeline_id,
                "pipeline_name": pipe.name if pipe else "",
                "run_id": run.id,
                "status": run.status,
                "trigger": run.trigger,
                "error": (run.error or "")[:500],
                "log_text": (run.log_text or "")[:3000],
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
        )
        if len(filtered) >= limit_n:
            break
    return {"logs": filtered, "count": len(filtered)}


async def execute_any_tool(
    name: str,
    arguments: dict[str, Any],
    runtime: ToolRuntime,
) -> dict[str, Any]:
    if name in SQL_TOOL_NAMES:
        return execute_sql_tool(name, arguments, runtime.datasources)
    if name == "search_knowledge":
        return _search_knowledge(runtime, arguments)
    if name == "list_pipelines":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _list_pipelines(runtime)
    if name == "run_pipeline":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _run_pipeline_tool(runtime, arguments)
    if name == "get_pipeline_run":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _get_pipeline_run(runtime, arguments)
    if name == "create_pipeline":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _create_pipeline(runtime, arguments)
    if name == "create_data_sync":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _create_data_sync(runtime, arguments)
    if name == "create_data_process":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _create_data_process(runtime, arguments)
    if name == "schedule_task":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _schedule_task(runtime, arguments)
    if name == "list_schedules":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _list_schedules(runtime, arguments)
    if name == "query_pipeline_logs":
        if not runtime.allow_pipeline:
            raise ValueError("未启用流水线工具")
        return _query_pipeline_logs(runtime, arguments)
    if name.startswith("mcp__"):
        if not runtime.allow_mcp:
            raise ValueError("未启用 MCP 工具")
        meta = runtime.mcp_tool_meta.get(name)
        if not meta:
            raise ValueError(f"未知 MCP 工具：{name}")
        return await call_mcp_tool(
            meta["server_name"],
            meta["config"],
            meta["tool_name"],
            arguments,
        )
    raise ValueError(f"未知工具：{name}")


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def filter_builtin_tools(
    enabled_tools: list[str] | None,
    *,
    has_datasources: bool,
    has_knowledge: bool,
    allow_pipeline: bool,
) -> list[dict[str, Any]]:
    allow = None if enabled_tools is None else {str(name) for name in enabled_tools}
    selected: list[dict[str, Any]] = []
    for item in BUILTIN_TOOL_DEFINITIONS:
        name = (item.get("function") or {}).get("name") or ""
        if allow is not None and name not in allow:
            continue
        if name in SQL_TOOL_NAMES and not has_datasources:
            continue
        if name in KB_TOOL_NAMES and not has_knowledge:
            continue
        if name in PIPELINE_TOOL_NAMES and not allow_pipeline:
            continue
        selected.append(item)
    return selected


async def collect_mcp_tool_definitions(
    servers: list[McpToolRef],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    definitions: list[dict[str, Any]] = []
    meta: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for server in servers:
        try:
            tools = await list_mcp_tools(server.name, server.config)
            for item in tools:
                fn = item.get("function") or {}
                tool_name = fn.get("name") or ""
                mcp_meta = item.pop("_mcp", None)
                if tool_name and mcp_meta:
                    meta[tool_name] = mcp_meta
                definitions.append(item)
        except Exception as exc:
            errors.append(f"{server.name}: {exc}")
    return definitions, meta, errors


async def run_tool_chat(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    message: str,
    history: list[dict[str, str]] | None,
    system_context: str,
    datasources: list[DataSource],
    enabled_tools: list[str] | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    db: Session | None = None,
    knowledge_refs: list[KnowledgeToolRef] | None = None,
    mcp_servers: list[McpToolRef] | None = None,
    allow_pipeline: bool = False,
    allow_mcp: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-compatible tool loop. Returns (answer, tool_traces)."""
    knowledge_refs = knowledge_refs or []
    mcp_servers = mcp_servers or []
    provider_key = (provider or "custom").lower().strip()

    runtime = ToolRuntime(
        db=db,
        datasources=datasources,
        knowledge_refs=knowledge_refs,
        mcp_servers=mcp_servers,
        allow_pipeline=allow_pipeline,
        allow_mcp=allow_mcp,
    )

    if provider_key in ("anthropic", "google"):
        from ..llm import call_llm

        hint_parts = [
            "\n\n## 能力说明\n当前模型提供方暂未接入工具调用，请基于上下文作答，不要声称已执行查询/流水线。"
        ]
        ds_hint = build_datasource_context(datasources)
        if ds_hint:
            hint_parts.append(ds_hint)
        answer = await call_llm(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            message=message,
            history=history,
            system_context=(system_context + "\n\n".join(hint_parts)).strip(),
        )
        return answer, []

    active_tools = filter_builtin_tools(
        enabled_tools,
        has_datasources=bool(datasources),
        has_knowledge=bool(knowledge_refs),
        allow_pipeline=allow_pipeline,
    )

    mcp_errors: list[str] = []
    if allow_mcp and mcp_servers:
        mcp_defs, mcp_meta, mcp_errors = await collect_mcp_tool_definitions(mcp_servers)
        active_tools.extend(mcp_defs)
        runtime.mcp_tool_meta = mcp_meta

    if not active_tools:
        from ..llm import call_llm

        hint = "\n\n## 工具说明\n当前没有可用工具，请仅根据上下文作答。"
        if mcp_errors:
            hint += "\nMCP 加载失败：" + "；".join(mcp_errors)
        answer = await call_llm(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            message=message,
            history=history,
            system_context=(system_context + hint).strip(),
        )
        return answer, []

    rounds = max(1, min(10, int(max_rounds or MAX_TOOL_ROUNDS)))
    system_prompt = SYSTEM_PROMPT
    if system_context:
        system_prompt += (
            "\n\n## 知识库上下文\n"
            "仅依据下列检索内容回答与知识库相关的事实；信息不足时可调用 search_knowledge 补充。"
            "引用事实时使用 [来源 N] 标记，不要编造来源。\n\n"
            + system_context
        )
    ds_context = build_datasource_context(datasources)
    if ds_context:
        system_prompt += "\n\n## 数据源与工具\n" + ds_context
    kb_context = build_knowledge_context(knowledge_refs, db)
    if kb_context:
        system_prompt += "\n\n## 知识库工具\n" + kb_context
    if allow_pipeline:
        system_prompt += "\n\n## 流水线工具\n" + build_pipeline_context(db)
    if allow_mcp and mcp_servers:
        names = ", ".join(item.name for item in mcp_servers)
        system_prompt += f"\n\n## MCP 工具\n已接入 MCP：{names}。可通过 mcp__ 前缀工具调用。"
        if mcp_errors:
            system_prompt += "\n部分 MCP 加载失败：" + "；".join(mcp_errors)

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    traces: list[dict[str, Any]] = []
    for _ in range(rounds):
        data = await call_openai_compatible_messages(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=active_tools,
            tool_choice="auto",
            temperature=0.2,
        )
        choice = ((data.get("choices") or [{}])[0] or {})
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        content = (msg.get("content") or "").strip()

        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = _parse_arguments(fn.get("arguments"))
                trace: dict[str, Any] = {
                    "tool": name,
                    "arguments": args,
                    "ok": False,
                }
                try:
                    result = await execute_any_tool(name, args, runtime)
                    trace["ok"] = True
                    trace["result"] = result
                    payload = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as exc:
                    trace["error"] = str(exc)
                    payload = json.dumps(
                        {"ok": False, "error": str(exc)}, ensure_ascii=False
                    )
                traces.append(trace)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": payload[:12000],
                    }
                )
            continue

        if content:
            return content, traces
        break

    data = await call_openai_compatible_messages(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages
        + [
            {
                "role": "user",
                "content": "请根据已有工具结果给出最终中文回答；若没有结果，说明原因和下一步。",
            }
        ],
        tools=None,
        temperature=0.2,
    )
    choice = ((data.get("choices") or [{}])[0] or {})
    msg = choice.get("message") or {}
    answer = (msg.get("content") or "").strip() or "未能生成回答，请重试或检查模型是否支持工具调用。"
    return answer, traces
