"""FastAPI routes for local knowledge-base management."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import UPLOAD_DIR, get_db
from .models import Chunk, Document, KnowledgeBase
from .schemas import (
    ChunkOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    RetrievalRequest,
    RetrievalResponse,
)
from .services.embedding import embed_texts
from .services.knowledge import document_path, index_document, retrieve
from .services.parsers import SUPPORTED_EXTENSIONS
from .services.vector_store import (
    create_client,
    delete_document_points,
    delete_knowledge_base_points,
)
from .services.web_page import fetch_web_page


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


def _dump(model, **kwargs):
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def _get_kb(db: Session, knowledge_base_id: int) -> KnowledgeBase:
    value = db.get(KnowledgeBase, knowledge_base_id)
    if not value:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return value


def _kb_out(db: Session, kb: KnowledgeBase) -> KnowledgeBaseOut:
    document_count = db.scalar(
        select(func.count(Document.id)).where(Document.knowledge_base_id == kb.id)
    ) or 0
    chunk_count = db.scalar(
        select(func.count(Chunk.id)).where(Chunk.knowledge_base_id == kb.id)
    ) or 0
    data = {column.name: getattr(kb, column.name) for column in kb.__table__.columns}
    return KnowledgeBaseOut(**data, document_count=document_count, chunk_count=chunk_count)


@router.get("", response_model=list[KnowledgeBaseOut])
def list_knowledge_bases(db: Session = Depends(get_db)):
    values = db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc())).all()
    return [_kb_out(db, value) for value in values]


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
def create_knowledge_base(payload: KnowledgeBaseCreate, db: Session = Depends(get_db)):
    if payload.chunk_overlap >= payload.chunk_size:
        raise HTTPException(status_code=422, detail="切片重叠必须小于切片大小")
    value = KnowledgeBase(**_dump(payload))
    db.add(value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="知识库名称已存在")
    db.refresh(value)
    return _kb_out(db, value)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
def get_knowledge_base(knowledge_base_id: int, db: Session = Depends(get_db)):
    return _kb_out(db, _get_kb(db, knowledge_base_id))


@router.put("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
def update_knowledge_base(
    knowledge_base_id: int, payload: KnowledgeBaseUpdate, db: Session = Depends(get_db)
):
    value = _get_kb(db, knowledge_base_id)
    updates = _dump(payload, exclude_unset=True)
    chunk_size = updates.get("chunk_size", value.chunk_size)
    chunk_overlap = updates.get("chunk_overlap", value.chunk_overlap)
    if chunk_overlap >= chunk_size:
        raise HTTPException(status_code=422, detail="切片重叠必须小于切片大小")
    for key, item in updates.items():
        setattr(value, key, item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="知识库名称已存在")
    db.refresh(value)
    return _kb_out(db, value)


@router.delete("/{knowledge_base_id}", status_code=204)
def delete_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    chroma_api_key: str = Header(default="", alias="X-Chroma-Api-Key"),
):
    value = _get_kb(db, knowledge_base_id)
    try:
        delete_knowledge_base_points(
            create_client(value.chroma_path, chroma_api_key), value.chroma_collection, value.id
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"清理 Chroma 失败：{exc}")
    paths = [document_path(document) for document in value.documents]
    db.delete(value)
    db.commit()
    for path in paths:
        path.unlink(missing_ok=True)


@router.get("/{knowledge_base_id}/documents")
def list_documents(knowledge_base_id: int, db: Session = Depends(get_db)):
    _get_kb(db, knowledge_base_id)
    values = db.scalars(
        select(Document)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .order_by(Document.created_at.desc())
    ).all()
    return [
        {
            "id": item.id,
            "knowledge_base_id": item.knowledge_base_id,
            "filename": item.filename,
            "content_type": item.content_type,
            "size": item.size,
            "status": item.status,
            "error": item.error,
            "chunk_count": item.chunk_count,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in values
    ]


def _create_pending_document(
    *,
    db: Session,
    knowledge_base_id: int,
    filename: str,
    stored_name: str,
    content_type: str,
    size: int,
    background_tasks: BackgroundTasks,
    embedding_api_key: str,
    chroma_api_key: str,
) -> dict:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        stored_name=stored_name,
        content_type=content_type or "",
        size=size,
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(
        index_document, document.id, embedding_api_key, chroma_api_key
    )
    return {"id": document.id, "status": document.status, "filename": document.filename}


@router.post("/{knowledge_base_id}/documents", status_code=202)
async def upload_document(
    knowledge_base_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    embedding_api_key: str = Form(default=""),
    chroma_api_key: str = Form(default=""),
    db: Session = Depends(get_db),
):
    _get_kb(db, knowledge_base_id)
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="仅支持 TXT、Markdown、PDF、DOCX、CSV、XLSX、PPTX",
        )
    stored_name = f"{uuid.uuid4().hex}{extension}"
    target = UPLOAD_DIR / stored_name
    size = 0
    try:
        with target.open("wb") as handle:
            while content := await file.read(1024 * 1024):
                size += len(content)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过上传大小限制")
                handle.write(content)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return _create_pending_document(
        db=db,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        stored_name=stored_name,
        content_type=file.content_type or "",
        size=size,
        background_tasks=background_tasks,
        embedding_api_key=embedding_api_key,
        chroma_api_key=chroma_api_key,
    )


@router.post("/{knowledge_base_id}/documents/text", status_code=202)
async def create_text_document(
    knowledge_base_id: int,
    background_tasks: BackgroundTasks,
    title: str = Form(default=""),
    content: str = Form(...),
    embedding_api_key: str = Form(default=""),
    chroma_api_key: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """Create a knowledge document from pasted / typed plain text."""
    _get_kb(db, knowledge_base_id)
    text = (content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请填写文本内容")
    payload = text.encode("utf-8")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文本超过大小限制")

    raw_title = (title or "").strip() or "未命名文本"
    safe_stem = "".join(
        ch for ch in raw_title if ch not in '<>:"/\\|?*'
    ).strip(" .") or "未命名文本"
    if len(safe_stem) > 80:
        safe_stem = safe_stem[:80].rstrip()
    filename = f"{safe_stem}.txt"
    stored_name = f"{uuid.uuid4().hex}.txt"
    target = UPLOAD_DIR / stored_name
    try:
        target.write_bytes(payload)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return _create_pending_document(
        db=db,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        stored_name=stored_name,
        content_type="text/plain; charset=utf-8",
        size=len(payload),
        background_tasks=background_tasks,
        embedding_api_key=embedding_api_key,
        chroma_api_key=chroma_api_key,
    )


def _safe_txt_filename(title: str, fallback: str = "未命名文档") -> str:
    raw_title = (title or "").strip() or fallback
    safe_stem = "".join(ch for ch in raw_title if ch not in '<>:"/\\|?*').strip(" .") or fallback
    if len(safe_stem) > 80:
        safe_stem = safe_stem[:80].rstrip()
    return f"{safe_stem}.txt"


@router.post("/{knowledge_base_id}/documents/url", status_code=202)
async def create_url_document(
    knowledge_base_id: int,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    title: str = Form(default=""),
    embedding_api_key: str = Form(default=""),
    chroma_api_key: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """Fetch a public web page, extract text, and index it like an uploaded document."""
    _get_kb(db, knowledge_base_id)
    try:
        page = fetch_web_page(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"抓取网页失败：{exc}") from exc

    body = (
        f"来源：{page['url']}\n"
        f"标题：{page['title'] or (title or '').strip() or '未命名网页'}\n\n"
        f"{page['text']}"
    )
    payload = body.encode("utf-8")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="网页正文超过大小限制")

    filename = _safe_txt_filename(
        (title or "").strip() or page["title"] or "网页内容",
        fallback="网页内容",
    )
    stored_name = f"{uuid.uuid4().hex}.txt"
    target = UPLOAD_DIR / stored_name
    try:
        target.write_bytes(payload)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    result = _create_pending_document(
        db=db,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        stored_name=stored_name,
        content_type="text/plain; charset=utf-8",
        size=len(payload),
        background_tasks=background_tasks,
        embedding_api_key=embedding_api_key,
        chroma_api_key=chroma_api_key,
    )
    result["source_url"] = page["url"]
    return result


@router.post("/{knowledge_base_id}/documents/{document_id}/retry", status_code=202)
def retry_document(
    knowledge_base_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    embedding_api_key: str = Form(default=""),
    chroma_api_key: str = Form(default=""),
    db: Session = Depends(get_db),
):
    document = db.get(Document, document_id)
    if not document or document.knowledge_base_id != knowledge_base_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if document.status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail="文档正在处理中")
    document.status = "pending"
    document.error = ""
    db.commit()
    background_tasks.add_task(index_document, document.id, embedding_api_key, chroma_api_key)
    return {"id": document.id, "status": "pending"}


@router.delete("/{knowledge_base_id}/documents/{document_id}", status_code=204)
def delete_document(
    knowledge_base_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    chroma_api_key: str = Header(default="", alias="X-Chroma-Api-Key"),
):
    knowledge_base = _get_kb(db, knowledge_base_id)
    document = db.get(Document, document_id)
    if not document or document.knowledge_base_id != knowledge_base_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        delete_document_points(
            create_client(knowledge_base.chroma_path, chroma_api_key),
            knowledge_base.chroma_collection,
            knowledge_base_id,
            document_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"清理 Chroma 失败：{exc}")
    path = document_path(document)
    db.delete(document)
    db.commit()
    path.unlink(missing_ok=True)


@router.get("/{knowledge_base_id}/chunks")
def list_chunks(
    knowledge_base_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    document_id: int | None = None,
    db: Session = Depends(get_db),
):
    _get_kb(db, knowledge_base_id)
    statement = (
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.knowledge_base_id == knowledge_base_id)
    )
    count_statement = select(func.count(Chunk.id)).where(
        Chunk.knowledge_base_id == knowledge_base_id
    )
    if document_id is not None:
        statement = statement.where(Chunk.document_id == document_id)
        count_statement = count_statement.where(Chunk.document_id == document_id)
    if search.strip():
        condition = Chunk.content.contains(search.strip())
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    total = db.scalar(count_statement) or 0
    rows = db.execute(
        statement.order_by(Chunk.document_id, Chunk.position)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for chunk, filename in rows:
        try:
            metadata = json.loads(chunk.source_metadata or "{}")
        except json.JSONDecodeError:
            metadata = {}
        items.append(
            ChunkOut(
                id=chunk.id,
                knowledge_base_id=chunk.knowledge_base_id,
                document_id=chunk.document_id,
                document_name=filename,
                position=chunk.position,
                content=chunk.content,
                metadata=metadata,
                point_id=chunk.point_id,
            )
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{knowledge_base_id}/retrieve", response_model=RetrievalResponse)
def test_retrieval(
    knowledge_base_id: int,
    payload: RetrievalRequest,
    db: Session = Depends(get_db),
):
    knowledge_base = _get_kb(db, knowledge_base_id)
    try:
        results = retrieve(
            knowledge_base,
            payload.query,
            embedding_api_key=payload.embedding_api_key,
            chroma_api_key=payload.chroma_api_key,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"query": payload.query, "results": results}


@router.post("/{knowledge_base_id}/embedding/test")
def test_embedding(
    knowledge_base_id: int,
    embedding_api_key: str = Form(default=""),
    embedding_model: str = Form(default=""),
    embedding_base_url: str = Form(default=""),
    embedding_dimension: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    knowledge_base = _get_kb(db, knowledge_base_id)
    model = (embedding_model or "").strip() or knowledge_base.embedding_model
    base_url = (embedding_base_url or "").strip() or knowledge_base.embedding_base_url
    dimension = embedding_dimension or knowledge_base.embedding_dimension
    try:
        vector = embed_texts(
            ["连接测试"],
            base_url=base_url,
            api_key=embedding_api_key,
            model=model,
            dimension=dimension,
            batch_size=1,
        )[0]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "dimension": len(vector)}
