"""In-process pipeline cron scheduler.

Reads pipelines with schedule_enabled=1 + schedule_cron, and triggers
run_pipeline(trigger='schedule') when the expression matches the current minute.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_fired_keys: set[str] = set()
_MAX_FIRED = 5000
_status: dict[str, Any] = {
    "running": False,
    "last_tick_at": None,
    "last_fired": [],
    "last_error": "",
}


def scheduler_enabled() -> bool:
    return (os.getenv("ENABLE_SCHEDULER") or "true").lower() in ("1", "true", "yes")


def get_scheduler_status() -> dict[str, Any]:
    return {
        **_status,
        "enabled": scheduler_enabled(),
        "tracked_fire_keys": len(_fired_keys),
    }


def _cron_matches(cron: str, when: datetime) -> bool:
    expr = (cron or "").strip()
    if not expr:
        return False
    try:
        from croniter import croniter
    except ImportError as exc:
        raise RuntimeError("缺少 croniter，请执行: pip install croniter") from exc

    # Normalize to minute resolution
    when = when.replace(second=0, microsecond=0)
    try:
        if hasattr(croniter, "match"):
            return bool(croniter.match(expr, when))
        # Fallback: previous tick equals current minute
        itr = croniter(expr, when)
        prev = itr.get_prev(datetime)
        return prev.replace(second=0, microsecond=0) == when
    except Exception as exc:
        logger.warning("invalid cron %r: %s", expr, exc)
        return False


def _remember_fire(key: str) -> bool:
    """Return True if first time seeing this key."""
    if key in _fired_keys:
        return False
    _fired_keys.add(key)
    if len(_fired_keys) > _MAX_FIRED:
        # drop arbitrary old half
        for item in list(_fired_keys)[: len(_fired_keys) // 2]:
            _fired_keys.discard(item)
    return True


def _tick_once() -> list[dict[str, Any]]:
    try:
        from ..database import SessionLocal
        from ..models import Pipeline
        from .pipeline_runner import run_pipeline
    except ImportError:
        from database import SessionLocal
        from models import Pipeline
        from services.pipeline_runner import run_pipeline

    now = datetime.now().astimezone()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    fired: list[dict[str, Any]] = []

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Pipeline).where(
                Pipeline.schedule_enabled == 1,
                Pipeline.status == "active",
            )
        ).all()
        for pipe in rows:
            cron = (getattr(pipe, "schedule_cron", None) or "").strip()
            if not cron:
                continue
            if not _cron_matches(cron, now):
                continue
            fire_key = f"{pipe.id}:{minute_key}"
            if not _remember_fire(fire_key):
                continue
            try:
                run = run_pipeline(db, pipe.id, trigger="schedule")
                item = {
                    "pipeline_id": pipe.id,
                    "name": pipe.name,
                    "run_id": run.id,
                    "status": run.status,
                    "at": minute_key,
                }
                fired.append(item)
                logger.info(
                    "scheduler fired pipeline=%s run=%s status=%s",
                    pipe.id,
                    run.id,
                    run.status,
                )
            except Exception as exc:
                logger.exception("scheduler failed pipeline=%s", pipe.id)
                fired.append(
                    {
                        "pipeline_id": pipe.id,
                        "name": pipe.name,
                        "error": str(exc),
                        "at": minute_key,
                    }
                )
    finally:
        db.close()

    _status["last_tick_at"] = now.isoformat()
    if fired:
        _status["last_fired"] = (fired + list(_status.get("last_fired") or []))[:20]
        _status["last_error"] = next((f.get("error") for f in fired if f.get("error")), "")
    return fired


async def _scheduler_loop() -> None:
    _status["running"] = True
    logger.info("pipeline scheduler started (cron tick ~60s)")
    try:
        while True:
            try:
                await asyncio.to_thread(_tick_once)
            except Exception as exc:
                _status["last_error"] = str(exc)
                logger.exception("scheduler tick error")
            # Align roughly to next minute
            now = datetime.now()
            sleep_sec = max(5, 60 - now.second)
            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("pipeline scheduler stopped")
        raise
    finally:
        _status["running"] = False


def start_scheduler() -> None:
    global _scheduler_task
    if not scheduler_enabled():
        logger.info("pipeline scheduler disabled (ENABLE_SCHEDULER=false)")
        return
    if _scheduler_task and not _scheduler_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("no running loop; scheduler not started")
        return
    _scheduler_task = loop.create_task(_scheduler_loop(), name="pipeline-scheduler")


async def stop_scheduler() -> None:
    global _scheduler_task
    task = _scheduler_task
    _scheduler_task = None
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
