"""Feishu (Lark) group bot helpers: token, reply, event parsing."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from base64 import b64decode
from typing import Any

import httpx

FEISHU_API = "https://open.feishu.cn/open-apis"

_token_cache: dict[str, Any] = {"token": "", "expire_at": 0.0}
_seen_events: dict[str, float] = {}
_SEEN_TTL_SEC = 600


def feishu_enabled() -> bool:
    return bool(os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET"))


def get_verification_token() -> str:
    return (os.getenv("FEISHU_VERIFICATION_TOKEN") or "").strip()


def get_encrypt_key() -> str:
    return (os.getenv("FEISHU_ENCRYPT_KEY") or "").strip()


def bot_name_keywords() -> list[str]:
    raw = (os.getenv("FEISHU_BOT_MENTION_NAMES") or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


class AESCipher:
    """Feishu event encrypt/decrypt (Encrypt Key)."""

    def __init__(self, key: str):
        # Feishu: SHA256(encrypt_key) as AES key
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    def decrypt(self, encrypt: str) -> str:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
        except ImportError as exc:
            raise RuntimeError("解密飞书事件需要安装 cryptography：pip install cryptography") from exc

        raw = b64decode(encrypt)
        iv = raw[:16]
        data = raw[16:]
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        plain = decryptor.update(data) + decryptor.finalize()
        # PKCS7 unpad
        pad = plain[-1]
        if isinstance(pad, int) and 1 <= pad <= 16:
            plain = plain[:-pad]
        return plain.decode("utf-8")


def maybe_decrypt_payload(body: dict[str, Any]) -> dict[str, Any]:
    encrypt = body.get("encrypt")
    if not encrypt:
        return body
    key = get_encrypt_key()
    if not key:
        raise ValueError("收到加密事件，但未配置 FEISHU_ENCRYPT_KEY")
    plain = AESCipher(key).decrypt(str(encrypt))
    return json.loads(plain)


def remember_event(event_id: str) -> bool:
    """Return True if this is a new event; False if duplicate."""
    now = time.time()
    expired = [k for k, ts in _seen_events.items() if now - ts > _SEEN_TTL_SEC]
    for k in expired:
        _seen_events.pop(k, None)
    if not event_id:
        return True
    if event_id in _seen_events:
        return False
    _seen_events[event_id] = now
    return True


async def get_tenant_access_token() -> str:
    app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (os.getenv("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise ValueError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")

    now = time.time()
    if _token_cache["token"] and _token_cache["expire_at"] > now + 60:
        return str(_token_cache["token"])

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = res.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    token = data.get("tenant_access_token") or ""
    expire = int(data.get("expire") or 7200)
    _token_cache["token"] = token
    _token_cache["expire_at"] = now + expire
    return token


def extract_text_from_message(message: dict[str, Any]) -> str:
    msg_type = (message.get("message_type") or message.get("msg_type") or "").strip()
    content_raw = message.get("content") or ""
    if isinstance(content_raw, dict):
        content = content_raw
    else:
        try:
            content = json.loads(content_raw) if content_raw else {}
        except Exception:
            content = {"text": str(content_raw)}

    if msg_type == "text" or "text" in content:
        text = str(content.get("text") or "").strip()
    elif msg_type == "post":
        # simplified: flatten post content
        text = _flatten_post(content)
    else:
        text = str(content.get("text") or "").strip()

    # strip @_user_1 style mentions
    text = re.sub(r"@_user_\d+", " ", text)
    text = re.sub(r"@\S+", " ", text)
    for name in bot_name_keywords():
        text = text.replace(f"@{name}", " ")
    return re.sub(r"\s+", " ", text).strip()


def _flatten_post(content: dict[str, Any]) -> str:
    parts: list[str] = []
    for lang_block in content.values():
        if not isinstance(lang_block, dict):
            continue
        for line in lang_block.get("content") or []:
            if not isinstance(line, list):
                continue
            for node in line:
                if isinstance(node, dict) and node.get("tag") == "text":
                    parts.append(str(node.get("text") or ""))
    return "".join(parts).strip()


def should_handle_group_message(message: dict[str, Any], event: dict[str, Any]) -> bool:
    chat_type = (message.get("chat_type") or "").strip()
    allow_p2p = (os.getenv("FEISHU_ALLOW_P2P") or "true").lower() in ("1", "true", "yes")
    if chat_type == "group":
        return True
    if chat_type in ("p2p", "private") and allow_p2p:
        return True
    return False


async def reply_text(message_id: str, text: str) -> dict[str, Any]:
    token = await get_tenant_access_token()
    # Feishu message length limit ~4k for text cards; truncate safely
    body_text = (text or "").strip() or "（模型未返回内容）"
    if len(body_text) > 3500:
        body_text = body_text[:3490] + "\n…(已截断)"

    payload = {
        "content": json.dumps({"text": body_text}, ensure_ascii=False),
        "msg_type": "text",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{FEISHU_API}/im/v1/messages/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        data = res.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书回复失败: {data}")
    return data


def default_llm_config() -> dict[str, str]:
    """Server-side model for Feishu (models in browser localStorage are not available here)."""
    return {
        "provider": (os.getenv("FEISHU_LLM_PROVIDER") or "openai").strip(),
        "model": (os.getenv("FEISHU_LLM_MODEL") or "").strip(),
        "api_key": (os.getenv("FEISHU_LLM_API_KEY") or "").strip(),
        "base_url": (os.getenv("FEISHU_LLM_BASE_URL") or "").strip(),
    }
