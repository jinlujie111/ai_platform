# MCP Tool Center — 任务拆解

> 对应总计划：`docs/AI_PLATFORM_BUILD_PLAN.md` 阶段 P2  
> 更新日期：2026-07-28  
> 预估周期：6–8 周（单人主开发）  
> 前置依赖：建议 **P0 鉴权已完成**；**P1 Gateway 至少 GW-1 可用**（Agent 调模型走统一出口）；本期可与 Gateway 尾段并行，但工具调用记账依赖 Gateway

---

## 1. 目标与边界

### 1.1 目标一句话

**把行情、基本面、新闻、只读 SQL、受限 Python 封装为标准 MCP 服务，经「工具注册中心」被 Agent 发现与调用；每个 Tool 响应必须带来源、时点与免责声明。**

### 1.2 现状（审计摘要）

| 项 | 现状 |
|----|------|
| MCP 客户端 | `backend/app/services/mcp_client.py`：仅 HTTP/SSE JSON-RPC（`tools/list` / `tools/call`）；**不支持 stdio** |
| 对话接入 | `chat_agent.py` 把 MCP tools 映射为 `mcp__{server}__{tool}`；`POST /api/chat` 可带 `mcpServers` |
| 连通测试 | `POST /api/mcp/test`（已鉴权） |
| 前端 | 「我的 MCP」+ 「MCP 市场」多为 **localStorage**（`user_mcp_configs` / `mcp_market_state`）；市场卡片多为静态示例 |
| 内置金融 MCP | **无**（无 `mcp-market` / `mcp-sql` 等独立进程） |
| 工具规范 | **无**统一 `source` / `as_of` / `disclaimer` |
| 缓存 / 限流 | **无** MCP 级 TTL 缓存与 QPS 限制 |
| 注册中心 | **无**服务端工具目录；靠用户粘贴 mcp.json |
| Python 沙箱 | **无** |

### 1.3 本期不做

| 不做 | 归期 |
|------|------|
| 多 Agent 编排 / Supervisor | P3 |
| Prompt 评测平台 | P4 |
| 自动下单 / 交易执行 | 明确范围外 |
| 宣称实盘交易级实时行情 | 合规外；公开源多为延时 |
| 完整 SaaS 多租户计费 | 后续；本期按用户限流即可 |
| 全量 stdio MCP 托管（任意 command） | 安全风险高；本期仅平台自托管 HTTP MCP + 可选白名单 |

### 1.4 与现有代码映射

| 现有 | 改造方向 |
|------|----------|
| `services/mcp_client.py` | 增强：超时、重试、错误归一、可选会话/initialize 握手 |
| `chat_agent.py` MCP 分支 | 优先从「注册中心」拉工具；保留外部 HTTP MCP 兼容 |
| 前端 MCP 面板 | 升级为「平台工具 + 我的外部 MCP」；市场改为服务端目录 |
| `datasource` 只读查询 | 抽为 `mcp-sql` 工具能力（复用护栏） |
| Agent `mcpServerIds` | 改为绑定 `tool_server_id` / 市场安装记录 |

---

## 2. 架构拆解

```
调用方：Web Chat / Agent /（后续飞书 Agent）
                │
                ▼
┌───────────────────────────────────────────┐
│  Chat Agent / Tool Router                   │
│  解析 mcp__* / 平台内置 tool 名               │
└──────────────────┬────────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────────┐
│  MCP Registry（工具注册中心）                 │
│  目录 · 启停 · 权限 · 健康检查 · 安装关系     │
└──────────────────┬────────────────────────┘
                   │
     ┌─────────────┼─────────────┬─────────────┐
     ▼             ▼             ▼             ▼
 mcp-market   mcp-fundamentals  mcp-news   mcp-sql
     │             │             │             │
     └─────────────┴──────┬──────┴─────────────┘
                          │
                          ▼
                    mcp-python（沙箱）
                          │
                          ▼
              缓存(TTL) · 限流 · 审计日志
```

**部署形态（建议）：**

