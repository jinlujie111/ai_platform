from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
from contextlib import asynccontextmanager
import os
import shutil
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

try:
    from .llm import call_llm, test_llm_connection
    from .database import engine, get_db, init_db
    from .knowledge_api import router as knowledge_router
    from .datasource_api import router as datasource_router
    from .pipeline_api import router as pipeline_router
    from .models import DataSource, KnowledgeBase, User
    from .services.knowledge import build_rag_context, retrieve
    from .services.chat_agent import KnowledgeToolRef, McpToolRef, run_tool_chat
    from .services.scheduler import start_scheduler, stop_scheduler
    from .access_control import RESOURCE_DS, RESOURCE_KB, can_use_resource
    from .deps_auth import require_usable_user
    from .middleware.request_id import RequestIdMiddleware
    from .gateway.errors import GatewayError
    from .gateway.schemas import UpstreamConfig
    from .gateway.service import chat_text as gateway_chat_text
except ImportError:
    from llm import call_llm, test_llm_connection
    from database import engine, get_db, init_db
    from knowledge_api import router as knowledge_router
    from datasource_api import router as datasource_router
    from pipeline_api import router as pipeline_router
    from models import DataSource, KnowledgeBase, User
    from services.knowledge import build_rag_context, retrieve
    from services.chat_agent import KnowledgeToolRef, McpToolRef, run_tool_chat
    from services.scheduler import start_scheduler, stop_scheduler
    from access_control import RESOURCE_DS, RESOURCE_KB, can_use_resource
    from deps_auth import require_usable_user
    from middleware.request_id import RequestIdMiddleware
    from gateway.errors import GatewayError
    from gateway.schemas import UpstreamConfig
    from gateway.service import chat_text as gateway_chat_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    await stop_scheduler()


app = FastAPI(title='AI Platform Demo', lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
init_db()
app.include_router(knowledge_router)
app.include_router(datasource_router)
app.include_router(pipeline_router)
try:
    from .auth_api import router as auth_router
except ImportError:
    from auth_api import router as auth_router
app.include_router(auth_router)
try:
    from .workspace_api import router as workspace_router
except ImportError:
    from workspace_api import router as workspace_router
app.include_router(workspace_router)
try:
    from .feishu_api import router as feishu_router
except ImportError:
    from feishu_api import router as feishu_router
app.include_router(feishu_router)
try:
    from .authz_api import router as authz_router
except ImportError:
    from authz_api import router as authz_router
app.include_router(authz_router)
try:
    from .gateway.router import router as gateway_router
except ImportError:
    from gateway.router import router as gateway_router
app.include_router(gateway_router)
try:
    from .mcp import tushare_mcp_router
except ImportError:
    from mcp import tushare_mcp_router
app.include_router(tushare_mcp_router)

# Frontend static files (source + Vite dist under the same /static mount)
_web_root = os.path.join(os.path.dirname(__file__), '..', '..', 'web')
if not os.path.isdir(_web_root):
    _web_root = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'web')
_web_dist = os.path.join(_web_root, 'dist')
app.mount('/static', StaticFiles(directory=_web_root), name='static')


def _can_use_kb(db: Session, user: User, resource) -> bool:
    return can_use_resource(db, user, resource, resource_type=RESOURCE_KB)


def _can_use_ds(db: Session, user: User, resource) -> bool:
    return can_use_resource(db, user, resource, resource_type=RESOURCE_DS)


def build_skill_context(skills: List[Any]) -> str:
    """Assemble enabled skill prompts into a system-context block."""
    blocks: list[str] = []
    for item in skills or []:
        if isinstance(item, dict):
            name = str(item.get('name') or '').strip()
            description = str(item.get('description') or '').strip()
            prompt = str(item.get('prompt') or '').strip()
        else:
            name = str(getattr(item, 'name', '') or '').strip()
            description = str(getattr(item, 'description', '') or '').strip()
            prompt = str(getattr(item, 'prompt', '') or '').strip()
        if not prompt and not description:
            continue
        title = name or '未命名 Skill'
        parts = [f'### {title}']
        if description:
            parts.append(f'说明：{description}')
        if prompt:
            parts.append(prompt)
        blocks.append('\n'.join(parts))
    if not blocks:
        return ''
    return (
        '## 已启用 Skill\n'
        '请优先遵循下列 Skill 的角色、步骤与输出要求；与用户问题冲突时以用户当前请求为准。\n\n'
        + '\n\n'.join(blocks)
    )


@app.get('/')
async def index():
    candidates = [
        os.path.join(_web_dist, 'index.html'),
        os.path.join(_web_root, 'index.html'),
    ]
    for fp in candidates:
        if os.path.exists(fp):
            return FileResponse(fp, media_type='text/html')
    return JSONResponse({'error': 'index not found'}, status_code=404)


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/ready')
async def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return {'status': 'ready'}
    except Exception as exc:
        return JSONResponse(
            {'status': 'not_ready', 'error': str(exc) or 'database unavailable'},
            status_code=503,
        )


