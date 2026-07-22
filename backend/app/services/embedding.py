"""OpenAI-compatible embedding client."""
from __future__ import annotations

from typing import Any

import httpx


def embedding_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("缺少 Embedding Base URL")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def embed_texts(
    texts: list[str],
    *,
    base_url: str,
    api_key: str,
    model: str,
    dimension: int | None = None,
    batch_size: int = 100,
    timeout: float = 60.0,
) -> list[list[float]]:
    if not texts:
        return []
    headers = {"Content-Type": "application/json"}
    # Local OpenAI-compatible servers (Xinference etc.) often ignore auth; cloud needs a real key.
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    vectors: list[list[float]] = []
    with httpx.Client(timeout=timeout) as client:
        for start in range(0, len(texts), max(1, batch_size)):
            payload: dict[str, Any] = {
                "model": model,
                "input": texts[start : start + max(1, batch_size)],
            }
            if dimension:
                payload["dimensions"] = dimension
            response = client.post(embedding_url(base_url), headers=headers, json=payload)
            data = _safe_json(response)
            if response.status_code >= 400:
                raise RuntimeError(_error_message(data, response.status_code, response.text))
            items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
            batch_vectors = [item.get("embedding") for item in items]
            if len(batch_vectors) != len(payload["input"]) or any(not vector for vector in batch_vectors):
                raise RuntimeError("Embedding 返回数量或格式异常")
            vectors.extend(batch_vectors)
    return vectors


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _error_message(data: dict[str, Any], status: int, raw: str) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("msg") or str(error)
    else:
        detail = error or data.get("message") or raw[:300] or "请求失败"
    return f"Embedding HTTP {status}: {detail}"
