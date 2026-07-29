"""Adapter base types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False


@dataclass
class UpstreamRef:
    provider_type: str  # openai_compatible | anthropic | google
    provider_name: str
    base_url: str
    api_key: str
    model: str
    price_prompt_per_1k: float = 0.0
    price_completion_per_1k: float = 0.0
    logical_model_id: str = ""


@dataclass
class ChatResult:
    text: str
    raw: dict[str, Any]
    usage: UsageInfo
    provider: str
    upstream_model: str
    logical_model_id: str
    latency_ms: int
    cost_cny: float = 0.0
    status: str = "ok"
    error_code: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate when upstream omits usage."""
    if not text:
        return 0
    # ~4 chars/token for mixed CN/EN
    return max(1, (len(text) + 3) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    parts: list[str] = []
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                else:
                    parts.append(str(part))
        else:
            parts.append(str(content or ""))
    return estimate_tokens_from_text("\n".join(parts))


def parse_usage(raw: dict[str, Any], *, messages: list[dict[str, Any]], reply: str) -> UsageInfo:
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        if total > 0 or prompt > 0 or completion > 0:
            return UsageInfo(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total or (prompt + completion),
                estimated=False,
            )
    prompt = estimate_messages_tokens(messages)
    completion = estimate_tokens_from_text(reply)
    return UsageInfo(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        estimated=True,
    )


def calc_cost_cny(usage: UsageInfo, upstream: UpstreamRef) -> float:
    cost = (
        usage.prompt_tokens / 1000.0 * float(upstream.price_prompt_per_1k or 0)
        + usage.completion_tokens / 1000.0 * float(upstream.price_completion_per_1k or 0)
    )
    return round(cost, 8)
