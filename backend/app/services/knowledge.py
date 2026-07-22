"""Knowledge-base indexing and retrieval orchestration."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from ..database import SessionLocal, UPLOAD_DIR
from ..models import Chunk, Document, KnowledgeBase
from .embedding import embed_texts
from .parsers import parse_document, split_text
from .vector_store import (
    create_client,
    delete_document_points,
    ensure_collection,
    search_points,
    upsert_points,
)


def document_path(document: Document) -> Path:
    return UPLOAD_DIR / document.stored_name


def index_document(
    document_id: int,
    embedding_api_key: str,
    chroma_api_key: str = "",
) -> None:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if not document:
            return
        document.status = "processing"
        document.error = ""
        db.commit()
        db.refresh(document)
        knowledge_base = db.get(KnowledgeBase, document.knowledge_base_id)
        if not knowledge_base:
            raise RuntimeError("知识库不存在")

        parsed = parse_document(document_path(document))
        prepared: list[tuple[str, dict[str, Any]]] = []
        for text, metadata in parsed:
            for value in split_text(
                text,
                mode=knowledge_base.chunk_mode,
                chunk_size=knowledge_base.chunk_size,
                overlap=knowledge_base.chunk_overlap,
                min_chars=knowledge_base.min_chunk_chars,
            ):
                prepared.append((value, metadata))
        if not prepared:
            raise ValueError("文档未解析出可索引文本")

        vectors = embed_texts(
            [text for text, _ in prepared],
            base_url=knowledge_base.embedding_base_url,
            api_key=embedding_api_key,
            model=knowledge_base.embedding_model,
            dimension=knowledge_base.embedding_dimension,
            batch_size=knowledge_base.embedding_batch_size,
        )
        client = create_client(knowledge_base.chroma_path, chroma_api_key)
        ensure_collection(client, knowledge_base.chroma_collection, len(vectors[0]))
        delete_document_points(
            client, knowledge_base.chroma_collection, knowledge_base.id, document.id
        )

        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        db.flush()
        chunks: list[Chunk] = []
        for position, (text, metadata) in enumerate(prepared):
            chunk = Chunk(
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                position=position,
                content=text,
                source_metadata=json.dumps(metadata, ensure_ascii=False),
                point_id=str(uuid.uuid4()),
            )
            db.add(chunk)
            chunks.append(chunk)
        db.flush()

        points = []
        for chunk, vector, (_, metadata) in zip(chunks, vectors, prepared):
            payload = {
                "knowledge_base_id": knowledge_base.id,
                "document_id": document.id,
                "document_name": document.filename,
                "chunk_id": chunk.id,
                "position": chunk.position,
                "content": chunk.content,
                **metadata,
            }
            points.append((chunk.point_id, vector, payload))
        upsert_points(client, knowledge_base.chroma_collection, points)
        document.chunk_count = len(chunks)
        document.status = "completed"
        document.error = ""
        db.commit()
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        if document:
            document.status = "failed"
            document.error = str(exc)[:2000]
            db.commit()
    finally:
        db.close()


def retrieve(
    knowledge_base: KnowledgeBase,
    query: str,
    *,
    embedding_api_key: str,
    chroma_api_key: str = "",
    top_k: int | None = None,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    vector = embed_texts(
        [query],
        base_url=knowledge_base.embedding_base_url,
        api_key=embedding_api_key,
        model=knowledge_base.embedding_model,
        dimension=knowledge_base.embedding_dimension,
        batch_size=1,
    )[0]
    client = create_client(knowledge_base.chroma_path, chroma_api_key)
    hits = search_points(
        client,
        knowledge_base.chroma_collection,
        vector,
        knowledge_base.id,
        limit=top_k or knowledge_base.top_k,
        score_threshold=(
            knowledge_base.score_threshold if score_threshold is None else score_threshold
        ),
    )
    results = []
    for hit in hits:
        payload = hit["payload"]
        results.append(
            {
                "knowledge_base_id": knowledge_base.id,
                "knowledge_base_name": knowledge_base.name,
                "document": payload.get("document_name", "未知文档"),
                "document_id": int(payload.get("document_id", 0)),
                "chunk_id": int(payload.get("chunk_id", 0)),
                "point_id": hit["id"],
                "page": payload.get("page"),
                "sheet": payload.get("sheet"),
                "score": hit["score"],
                "content": payload.get("content", ""),
            }
        )
    return results


def build_rag_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    blocks = []
    for index, item in enumerate(results, start=1):
        location = f"第 {item['page']} 页" if item.get("page") else item.get("sheet") or ""
        kb_name = item.get("knowledge_base_name") or ""
        source_title = f"文档：{item['document']}"
        if kb_name:
            source_title = f"知识库：{kb_name} · {source_title}"
        blocks.append(
            f"[来源 {index}] {source_title}"
            + (f"（{location}）" if location else "")
            + f"\n{item['content']}"
        )
    return "\n\n".join(blocks)
