# AI Gateway API 契约（冻结草案）

> 对应 `docs/AI_GATEWAY_TASK_BREAKDOWN.md` GW-0.1  
> 前缀：`/api/gateway/v1`

## 鉴权

`Authorization: Bearer <user_jwt | platform_api_key>`

- 用户 JWT：与平台登录相同
- 平台 API Key：`apk_` 前缀明文，服务端只存 hash

## Chat

`POST /api/gateway/v1/chat/completions`

```json
{
  "model": "default",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.7,
  "stream": false,
  "tools": null,
  "tool_choice": null,
  "upstream": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "...",
    "base_url": "https://api.deepseek.com"
  },
  "metadata": {"source": "web_chat", "conversation_id": "..."}
}
```

- `model`：逻辑模型 id 或路由策略名（`default` / `cheap` / `quality`）
- `upstream`：兼容期可选；存在时优先用于探测/旧前端直传配置

响应兼容 OpenAI chat.completions，并附加：

```json
{
  "id": "...",
  "choices": [...],
  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "estimated": false},
  "gateway": {
    "model_id": "deepseek-chat",
    "provider": "deepseek",
    "upstream_model": "deepseek-chat",
    "latency_ms": 320,
    "request_id": "...",
    "cost_cny": 0.0001
  }
}
```

## Test

`POST /api/gateway/v1/models/test`

```json
{
  "model": "deepseek-chat",
  "upstream": { "provider": "deepseek", "model": "deepseek-chat", "api_key": "...", "base_url": "..." }
}
```

## Usage

`GET /api/gateway/v1/usage?from=2026-07-01&to=2026-07-28&group_by=model`

管理员可看全站；普通用户仅本人。

## 管理端（需 admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/gateway/v1/admin/providers` | 厂商 |
| PATCH/DELETE | `/api/gateway/v1/admin/providers/{id}` | |
| GET/POST | `/api/gateway/v1/admin/models` | 逻辑模型 |
| PATCH/DELETE | `/api/gateway/v1/admin/models/{id}` | |
| GET/POST | `/api/gateway/v1/admin/routes` | 路由策略 |
| GET/POST | `/api/gateway/v1/admin/api-keys` | 平台 API Key |
| POST | `/api/gateway/v1/admin/api-keys/{id}/revoke` | 停用 |

## 错误码

| code | HTTP | 含义 |
|------|------|------|
| `unauthorized` | 401 | 未鉴权 |
| `rate_limited` | 429 | 限流 |
| `model_not_found` | 404 | 逻辑模型/路由不存在 |
| `upstream_auth` | 502 | 上游鉴权失败 |
| `upstream_timeout` | 504 | 上游超时 |
| `upstream_error` | 502 | 上游其它错误 |
