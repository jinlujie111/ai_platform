"""Third-party LLM client for configured models."""
from __future__ import annotations

from typing import Any, Optional

import httpx

SYSTEM_PROMPT = """
你是“AI平台”的数据智能助手。平台主要服务于企业数据接入、数据处理、
数据衍生、数据查询与分析场景。你的目标是帮助用户准确、安全、可追溯地
完成从原始数据到业务结论的全过程。

## 核心能力

1. 数据接入
   - 协助接入 MySQL、PostgreSQL、Oracle、SQL Server、ClickHouse、
     MongoDB、Hive、Spark、Kafka、HTTP API、CSV、Excel 等数据源。
   - 根据数据源类型说明连接参数、网络要求、认证方式、字段类型映射、
     增量同步策略和连通性检查步骤。
   - 接入前确认数据源、库表、主键、时间字段、更新频率和目标存储。
   - 不得编造连接成功、表结构、数据量或执行结果；没有真实工具返回时，
     必须明确说明当前提供的是配置建议或待执行方案。

2. 数据处理
   - 支持清洗、去重、过滤、关联、聚合、拆分、合并、格式转换、
     缺失值处理、异常值识别、标准化和 ETL/ELT 流程设计。
   - 生成 SQL、Python 或处理方案前，先确认数据库方言、输入表、
     输出表、字段定义、数据粒度和处理范围。
   - 输出处理逻辑时说明输入、步骤、输出、质量校验和失败处理方式，
     保证流程可复现、可验证、可审计。

3. 数据衍生
   - 协助设计派生字段、指标、标签、维度、宽表、主题模型和统计口径。
   - 每个衍生指标应说明业务含义、计算公式、数据来源、统计粒度、
     时间窗口、过滤条件、空值规则和去重规则。
   - 识别口径冲突、重复计算、未来数据泄漏、时间穿越和维度错配风险。
   - 未获得用户确认时，不擅自修改关键业务口径。

4. 数据查询与分析
   - 将自然语言需求转换为清晰的查询条件、执行计划或 SQL。
   - 生成 SQL 前确认表结构和字段含义；信息不足时先提出最少且必要的问题。
   - 默认只生成只读查询。除非用户明确授权，不执行或建议直接执行
     DROP、TRUNCATE、DELETE、UPDATE、ALTER 等高风险操作。
   - 查询大表时优先添加时间范围、分区条件和合理的 LIMIT，并说明性能风险。
   - 分析结果时区分“数据事实、计算结果、合理推断和建议”，不得把推断写成事实。

## 数据提示词与工作规则

- 首先识别用户意图属于：数据接入、数据处理、数据衍生、数据查询、
  数据分析、故障排查或平台配置。
- 优先使用用户提供的数据库类型、表结构、字段说明、样例数据和业务口径。
- 缺少必要信息时，不猜测真实表名、字段名或数据值；列出缺失项并向用户确认。
- 若必须给出示例，明确标注“示例”或“假设”，并让示例易于替换。
- SQL 必须匹配目标数据库方言；未知方言时先询问，或明确说明采用的默认方言。
- 对查询和处理方案给出必要的数据质量校验，例如行数、唯一性、完整性、
  合法值范围、关联命中率和聚合前后核对。
- 涉及身份证号、手机号、银行卡、邮箱、地址、密钥等敏感数据时，
  默认建议脱敏、最小权限和审计，不在回答中回显完整密钥或隐私数据。
- 只有在获得真实工具/API 返回后，才能声称“已查询、已执行、已连接或已写入”；
  否则应使用“建议、可执行方案、待验证”等表述。
- 知识库文档 ≠ 数据库实时数据。文档可用于理解表结构、字段和业务口径；
  当已配置数据源且问题需要真实配置值、条数、金额、名单或现状时，
  必须先调用 SQL 工具；禁止把文档说明或推断写成“查询结果/实际情况”。
- 当用户需求可能造成数据丢失、重复写入、全表扫描、口径错误或权限风险时，
  必须先提示风险并提供更安全的替代方案。

## 回答规范

- 默认使用简洁、专业的中文。
- 简单问题直接回答；复杂任务优先按“结论/方案、关键步骤、代码或 SQL、
  校验方法、风险与假设”组织内容。
- SQL、Python、配置和公式使用代码块；关键业务口径使用清单说明。
- 不虚构数据、来源、工具调用或执行结果。
- 若问题超出当前信息范围，明确说明限制，并告诉用户下一步需要提供什么。
""".strip()


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _openai_chat_url(base_url: str) -> str:
    base = _normalize_base_url(base_url)
    if not base:
        raise ValueError("缺少官方连接 (Base URL)")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


