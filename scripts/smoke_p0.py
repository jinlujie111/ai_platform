#!/usr/bin/env python3
"""P0 foundation smoke tests.

Usage (from repo root):
  python scripts/smoke_p0.py
  python scripts/smoke_p0.py --base-url http://127.0.0.1:8000
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


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 smoke tests")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    suffix = uuid.uuid4().hex[:8]
    user_a = f"测A_{suffix}"
    user_b = f"测B_{suffix}"
    password = "TestPass!234"

    print(f"Target: {base}\n")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        # --- P0-4 health ---
        r = client.get("/health")
        _ok("GET /health", r.status_code == 200 and r.json().get("status") == "ok")
        _ok("X-Request-Id present", bool(r.headers.get("x-request-id")))

        r = client.get("/ready")
        _ok("GET /ready", r.status_code == 200 and r.json().get("status") == "ready")

        # --- P0-1 anonymous 401 ---
        for path, method in (
            ("/api/knowledge-bases", "GET"),
            ("/api/datasources", "GET"),
            ("/api/pipelines", "GET"),
            ("/api/chat", "POST"),
        ):
            if method == "GET":
                r = client.get(path)
            else:
                r = client.post(path, json={"message": "hi"})
            _ok(f"anon {method} {path} → 401", r.status_code == 401, str(r.status_code))

        # --- register two users ---
        r = client.post(
            "/api/auth/register",
            json={"username": user_a, "password": password, "display_name": "User A"},
        )
        _ok("register user A", r.status_code in (200, 201), f"{r.status_code} {r.text[:120]}")
        token_a = r.json()["token"]
        h_a = {"Authorization": f"Bearer {token_a}"}

        r = client.post(
            "/api/auth/register",
            json={"username": user_b, "password": password, "display_name": "User B"},
        )
        _ok("register user B", r.status_code in (200, 201), f"{r.status_code} {r.text[:120]}")
        token_b = r.json()["token"]
        h_b = {"Authorization": f"Bearer {token_b}"}

        # --- P0-2 isolation ---
        kb_name = f"kb-p0-{suffix}"
        r = client.post(
            "/api/knowledge-bases",
            headers=h_a,
            json={"name": kb_name, "description": "p0 smoke"},
        )
        _ok("user A create KB", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
        kb_id = r.json()["id"]

        r = client.get("/api/knowledge-bases", headers=h_b)
        ids = [item["id"] for item in r.json()]
        _ok("user B cannot list A's KB", kb_id not in ids)

        r = client.get(f"/api/knowledge-bases/{kb_id}", headers=h_b)
        _ok("user B get A's KB → 404", r.status_code == 404, str(r.status_code))

        r = client.get(f"/api/knowledge-bases/{kb_id}", headers=h_a)
        _ok("user A get own KB → 200", r.status_code == 200)

        # --- P0-3 encrypt password ---
        ds_name = f"ds-p0-{suffix}"
        r = client.post(
            "/api/datasources",
            headers=h_a,
            json={
                "name": ds_name,
                "type": "mysql",
                "host": "127.0.0.1",
                "port": "3306",
                "database": "ai_platform",
                "username": "root",
                "password": "plain-secret-should-encrypt",
            },
        )
        _ok("user A create DS", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
        ds = r.json()
        ds_id = ds["id"]
        _ok("DS response has no password field", "password" not in ds)
        _ok("DS has_password flag", bool(ds.get("has_password")))

        # DB-side check via API list still no plaintext
        r = client.get("/api/datasources", headers=h_a)
        row = next((x for x in r.json() if x["id"] == ds_id), None)
        _ok("list DS has no password", row is not None and "password" not in row)

        # --- P0-5 admin force-change gate (read-only unless still on default) ---
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if r.status_code == 200:
            admin = r.json().get("user") or {}
            token_admin = r.json()["token"]
            h_admin = {"Authorization": f"Bearer {token_admin}"}
            if admin.get("must_change_password"):
                r = client.get("/api/knowledge-bases", headers=h_admin)
                _ok("admin blocked before change-password", r.status_code == 403, str(r.status_code))
                r = client.get("/api/auth/me", headers=h_admin)
                _ok("admin can still call /me", r.status_code == 200)
                print(
                    "[INFO] admin still on default password — complete force-change in UI, "
                    "or POST /api/auth/change-password"
                )
            else:
                r = client.get("/api/knowledge-bases", headers=h_admin)
                _ok("admin after password change can list KB", r.status_code == 200)
        else:
            print("[INFO] admin/admin123 login failed; skip admin force-change checks")

        # cleanup
        client.delete(f"/api/knowledge-bases/{kb_id}", headers=h_a)
        client.delete(f"/api/datasources/{ds_id}", headers=h_a)

    print("\nAll P0 smoke checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError:
        print("\nP0 smoke FAILED.", file=sys.stderr)
        raise SystemExit(1)
    except httpx.ConnectError:
        print(
            "Cannot connect. Start backend first, e.g.\n"
            "  cd backend && uvicorn app.main:app --reload --port 8000",
            file=sys.stderr,
        )
        raise SystemExit(2)
