"""In-process rate limiting (single worker; Redis later)."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from .errors import GatewayError

_lock = threading.Lock()
# key -> deque of timestamps (seconds)
_rpm_buckets: dict[str, deque[float]] = defaultdict(deque)
# key -> tokens used today (date_str, count)
_day_tokens: dict[str, tuple[str, int]] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def rpm_limit_user() -> int:
    return _env_int("GATEWAY_RPM", 30)


def rpm_limit_api_key() -> int:
    return _env_int("GATEWAY_API_KEY_RPM", 60)


def daily_token_limit_user() -> int:
    return _env_int("GATEWAY_DAILY_TOKENS", 500_000)


def _prune(bucket: deque[float], now: float, window: float = 60.0) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def check_rate_limit(
    *,
    user_id: int | None,
    api_key_id: int | None,
    is_admin: bool = False,
) -> None:
    if is_admin:
        return
    now = time.time()
    checks: list[tuple[str, int]] = []
    if api_key_id:
        checks.append((f"key:{api_key_id}", rpm_limit_api_key()))
    elif user_id:
        checks.append((f"user:{user_id}", rpm_limit_user()))

    with _lock:
        for key, limit in checks:
            if limit <= 0:
                continue
            bucket = _rpm_buckets[key]
            _prune(bucket, now)
            if len(bucket) >= limit:
                retry = max(1, int(60 - (now - bucket[0])))
                raise GatewayError(
                    "rate_limited",
                    f"请求过于频繁，请 {retry} 秒后重试",
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
            bucket.append(now)


def check_daily_tokens(*, user_id: int | None, is_admin: bool = False) -> None:
    if is_admin or not user_id:
        return
    limit = daily_token_limit_user()
    if limit <= 0:
        return
    day = time.strftime("%Y-%m-%d", time.gmtime())
    key = f"user:{user_id}"
    with _lock:
        cur_day, used = _day_tokens.get(key, (day, 0))
        if cur_day != day:
            used = 0
            cur_day = day
        if used >= limit:
            raise GatewayError(
                "rate_limited",
                "今日 Token 额度已用尽",
                status_code=429,
                headers={"Retry-After": "3600"},
            )
        _day_tokens[key] = (cur_day, used)


def record_daily_tokens(*, user_id: int | None, tokens: int) -> None:
    if not user_id or tokens <= 0:
        return
    day = time.strftime("%Y-%m-%d", time.gmtime())
    key = f"user:{user_id}"
    with _lock:
        cur_day, used = _day_tokens.get(key, (day, 0))
        if cur_day != day:
            used = 0
            cur_day = day
        _day_tokens[key] = (cur_day, used + int(tokens))