async def call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    system_context: str = "",
    timeout: float = 60.0,
) -> str:
    system_prompt = SYSTEM_PROMPT
    if system_context:
        system_prompt += (
            "\n\n## 知识库上下文\n"
            "仅依据下列检索内容回答与知识库相关的事实；信息不足时明确说明。"
            "引用事实时使用 [来源 N] 标记，不要编造来源。\n\n"
            + system_context
        )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    data = await call_openai_compatible_messages(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        timeout=timeout,
    )
    return _extract_openai_text(data)


async def call_openai_compatible_messages(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    temperature: float = 0.7,
    timeout: float = 90.0,
) -> dict[str, Any]:
    url = _openai_chat_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        return data if isinstance(data, dict) else {"raw": data}

async def call_anthropic(
    *,
    base_url: str,
    api_key: str,
    model: str,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    system_context: str = "",
    timeout: float = 60.0,
) -> str:
    base = _normalize_base_url(base_url) or "https://api.anthropic.com"
    url = f"{base}/v1/messages" if not base.endswith("/messages") else base
    messages: list[dict[str, str]] = []
    if history:
        for item in history:
            role = item.get("role")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": item.get("content", "")})
    messages.append({"role": "user", "content": message})

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT + (
            "\n\n## 知识库上下文\n仅依据以下内容回答并使用 [来源 N] 标记：\n"
            + system_context
            if system_context
            else ""
        ),
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        content = data.get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            raise RuntimeError("Anthropic 返回为空")
        return text


async def call_google(
    *,
    base_url: str,
    api_key: str,
    model: str,
    message: str,
    system_context: str = "",
    timeout: float = 60.0,
) -> str:
    base = _normalize_base_url(base_url) or "https://generativelanguage.googleapis.com/v1beta"
    # Accept either .../v1beta or full generateContent URL
    if "generateContent" in base:
        url = f"{base}?key={api_key}" if "key=" not in base else base
    else:
        url = f"{base}/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "systemInstruction": {
            "parts": [
                {
                    "text": SYSTEM_PROMPT
                    + (
                        "\n\n## 知识库上下文\n仅依据以下内容回答并使用 [来源 N] 标记：\n"
                        + system_context
                        if system_context
                        else ""
                    )
                }
            ]
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Google Gemini 返回为空")
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        if not text:
            raise RuntimeError("Google Gemini 返回为空")
        return text


async def call_llm(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    system_context: str = "",
) -> str:
    if not api_key:
        raise ValueError("当前模型未配置 API Key")
    if not model:
        raise ValueError("当前模型未配置模型名称")

    provider = (provider or "custom").lower().strip()

    if provider == "anthropic":
        return await call_anthropic(
            base_url=base_url,
            api_key=api_key,
            model=model,
            message=message,
            history=history,
            system_context=system_context,
        )
    if provider == "google":
        return await call_google(
            base_url=base_url,
            api_key=api_key,
            model=model,
            message=message,
            system_context=system_context,
        )

    # OpenAI-compatible: openai / deepseek / qwen / moonshot / minimax / zhipu / spark / baidu / custom
    return await call_openai_compatible(
        base_url=base_url,
        api_key=api_key,
        model=model,
        message=message,
        history=history,
        system_context=system_context,
    )


async def test_llm_connection(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> str:
    """Lightweight connectivity check."""
    return await call_llm(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        message="请只回复：连接成功",
        history=None,
    )


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _extract_error(data: Any, status: int, raw: str) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg") or str(err)
            return f"HTTP {status}: {msg}"
        if isinstance(err, str):
            return f"HTTP {status}: {err}"
        if data.get("message"):
            return f"HTTP {status}: {data.get('message')}"
    text = (raw or "").strip()
    return f"HTTP {status}: {text[:300] or '请求失败'}"


def _extract_openai_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("模型返回格式异常")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("模型未返回内容")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        # Some providers return content parts
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        ).strip()
        if text:
            return text
    if isinstance(content, str) and content.strip():
        return content.strip()
    # fallback older format
    text = choice.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise RuntimeError("模型返回内容为空")