class ModelConfig(BaseModel):
    provider: str = Field(..., description='厂商标识，如 openai / anthropic / google / gateway')
    providerName: Optional[str] = None
    name: str = Field(..., description='模型名或 Gateway 逻辑模型/路由名')
    displayName: Optional[str] = None
    apiKey: str = ''
    baseUrl: str = ''
    # True: 使用管理员配置的平台逻辑模型/路由，无需用户自带 Key
    useGateway: bool = False


class ChatMessage(BaseModel):
    role: str
    content: str


class KnowledgeBaseChatRef(BaseModel):
    id: int
    embeddingApiKey: str = ''
    chromaApiKey: str = ''


class ChatMcpServer(BaseModel):
    name: str
    config: Dict[str, Any]


class ChatToolConfig(BaseModel):
    enabled: bool = True
    maxRounds: int = Field(default=6, ge=1, le=10)
    enabledTools: Optional[List[str]] = None
    allowMcp: bool = False
    allowPipeline: bool = False


class ChatSkill(BaseModel):
    id: Optional[str] = None
    name: str = ''
    description: str = ''
    prompt: str = ''


class ChatReq(BaseModel):
    message: str
    model: Optional[ModelConfig] = None
    history: Optional[List[ChatMessage]] = None
    knowledgeBaseId: Optional[int] = None
    knowledgeBaseIds: Optional[List[int]] = None
    knowledgeBases: Optional[List[KnowledgeBaseChatRef]] = None
    dataSourceIds: Optional[List[int]] = None
    mcpServers: Optional[List[ChatMcpServer]] = None
    toolConfig: Optional[ChatToolConfig] = None
    skills: Optional[List[ChatSkill]] = None
    embeddingApiKey: str = ''
    chromaApiKey: str = ''
    topK: Optional[int] = Field(default=None, ge=1, le=50)
    scoreThreshold: Optional[float] = Field(default=None, ge=0, le=1)


class TestModelReq(BaseModel):
    model: ModelConfig


class TestMcpReq(BaseModel):
    name: str
    config: Dict[str, Any]


