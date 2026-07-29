"""FastAPI routes for data pipelines."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .database import SessionLocal, get_db
from .access_control import assert_owner, owned_query
from .deps_auth import require_admin, require_usable_user
from .models import Pipeline, PipelineRun, PipelineStep, User
from .pipeline_schemas import (
    PipelineCreate,
    PipelineOut,
    PipelineRunOut,
    PipelineStepIn,
    PipelineStepOut,
    PipelineStepRunOut,
    PipelineUpdate,
)
from .services.pipeline_runner import run_pipeline

try:
    from .services.scheduler import get_scheduler_status
except ImportError:
    from services.scheduler import get_scheduler_status

router = APIRouter(
    prefix="/api/pipelines",
    tags=["pipelines"],
    dependencies=[Depends(require_usable_user)],
)


@router.get("/scheduler/status")
def scheduler_status(
    user: User = Depends(require_usable_user),
):
    """Inspect in-process cron scheduler."""
    return get_scheduler_status()


def _dump(model, **kwargs):
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def _step_out(step: PipelineStep) -> PipelineStepOut:
    return PipelineStepOut(
        id=step.id,
        pipeline_id=step.pipeline_id,
        position=step.position,
        name=step.name or "",
        step_type=step.step_type,
        datasource_id=step.datasource_id,
        target_datasource_id=step.target_datasource_id,
        target_table=step.target_table or "",
        sql_text=step.sql_text or "",
        write_mode=step.write_mode or "append",
        sync_engine=(getattr(step, "sync_engine", None) or "sqoop"),
        enabled=bool(step.enabled),
    )


def _pipeline_out(pipeline: Pipeline, last_run: PipelineRun | None = None) -> PipelineOut:
    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        description=pipeline.description or "",
        status=pipeline.status or "draft",
        schedule_cron=getattr(pipeline, "schedule_cron", None) or "",
        schedule_enabled=bool(getattr(pipeline, "schedule_enabled", 0) or 0),
        schedule_exec_date=getattr(pipeline, "schedule_exec_date", None) or "",
        schedule_note=getattr(pipeline, "schedule_note", None) or "",
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
        steps=[_step_out(step) for step in (pipeline.steps or [])],
        last_run_status=last_run.status if last_run else None,
        last_run_id=last_run.id if last_run else None,
    )


def _run_out(run: PipelineRun, pipeline_name: str = "") -> PipelineRunOut:
    return PipelineRunOut(
        id=run.id,
        pipeline_id=run.pipeline_id,
        pipeline_name=pipeline_name,
        status=run.status,
        trigger=run.trigger or "manual",
        error=run.error or "",
        log_text=run.log_text or "",
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        step_runs=[
            PipelineStepRunOut(
                id=item.id,
                run_id=item.run_id,
                step_id=item.step_id,
                step_name=item.step_name or "",
                step_type=item.step_type or "",
                status=item.status,
                message=item.message or "",
                sql_executed=item.sql_executed or "",
                row_count=item.row_count or 0,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in (run.step_runs or [])
        ],
    )


def _get_pipeline(db: Session, pipeline_id: int, user: User) -> Pipeline:
    value = db.scalars(
        select(Pipeline)
        .where(Pipeline.id == pipeline_id)
        .options(selectinload(Pipeline.steps))
    ).first()
    if not value:
        raise HTTPException(status_code=404, detail="流水线不存在")
    assert_owner(value, user, not_found_detail="流水线不存在")
    return value


def _replace_steps(db: Session, pipeline: Pipeline, steps: list[PipelineStepIn]) -> None:
    for old in list(pipeline.steps or []):
        db.delete(old)
    db.flush()
    for index, item in enumerate(steps):
        data = _dump(item)
        enabled = 1 if data.pop("enabled", True) else 0
        position = data.pop("position", None)
        db.add(
            PipelineStep(
                pipeline_id=pipeline.id,
                position=int(position if position is not None else index),
                name=data.get("name") or f"步骤{index + 1}",
                step_type=data.get("step_type") or "execute",
                datasource_id=data.get("datasource_id"),
                target_datasource_id=data.get("target_datasource_id"),
                target_table=data.get("target_table") or "",
                sql_text=data.get("sql_text") or "",
                write_mode=data.get("write_mode") or "append",
                sync_engine=(data.get("sync_engine") or "sqoop").strip().lower() or "sqoop",
                enabled=enabled,
            )
        )


def _last_run(db: Session, pipeline_id: int) -> PipelineRun | None:
    return db.scalars(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.id.desc())
        .limit(1)
    ).first()


@router.get("", response_model=list[PipelineOut])
def list_pipelines(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    stmt = select(Pipeline).options(selectinload(Pipeline.steps)).order_by(Pipeline.updated_at.desc())
    stmt = owned_query(stmt, Pipeline, user)
    if status:
        stmt = stmt.where(Pipeline.status == status)
    pipelines = db.scalars(stmt).all()
    return [_pipeline_out(item, _last_run(db, item.id)) for item in pipelines]


@router.post("", response_model=PipelineOut, status_code=201)
def create_pipeline(
    payload: PipelineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    pipeline = Pipeline(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description or "",
        status=payload.status or "draft",
        schedule_cron=payload.schedule_cron or "",
        schedule_enabled=1 if payload.schedule_enabled else 0,
        schedule_exec_date=payload.schedule_exec_date or "",
        schedule_note=payload.schedule_note or "",
    )
    db.add(pipeline)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="流水线名称已存在")
    db.refresh(pipeline)
    if payload.steps:
        _replace_steps(db, pipeline, payload.steps)
        db.commit()
    pipeline = _get_pipeline(db, pipeline.id, user)
    return _pipeline_out(pipeline)


@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs(
    pipeline_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),

    user: User = Depends(require_usable_user),
):
    stmt = select(PipelineRun).options(selectinload(PipelineRun.step_runs)).order_by(PipelineRun.id.desc())
    if pipeline_id is not None:
        stmt = stmt.where(PipelineRun.pipeline_id == pipeline_id)
    if status:
        stmt = stmt.where(PipelineRun.status == status)
    runs = db.scalars(stmt.limit(limit)).all()
    names = {}
    result = []
    for run in runs:
        if run.pipeline_id not in names:
            pipe = db.get(Pipeline, run.pipeline_id)
            names[run.pipeline_id] = pipe.name if pipe else ""
        result.append(_run_out(run, names[run.pipeline_id]))
    return result


@router.get("/runs/{run_id}", response_model=PipelineRunOut)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    run = db.scalars(
        select(PipelineRun)
        .where(PipelineRun.id == run_id)
        .options(selectinload(PipelineRun.step_runs))
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    pipe = _get_pipeline(db, run.pipeline_id, user)
    return _run_out(run, pipe.name if pipe else "")


@router.post("/templates/abcd", response_model=PipelineOut, status_code=201)
def create_abcd_template(
    name: str = Query(default="A+B→C→D 示例流水线"),
    db: Session = Depends(get_db),

    user: User = Depends(require_usable_user),
):
    """Create a 4-step starter pipeline for A/B extract → C transform → D load."""
    payload = PipelineCreate(
        name=name,
        description="模板：从 A/B 抽取到 C 加工表，再在 C 执行转换，最后装载到 D。请先在步骤中选择对应数据源并填写 SQL。",
        status="draft",
        steps=[
            PipelineStepIn(
                name="1. A库抽取到C",
                step_type="transfer",
                sql_text="SELECT * FROM source_table_a LIMIT 1000",
                target_table="stg_from_a",
                write_mode="replace",
                sync_engine="sqoop",
            ),
            PipelineStepIn(
                name="2. B库抽取到C",
                step_type="transfer",
                sql_text="SELECT * FROM source_table_b LIMIT 1000",
                target_table="stg_from_b",
                write_mode="replace",
                sync_engine="sqoop",
            ),
            PipelineStepIn(
                name="3. C库加工",
                step_type="execute",
                sql_text=(
                    "CREATE TABLE IF NOT EXISTS result_c AS "
                    "SELECT * FROM stg_from_a LIMIT 0"
                ),
            ),
            PipelineStepIn(
                name="4. 结果装载到D",
                step_type="transfer",
                sql_text="SELECT * FROM result_c LIMIT 1000",
                target_table="ads_result",
                write_mode="replace",
                sync_engine="sqoop",
            ),
        ],
    )
    return create_pipeline(payload, db, user)


@router.get("/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    return _pipeline_out(pipeline, _last_run(db, pipeline.id))


@router.put("/{pipeline_id}", response_model=PipelineOut)
def update_pipeline(pipeline_id: int, payload: PipelineUpdate, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    data = _dump(payload, exclude_unset=True)
    steps = data.pop("steps", None)
    if "schedule_enabled" in data:
        data["schedule_enabled"] = 1 if data["schedule_enabled"] else 0
    for key, value in data.items():
        setattr(pipeline, key, value)
    if steps is not None:
        normalized = []
        for item in steps:
            if isinstance(item, PipelineStepIn):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(PipelineStepIn(**item))
            else:
                normalized.append(PipelineStepIn(**_dump(item)))
        _replace_steps(db, pipeline, normalized)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="流水线名称已存在")
    pipeline = _get_pipeline(db, pipeline_id, user)
    return _pipeline_out(pipeline, _last_run(db, pipeline.id))


@router.delete("/{pipeline_id}", status_code=204)
def delete_pipeline(pipeline_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    db.delete(pipeline)
    db.commit()
    return None


def _bg_run(pipeline_id: int) -> None:
    db = SessionLocal()
    try:
        run_pipeline(db, pipeline_id, trigger="manual")
    finally:
        db.close()


@router.post("/{pipeline_id}/run", response_model=PipelineRunOut)
def trigger_pipeline(
    pipeline_id: int,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=True),
    db: Session = Depends(get_db),

    user: User = Depends(require_usable_user),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    if sync:
        try:
            run = run_pipeline(db, pipeline.id, trigger="manual")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.refresh(run)
        run = db.scalars(
            select(PipelineRun)
            .where(PipelineRun.id == run.id)
            .options(selectinload(PipelineRun.step_runs))
        ).first()
        return _run_out(run, pipeline.name)
    if (pipeline.status or "").strip().lower() != "active":
        raise HTTPException(
            status_code=400,
            detail=f"流水线「{pipeline.name}」当前不可执行（状态：{pipeline.status}）",
        )
    background_tasks.add_task(_bg_run, pipeline.id)
    return PipelineRunOut(
        id=0,
        pipeline_id=pipeline.id,
        pipeline_name=pipeline.name,
        status="pending",
        trigger="manual",
        error="",
        log_text="已提交后台执行，请稍后在执行日志中查看。",
    )


@router.post("/{pipeline_id}/approve", response_model=PipelineOut)
def approve_pipeline(
    pipeline_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    status = (pipeline.status or "").strip().lower()
    if status not in ("pending_approval", "pending", "rejected", "draft"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态「{pipeline.status}」无需审批或不可批准",
        )
    pipeline.status = "active"
    note = (getattr(pipeline, "schedule_note", None) or "").strip()
    if "approved=1" not in note:
        pipeline.schedule_note = (note + ";approved=1").strip(";")
    db.add(pipeline)
    db.commit()
    pipeline = _get_pipeline(db, pipeline_id, user)
    return _pipeline_out(pipeline, _last_run(db, pipeline.id))


@router.post("/{pipeline_id}/reject", response_model=PipelineOut)
def reject_pipeline(
    pipeline_id: int,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    pipeline = _get_pipeline(db, pipeline_id, user)
    status = (pipeline.status or "").strip().lower()
    if status not in ("pending_approval", "pending", "active", "draft"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态「{pipeline.status}」不可驳回",
        )
    pipeline.status = "rejected"
    note = (getattr(pipeline, "schedule_note", None) or "").strip()
    extra = f"rejected=1;reason={reason.strip()}" if reason.strip() else "rejected=1"
    pipeline.schedule_note = (note + ";" + extra).strip(";")
    if reason.strip():
        desc = (pipeline.description or "").strip()
        pipeline.description = (desc + f"\n[驳回原因] {reason.strip()}").strip()
    db.add(pipeline)
    db.commit()
    pipeline = _get_pipeline(db, pipeline_id, user)
    return _pipeline_out(pipeline, _last_run(db, pipeline.id))
