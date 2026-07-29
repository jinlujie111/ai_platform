# AI Gateway 任务拆解

> 对应总计划：`docs/AI_PLATFORM_BUILD_PLAN.md` 阶段 P1  
> 更新日期：2026-07-27  
> 预估周期：6–8 周（单人主开发）  
> 前置依赖：建议先完成或部分完成 **P0 地基**（chat 等接口至少可鉴权）

---

## 1. 目标与边界

### 1.1 目标

把所有模型调用收口到 **AI Gateway**：

- 业务只认逻辑 `model_id`（或路由策略名）
- Gateway 负责：厂商适配、路由、认证、限流、Token/成本记账、统一错误码

### 1.2 本期不做

| 不做 | 原因 |
|------|------|
| 本地大模型推理服务 | 本机算力不足，走云端 API |
| 完整 LLMOps 评测平台 | 归 P4，本期只埋点 |
| 多租户 SaaS 计费体系 | 先做单租户/按用户记账 |
| 流式 SSE 全链路改造（可选） | 可作 M1.5 增强，不阻塞主验收 |

### 1.3 现有代码锚点

| 现有 | 改造方向 |
|------|----------|
| `backend/app/llm.py` | 拆为 adapters，由 Gateway 调用 |
| `POST /api/chat` | 改为调 Gateway，不再各自拼厂商请求 |
| `POST /api/models/test` | 改为调 Gateway `test` |
| 飞书 `FEISHU_LLM_*` | 逐步切到 Gateway 逻辑模型 |
| 前端 `configured_models`（workspace） | 升级为「逻辑模型 + 上游映射」，密钥服务端托管优先 |

---

## 2. 架构拆解

```
调用方：Web Chat / 飞书 / Agent / 开放 API Key
                │
                ▼
┌───────────────────────────────────────┐
│  Gateway API                            │
│  POST /api/gateway/v1/chat/completions  │
│  POST /api/gateway/v1/embeddings        │  (可选同期)
│  POST /api/gateway/v1/models/test       │
│  GET  /api/gateway/v1/usage             │
└──────────────────┬────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
  Auth/Key     Rate Limit    Router
     │             │             │
     └─────────────┼─────────────┘
                   ▼
            Adapter Layer
     openai | anthropic | qwen | deepseek | custom
                   │
                   ▼
            usage_ledger 落库
```

---

## 3. 里程碑总览

| 里程碑 | 名称 | 建议周次 | 验收一句话 |
|--------|------|----------|------------|
| **GW-0** | 地基与设计冻结 | W0–W1 | 表结构/API 契约评审通过 |
| **GW-1** | 适配器 + 统一出口 | W1–W2 | chat/test 全部经 Gateway |
| **GW-2** | 逻辑模型与路由 | W3–W4 | 可按策略选模型 |
| **GW-3** | 认证与限流 | W5–W6 | API Key + 429 限流生效 |
| **GW-4** | 用量与成本 | W7–W8 | 可按人/模型出日报表 |
| **GW-5** | 收口与联调 | W8 | 飞书/前端切换完成，旧直连下线 |

---

## 4. 任务拆解（可执行）

### GW-0 设计与地基（3–5 人天）

| ID | 任务 | 产出 | 优先级 |
|----|------|------|--------|
| GW-0.1 | 冻结 Gateway API 契约（OpenAPI 草案） | `docs/gateway-api.md` 或路由注释 | P0 |
| GW-0.2 | 设计 MySQL 表结构 | 迁移脚本 / SQLAlchemy models | P0 |
| GW-0.3 | 明确定价表（每 1K token 单价，可配置） | `model_pricing` 或配置 JSON | P0 |
| GW-0.4 | chat / models/test / 飞书 调用点清单 | 改造 checklist | P0 |
| GW-0.5 | （建议同步）`/api/chat` 强制登录 | 依赖 P0 | P0 |

**建议表结构：**

```text
model_providers       # 厂商：openai/anthropic/qwen/deepseek/custom
model_definitions     # 逻辑模型 model_id → 上游 model_name + provider_id
model_routes          # 路由策略：default / cheap / quality / embed
platform_api_keys     # 对外开放 Key（hash 存储）
usage_ledger          # 每次调用用量流水
rate_limit_policies   # 限额策略（可选，初期可写死配置）
```

**核心字段（usage_ledger）：**

- `user_id` / `api_key_id` / `request_id`
- `model_id` / `provider` / `upstream_model`
- `prompt_tokens` / `completion_tokens` / `total_tokens`
- `cost_cny`（或 USD）
- `latency_ms` / `status` / `error_code`
- `source`：`web_chat` | `feishu` | `agent` | `api_key` | `test`

---

