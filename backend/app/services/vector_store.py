"""ChromaDB adapter with knowledge-base metadata isolation."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import chromadb

from ..database import DATA_DIR


def create_client(path_or_url: str = "", api_key: str = ""):
    value = (path_or_url or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        kwargs: dict[str, Any] = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 8000,
        }
        if api_key:
            kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        return chromadb.HttpClient(**kwargs)

    path = Path(value) if value else (DATA_DIR / "chroma")
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def ensure_collection(client, collection: str, dimension: int | None = None):
    return client.get_or_create_collection(
        name=collection,
        metadata={"hnsw:space": "cosine"},
    )


def _get_collection(client, collection: str):
    return client.get_or_create_collection(
        name=collection,
        metadata={"hnsw:space": "cosine"},
    )


def _sanitize_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "content" or value is None:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float, str)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def upsert_points(
    client,
    collection: str,
    points: list[tuple[str, list[float], dict[str, Any]]],
) -> None:
    if not points:
        return
    coll = _get_collection(client, collection)
    coll.upsert(
        ids=[point_id for point_id, _, _ in points],
        embeddings=[vector for _, vector, _ in points],
        documents=[payload.get("content", "") for _, _, payload in points],
        metadatas=[_sanitize_metadata(payload) for _, _, payload in points],
    )


def delete_document_points(
    client, collection: str, knowledge_base_id: int, document_id: int
) -> None:
    try:
        coll = client.get_collection(collection)
    except Exception:
        return
    coll.delete(
        where={
            "$and": [
                {"knowledge_base_id": int(knowledge_base_id)},
                {"document_id": int(document_id)},
            ]
        }
    )


def delete_knowledge_base_points(client, collection: str, knowledge_base_id: int) -> None:
    try:
        coll = client.get_collection(collection)
    except Exception:
        return
    coll.delete(where={"knowledge_base_id": int(knowledge_base_id)})


def search_points(
    client,
    collection: str,
    vector: list[float],
    knowledge_base_id: int,
    *,
    limit: int,
    score_threshold: float,
) -> list[dict[str, Any]]:
    try:
        coll = client.get_collection(collection)
    except Exception:
        return []

    response = coll.query(
        query_embeddings=[vector],
        n_results=max(1, limit),
        where={"knowledge_base_id": int(knowledge_base_id)},
        include=["documents", "metadatas", "distances"],
    )
    ids = (response.get("ids") or [[]])[0]
    documents = (response.get("documents") or [[]])[0]
    metadatas = (response.get("metadatas") or [[]])[0]
    distances = (response.get("distances") or [[]])[0]

    results = []
    for point_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        # cosine space distance ≈ 1 - similarity
        score = 1.0 - float(distance)
        if score < score_threshold:
            continue
        payload = dict(metadata or {})
        payload["content"] = document or payload.get("content", "")
        results.append({"id": str(point_id), "score": score, "payload": payload})
    return results
