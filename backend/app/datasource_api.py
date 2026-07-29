"""FastAPI routes for datasource management and read-only SQL."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access_control import (
    RESOURCE_DS,
    accessible_query,
    assert_can_manage,
    assert_can_use,
)
from .database import get_db
from .deps_auth import require_usable_user
from .models import DataSource, User
from .services.secret_box import encrypt_secret
from .schemas import (
    DataSourceCreate,
    DataSourceOut,
    DataSourceQueryRequest,
    DataSourceTestRequest,
    DataSourceUpdate,
)
from .services import datasource as ds_service

router = APIRouter(
    prefix="/api/datasources",
    tags=["datasources"],
    dependencies=[Depends(require_usable_user)],
)


def _dump(model, **kwargs):
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def _get_ds(
    db: Session,
    datasource_id: int,
    user: User,
    *,
    manage: bool = False,
) -> DataSource:
    value = db.get(DataSource, datasource_id)
    if not value:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if manage:
        assert_can_manage(value, user, not_found_detail="数据源不存在")
    else:
        assert_can_use(
            db, value, user, resource_type=RESOURCE_DS, not_found_detail="数据源不存在"
        )
    return value


def _as_flag(value) -> int:
    return 1 if value else 0


def _out(ds: DataSource) -> DataSourceOut:
    return DataSourceOut(
        id=ds.id,
        name=ds.name,
        type=ds.type,
        host=ds.host,
        port=ds.port or "",
        database=ds.database or "",
        username=ds.username or "",
        extra=ds.extra or "",
        query_only=bool(getattr(ds, "query_only", 0)),
        status=ds.status or "idle",
        last_error=ds.last_error or "",
        created_at=ds.created_at,
        updated_at=ds.updated_at,
        has_password=bool(ds.password),
    )


def _apply_status(db: Session, ds: DataSource, *, ok: bool, error: str = "") -> None:
    ds.status = "connected" if ok else "error"
    ds.last_error = "" if ok else (error or "连接失败")
    db.add(ds)
    db.commit()
    db.refresh(ds)


@router.get("", response_model=list[DataSourceOut])
def list_datasources(
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    stmt = accessible_query(
        select(DataSource).order_by(DataSource.updated_at.desc()),
        DataSource,
        user,
        db,
        resource_type=RESOURCE_DS,
    )
    values = db.scalars(stmt).all()
    return [_out(value) for value in values]


@router.post("", response_model=DataSourceOut, status_code=201)
def create_datasource(
    payload: DataSourceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    data = _dump(payload)
    data["query_only"] = _as_flag(data.get("query_only", True))
    data["owner_id"] = user.id
    if data.get("password"):
        data["password"] = encrypt_secret(data["password"])
    value = DataSource(**data)
    db.add(value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="数据源名称已存在")
    db.refresh(value)
    return _out(value)


@router.put("/{datasource_id}", response_model=DataSourceOut)
def update_datasource(
    datasource_id: int, payload: DataSourceUpdate, db: Session = Depends(get_db),

    user: User = Depends(require_usable_user),
):
    value = _get_ds(db, datasource_id, user, manage=True)
    data = _dump(payload, exclude_unset=True)
    if "password" in data and data["password"] == "":
        data.pop("password")
    elif "password" in data and data.get("password"):
        data["password"] = encrypt_secret(data["password"])
    if "query_only" in data:
        data["query_only"] = _as_flag(data.get("query_only"))
    for key, item in data.items():
        setattr(value, key, item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="数据源名称已存在")
    db.refresh(value)
    return _out(value)


@router.delete("/{datasource_id}", status_code=204)
def delete_datasource(datasource_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    value = _get_ds(db, datasource_id, user, manage=True)
    db.delete(value)
    db.commit()
    return None


@router.post("/test")
def test_datasource_payload(payload: DataSourceTestRequest,
    user: User = Depends(require_usable_user),
):
    temp = DataSource(
        name="__test__",
        type=payload.type,
        host=payload.host,
        port=payload.port or "",
        database=payload.database or "",
        username=payload.username or "",
        password=payload.password or "",
        extra=payload.extra or "",
    )
    try:
        return ds_service.test_connection(temp)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "连接失败")


@router.post("/{datasource_id}/test")
def test_datasource(datasource_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    value = _get_ds(db, datasource_id, user)
    try:
        result = ds_service.test_connection(value)
        _apply_status(db, value, ok=True)
        return result
    except Exception as exc:
        _apply_status(db, value, ok=False, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc) or "连接失败")


@router.post("/{datasource_id}/query")
def query_datasource(
    datasource_id: int, payload: DataSourceQueryRequest, db: Session = Depends(get_db),

    user: User = Depends(require_usable_user),
):
    value = _get_ds(db, datasource_id, user)
    try:
        result = ds_service.run_readonly_query(value, payload.sql, max_rows=payload.max_rows)
        _apply_status(db, value, ok=True)
        return result
    except Exception as exc:
        _apply_status(db, value, ok=False, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc) or "查询失败")


@router.get("/{datasource_id}/tables")
def datasource_tables(datasource_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    value = _get_ds(db, datasource_id, user)
    try:
        result = ds_service.list_tables(value)
        _apply_status(db, value, ok=True)
        return result
    except Exception as exc:
        _apply_status(db, value, ok=False, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc) or "列出表失败")
