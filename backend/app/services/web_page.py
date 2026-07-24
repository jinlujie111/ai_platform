"""Fetch and extract readable text from a public web page."""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

MAX_HTML_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 20.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; AIPlatformKnowledgeBot/1.0; +https://localhost)"
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript", "svg", "iframe", "template"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name == "title":
            self._in_title = True
        if name in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript", "svg", "iframe", "template"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if name == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self._chunks.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(url: str) -> str:
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http / https 网页地址")
    host = parsed.hostname
    if not host:
        raise ValueError("网页地址无效")
    if host.lower() in {"localhost"} or host.endswith(".localhost"):
        raise ValueError("不允许抓取本地地址")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"无法解析域名：{host}") from exc
    if not infos:
        raise ValueError(f"无法解析域名：{host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _is_public_ip(ip):
            raise ValueError("不允许抓取内网或本地地址")
    return value


def html_to_text(html: str) -> tuple[str, str]:
    parser = _HTMLTextExtractor()
    parser.feed(html or "")
    parser.close()
    return parser.title.strip(), parser.get_text()


def fetch_web_page(url: str) -> dict[str, Any]:
    safe_url = validate_public_http_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers=headers,
        max_redirects=5,
    ) as client:
        response = client.get(safe_url)
        # Re-validate final URL host after redirects
        validate_public_http_url(str(response.url))
        if response.status_code >= 400:
            raise RuntimeError(f"网页请求失败（HTTP {response.status_code}）")
        content_type = (response.headers.get("content-type") or "").lower()
        if "html" not in content_type and "text/" not in content_type and content_type:
            raise RuntimeError(f"不支持的内容类型：{content_type}")
        raw = response.content
        if len(raw) > MAX_HTML_BYTES:
            raise RuntimeError("网页内容过大")
        encoding = response.encoding or "utf-8"
        try:
            html = raw.decode(encoding, errors="replace")
        except Exception:
            html = raw.decode("utf-8", errors="replace")

    page_title, text = html_to_text(html)
    if len(text) < 40:
        raise RuntimeError("未能从网页提取到有效正文，请检查链接是否可公开访问")
    return {
        "url": str(response.url),
        "title": page_title or "",
        "text": text,
        "content_type": content_type or "text/html",
    }
