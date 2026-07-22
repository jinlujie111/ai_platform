# 本地 AI 平台

FastAPI + 原生 Web 前端的演示平台，支持第三方聊天模型、自建知识库、多格式文档索引、ChromaDB 向量检索和带来源引用的 RAG 问答。

## 组件

- SQLite / SQLAlchemy：知识库、文档、片段和处理状态
- ChromaDB：默认本地持久化到 `data/chroma/`，共享 collection，通过 `knowledge_base_id` metadata 隔离知识库
- OpenAI-compatible `/embeddings`：文档和问题向量化
- 本地 `data/uploads/`：保存原始文件
- 支持格式：TXT、Markdown、PDF、DOCX、CSV、XLSX、PPTX

旧版 DOC、XLS、PPT 不受支持；请先转换成 DOCX、XLSX、PPTX。

## 启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn backend.app.main:app --reload --port 8000
```

访问 http://localhost:8000，API 文档位于 http://localhost:8000/docs。

ChromaDB 默认嵌入式运行，无需单独启动向量库进程。如需远程 Chroma Server，在知识库“索引配置”中填写 HTTP 地址（如 `http://localhost:8001`）。Embedding API Key 和 Chroma API Key 随请求提交，不会写入 SQLite。

本地部署 Embedding 模型时，可直接运行：

```powershell
.\start-local-embeddings.ps1
```

该脚本会安装轻量版 Xinference（**不安装 vLLM**），启动服务并拉起：

- `bge-m3`
- `bge-large-zh-v1.5`
- `gte-qwen2-1.5B-instruct`

如果之前用 `pip install "xinference[all]"` 安装失败（Windows 长路径 / vLLM 报错），请改用：

```powershell
pip install xinference sentence-transformers torch
```

Windows 如仍遇到路径过长错误，可用管理员 PowerShell 开启长路径：

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

然后重启电脑后再安装。

启动完成后，在知识库的 Embedding 配置中填写：

- Base URL：`http://127.0.0.1:9997/v1`
- 模型名称：对应上面启动的模型名
- 维度：`1024`
- API Key：本地模式可留空，或填 `test`

**注意（Windows）**：不要用 `--host 0.0.0.0`，会报 `Cluster is not available`。请用：

```powershell
$env:XINFERENCE_AUTH_ADVANCED="false"
xinference-local --host 127.0.0.1 --port 9997
```

Xinference 3.x 默认开启登录认证。本地个人使用请加上面的 `XINFERENCE_AUTH_ADVANCED=false`，否则 `xinference launch` 会报 `please login first`。

另开一个终端拉模型：

```powershell
xinference launch --endpoint http://127.0.0.1:9997 --model-name bge-m3 --model-type embedding
```

## 使用流程

1. 在“设置 → 模型配置”添加并启用聊天模型。
2. 在“设置 → 知识库”切换到“自建知识库”并新建知识库。
3. 保存切片、Embedding、Chroma 和检索配置。
4. 填写 Embedding API Key（留空时使用当前聊天模型 Key），上传文档。
5. 等待状态从“等待中/处理中”变为“已完成”；失败时查看错误并重试。
6. 在“片段”中检查解析结果，在“检索试测”中验证 Top-K 和阈值。
7. 在聊天标题栏选择知识库后提问，回答下方会显示可点击的文档、页码和相似度来源。

修改切片或 Embedding 配置不会自动重建已有向量。对失败文档执行重试，或重新上传文档以使用新配置。

## 配置与数据

- `AI_PLATFORM_DATA_DIR`：数据库和上传目录，默认 `./data`
- `DATABASE_URL`：默认 `sqlite:///./data/ai_platform.db`
- `MAX_UPLOAD_BYTES`：单文件上限，默认 50 MiB
- 默认 Chroma 路径：`./data/chroma`（知识库配置中留空即可）
- 默认共享 collection：`ai_platform_knowledge`
- 默认服务端口：`8000`

所有使用同一个 collection 的知识库必须采用相同的向量维度。切换 Embedding 维度时应使用新的 collection，或先删除并重建原 collection。

## 验证

```powershell
pytest -q
python -m compileall backend
node --check web/app.js
```

测试使用临时 SQLite 数据库和 Chroma/Embedding mock，覆盖切片、CRUD、上传格式、状态、索引幂等、结构化来源，以及不选择知识库时的聊天兼容性。

真实全链路冒烟验证：

1. 启动服务后访问 http://localhost:8000。
2. 新建知识库并上传一个 TXT 文件。
3. 状态完成后检查 `data/chroma` 目录已生成，且检索测试能返回片段。
4. 提高相似度阈值后，低分结果应被过滤。
5. 聊天选择该知识库，确认回答带 `[来源 N]`，且来源按钮可定位片段。
6. 删除文档或知识库，确认 SQLite、上传文件和对应 Chroma 向量同步清理。