@app.post('/api/chat')
async def chat(
    req: ChatReq,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    text = (req.message or '').strip()
    if not text:
        return JSONResponse({'error': '消息不能为空'}, status_code=400)

    if not req.model:
        return JSONResponse(
            {
                'error': '未指定模型',
                'answer': '请先在「配置中心 → 模型配置」中添加模型，并点击「设为当前」。',
                'sources': [],
            },
            status_code=400,
        )

    cfg = req.model
    use_gateway = bool(getattr(cfg, "useGateway", False)) or (cfg.provider or "").lower() == "gateway"
    if not use_gateway and not cfg.apiKey:
        return JSONResponse(
            {
                'error': '缺少 API Key',
                'answer': f'当前模型「{cfg.displayName or cfg.name}」未配置 API Key，请先在配置中心填写；或改用管理员配置的平台模型。',
                'sources': [],
            },
            status_code=400,
        )
    if not use_gateway and not cfg.baseUrl and cfg.provider not in ('anthropic', 'google'):
        return JSONResponse(
            {
                'error': '缺少 Base URL',
                'answer': f'当前模型「{cfg.displayName or cfg.name}」未配置官方连接，请先在配置中心填写。',
                'sources': [],
            },
            status_code=400,
        )

    history = None
    if req.history:
        history = [
            {'role': m.role, 'content': m.content}
            for m in req.history
            if m.role in ('user', 'assistant') and m.content
        ][-12:]

    sources = []
    system_context = ''
    kb_refs: list[KnowledgeBaseChatRef] = []
    if req.knowledgeBases:
        kb_refs = list(req.knowledgeBases)
    else:
        ids: list[int] = []
        if req.knowledgeBaseIds:
            ids.extend(int(item) for item in req.knowledgeBaseIds if item is not None)
        elif req.knowledgeBaseId is not None:
            ids.append(int(req.knowledgeBaseId))
        # de-dupe while preserving order
        seen = set()
        for kb_id in ids:
            if kb_id in seen:
                continue
            seen.add(kb_id)
            kb_refs.append(
                KnowledgeBaseChatRef(
                    id=kb_id,
                    embeddingApiKey=req.embeddingApiKey,
                    chromaApiKey=req.chromaApiKey,
                )
            )

    if kb_refs:
        merged: list[dict] = []
        missing = []
        try:
            for ref in kb_refs:
                knowledge_base = db.get(KnowledgeBase, ref.id)
                if not _can_use_kb(db, user, knowledge_base):
                    missing.append(str(ref.id))
                    continue
                hits = retrieve(
                    knowledge_base,
                    text,
                    embedding_api_key=ref.embeddingApiKey or req.embeddingApiKey,
                    chroma_api_key=ref.chromaApiKey or req.chromaApiKey,
                    top_k=req.topK,
                    score_threshold=req.scoreThreshold,
                )
                for hit in hits:
                    hit["knowledge_base_name"] = knowledge_base.name
                    merged.append(hit)
        except Exception as e:
            msg = str(e) or '知识库检索失败'
            return JSONResponse(
                {'error': msg, 'answer': f'知识库检索失败：{msg}', 'sources': []},
                status_code=502,
            )
        if missing and not merged and len(missing) == len(kb_refs):
            return JSONResponse(
                {'error': '知识库不存在', 'answer': '选择的知识库不存在或已删除。', 'sources': []},
                status_code=404,
            )
        merged.sort(key=lambda item: float(item.get('score') or 0), reverse=True)
        per_kb = req.topK or 5
        limit = min(20, max(per_kb, per_kb * len(kb_refs)))
        sources = merged[:limit]
        system_context = build_rag_context(sources)

    datasource_ids: list[int] = []
    if req.dataSourceIds:
        seen_ds = set()
        for item in req.dataSourceIds:
            if item is None:
                continue
            ds_id = int(item)
            if ds_id in seen_ds:
                continue
            seen_ds.add(ds_id)
            datasource_ids.append(ds_id)
    datasources = []
    if datasource_ids:
        for ds_id in datasource_ids:
            ds = db.get(DataSource, ds_id)
            if _can_use_ds(db, user, ds):
                datasources.append(ds)
        if not datasources:
            return JSONResponse(
                {'error': '数据源不存在', 'answer': '选择的数据源不存在或已删除。', 'sources': sources},
                status_code=404,
            )

    skill_context = build_skill_context(req.skills or [])
    if skill_context:
        system_context = (skill_context + ("\n\n" + system_context if system_context else "")).strip()

    request_id = getattr(request.state, 'request_id', '') or ''
    is_admin = (user.role or '').strip().lower() == 'admin'
    try:
        tool_traces: list = []
        tool_cfg = req.toolConfig
        tools_enabled = True if tool_cfg is None else bool(tool_cfg.enabled)
        allow_pipeline = bool(tool_cfg.allowPipeline) if tool_cfg else False
        allow_mcp = bool(tool_cfg.allowMcp) if tool_cfg else False
        enabled_tools = tool_cfg.enabledTools if tool_cfg else None
        max_rounds = tool_cfg.maxRounds if tool_cfg else 6

        knowledge_tool_refs = [
            KnowledgeToolRef(
                id=int(ref.id),
                embedding_api_key=ref.embeddingApiKey or req.embeddingApiKey or '',
                chroma_api_key=ref.chromaApiKey or req.chromaApiKey or '',
            )
            for ref in kb_refs
        ]
        mcp_refs: list[McpToolRef] = []
        if allow_mcp and req.mcpServers:
            for item in req.mcpServers:
                name = (item.name or '').strip()
                if not name or not isinstance(item.config, dict):
                    continue
                mcp_refs.append(McpToolRef(name=name, config=item.config))

        want_sql = bool(datasources)
        want_kb_tool = bool(knowledge_tool_refs)
        want_pipeline = allow_pipeline
        want_mcp = allow_mcp and bool(mcp_refs)
        use_tool_loop = tools_enabled and (want_sql or want_kb_tool or want_pipeline or want_mcp)

        if use_tool_loop:
            answer, tool_traces = await run_tool_chat(
                provider=cfg.provider,
                model=cfg.name,
                api_key=cfg.apiKey,
                base_url=cfg.baseUrl,
                message=text,
                history=history,
                system_context=system_context,
                datasources=datasources,
                enabled_tools=enabled_tools,
                max_rounds=max_rounds,
                db=db,
                knowledge_refs=knowledge_tool_refs,
                mcp_servers=mcp_refs,
                allow_pipeline=allow_pipeline,
                allow_mcp=allow_mcp,
                user_id=user.id,
                request_id=request_id,
                is_admin=is_admin,
                use_gateway=use_gateway,
            )
        else:
            answer = await gateway_chat_text(
                db,
                provider=cfg.provider,
                model=cfg.name,
                api_key=cfg.apiKey,
                base_url=cfg.baseUrl,
                message=text,
                history=history,
                system_context=system_context,
                user_id=user.id,
                source='web_chat',
                request_id=request_id,
                is_admin=is_admin,
                use_gateway=use_gateway,
            )
        label = cfg.displayName or cfg.name
        return {
            'answer': answer,
            'sources': sources,
            'toolTraces': tool_traces,
            'model': label,
            'provider': cfg.providerName or cfg.provider,
        }
    except GatewayError as e:
        return JSONResponse(
            {
                'error': e.message,
                'answer': f'调用大模型失败：{e.message}',
                'sources': [],
                'toolTraces': [],
                'code': e.code,
            },
            status_code=e.status_code,
            headers=e.headers or None,
        )
    except Exception as e:
        msg = str(e) or '调用大模型失败'
        return JSONResponse(
            {
                'error': msg,
                'answer': f'调用大模型失败：{msg}',
                'sources': [],
                'toolTraces': [],
            },
            status_code=502,
        )


@app.post('/api/models/test')
async def test_model(
    req: TestModelReq,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_usable_user),
):
    cfg = req.model
    use_gateway = bool(getattr(cfg, "useGateway", False)) or (cfg.provider or "").lower() == "gateway"
    if not use_gateway and not cfg.apiKey:
        return JSONResponse({'ok': False, 'message': '请先填写 API Key'}, status_code=400)
    if not cfg.name:
        return JSONResponse({'ok': False, 'message': '请填写模型名称'}, status_code=400)
    try:
        from .gateway.service import test_model_connection
    except ImportError:
        from gateway.service import test_model_connection
    try:
        result = await test_model_connection(
            db,
            model=cfg.name,
            upstream=None if use_gateway else UpstreamConfig(
                provider=cfg.provider,
                model=cfg.name,
                api_key=cfg.apiKey,
                base_url=cfg.baseUrl,
            ),
            user_id=user.id,
            is_admin=(user.role or '').strip().lower() == 'admin',
            request_id=getattr(request.state, 'request_id', '') or '',
        )
        return {'ok': True, 'message': '连接成功', 'reply': (result.text or '')[:200]}
    except GatewayError as e:
        return JSONResponse(
            {'ok': False, 'message': e.message, 'code': e.code},
            status_code=e.status_code,
            headers=e.headers or None,
        )
    except Exception as e:
        return JSONResponse({'ok': False, 'message': str(e) or '连接失败'}, status_code=502)


