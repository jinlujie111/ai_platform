"""SQLAlchemy models for knowledge bases, documents, datasources, and pipelines."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    chunk_mode: Mapped[str] = mapped_column(String(32), default="recursive")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    min_chunk_chars: Mapped[int] = mapped_column(Integer, default=50)
    embedding_model: Mapped[str] = mapped_column(String(200), default="bge-m3")
    embedding_base_url: Mapped[str] = mapped_column(String(500), default="http://127.0.0.1:9997/v1")
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024)
    embedding_batch_size: Mapped[int] = mapped_column(Integer, default=100)
    chroma_path: Mapped[str] = mapped_column(String(500), default="")
    chroma_collection: Mapped[str] = mapped_column(String(200), default="ai_platform_knowledge")
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    score_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(500))
    stored_name: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(200), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[str] = mapped_column(Text, default="{}")
    point_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="chunks")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[str] = mapped_column(String(16), default="")
    database: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str] = mapped_column(String(200), default="")
    password: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[str] = mapped_column(String(500), default="")
    # 1 = 仅查询（禁止写入）；新建默认开启，存量迁移默认 0
    query_only: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    schedule_cron: Mapped[str] = mapped_column(String(120), default="")
    schedule_enabled: Mapped[int] = mapped_column(Integer, default=0)
    schedule_exec_date: Mapped[str] = mapped_column(String(32), default="")
    schedule_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="PipelineStep.position",
    )
    runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), default="")
    step_type: Mapped[str] = mapped_column(String(32), default="execute")
    datasource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_datasource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_table: Mapped[str] = mapped_column(String(200), default="")
    sql_text: Mapped[str] = mapped_column(Text, default="")
    write_mode: Mapped[str] = mapped_column(String(32), default="append")
    # sqoop | mysql | datax；新建默认可在业务层指定为 sqoop
    sync_engine: Mapped[str] = mapped_column(String(32), default="sqoop")
    enabled: Mapped[int] = mapped_column(Integer, default=1)

    pipeline: Mapped[Pipeline] = relationship(back_populates="steps")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    error: Mapped[str] = mapped_column(Text, default="")
    log_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pipeline: Mapped[Pipeline] = relationship(back_populates="runs")
    step_runs: Mapped[list["PipelineStepRun"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="PipelineStepRun.id"
    )


class PipelineStepRun(Base):
    __tablename__ = "pipeline_step_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_name: Mapped[str] = mapped_column(String(200), default="")
    step_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    message: Mapped[str] = mapped_column(Text, default="")
    sql_executed: Mapped[str] = mapped_column(Text, default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[PipelineRun] = relationship(back_populates="step_runs")


class User(Base):
    """Platform login account: admin or normal user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(32), default="user", index=True)  # admin | user
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    workspace_settings: Mapped[list["UserWorkspaceSetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserWorkspaceSetting(Base):
    """Per-user settings previously kept in browser localStorage."""

    __tablename__ = "user_workspace_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "setting_key", name="uq_user_workspace_setting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    setting_key: Mapped[str] = mapped_column(String(64), index=True)
    setting_value: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"),
        default="null",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="workspace_settings")


class Group(Base):
    """Named user group for resource authorization."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    group: Mapped[Group] = relationship(back_populates="members")


class ResourceGrant(Base):
    """Authorize a KB/datasource to a user or group (admin-managed)."""

    __tablename__ = "resource_grants"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "grantee_type",
            "grantee_id",
            name="uq_resource_grant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # knowledge_base | datasource | capability_*
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[int] = mapped_column(Integer, index=True)
    # user | group
    grantee_type: Mapped[str] = mapped_column(String(16), index=True)
    grantee_id: Mapped[int] = mapped_column(Integer, index=True)
    # use = read/query/chat; manage reserved
    permission: Mapped[str] = mapped_column(String(16), default="use")
    granted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ─── AI Gateway ───────────────────────────────────────────────────────────────


class ModelProvider(Base):
    """Upstream LLM vendor / endpoint configuration."""

    __tablename__ = "model_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # openai_compatible | anthropic | google
    adapter: Mapped[str] = mapped_column(String(32), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    # encrypted with secret_box
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    definitions: Mapped[list["ModelDefinition"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class ModelDefinition(Base):
    """Logical model_id → upstream model + provider."""

    __tablename__ = "model_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("model_providers.id", ondelete="CASCADE"), index=True
    )
    upstream_model: Mapped[str] = mapped_column(String(200))
    # CNY per 1K tokens
    price_prompt_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    price_completion_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    provider: Mapped[ModelProvider] = relationship(back_populates="definitions")


class ModelRoute(Base):
    """Named routing strategy → ordered model_id list (fallback)."""

    __tablename__ = "model_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # default | cheap | quality | embed | custom
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    # JSON array of model_id strings, first = preferred
    model_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlatformApiKey(Base):
    """External API key for calling Gateway without user login."""

    __tablename__ = "platform_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # comma-separated scopes, e.g. chat
    scopes: Mapped[str] = mapped_column(String(200), default="chat")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageLedger(Base):
    """Per-call token / cost ledger."""

    __tablename__ = "usage_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    api_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    upstream_model: Mapped[str] = mapped_column(String(200), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    # web_chat | feishu | agent | api_key | test
    source: Mapped[str] = mapped_column(String(32), default="web_chat", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
