"""Pipeline runner: ordered execute/transfer steps with run logs."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import DataSource, Pipeline, PipelineRun, PipelineStep, PipelineStepRun, utcnow
from . import datasource as ds_service
from . import sync_engines


def _append_log(run: PipelineRun, line: str) -> None:
    stamp = utcnow().strftime("%H:%M:%S")
    run.log_text = (run.log_text or "") + f"[{stamp}] {line}\n"


def _get_ds(db: Session, datasource_id: int | None, label: str) -> DataSource:
    if not datasource_id:
        raise ValueError(f"{label}未配置数据源")
    ds = db.get(DataSource, int(datasource_id))
    if not ds:
        raise ValueError(f"{label}数据源不存在：{datasource_id}")
    return ds


def run_pipeline(db: Session, pipeline_id: int, *, trigger: str = "manual") -> PipelineRun:
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise ValueError("流水线不存在")
    status = (pipeline.status or "").strip().lower()
    if status != "active":
        if status in ("pending_approval", "pending"):
            raise ValueError(
                f"流水线「{pipeline.name}」待管理员审批，审批通过后才可执行"
            )
        if status == "rejected":
            raise ValueError(f"流水线「{pipeline.name}」已被驳回，无法执行")
        raise ValueError(
            f"流水线「{pipeline.name}」当前状态为 {pipeline.status or 'unknown'}，仅 active 可执行"
        )
    steps = [s for s in (pipeline.steps or []) if int(s.enabled or 0) == 1]
    steps = sorted(steps, key=lambda s: int(s.position or 0))
    if not steps:
        raise ValueError("流水线没有可执行步骤")

    exec_date = (getattr(pipeline, "schedule_exec_date", None) or "").strip()

    run = PipelineRun(
        pipeline_id=pipeline.id,
        status="running",
        trigger=trigger or "manual",
        started_at=utcnow(),
        log_text="",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _append_log(run, f"开始执行流水线「{pipeline.name}」，共 {len(steps)} 步")
        if exec_date:
            _append_log(run, f"执行日期 exec_date={exec_date}")
        db.add(run)
        db.commit()

        total_rows = 0
        for step in steps:
            step_run = PipelineStepRun(
                run_id=run.id,
                step_id=step.id,
                step_name=step.name or f"步骤{step.position}",
                step_type=step.step_type,
                status="running",
                started_at=utcnow(),
            )
            db.add(step_run)
            db.commit()
            db.refresh(step_run)

            try:
                result = _run_step(db, step, exec_date=exec_date)
                step_run.status = "success"
                step_run.row_count = int(result.get("row_count") or 0)
                total_rows += step_run.row_count
                step_run.sql_executed = str(
                    result.get("sql") or result.get("insert_sql") or step.sql_text or ""
                )[:4000]
                default_msg = "完成" if step_run.row_count > 0 else "完成（0 行，请检查源 SQL / 条件）"
                step_run.message = str(result.get("message") or default_msg)
                _append_log(
                    run,
                    f"步骤成功：{step_run.step_name} ({step.step_type}) rows={step_run.row_count}"
                    + (f" · {step_run.message}" if step_run.row_count == 0 else ""),
                )
            except Exception as exc:
                step_run.status = "failed"
                step_run.message = str(exc)
                step_run.sql_executed = (step.sql_text or "")[:4000]
                step_run.finished_at = utcnow()
                db.add(step_run)
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = utcnow()
                _append_log(run, f"步骤失败：{step_run.step_name} · {exc}")
                db.add(run)
                db.commit()
                return run
            finally:
                if step_run.finished_at is None:
                    step_run.finished_at = utcnow()
                db.add(step_run)
                db.add(run)
                db.commit()

        run.status = "success"
        run.finished_at = utcnow()
        if total_rows == 0:
            _append_log(run, "流水线执行成功，但合计写入/影响 0 行（请检查源查询、执行日期与目标表）")
        else:
            _append_log(run, f"流水线执行成功，合计 rows={total_rows}")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utcnow()
        _append_log(run, f"流水线异常：{exc}")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


def _apply_exec_date(sql: str, exec_date: str = "") -> str:
    value = (sql or "").strip()
    if not value:
        return value
    date = (exec_date or "").strip()
    if date:
        value = value.replace("{exec_date}", date).replace("${exec_date}", date)
    return value


def _run_step(db: Session, step: PipelineStep, *, exec_date: str = "") -> dict:
    step_type = (step.step_type or "execute").lower().strip()
    sql_text = _apply_exec_date(step.sql_text or "", exec_date)
    if step_type == "transfer":
        source = _get_ds(db, step.datasource_id, "源")
        target = _get_ds(db, step.target_datasource_id, "目标")
        engine = (getattr(step, "sync_engine", None) or "sqoop").strip().lower() or "sqoop"
        return sync_engines.run_sync(
            source,
            sql_text,
            target,
            step.target_table or "",
            write_mode=step.write_mode or "append",
            sync_engine=engine,
        )
    if step_type == "execute":
        ds = _get_ds(db, step.datasource_id, "执行")
        return ds_service.run_execute_sql(ds, sql_text)
    if step_type == "query":
        ds = _get_ds(db, step.datasource_id, "查询")
        return ds_service.run_readonly_query(ds, sql_text, max_rows=500)
    raise ValueError(f"未知步骤类型：{step.step_type}")
