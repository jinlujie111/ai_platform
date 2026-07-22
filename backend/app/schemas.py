"""API schemas for the knowledge-base feature."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    chunk_mode: str = "recursive"
    chunk_size: int = Field(default=500, ge=100, le=10000)
    chunk_overlap: int = Field(default=50, ge=0, le=2000)
    min_chunk_chars: int = Field(default=50, ge=1, le=2000)
    embedding_model: str = "bge-m3"
    embedding_base_url: str = "http://127.0.0.1:9997/v1"
    embedding_dimension: int = Field(default=1024, ge=1, le=65536)
    embedding_batch_size: int = Field(default=100, ge=1, le=1000)
    chroma_path: str = ""
    chroma_collection: str = "ai_platform_knowledge"
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.5, ge=0, le=1)


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    chunk_mode: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=10000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    min_chunk_chars: int | None = Field(default=None, ge=1, le=2000)
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_dimension: int | None = Field(default=None, ge=1, le=65536)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=1000)
    chroma_path: str | None = None
    chroma_collection: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0, le=1)


class KnowledgeBaseOut(KnowledgeBaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    filename: str
    content_type: str
    size: int
    status: str
    error: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime

class ChunkOut(BaseModel):
    id: int
    knowledge_base_id: int
    document_id: int
    document_name: str
    position: int
    content: str
    metadata: dict[str, Any]
    point_id: str


class Credentials(BaseModel):
    embedding_api_key: str = ""
    chroma_api_key: str = ""


class RetrievalRequest(Credentials):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0, le=1)


class RetrievalSource(BaseModel):
    knowledge_base_id: int
    document: str
    document_id: int
    chunk_id: int
    point_id: str
    page: int | None = None
    sheet: str | None = None
    score: float
    content: str


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalSource]


class DataSourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: str = ""
    database: str = ""
    username: str = ""
    password: str = ""
    extra: str = ""
    query_only: bool = True


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = None
    host: str | None = None
    port: str | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    extra: str | None = None
    query_only: bool | None = None


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    host: str
    port: str = ""
    database: str = ""
    username: str = ""
    extra: str = ""
    query_only: bool = True
    status: str = "idle"
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    has_password: bool = False


class DataSourceQueryRequest(BaseModel):
    sql: str = Field(min_length=1)
    max_rows: int = Field(default=100, ge=1, le=500)


class DataSourceTestRequest(BaseModel):
    type: str
    host: str
    port: str = ""
    database: str = ""
    username: str = ""
    password: str = ""
    extra: str = ""