### GW-1 适配器与统一出口（5–8 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| GW-1.1 | 新建 `backend/app/gateway/` 包 | `router.py` / `service.py` / `adapters/` | P0 |
| GW-1.2 | 抽取 `OpenAICompatibleAdapter` | 覆盖 OpenAI / DeepSeek / Qwen / 自定义 Base URL | P0 |
| GW-1.3 | 抽取 `AnthropicAdapter` | 从现有 `llm.py` 迁出 | P0 |
| GW-1.4 | 抽取 `GoogleAdapter`（若仍需） | 可降级为 P1 | P1 |
| GW-1.5 | 统一内部接口 | `chat(messages, model_ref, **opts) -> ChatResult` | P0 |
| GW-1.6 | 实现 `POST /api/gateway/v1/chat/completions` | 入参兼容 OpenAI 形态更佳 | P0 |
| GW-1.7 | 实现 `POST /api/gateway/v1/models/test` | 替换/代理原 `/api/models/test` | P0 |
| GW-1.8 | 改造 `/api/chat` 改为调用 Gateway service | **禁止**业务再直接 `httpx` 打厂商 | P0 |
| GW-1.9 | 统一错误码 | `upstream_timeout` / `upstream_auth` / `rate_limited` / `model_not_found` | P0 |
| GW-1.10 | 单测：各 adapter mock 响应 | pytest | P1 |

**验收：**

- [x] 前端聊天走 Gateway 后行为与现网一致  
- [x] 「测试连接」走 Gateway  
- [ ] `llm.py` 不再被 chat 直接依赖（可保留薄封装转调）

---

### GW-2 逻辑模型与路由（5–7 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| GW-2.1 | CRUD：providers / model_definitions | 管理端 API + 管理员权限 | P0 |
| GW-2.2 | 种子数据 | DeepSeek / Qwen / OpenAI / Anthropic 示例逻辑模型 | P0 |
| GW-2.3 | 路由策略 `model_routes` | `default` / `cheap` / `quality` | P0 |
| GW-2.4 | Router 实现 | 按策略解析到具体 upstream；支持 fallback 列表 | P0 |
| GW-2.5 | 前端「模型配置」升级 | 配置逻辑模型，而不仅是浏览器直填厂商 | P0 |
| GW-2.6 | 密钥托管 | provider 级 API Key 加密存 MySQL；前端可只存引用 | P0 |
| GW-2.7 | 兼容迁移 | 旧 `configured_models` workspace 数据可导入为 definitions | P1 |

**路由示例：**

| 策略 | 首选 | Fallback |
|------|------|----------|
| `cheap` | deepseek-chat | qwen-turbo |
| `quality` | gpt-4o / claude | deepseek-reasoner |
| `default` | 用户当前选用模型 | cheap |

**验收：**

- [ ] 请求只传 `model=cheap` 也能完成对话  
- [x] 上游失败可按 fallback 切换（至少日志可观测）  
- [x] 管理员可在配置中心维护逻辑模型

---

### GW-3 认证与限流（5–7 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| GW-3.1 | Gateway 强制鉴权 | 登录用户 Bearer **或** `platform_api_keys` | P0 |
| GW-3.2 | API Key 管理 | 创建/停用/轮换；只回显一次明文 | P0 |
| GW-3.3 | Key 权限范围 | 可先简单：`chat` 范围即可 | P1 |
| GW-3.4 | 限流策略 | 用户维度 + Key 维度 + 模型维度 | P0 |
| GW-3.5 | 限流存储 | 一期 MySQL/内存；二期 Redis | P0 |
| GW-3.6 | 返回 429 | 带 `Retry-After` 与剩余额度提示 | P0 |
| GW-3.7 | 前端提示 | 超限 Toast / 状态文案 | P1 |
| GW-3.8 | 配置项 | `.env`：`GATEWAY_RPM` / `GATEWAY_TPM` / 日预算 | P0 |

**建议默认限额（可改）：**

| 维度 | 默认 |
|------|------|
| 每用户 RPM | 30 |
| 每用户 日 Token | 500,000 |
| 每 API Key RPM | 60 |
| 管理员 | 可单独放宽 |

**验收：**

- [x] 无 Token/无 Key 调 Gateway → 401  
- [x] 超限 → 429，且不产生上游费用（或极少探测）  
- [x] API Key 可独立调用 chat completions

---

### GW-4 用量与成本（4–6 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| GW-4.1 | 每次调用写 `usage_ledger` | 成功/失败都记（失败 tokens 可为 0） | P0 |
| GW-4.2 | Token 解析 | 从 upstream usage 字段提取；无则估算 | P0 |
| GW-4.3 | 成本计算 | `tokens * price_per_1k` | P0 |
| GW-4.4 | `GET /api/gateway/v1/usage` | 按日/用户/模型聚合 | P0 |
| GW-4.5 | 管理端用量页 | 配置中心简单表格即可 | P0 |
| GW-4.6 | 导出 CSV（可选） | 便于对账 | P2 |
| GW-4.7 | request_id 贯穿 | 日志与 ledger 可关联 | P0 |

**验收：**

- [x] 连续 10 次对话后，ledger 有 10 条对应记录  
- [x] 可查看「今日费用 Top 模型 / Top 用户」  
- [ ] 测试连接也记账（source=`test`）

---