| 形态 | 说明 |
|------|------|
| 一期 | 同机多进程 / FastAPI 子应用挂载（`/mcp/{name}/`），开发成本低 |
| 二期 | 独立容器（尤其 `mcp-python`）；Registry 用 URL 发现 |

---

## 3. 里程碑总览

| 里程碑 | 名称 | 建议周次 | 验收一句话 |
|--------|------|----------|------------|
| **MCP-0** | 设计冻结 + 规范 | W0–W1 | Tool 响应 Schema、服务清单、目录结构评审通过 |
| **MCP-1** | 注册中心 + 客户端加固 | W1–W2 | Agent 可从 Registry 拉工具并调用 |
| **MCP-2** | `mcp-market` + `mcp-sql` | W2–W4 | 对话可查某票行情 + 只读 SQL，带来源 |
| **MCP-3** | `mcp-fundamentals` + `mcp-news` | W4–W6 | 「行情 + 财报摘要 + 新闻」一次对话跑通 |
| **MCP-4** | `mcp-python` 沙箱 + 收口 | W6–W8 | 沙箱无法读宿主机敏感目录；前端市场切服务端 |

---

## 4. 任务拆解（可执行）

### MCP-0 设计冻结与规范（2–4 人天）

| ID | 任务 | 产出 | 优先级 |
|----|------|------|--------|
| MCP-0.1 | 冻结首批 Tool 清单与命名 | 见 §5 | P0 |
| MCP-0.2 | 冻结统一响应 Envelope | JSON Schema / 文档示例 | P0 |
| MCP-0.3 | 冻结错误码 | `upstream_error` / `rate_limited` / `invalid_symbol` / `timeout` / `sandbox_denied` | P0 |
| MCP-0.4 | 选定行情/资讯数据源 | AkShare 为主；东方财富公开接口备选；注明延时与版权 | P0 |
| MCP-0.5 | 代码与进程边界 | 目录结构 + 启动方式（uvicorn 多 app / 多进程） | P0 |
| MCP-0.6 | 安全边界评审 | SQL 只读、Python 禁网/禁挂载、密钥不进 Tool 回包 | P0 |
| MCP-0.7 | 与 Gateway 对接点 | Tool 调用是否记 `usage_ledger`（建议记 `source=mcp_tool` 元数据） | P1 |

