# P0 地基加固 — 任务拆解

> 对应总计划：`docs/AI_PLATFORM_BUILD_PLAN.md` 阶段 0  
> 更新日期：2026-07-27  
> 预估周期：2–3 周（单人主开发）  
> 目标：在做 AI Gateway 之前，先补齐鉴权、隔离、密钥、可观测与健康检查，避免能力建在「裸奔沙箱」上

---

## 1. 目标与边界

### 1.1 目标一句话

**无 Token 调不通业务 API；用户之间数据不串；密钥不以明文落库/回包/打日志；请求可追踪；服务可探活。**

### 1.2 现状（审计摘要）

| 项 | 现状 |
|----|------|
| 鉴权 | 仅 `auth`（部分）+ `workspace` + 流水线 approve/reject；**chat / KB / DS / 多数 pipeline 开放** |
| 归属 | KB / DS / Pipeline **无** `owner_id`；全局共享 |
| 密钥 | 数据源密码、模型 Key、KB 凭证等多处 **明文**（用户登录密码已 bcrypt） |
| 追踪 | **无** `request_id` / `trace_id` 中间件 |
| 健康检查 | **无** `/health`、`/ready` |
| 默认管理员 | `admin` / `admin123` 可种子创建，**无强制改密** |

### 1.3 本期不做

| 不做 | 归期 |
|------|------|
| AI Gateway 路由/限流/计费 | P1 |
| MCP 工具中心 | P2 |
| 多 Agent 编排 | P3 |
| Prompt 评测平台 | P4 |
| 完整多租户 SaaS（组织/账单） | 后续；P0 只做 **按用户归属** |
| 等保测评 / KMS 云密钥 | 后续；P0 用本地主密钥加密即可 |

---

## 2. 里程碑总览

| 里程碑 | 名称 | 建议周次 | 验收一句话 |
|--------|------|----------|------------|
| **P0-0** | 设计冻结 | D1–D2 | 鉴权矩阵 + 归属模型评审通过 |
| **P0-1** | 业务 API 全面鉴权 | W1 | 无 Token → 401 |
| **P0-2** | 资源归属与隔离 | W1–W2 | 用户 A 看不到用户 B 的 KB/DS/流水线 |
| **P0-3** | 密钥加密存储 | W2 | DB 中无明文密码/Key |
| **P0-4** | 请求追踪 + 健康检查 | W2 | 有 `X-Request-Id`；`/health` `/ready` 可用 |
| **P0-5** | 管理员强制改密 + 收口 | W3 | 默认口令无法继续裸用；回归通过 |

---

## 3. 鉴权矩阵（冻结用）

| 接口域 | 匿名 | 登录用户 | 管理员 | 备注 |
|--------|------|----------|--------|------|
| `POST /api/auth/login` | ✅ | — | — | |
| `POST /api/auth/register` | ✅* | — | — | `*ALLOW_PUBLIC_REGISTER` |
| `GET /api/auth/register-status` | ✅ | — | — | |
| `GET /api/auth/me` | ❌ | ✅ | ✅ | |
| `POST /api/auth/logout` | ❌ | ✅ | ✅ | |
| `/api/auth/users*` | ❌ | ❌ | ✅ | |
| `/api/workspace*` | ❌ | ✅（仅本人） | ✅（仅本人） | 已具备 |
| `POST /api/chat` | ❌ | ✅ | ✅ | **P0 必改** |
| `POST /api/models/test` | ❌ | ✅ | ✅ | **P0 必改** |
| `POST /api/mcp/test` | ❌ | ✅ | ✅ | **P0 必改** |
| `/api/knowledge-bases*` | ❌ | ✅（本人资源） | ✅ | **P0 必改** |
| `/api/datasources*` | ❌ | ✅（本人资源） | ✅ | **P0 必改** |
| `/api/pipelines*` CRUD/run | ❌ | ✅（本人资源） | ✅ | **P0 必改** |
| `/api/pipelines/*/approve|reject` | ❌ | ❌ | ✅ | 已具备 |
| `/api/feishu/webhook` | ✅** | — | — | `**` 飞书签名/Token 校验，不走用户登录 |
| `GET /api/feishu/status` | ❌ | ✅ | ✅ | 建议收紧 |
| `GET /health` | ✅ | — | — | 新建 |
| `GET /ready` | ✅ | — | — | 新建，可检查 DB |

