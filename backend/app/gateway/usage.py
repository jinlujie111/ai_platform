"""Usage ledger write & aggregate."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import UsageLedger
from .adapters.base import ChatResult


def write_ledger(
    db: Session,
    *,
    result: ChatResult | None,
    request_id: str,
    user_id: int | None,
    api_key_id: int | None,
    source: str,
    status: str = "ok",
    error_code: str = "",
    model_id: str = "",
    provider: str = "",
    upstream_model: str = "",
) -> UsageLedger:
    usage = result.usage if result else None
    row = UsageLedger(
        request_id=request_id or "",
        user_id=user_id,
        api_key_id=api_key_id,
        model_id=(result.logical_model_id if result else model_id) or model_id,
        provider=(result.provider if result else provider) or provider,
        upstream_model=(result.upstream_model if result else upstream_model) or upstream_model,
        prompt_tokens=int(usage.prompt_tokens if usage else 0),
        completion_tokens=int(usage.completion_tokens if usage else 0),
        total_tokens=int(usage.total_tokens if usage else 0),
        estimated=1 if (usage and usage.estimated) else 0,
        cost_cny=float(result.cost_cny if result else 0),
        latency_ms=int(result.latency_ms if result else 0),
        status=status,
        error_code=error_code or "",
        source=source or "web_chat",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def aggregate_usage(
    db: Session,
    *,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    group_by: str = "model",
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    group_by = (group_by or "model").lower().strip()
    if group_by == "user":
        key_col = UsageLedger.user_id
        key_name = "user_id"
    elif group_by == "source":
        key_col = UsageLedger.source
        key_name = "source"
    elif group_by == "day":
        # SQLite/MySQL: cast created_at date via func.date
        key_col = func.date(UsageLedger.created_at)
        key_name = "day"
    else:
        key_col = UsageLedger.model_id
        key_name = "model_id"

    stmt = select(
        key_col.label("key"),
        func.count(UsageLedger.id).label("calls"),
        func.coalesce(func.sum(UsageLedger.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(UsageLedger.completion_tokens), 0).label("completion_tokens"),
        func.coalesce(func.sum(UsageLedger.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(UsageLedger.cost_cny), 0.0).label("cost_cny"),
    )
    if date_from is not None:
        stmt = stmt.where(UsageLedger.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(UsageLedger.created_at <= date_to)
    if user_id is not None:
        stmt = stmt.where(UsageLedger.user_id == user_id)
    stmt = stmt.group_by(key_col).order_by(func.sum(UsageLedger.cost_cny).desc())

    rows = db.execute(stmt).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = row.key
        if hasattr(key, "isoformat"):
            key = key.isoformat()
        out.append(
            {
                key_name: key,
                "calls": int(row.calls or 0),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "cost_cny": round(float(row.cost_cny or 0), 6),
            }
        )
    return out