**统一响应 Envelope（强制）：**

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "source": "akshare.stock_zh_a_hist",
    "as_of": "2026-07-28T15:00:00+08:00",
    "disclaimer": "延时公开数据，仅供研究，不构成投资建议",
    "symbol": "600519.SH",
    "request_id": "..."
  }
}
```

失败时：

```json
{
  "ok": false,
  "error": {
    "code": "invalid_symbol",
    "message": "无法识别的股票代码"
  },
  "meta": {
    "source": "mcp-market",
    "as_of": "2026-07-28T15:00:00+08:00",
    "disclaimer": "..."
  }
}
```

**验收：**

- [ ] Schema / 错误码 / 首批 Tool 清单评审勾选  
- [ ] 明确「不做交易执行」写入文档  

---

### MCP-1 注册中心 + 客户端加固（5–7 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| MCP-1.1 | 新建 `mcp_registry` 表模型 | 服务定义、健康状态、启停、分类标签 | P0 |
| MCP-1.2 | 用户安装关系表 | `user_mcp_installs`：用户启用了哪些平台 MCP | P0 |
| MCP-1.3 | Registry API | `GET/POST/PATCH` 目录；用户 `install/uninstall/enable` | P0 |
| MCP-1.4 | 管理员维护市场条目 | 发布 / 下线 / 改描述（替代前端假市场） | P0 |
| MCP-1.5 | 加固 `mcp_client.py` | 统一 timeout、initialize 握手、错误归一、截断超大回包 | P0 |
| MCP-1.6 | Agent 改走 Registry | `allow_mcp` 时合并：平台已装 MCP + 用户自定义 HTTP MCP | P0 |
| MCP-1.7 | 工具调用审计日志 | `mcp_tool_calls`：user、server、tool、latency、ok/error | P0 |
| MCP-1.8 | 健康检查 | Registry 定期 ping；`/ready` 可汇总关键 MCP | P1 |
| MCP-1.9 | 前端：我的 MCP 读服务端 | 配置落 MySQL（可进 workspace 或独立表），摆脱纯 localStorage | P0 |

**建议表结构：**

```text
mcp_servers          # 平台目录：name, base_url, transport, tags, status, config_json
user_mcp_installs    # user_id, server_id, enabled, installed_at
user_mcp_configs     # 用户自建外部 MCP（加密 headers/token）
mcp_tool_calls       # 调用审计流水
```

**验收：**

- [ ] 管理员可上下线一个 MCP 市场条目  
- [ ] 用户安装后，Agent 对话能 `tools/list` 到该服务工具  
- [ ] 外部 HTTP MCP 仍可配置（兼容现网）  
- [ ] 无 Token 无法调 Registry 写接口  

---

### MCP-2 `mcp-market` + `mcp-sql`（8–12 人天）

#### 2.A mcp-market

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| MCP-2.1 | 脚手架 `mcp_servers/market` | FastMCP 或自研 JSON-RPC HTTP 服务 | P0 |
| MCP-2.2 | 代码规范化 | `normalize_symbol`：`600519` / `sh600519` / `600519.SH` → 统一 | P0 |
| MCP-2.3 | Tool: `get_realtime_quote` | 单票/少票行情；短 TTL 缓存（如 30–60s） | P0 |
| MCP-2.4 | Tool: `get_kline` | 日/周/月 K；参数校验 + 限行数 | P0 |
| MCP-2.5 | Tool: `get_money_flow` | 资金流（若源可用）；否则明确 `not_supported` | P1 |
| MCP-2.6 | 限流与缓存 | 进程内 LRU/TTL；可选 Redis；防打爆上游 | P0 |
| MCP-2.7 | 单元/联调测试 | mock 上游；真实源可选 smoke | P0 |

#### 2.B mcp-sql

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| MCP-2.8 | 脚手架 `mcp_servers/sql` | 包装现有 datasource 只读能力 | P0 |
| MCP-2.9 | Tool: `list_tables` | 绑定用户可访问的 datasource_id | P0 |
| MCP-2.10 | Tool: `describe_table` | 表结构 | P0 |
| MCP-2.11 | Tool: `run_readonly_sql` | 复用禁写护栏 + auto LIMIT | P0 |
| MCP-2.12 | 权限穿透 | 仅能访问 `can_use` 的数据源；禁止跨用户 | P0 |
| MCP-2.13 | 与内置 Agent SQL 工具关系 | 二选一或薄封装互转，避免双实现漂移 | P0 |

**验收：**

- [ ] Agent 问「贵州茅台近 5 日收盘价」→ 调 market 工具 → 回答含 `source`/`as_of`  
- [ ] Agent 经 sql 工具查本人数据源成功；查他人数据源失败  
- [ ] 写入类 SQL 被拒绝  
- [ ] 上游限流/超时返回结构化错误，会话不崩  

---

### MCP-3 `mcp-fundamentals` + `mcp-news`（8–10 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| MCP-3.1 | 脚手架 `mcp_servers/fundamentals` | | P0 |
| MCP-3.2 | Tool: `get_financial_indicators` | 关键财务指标；长 TTL（如 6–24h） | P0 |
| MCP-3.3 | Tool: `list_announcements` | 公告列表（标题/日期/链接） | P0 |
| MCP-3.4 | Tool: `get_announcement_meta` | 单条元数据；正文抓取谨慎（版权） | P1 |
| MCP-3.5 | 脚手架 `mcp_servers/news` | | P0 |
| MCP-3.6 | Tool: `search_news` | 关键词/股票相关新闻检索 | P0 |
| MCP-3.7 | Tool: `summarize_news_bundle` | 可选：返回素材包供 LLM 摘要，不在工具内「编结论」 | P1 |
| MCP-3.8 | 证据字段 | 每条新闻/公告保留 url、publish_time | P0 |
| MCP-3.9 | 联调场景 | 「某票行情 + 最新财报要点 + 近一周新闻」 | P0 |
| MCP-3.10 | 免责声明统一注入 | 所有金融 Tool 默认 disclaimer | P0 |

**验收：**

- [ ] 一次对话完成「行情 + 财报摘要素材 + 新闻列表」，且可追溯来源链接/时点  
- [ ] 工具不直接输出「强烈推荐买入」类投资建议话术（prompt/disclaimer 约束）  

---

### MCP-4 `mcp-python` 沙箱 + 前端收口（6–9 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| MCP-4.1 | 沙箱方案选型 | 优先 Docker；本机无 Docker 时可用受限子进程 + 严格 seccomp/资源限制（降级需文档声明） | P0 |
| MCP-4.2 | Tool: `run_python` | 超时、内存上限、禁 `os.system`/网络（可配置） | P0 |
| MCP-4.3 | 输入输出约定 | 仅 stdout/返回值；禁止读 `/`、用户目录、`.env` | P0 |
| MCP-4.4 | 预装科学计算白名单 | 如 pandas/numpy（镜像内固定版本） | P1 |
| MCP-4.5 | 与 market/sql 协作 | 允许把 Tool 结果作为 DF 输入，而非让沙箱直连外网 | P1 |
| MCP-4.6 | 前端 MCP 市场切服务端 | 去掉静态假卡片依赖；安装走 API | P0 |
| MCP-4.7 | Agent 面板绑定 | Agent 勾选平台 MCP 服务（替代仅本地 id） | P0 |
| MCP-4.8 | 文档与 `.env.example` | MCP 启停、数据源、沙箱开关 | P0 |
| MCP-4.9 | 回归清单 + smoke 脚本 | `scripts/smoke_mcp.py` | P0 |
| MCP-4.10 | 性能护栏 | 全市场类接口默认禁止或强分页 | P0 |

**验收：**

- [ ] `run_python` 无法读取宿主机 `.env` / 业务目录  
- [ ] 超时进程被杀掉，Registry 仍健康  
- [ ] 前端市场条目来自服务端；管理员可下线  
- [ ] smoke：market + sql + fundamentals/news（至少 2 个）+ registry 通过  

---

## 5. 首批 Tool 清单（冻结草案）

### mcp-market

| Tool | 必做 | 说明 |
|------|------|------|
| `normalize_symbol` | ✅ | 也可作为内部函数，不暴露 |
| `get_realtime_quote` | ✅ | |
| `get_kline` | ✅ | |
| `get_money_flow` | 可选 | |

### mcp-sql

| Tool | 必做 |
|------|------|
| `list_tables` | ✅ |
| `describe_table` | ✅ |
| `run_readonly_sql` | ✅ |

### mcp-fundamentals

| Tool | 必做 |
|------|------|
| `get_financial_indicators` | ✅ |
| `list_announcements` | ✅ |
| `get_announcement_meta` | 可选 |

### mcp-news

| Tool | 必做 |
|------|------|
| `search_news` | ✅ |
| `summarize_news_bundle` | 可选 |

### mcp-python

| Tool | 必做 |
|------|------|
| `run_python` | ✅ |

---

## 6. 建议目录结构

```text
backend/app/mcp_center/
  __init__.py
  registry_api.py          # FastAPI：目录 / 安装 / 审计查询
  models.py                # SQLAlchemy（或并入 models.py）
  client.py                # 从现有 mcp_client 升级迁入
  audit.py
  schemas.py