---

## 4. 任务拆解

### P0-0 设计冻结（1–2 人天）

| ID | 任务 | 产出 | 优先级 |
|----|------|------|--------|
| P0-0.1 | 确认鉴权矩阵（上文） | 本文档评审勾选 | P0 |
| P0-0.2 | 确认归属模型 | `owner_id` 策略：创建者所有；管理员可见全部（可选） | P0 |
| P0-0.3 | 确认密钥方案 | 主密钥 `SECRETS_MASTER_KEY` + Fernet/AES；轮换策略 | P0 |
| P0-0.4 | 列改造文件清单 | 见第 7 节 | P0 |
| P0-0.5 | 定回归用例 | Postman/脚本：匿名 401、跨用户 403/404 | P0 |

**归属策略建议（P0 采用）：**

- 每条业务资源增加 `owner_id`（FK → `users.id`）
- 普通用户：只能 CRUD **自己的** 资源  
- 管理员：可读写全部（便于运维）；审批仍仅管理员  
- 历史数据：迁移时挂到种子管理员 `admin`

---

### P0-1 业务 API 全面鉴权（3–5 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| P0-1.1 | 统一依赖注入 | 业务路由默认 `Depends(get_current_user)` | P0 |
| P0-1.2 | 改造 `main.py` | `/api/chat`、`/api/models/test`、`/api/mcp/test` 鉴权 | P0 |
| P0-1.3 | 改造 `knowledge_api.py` | 全部路由加登录依赖 | P0 |
| P0-1.4 | 改造 `datasource_api.py` | 全部路由加登录依赖 | P0 |
| P0-1.5 | 改造 `pipeline_api.py` | CRUD/run/logs 加登录；保留 approve/reject 管理员 | P0 |
| P0-1.6 | 收紧 `feishu` status | `GET /api/feishu/status` 需登录 | P1 |
| P0-1.7 | 前端 `apiFetch` 回归 | 401 已跳登录；补齐遗漏的裸 `fetch` | P0 |
| P0-1.8 | 错误体统一 | `401`/`403` detail 中文可读 | P1 |

**验收：**

- [x] 不带 Token 调 `/api/chat`、`/api/knowledge-bases`、`/api/datasources`、`/api/pipelines` → **401**  
- [x] 带普通用户 Token 可调本人业务接口  
- [x] 飞书 webhook 仍可匿名（有校验）  

---

### P0-2 资源归属与隔离（4–6 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| P0-2.1 | 模型加字段 | `KnowledgeBase` / `DataSource` / `Pipeline` 增加 `owner_id` | P0 |
| P0-2.2 | DB 迁移 | MySQL：`ALTER TABLE` + 回填 `owner_id=admin`；兼容 SQLite | P0 |
| P0-2.3 | 创建时写入 owner | create 接口自动 `owner_id=current_user.id` | P0 |
| P0-2.4 | 列表过滤 | list 默认 `owner_id=me`；管理员可 `?all=1` | P0 |
| P0-2.5 | 单资源鉴权 | get/update/delete/run：非主人且非管理员 → **404**（防枚举）或 403 | P0 |
| P0-2.6 | 文档/片段/运行记录 | 跟随父资源（KB/Pipeline）做权限校验 | P0 |
| P0-2.7 | Chat 选用校验 | 聊天请求中的 KB ID / DS ID 必须属于当前用户（或已分享，P0 不做分享） | P0 |
| P0-2.8 | 前端提示 | 空列表文案区分「无数据」与「无权限」 | P2 |

**表变更草案：**

```sql
ALTER TABLE knowledge_bases ADD COLUMN owner_id INT NULL;
ALTER TABLE data_sources    ADD COLUMN owner_id INT NULL;
ALTER TABLE pipelines       ADD COLUMN owner_id INT NULL;
-- 回填后：
-- UPDATE ... SET owner_id = (SELECT id FROM users WHERE username='admin' LIMIT 1);
-- 再改为 NOT NULL + 索引 + FK（按库能力）
```

**验收：**

- [x] 用户 A 创建的 KB，用户 B list 不可见、get 返回 404/403  
- [x] 用户 B 无法用 A 的 `knowledge_base_id` 检索/上传  
- [x] 管理员可管理全部资源  

