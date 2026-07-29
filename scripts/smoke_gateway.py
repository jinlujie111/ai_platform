#!/usr/bin/env python3
"""AI Gateway smoke tests (GW-1 ~ GW-5).

前置：后端已启动，例如
  cd backend && uvicorn app.main:app --reload --port 8000

用法（仓库根目录）：
  python scripts/smoke_gateway.py
  python scripts/smoke_gateway.py --base-url http://127.0.0.1:8000
  python scripts/smoke_gateway.py --live-chat   # 需已配置厂商 Key，会真实打上游
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _ok(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {name}{suffix}")
    if not cond:
        raise AssertionError(name)


def _soft(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "SKIP"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {name}{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Gateway smoke tests")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--live-chat",
        action="store_true",
        help="Call real upstream via model=cheap (needs seeded provider API key)",
    )
    parser.add_argument("--admin-user", default="")
    parser.add_argument("--admin-pass", default="")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    suffix = uuid.uuid4().hex[:8]

    print(f"Target: {base}\n")
    with httpx.Client(base_url=base, timeout=60.0) as client:
        # --- health ---
        r = client.get("/health")
        _ok("GET /health", r.status_code == 200, str(r.status_code))

        # --- anon gateway 401 ---
        r = client.post(
            "/api/gateway/v1/chat/completions",
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        _ok("anon chat/completions → 401", r.status_code == 401, str(r.status_code))

        r = client.get("/api/gateway/v1/usage")
        _ok("anon usage → 401", r.status_code == 401, str(r.status_code))

        # --- login / register ---
        token = None
        is_admin = False
        if args.admin_user and args.admin_pass:
            r = client.post(
                "/api/auth/login",
                json={"username": args.admin_user, "password": args.admin_pass},
            )
            _ok("admin login", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
            token = r.json().get("token")
            is_admin = True
        else:
            username = f"gw_{suffix}"
            password = "TestPass!234"
            r = client.post(
                "/api/auth/register",
                json={"username": username, "password": password, "display_name": "GW Tester"},
            )
            if r.status_code in (200, 201):
                token = r.json().get("token")
                _ok("register tester", True, username)
            else:
                # fallback login admin from env defaults
                r = client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admin123"},
                )
                _ok(
                    "fallback admin login",
                    r.status_code == 200,
                    f"{r.status_code} {r.text[:160]}",
                )
                token = r.json().get("token")
                is_admin = True
                # may require password change
                me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
                if me.status_code == 200 and me.json().get("must_change_password"):
                    print(
                        "[SKIP] admin must_change_password=1 — "
                        "请先改密，或用 --admin-user/--admin-pass 传入可用账号"
                    )
                    return 0

        headers = {"Authorization": f"Bearer {token}"}

        # --- list logical models ---
        r = client.get("/api/gateway/v1/models", headers=headers)
        _ok("GET /models", r.status_code == 200, str(r.status_code))
        payload = r.json()
        _ok("models/routes seeded", bool(payload.get("models") or payload.get("routes")), str(payload)[:160])

        # --- usage ---
        r = client.get("/api/gateway/v1/usage?group_by=model", headers=headers)
        _ok("GET /usage", r.status_code == 200, str(r.status_code))

        # --- models/test with fake key (expect upstream error, but via gateway) ---
        r = client.post(
            "/api/gateway/v1/models/test",
            headers=headers,
            json={
                "model": "probe",
                "upstream": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "api_key": "sk-invalid-for-smoke",
                    "base_url": "https://api.deepseek.com",
                },
            },
        )
        _ok(
            "models/test via gateway (invalid key → not 401/404)",
            r.status_code in (400, 502, 504),
            f"{r.status_code} {r.text[:160]}",
        )

        # --- legacy /api/models/test also gateway ---
        r = client.post(
            "/api/models/test",
            headers=headers,
            json={
                "model": {
                    "provider": "deepseek",
                    "name": "deepseek-chat",
                    "apiKey": "sk-invalid-for-smoke",
                    "baseUrl": "https://api.deepseek.com",
                    "displayName": "smoke",
                }
            },
        )
        _ok(
            "legacy /api/models/test via gateway",
            r.status_code in (400, 502, 504),
            f"{r.status_code} {r.text[:120]}",
        )

        # --- admin API key ---
        me = client.get("/api/auth/me", headers=headers)
        role = (me.json() or {}).get("role") if me.status_code == 200 else ""
        if role == "admin" or is_admin:
            r = client.post(
                "/api/gateway/v1/admin/api-keys",
                headers=headers,
                json={"name": f"smoke-{suffix}", "scopes": "chat"},
            )
            _ok("create platform API key", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
            api_key = r.json().get("api_key")
            key_id = r.json().get("id")
            _ok("api_key plaintext once", bool(api_key and str(api_key).startswith("apk_")))

            r = client.post(
                "/api/gateway/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "probe",
                    "messages": [{"role": "user", "content": "ping"}],
                    "upstream": {
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "api_key": "sk-invalid",
                        "base_url": "https://api.deepseek.com",
                    },
                    "metadata": {"source": "api_key"},
                },
            )
            _ok(
                "API Key auth reaches gateway",
                r.status_code in (400, 502, 504),
                f"{r.status_code} {r.text[:160]}",
            )

            if key_id:
                r = client.post(
                    f"/api/gateway/v1/admin/api-keys/{key_id}/revoke",
                    headers=headers,
                )
                _ok("revoke API key", r.status_code == 200, str(r.status_code))
        else:
            _soft("admin API key flow", False, "当前账号非 admin，跳过")

        # --- optional live chat ---
        if args.live_chat:
            r = client.post(
                "/api/gateway/v1/chat/completions",
                headers=headers,
                json={
                    "model": "cheap",
                    "messages": [{"role": "user", "content": "只回复：ok"}],
                    "metadata": {"source": "web_chat"},
                },
            )
            _ok(
                "live chat model=cheap",
                r.status_code == 200 and bool((r.json().get("choices") or [{}])[0]),
                f"{r.status_code} {r.text[:200]}",
            )
            r = client.get("/api/gateway/v1/usage?group_by=model", headers=headers)
            items = (r.json() or {}).get("items") or []
            _ok("usage has rows after live chat", len(items) > 0, str(items[:2]))
        else:
            _soft("live chat", False, "加 --live-chat 且配置厂商 Key 后再测真实对话")

    print("\nAll required smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError:
        print(
            "\n失败时请确认服务已启动：\n"
            "  cd backend && uvicorn app.main:app --reload --port 8000\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except httpx.ConnectError:
        print(
            f"无法连接服务。请先启动：\n"
            f"  cd backend && uvicorn app.main:app --reload --port 8000\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