backend/mcp_servers/       # 可独立进程启动
  common/
    envelope.py            # 统一响应
    cache.py
    rate_limit.py
    symbols.py
  market/
    server.py
    tools.py
  fundamentals/
    server.py
    tools.py
  news/
    server.py
    tools.py
  sql/
    server.py
    tools.py               # 复用 datasource 服务
  python_sandbox/
    server.py
    runner.py
    Dockerfile

scripts/
  smoke_mcp.py
  run_mcp_market.py        # 本地一键启动示例
```

---

## 7. API 草案（注册中心）

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| `GET` | `/api/mcp-center/servers` | 登录用户 | 平台目录（含安装状态） |
| `POST` | `/api/mcp-center/servers` | 管理员 | 发布/登记平台 MCP |
| `PATCH` | `/api/mcp-center/servers/{id}` | 管理员 | 上下线、改元数据 |
| `POST` | `/api/mcp-center/servers/{id}/install` | 登录用户 | 安装到「我的」 |
| `DELETE` | `/api/mcp-center/servers/{id}/install` | 登录用户 | 卸载 |
| `POST` | `/api/mcp-center/servers/{id}/enable` | 登录用户 | 启用/停用 |
| `GET` | `/api/mcp-center/my-configs` | 登录用户 | 自建外部 MCP |
| `PUT` | `/api/mcp-center/my-configs` | 登录用户 | 保存自建（密钥加密） |
| `POST` | `/api/mcp/test` | 登录用户 | 保留；可代理到 center |
| `GET` | `/api/mcp-center/calls` | 管理员/本人 | 调用审计（管理员看全部） |

---

## 8. 缓存与限流建议（默认值可改）

| 数据类型 | TTL | 备注 |
|----------|-----|------|
| 实时行情 | 30–60s | |
| K 线日线 | 5–15min | |
| 财务指标 | 6–24h | |
| 新闻检索 | 2–5min | |
| SQL 结果 | 默认不缓存 | 防脏读；可按查询 hash 短缓存 |

| 维度 | 默认 |
|------|------|
| 每用户 MCP 调用 RPM | 60 |
| 单 Tool 并发 | 2–4 |
| 单次回包大小 | ≤ 256KB（超出截断 + 提示） |
| `run_python` 超时 | 10–20s |
| `run_python` 内存 | ≤ 512MB（容器） |

---

## 9. 风险与合规

| 风险 | 缓解 |
|------|------|
| 数据版权 / 展示授权 | 法务确认；Tool meta 标明来源；可开关商业源 |
| 被当成投资建议 | 统一 disclaimer；系统提示禁止下单话术 |
| 公开接口限流/封禁 | 缓存 + 本机 QPS；失败降级 |
| Python 逃逸 | 默认 Docker；无容器则关闭该服务 |
| SQL 注入 / 写库 | 只读解析器 + 账号只读权限 |
| 密钥泄露 | headers/token Fernet 加密；审计日志脱敏 |

---

## 10. 人天与排期粗估

| 里程碑 | 人天（约） |
|--------|------------|
| MCP-0 | 2–4 |
| MCP-1 | 5–7 |
| MCP-2 | 8–12 |
| MCP-3 | 8–10 |
| MCP-4 | 6–9 |
| **合计** | **约 29–42 人天（6–8 周）** |

并行建议：MCP-2.A（market）与 MCP-2.B（sql）可两人并行；Registry（MCP-1）应先于或紧贴首个业务 MCP。

---

## 11. 回归与 Smoke（收口清单）

- [ ] Registry：管理员发布 → 用户安装 → Agent 可见工具  
- [ ] `get_realtime_quote` + `get_kline` 正常且含 meta  
- [ ] `run_readonly_sql` 拒写、拒跨用户  
- [ ] fundamentals + news 联调场景  
- [ ] python 沙箱读 `.env` 失败  
- [ ] 上游超时不拖死 chat  
- [ ] 前端市场无静态假数据依赖  
- [ ] 审计表有对应调用记录  

---

## 12. 文档维护

| 项 | 说明 |
|----|------|
| 本文档 | `docs/MCP_TOOL_CENTER_TASK_BREAKDOWN.md` |
| 总计划 | `docs/AI_PLATFORM_BUILD_PLAN.md` §6 |
| 更新频率 | 每里程碑验收后勾选并改日期 |
| 关联 | `.env.example`、`scripts/smoke_mcp.py`（落地后） |

### 状态栏

- [ ] MCP-0 设计冻结  
- [ ] MCP-1 注册中心可用  
- [ ] MCP-2 market + sql 可用  
- [ ] MCP-3 fundamentals + news 可用  
- [ ] MCP-4 python 沙箱 + 前端收口  

---

*本拆解基于现有 `mcp_client` + 前端 MCP 面板能力，目标演进为可运营的金融 MCP Tool Center；默认「云端模型 + 本机编排 MCP」。*