def _resolve_mcp_server(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    servers = config.get('mcpServers')
    if isinstance(servers, dict):
        server = servers.get(name)
        if server is None and len(servers) == 1:
            server = next(iter(servers.values()))
        if not isinstance(server, dict):
            raise ValueError('mcp.json 中未找到对应的 MCP 服务器配置')
        return server
    return config


@app.post('/api/mcp/test')
async def test_mcp(req: TestMcpReq, user: User = Depends(require_usable_user)):
    try:
        server = _resolve_mcp_server(req.name.strip(), req.config)
        url = str(server.get('url') or server.get('serverUrl') or '').strip()
        command = str(server.get('command') or '').strip()

        if url:
            if not url.startswith(('http://', 'https://')):
                return JSONResponse(
                    {'ok': False, 'message': 'MCP URL 必须以 http:// 或 https:// 开头'},
                    status_code=400,
                )
            headers = server.get('headers') if isinstance(server.get('headers'), dict) else {}
            headers = {str(key): str(value) for key, value in headers.items()}
            headers.setdefault('Accept', 'application/json, text/event-stream')
            payload = {
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2025-03-26',
                    'capabilities': {},
                    'clientInfo': {'name': 'ai-platform', 'version': '1.0'},
                },
            }
            timeout = httpx.Timeout(8.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream('POST', url, headers=headers, json=payload) as response:
                    status = response.status_code
                if status == 405:
                    async with client.stream('GET', url, headers=headers) as response:
                        status = response.status_code
            if status in (401, 403):
                return JSONResponse(
                    {'ok': False, 'message': f'MCP 服务已响应，但认证失败（HTTP {status}）'},
                    status_code=502,
                )
            if status >= 400:
                return JSONResponse(
                    {'ok': False, 'message': f'MCP 接口校验失败（HTTP {status}）'},
                    status_code=502,
                )
            return {'ok': True, 'message': f'MCP 服务连接成功（HTTP {status}）', 'transport': 'http'}

        if command:
            executable = shutil.which(command)
            if executable is None and os.path.isfile(command):
                executable = command
            if not executable:
                return JSONResponse(
                    {'ok': False, 'message': f'未找到 stdio 启动命令：{command}'},
                    status_code=400,
                )
            return {
                'ok': True,
                'message': f'stdio 命令可用：{executable}',
                'transport': 'stdio',
            }

        return JSONResponse(
            {'ok': False, 'message': 'mcp.json 必须包含 url 或 command 配置'},
            status_code=400,
        )
    except (ValueError, TypeError) as e:
        return JSONResponse({'ok': False, 'message': str(e)}, status_code=400)
    except httpx.TimeoutException:
        return JSONResponse({'ok': False, 'message': '连接超时，请检查 MCP 服务地址'}, status_code=504)
    except httpx.HTTPError as e:
        return JSONResponse({'ok': False, 'message': f'连接失败：{e}'}, status_code=502)
