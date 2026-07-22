"""Pipeline schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PipelineStepIn(BaseModel):
    name: str = Field(default="", max_length=200)
    step_type: str = Field(default="execute")  # execute | transfer
    datasource_id: int | None = None
    target_datasource_id: int | None = None
    target_table: str = ""
    sql_text: str = ""
    write_mode: str = "append"  # append | replace
    sync_engine: str = "sqoop"  # sqoop | mysql | datax
    enabled: bool = True
    position: int | None = None


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: str = "draft"
    schedule_cron: str = ""
    schedule_enabled: bool = False
    schedule_exec_date: str = ""
    schedule_note: str = ""
    steps: list[PipelineStepIn] = Field(default_factory=list)


class PipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    schedule_cron: str | None = None
    schedule_enabled: bool | None = None
    schedule_exec_date: str | None = None
    schedule_note: str | None = None
    steps: list[PipelineStepIn] | None = None


class PipelineStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pipeline_id: int
    position: int
    name: str
    step_type: str
    datasource_id: int | None = None
    target_datasource_id: int | None = None
    target_table: str = ""
    sql_text: str = ""
    write_mode: str = "append"
    sync_engine: str = "sqoop"
    enabled: bool = True


class PipelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str = ""
    status: str = "draft"
    schedule_cron: str = ""
    schedule_enabled: bool = False
    schedule_exec_date: str = ""
    schedule_note: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    steps: list[PipelineStepOut] = Field(default_factory=list)
    last_run_status: str | None = None
    last_run_id: int | None = None


class PipelineStepRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_id: int | None = None
    step_name: str = ""
    step_type: str = ""
    status: str = "pending"
    message: str = ""
    sql_executed: str = ""
    row_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PipelineRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pipeline_id: int
    pipeline_name: str = ""
    status: str
    trigger: str = "manual"
    error: str = ""
    log_text: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    step_runs: list[PipelineStepRunOut] = Field(default_factory=list)