---

### P0-3 密钥加密存储（4–6 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| P0-3.1 | 新增 `services/secret_box.py` | 基于 `SECRETS_MASTER_KEY` 的加密/解密 | P0 |
| P0-3.2 | `.env` 增加主密钥 | 文档说明生成方式；禁止提交真实密钥 | P0 |
| P0-3.3 | 数据源密码加密 | 写入加密；读出解密仅供连接；API **永不回明文** | P0 |
| P0-3.4 | 存量密码迁移脚本 | 识别明文 → 加密；可重复执行 | P0 |
| P0-3.5 | Workspace 敏感字段 | `configured_models[].apiKey`、`knowledge_credentials` 等加密或拆表 | P0 |
| P0-3.6 | 日志脱敏 | 禁止打印 `api_key`/`password`/`Authorization` | P0 |
| P0-3.7 | 回包检查 | schemas 确认无 password/apiKey 明文字段 | P0 |
| P0-3.8 | 单测 | 加解密往返；错误主密钥失败可控 | P1 |

**建议环境变量：**

```env
# 32 字节 urlsafe base64，例：python -c "import secrets;print(secrets.token_urlsafe(32))"
SECRETS_MASTER_KEY=
```

**Workspace 策略（二选一，推荐 A）：**

| 方案 | 做法 |
|------|------|
| **A. 字段级加密** | JSON 写入前对已知敏感 key 加密，读出解密 | 
| **B. 拆表** | `user_secrets` 表存密文，workspace 只存引用 | 更干净，工期略长 |

P0 推荐 **A**，P1 Gateway 托管密钥时再演进到 B。

**验收：**

- [x] DB 中 `data_sources.password` 不是明文可辨密码  
- [x] `GET /api/datasources` 响应无密码字段  
- [ ] 应用日志检索不到完整 API Key  
- [ ] 换错 `SECRETS_MASTER_KEY` 时启动或解密失败有明确错误  

---

### P0-4 请求追踪 + 健康检查（2–3 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| P0-4.1 | 中间件 `RequestIdMiddleware` | 读/生成 `X-Request-Id`，写入 `request.state` | P0 |
| P0-4.2 | 响应回写 Header | `X-Request-Id: ...` | P0 |
| P0-4.3 | 结构化日志 | 关键路径日志带 `request_id` / `user_id` | P0 |
| P0-4.4 | `GET /health` | 进程存活，恒 200 | P0 |
| P0-4.5 | `GET /ready` | 检查 DB `SELECT 1`；失败 503 | P0 |
| P0-4.6 | （可选）简易 `/api/meta` | 版本号、环境名，需登录 | P2 |

**验收：**

- [x] 任意业务响应含 `X-Request-Id`  
- [x] `/health` 匿名可访问  
- [ ] DB 停掉时 `/ready` 非 200  

---

### P0-5 管理员强制改密 + 收口（2–3 人天）

| ID | 任务 | 说明 | 优先级 |
|----|------|------|--------|
| P0-5.1 | `users` 增加 `must_change_password` | 种子管理员默认 `1` | P0 |
| P0-5.2 | 登录响应提示 | 返回 `must_change_password: true` | P0 |
| P0-5.3 | 改密 API | `POST /api/auth/change-password` | P0 |
| P0-5.4 | 门禁 | `must_change_password=1` 时，除改密/me/logout 外业务 403 | P0 |
| P0-5.5 | 前端改密弹窗 | 登录后强制改密再进系统 | P0 |
| P0-5.6 | 禁止弱口令 | 拒绝 `admin123` 等常见弱密码（可配置） | P1 |
| P0-5.7 | 文档更新 | README / `.env.example` 说明首次必改密 | P0 |
| P0-5.8 | 全量回归 | 按第 6 节清单打勾 | P0 |

**验收：**

- [x] 新环境种子管理员首次登录必须改密  
- [x] 未改密无法调用 `/api/chat`  
- [x] 改密后可正常使用  

---

## 5. 建议排期（单人）