### GW-5 收口、联调、下线直连（3–5 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| GW-5.1 | 飞书机器人改走 Gateway | 去掉进程内直连配置的主路径 | P0 |
| GW-5.2 | Agent/`chat_agent` 调模型改走 Gateway | 为 P3 打底 | P0 |
| GW-5.3 | Embedding 是否纳入 Gateway | 建议至少预留接口；可本期做最小实现 | P1 |
| GW-5.4 | 文档与 `.env.example` | Gateway 相关配置说明 | P0 |
| GW-5.5 | 回归清单 | 聊天、测试连接、限流、用量、飞书 | P0 |
| GW-5.6 | 标记废弃 | 旧「前端直传完整厂商配置打上游」路径逐步废弃 | P1 |

---

## 5. 建议目录结构

```text
backend/app/gateway/
  __init__.py
  router.py              # FastAPI routes
  schemas.py             # 请求/响应
  service.py             # chat/test/embed 编排
  router_policy.py       # 路由策略
  rate_limit.py
  usage.py               # ledger 写入与聚合
  security.py            # api key 校验
  adapters/
    base.py
    openai_compatible.py
    anthropic.py
    google.py
```

---

## 6. API 契约草案（冻结用）

### 6.1 Chat

`POST /api/gateway/v1/chat/completions`

```json
{
  "model": "default",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.7,
  "stream": false,
  "metadata": {"source": "web_chat", "conversation_id": "..."}
}
```

鉴权：`Authorization: Bearer <user_token|platform_api_key>`

### 6.2 Test

`POST /api/gateway/v1/models/test`

```json
{
  "model": "deepseek-chat"
}
```

或兼容旧前端：传 provider 配置做一次性探测（仅管理员 / 仅测试环境）。

### 6.3 Usage

`GET /api/gateway/v1/usage?from=2026-07-01&to=2026-07-27&group_by=model`

---

## 7. 人员与排期（单人参考）

| 周 | 焦点 |
|----|------|
| W1 | GW-0 + GW-1.1～1.6 |
| W2 | GW-1.7～1.9，chat 切换 |
| W3 | GW-2 表 + CRUD + 种子 |
| W4 | Router + 前端模型页改造 |
| W5 | API Key + 鉴权 |
| W6 | 限流 |
| W7 | usage_ledger + 报表 API |
| W8 | 前端用量页 + 飞书收口 + 回归 |

两人并行时：A 做适配器/路由，B 做鉴权/限流/用量，可压到 **4–5 周**。

---

## 8. 风险与依赖

| 风险 | 应对 |
|------|------|
| 前端仍把 API Key 放在请求体 | Gateway 优先用服务端托管 Key；前端 Key 仅作兼容期 |
| 限流用内存，多 worker 不准 | 文档标明单 worker；或上 Redis |
| 厂商 usage 字段不一致 | adapter 内归一化；缺失则字符估算并标记 `estimated=true` |
| 与 P0 鉴权冲突/重复 | Gateway 鉴权复用 `deps_auth`，不要两套用户体系 |
| 范围膨胀到评测/Prompt 管理 | 坚决留给 P4，只留 `request_id` 埋点 |

---

## 9. 完成定义（DoD）

同时满足以下，视为 **AI Gateway v1 完成**：

1. **唯一出口**：Web 聊天、模型测试、飞书主路径均经 Gateway  
2. **可路由**：至少 2 套策略（default/cheap）可用  
3. **可认证**：用户登录态与平台 API Key 均可调用  
4. **可限流**：超限返回 429  
5. **可算账**：usage 可按用户、模型、日维度查询  
6. **可回归**：核心用例清单全部勾选  

---

## 10. 本周启动清单（立刻可做）

1. [x] 评审并冻结本文档的表结构与 API 契约  
2. [ ] 建 `backend/app/gateway/` 空包与 router 挂载到 `main.py`  
3. [ ] 把 `llm.py` 中 OpenAI 兼容调用抽成 `OpenAICompatibleAdapter`  
4. [ ] 让 `/api/models/test` 内部转调 Gateway service（先不改前端）  
5. [ ] 建表：`model_providers` / `model_definitions` / `usage_ledger`  

---

## 11. 状态跟踪

- [x] GW-0 设计冻结（见 docs/gateway-api.md + 表结构）  
- [x] GW-1 统一出口（chat / models/test 经 Gateway service）  
- [x] GW-2 路由（providers / definitions / routes + admin API + 种子）  
- [x] GW-3 认证限流（JWT / API Key + RPM/日 Token + 429）  
- [x] GW-4 用量成本（usage_ledger + /usage + 用量统计面板）  
- [x] GW-5 收口完成（飞书 / Agent 工具环经 Gateway；.env.example 已补）  

> 更新：2026-07-28 — 已落地 v1 主路径；流式 SSE / Redis 限流 / 完整前端逻辑模型编辑器仍可后续增强。  

---

*本文是 P1 的实施拆解；总路线图见 `AI_PLATFORM_BUILD_PLAN.md`。*
