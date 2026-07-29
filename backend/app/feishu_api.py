"""Feishu group chat bot webhook."""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

try:
    from .database import SessionLocal
    from .deps_auth import require_usable_user
    from .gateway.errors import GatewayError
    from .gateway.service import chat_text as gateway_chat_text
    from .models import User
    from .services.feishu_bot import (
        default_llm_config,
        extract_text_from_message,
        feishu_enabled,
        get_verification_token,
        maybe_decrypt_payload,
        remember_event,
        reply_text,
        should_handle_group_message,
    )
except ImportError:
    from database import SessionLocal
    from deps_auth import require_usable_user
    from gateway.errors import GatewayError
    from gateway.service import chat_text as gateway_chat_text
    from models import User
    from services.feishu_bot import (
        default_llm_config,
        extract_text_from_message,
        feishu_enabled,
        get_verification_token,
        maybe_decrypt_payload,
        remember_event,
        reply_text,
        should_handle_group_message,
    )

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feishu", tags=["feishu"])


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env")
    except Exception:
        pass


_load_dotenv()


async def _answer_and_reply(message_id: str, user_text: str) -> None:
    cfg = default_llm_config()
    gateway_model = (os.getenv("FEISHU_GATEWAY_MODEL") or "default").strip() or "default"
    if not cfg["api_key"] and not gateway_model:
        await reply_text(
            message_id,
            "飞书机器人尚未配置模型：请在服务器 .env 中设置 FEISHU_LLM_* 或在 Gateway 配置 default 路由。",
        )
        return
    db = SessionLocal()
    try:
        if cfg["api_key"] and cfg["model"]:
            answer = await gateway_chat_text(
                db,
                provider=cfg["provider"],
                model=cfg["model"],
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                message=user_text,
                history=None,
                system_context="",
                source="feishu",
                is_admin=True,
            )
        else:
            # Resolve via Gateway logical model / route (server-hosted keys)
            try:
                from .gateway.service import chat_completion
            except ImportError:
                from gateway.service import chat_completion

            result = await chat_completion(
                db,
                model=gateway_model,
                messages=[{"role": "user", "content": user_text}],
                source="feishu",
                is_admin=True,
            )
            answer = result.text
    except GatewayError as exc:
        logger.exception("feishu gateway failed")
        answer = f"调用模型失败：{exc.message}"
    except Exception as exc:
        logger.exception("feishu llm failed")
        answer = f"调用模型失败：{exc}"
    finally:
        db.close()
    try:
        await reply_text(message_id, answer)
    except Exception:
        logger.exception("feishu reply failed")


@router.get("/status")
async def feishu_status(user: User = Depends(require_usable_user)):
    cfg = default_llm_config()
    return {
        "enabled": feishu_enabled(),
        "verification_token_set": bool(get_verification_token()),
        "llm_model_set": bool(cfg["model"] and cfg["api_key"]),
        "gateway_model": (os.getenv("FEISHU_GATEWAY_MODEL") or "default").strip(),
        "webhook": "/api/feishu/webhook",
    }


@router.post("/webhook")
async def feishu_webhook(request: Request, background: BackgroundTasks):
    if not feishu_enabled():
        return JSONResponse({"error": "Feishu bot not configured"}, status_code=503)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    try:
        payload = maybe_decrypt_payload(body)
    except Exception as exc:
        logger.warning("feishu decrypt failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=400)

    # URL verification challenge
    if payload.get("type") == "url_verification" or payload.get("challenge"):
        token = get_verification_token()
        if token and payload.get("token") and payload.get("token") != token:
            return JSONResponse({"error": "invalid verification token"}, status_code=403)
        return {"challenge": payload.get("challenge")}

    # Optional token check for event callbacks
    header = payload.get("header") or {}
    token = get_verification_token()
    event_token = header.get("token") or payload.get("token")
    if token and event_token and event_token != token:
        return JSONResponse({"error": "invalid token"}, status_code=403)

    event_id = str(header.get("event_id") or payload.get("uuid") or "")
    if not remember_event(event_id):
        return {"ok": True, "duplicated": True}

    event_type = header.get("event_type") or payload.get("type") or ""
    event = payload.get("event") or {}

    # v2 message receive
    if event_type == "im.message.receive_v1" or (
        isinstance(event.get("message"), dict) and "message_id" in (event.get("message") or {})
    ):
        message = event.get("message") or {}
        if not should_handle_group_message(message, event):
            return {"ok": True, "skipped": True}

        msg_type = (message.get("message_type") or "").strip()
        if msg_type and msg_type not in ("text", "post"):
            return {"ok": True, "skipped": "unsupported_message_type"}

        text = extract_text_from_message(message)
        message_id = message.get("message_id") or ""
        if not text or not message_id:
            return {"ok": True, "skipped": "empty"}

        background.add_task(_answer_and_reply, message_id, text)
        return {"ok": True}

    return {"ok": True, "ignored_event": event_type}