| 天 | 焦点 |
|----|------|
| D1–D2 | P0-0 设计冻结 + 建迁移草稿 |
| D3–D5 | P0-1 全 API 鉴权 + 前端 401 回归 |
| D6–D9 | P0-2 owner_id 迁移 + 列表/读写隔离 + chat 校验 |
| D10–D12 | P0-3 密钥加密 + 存量迁移 + 日志脱敏 |
| D13–D14 | P0-4 request_id + health/ready |
| D15–D16 | P0-5 强制改密 + 全文回归 + 文档 |

两人并行：A 鉴权+归属，B 加密+追踪+改密，可压到 **约 8–10 个工作日**。

---

## 6. 回归清单（DoD）

### 6.1 安全

- [x] 匿名访问业务 API → 401  
- [ ] 用户跨资源访问 → 404/403  
- [ ] 管理员可审批流水线；普通用户不能  
- [ ] 响应与日志无明文密码/完整 Key  

### 6.2 功能不回归

- [x] 登录 / 注册 / 退出正常  
- [ ] 聊天（需登录）正常  
- [ ] 知识库创建/上传/检索正常（仅本人数据）  
- [ ] 数据源测试连接正常（密码加密后仍可用）  
- [ ] 流水线创建/运行/审批正常  
- [ ] Workspace 配置同步正常  

### 6.3 运维

- [x] `/health`、`/ready` 可用  
- [ ] 响应含 `X-Request-Id`  
- [ ] 种子管理员强制改密流程走通  

**全部勾选 = P0 完成，可进入 P1 AI Gateway。**

---

## 7. 涉及文件清单

| 类别 | 路径 |
|------|------|
| 鉴权 | `backend/app/deps_auth.py`、`main.py`、`knowledge_api.py`、`datasource_api.py`、`pipeline_api.py`、`feishu_api.py` |
| 模型/迁移 | `backend/app/models.py`、`backend/app/database.py`、新建 `scripts/migrate_p0_owner_secrets.py` |
| 密钥 | 新建 `backend/app/services/secret_box.py`、`datasource_api.py`、`workspace_api.py`、相关 services |
| 追踪/健康 | `main.py`、新建 `backend/app/middleware/request_id.py` |
| 改密 | `auth_api.py`、`models.py`（User）、前端登录/强制改密 UI |
| 配置文档 | `.env.example`、`README.md`、本文档 |
| 前端 | `web/src/legacy/initApp.js`（apiFetch、资源列表、改密弹窗） |

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| 加鉴权后前端大量 401 | 先统一 `apiFetch`；联调时带 Token；改完立即回归登录态 |
| 历史数据无 owner | 一律回填 admin；文档告知「旧数据归管理员」 |
| 加密后主密钥丢失 | 主密钥进 `.env`/密钥保管；备份；文档强调不可丢 |
| 加密迁移误伤明文格式 | 密文加前缀如 `enc:v1:`，迁移脚本幂等 |
| 管理员可见全部引发争议 | P0 接受；后续再做「组织/项目」级 ACL |
| 范围膨胀到 Gateway | 严格按本文；路由/计费留给 P1 |

---

## 9. 本周启动清单（立刻可做）

1. [ ] 评审并冻结鉴权矩阵与 `owner_id` 策略  
2. [ ] 给 `/api/chat`、`/api/models/test` 加上 `get_current_user`（最小收益最大）  
3. [ ] 设计 `owner_id` 迁移 SQL 并在测试库演练  
4. [ ] 生成并配置 `SECRETS_MASTER_KEY`（先不强制加密全量，先打通工具类）  
5. [ ] 实现 `/health` + `/ready`（半日可完成）  

---

## 10. 状态跟踪

- [x] P0-0 设计冻结  
- [x] P0-1 全面鉴权  
- [ ] P0-2 归属隔离  
- [x] P0-3 密钥加密  
- [ ] P0-4 追踪与健康检查  
- [ ] P0-5 强制改密与收口  

---

## 11. 与后续阶段关系

```
P0 地基 ──▶ P1 AI Gateway ──▶ P2 MCP ──▶ P3 Agent ──▶ P4 LLMOps
   │              │
   │              └─ 复用：用户鉴权、request_id、密钥箱、owner 模型
   └─ 没有 P0：Gateway 计费/限流也无法信任「调用者是谁」
```

---

*本文是 P0 的实施拆解；总路线图见 `AI_PLATFORM_BUILD_PLAN.md`；Gateway 拆解见 `AI_GATEWAY_TASK_BREAKDOWN.md`。*
