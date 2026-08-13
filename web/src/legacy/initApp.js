/**
 * Legacy application bootstrap (extracted from web/app.js).
 * Readable feature slices are under ./parts/*.js for navigation and code-splitting stubs.
 */
export function initApp() {
  const messagesEl = document.getElementById('messages');
  const queryInput = document.getElementById('queryInput');
  const sendBtn = document.getElementById('sendBtn');
  const newReportBtn = document.getElementById('newReportBtn');
  const charCountEl = document.getElementById('charCount');
  const reportList = document.getElementById('reportList');
  const sidebar = document.getElementById('sidebar');
  const mobileMenuBtn = document.getElementById('mobileMenuBtn');
  const sidebarOverlay = document.getElementById('sidebarOverlay');
  const reportTitle = document.getElementById('currentReportTitle');
  const settingsBtn = document.getElementById('settingsBtn');
  const currentModelLabel = document.getElementById('currentModelLabel');

  const settingsModal = document.getElementById('settingsModal');
  const addModelModal = document.getElementById('addModelModal');
  const addDsModal = document.getElementById('addDsModal');
  const createKbModal = document.getElementById('createKbModal');
  const kbDetailModal = document.getElementById('kbDetailModal');
  const modalTitleEl = document.getElementById('modalTitle');
  const modelListEl = document.getElementById('modelList');
  const dsListEl = document.getElementById('dsList');

  let currentSources = [];
  const AUTH_TOKEN_KEY = 'ai_platform_auth_token';
  let currentAuthUser = null;

  function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY) || '';
  }

  function setAuthToken(token) {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
    else localStorage.removeItem(AUTH_TOKEN_KEY);
  }

  function authHeaders(extra = {}) {
    const headers = { ...(extra || {}) };
    const token = getAuthToken();
    if (token) headers.Authorization = 'Bearer ' + token;
    return headers;
  }

  function mergeAuthIntoFetchOptions(options = {}) {
    const opts = { ...(options || {}) };
    const headers = new Headers(opts.headers || {});
    const token = getAuthToken();
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', 'Bearer ' + token);
    }
    opts.headers = headers;
    return opts;
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, mergeAuthIntoFetchOptions(options));
    if (response.status === 401 && !String(url).includes('/api/auth/login')) {
      currentAuthUser = null;
      setAuthToken('');
      showLoginOverlay('登录已过期，请重新登录');
    } else if (
      response.status === 403
      && !String(url).includes('/api/auth/change-password')
      && !String(url).includes('/api/auth/me')
    ) {
      const data = await response.clone().json().catch(() => ({}));
      const detail = typeof data.detail === 'string' ? data.detail : '';
      // Only force the change-password UI when server explicitly says so.
      if (detail.includes('修改密码')) {
        if (currentAuthUser) currentAuthUser.must_change_password = true;
        showChangePasswordOverlay(detail || '请先修改密码后再使用平台功能');
      }
    }
    return response;
  }

  // Keys synced to MySQL ai_platform.user_workspace_settings (auth token stays local).
  const WORKSPACE_LS_KEYS = new Set([
    'configured_models',
    'active_model_id',
    'user_mcp_configs',
    'mcp_market_state',
    'custom_mcp_market',
    'user_skill_configs',
    'skill_market_state',
    'custom_skill_market',
    'user_agent_configs',
    'active_agent_id',
    'ai_platform_tool_settings',
    'knowledge_api_configs',
    'knowledge_credentials',
    'knowledge_self_enabled',
    'selected_knowledge_base_id',
    'chat_knowledge_base_ids',
    'chat_knowledge_base_id',
    'chat_data_source_ids',
    'ai_platform_conversations',
    'ai_platform_current_conversation',
    'ai_platform_approval_audit',
  ]);
  let workspaceHydrated = false;
  let workspaceSyncTimer = null;
  let workspaceSyncInFlight = false;
  let workspaceSyncQueued = false;
  const nativeLocalStorageSetItem = localStorage.setItem.bind(localStorage);
  const nativeLocalStorageRemoveItem = localStorage.removeItem.bind(localStorage);

  function scheduleWorkspaceSync() {
    if (!workspaceHydrated || !getAuthToken()) return;
    clearTimeout(workspaceSyncTimer);
    workspaceSyncTimer = setTimeout(() => {
      workspaceSyncTimer = null;
      flushWorkspaceToServer();
    }, 500);
  }

  localStorage.setItem = function patchedSetItem(key, value) {
    nativeLocalStorageSetItem(key, value);
    if (WORKSPACE_LS_KEYS.has(String(key))) scheduleWorkspaceSync();
  };
  localStorage.removeItem = function patchedRemoveItem(key) {
    nativeLocalStorageRemoveItem(key);
    if (WORKSPACE_LS_KEYS.has(String(key))) scheduleWorkspaceSync();
  };

  const CONVERSATIONS_KEY = 'ai_platform_conversations';
  const CURRENT_CONVERSATION_KEY = 'ai_platform_current_conversation';
  const MAX_CONVERSATIONS = 50;
  const MAX_MESSAGES_PER_CONVERSATION = 50;

  function loadConversations() {
    try {
      const value = JSON.parse(localStorage.getItem(CONVERSATIONS_KEY) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  let conversations = loadConversations();
  let currentConversationId = localStorage.getItem(CURRENT_CONVERSATION_KEY) || null;

  // 市场上常见的大模型厂商预设，选择后自动填充供应商名称与官方连接
  const PROVIDER_PRESETS = [
    {
      id: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o', keyHint: 'sk-...',
      models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'o3', 'o3-mini', 'o4-mini', 'o1', 'o1-mini'],
    },
    {
      id: 'anthropic', name: 'Anthropic', baseUrl: 'https://api.anthropic.com', model: 'claude-3-5-sonnet-20241022', keyHint: 'sk-ant-...',
      models: ['claude-opus-4-20250514', 'claude-sonnet-4-20250514', 'claude-3-7-sonnet-20250219', 'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307'],
    },
    {
      id: 'google', name: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', model: 'gemini-2.0-flash', keyHint: 'AIza...',
      models: ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-pro', 'gemini-1.5-flash'],
    },
    {
      id: 'minimax', name: 'MiniMax', baseUrl: 'https://api.minimax.chat/v1', model: 'MiniMax-M2.7', keyHint: 'eyJ...',
      models: ['MiniMax-M2.7', 'MiniMax-Text-01', 'MiniMax-M1', 'abab6.5s-chat', 'abab6.5-chat'],
    },
    {
      id: 'zhipu', name: '智谱 GLM', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4', keyHint: 'xxxx.xxxx',
      models: ['glm-4.5', 'glm-4.5-air', 'glm-4.5-flash', 'glm-4', 'glm-4-plus', 'glm-4-air', 'glm-4-airx', 'glm-4-flash', 'glm-4-long', 'glm-3-turbo'],
    },
    {
      id: 'qwen', name: '阿里通义千问', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', keyHint: 'sk-...',
      models: ['qwen-max', 'qwen-plus', 'qwen-turbo', 'qwen-long', 'qwen2.5-72b-instruct', 'qwen2.5-32b-instruct', 'qwq-plus', 'qwen-vl-max'],
    },
    {
      id: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', keyHint: 'sk-...',
      models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-coder'],
    },
    {
      id: 'moonshot', name: '月之暗面 Kimi', baseUrl: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k', keyHint: 'sk-...',
      models: ['kimi-latest', 'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-k2-0711-preview'],
    },
    {
      id: 'spark', name: '讯飞星火', baseUrl: 'https://spark-api-open.xf-yun.com/v1', model: 'generalv3.5', keyHint: 'xxxx:xxxx',
      models: ['generalv3.5', 'generalv3', '4.0Ultra', 'max-32k', 'pro-128k', 'lite'],
    },
    {
      id: 'baidu', name: '百度文心一言', baseUrl: 'https://qianfan.baidubce.com/v2', model: 'ernie-4.0-8k', keyHint: 'bce-v3/...',
      models: ['ernie-4.0-8k', 'ernie-4.0-turbo-8k', 'ernie-3.5-8k', 'ernie-speed-8k', 'ernie-lite-8k', 'ernie-tiny-8k'],
    },
    {
      id: 'custom', name: '自定义', baseUrl: '', model: '', keyHint: 'sk-...',
      models: [],
    },
  ];

  function loadModels() {
    try {
      const arr = JSON.parse(localStorage.getItem('configured_models') || '[]');
      return Array.isArray(arr) ? arr : [];
    } catch (_) {
      return [];
    }
  }

  let models = loadModels();
  let activeModelId = localStorage.getItem('active_model_id') || (models.find((m) => m.active)?.id) || null;
  let platformModels = []; // admin-configured gateway models/routes (no user key)
  let selectedProviderId = null;
  window.models = models;

  const DEFAULT_PORTS = {
    mysql: '3306', hive: '10000', spark: '10000', kafka: '9092',
    postgres: '5432', mongodb: '27017', clickhouse: '8123', oracle: '1521', sqlserver: '1433',
  };

  let dataSources = [];
  let editingDsId = null;

  async function datasourceApi(path = '', options = {}) {
    const response = await apiFetch('/api/datasources' + path, options);
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      let message = data.error || data.message || ('请求失败（HTTP ' + response.status + '）');
      if (typeof detail === 'string') message = detail;
      else if (Array.isArray(detail)) {
        message = detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
      }
      throw new Error(message);
    }
    return data;
  }

  async function loadDataSourcesFromApi() {
    try {
      const list = await datasourceApi('');
      dataSources = Array.isArray(list) ? list : [];
      await maybeMigrateLegacyDataSources();
      renderDataSourceList();
      updateChatDataSourceOptions();
      initOverview();
    } catch (error) {
      console.warn('加载数据源失败', error);
      dataSources = [];
      renderDataSourceList();
      updateChatDataSourceOptions();
    }
  }

  async function maybeMigrateLegacyDataSources() {
    if (dataSources.length) {
      localStorage.removeItem('dataSources');
      return;
    }
    let legacy = [];
    try {
      legacy = JSON.parse(localStorage.getItem('dataSources') || '[]') || [];
    } catch (_) {
      legacy = [];
    }
    if (!legacy.length) return;
    for (const item of legacy) {
      if (!item?.name || !item?.host || !item?.type) continue;
      try {
        await datasourceApi('', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: item.name,
            type: item.type,
            host: item.host,
            port: String(item.port || ''),
            database: item.database || '',
            username: item.user || item.username || '',
            password: item.password || '',
            extra: item.extra || '',
          }),
        });
      } catch (_) { /* skip duplicates / failures */ }
    }
    localStorage.removeItem('dataSources');
    const list = await datasourceApi('');
    dataSources = Array.isArray(list) ? list : [];
  }

  function loadStoredArray(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  function loadStoredObject(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch (_) {
      return {};
    }
  }

  let mcpConfigs = loadStoredArray('user_mcp_configs');
  let skillConfigs = loadStoredArray('user_skill_configs');
  const SKILL_MARKET_PROMPTS = {
    'data-verify': [
      '你是数据验证校验助手。目标：确保涉及库内真实数据的结论都有工具证据。',
      '',
      '## 强制流程',
      '1. 判断问题是否需要真实数据（配置值、条数、金额、名单、是否存在、现状等）。',
      '2. 若需要：先调用 list_tables / describe_table / run_readonly_sql 查询，再作答。',
      '3. 知识库文档只用于理解表结构、字段含义、业务口径；不得当作查询结果。',
      '4. 没有工具返回前，禁止写「查询结果如下」「实际情况是」「当前配置为」等肯定表述。',
      '5. 若无法调用工具，必须明确写「未实际查询数据库」，并说明原因与下一步。',
      '',
      '## 输出要求',
      '- 先给出可核验的结论（附工具依据）。',
      '- 区分：工具返回的事实 / 文档口径说明 / 合理推断。',
      '- SQL 使用只读查询，优先 LIMIT，避免全表扫描。',
    ].join('\n'),
    'sql-analyzer': [
      '你是 SQL 查询分析助手。',
      '1. 先确认数据源与表结构（必要时 list_tables / describe_table）。',
      '2. 再编写并执行只读 SQL（run_readonly_sql）。',
      '3. 解释结果含义，并给出可复现的 SQL。',
      '禁止编造未查询到的数据。',
    ].join('\n'),
  };

  let agentConfigs = loadStoredArray('user_agent_configs').map((item) => {
    if (!item || typeof item !== 'object') return item;
    const next = { ...item };
    delete next.modelId;
    return next;
  });
  let activeAgentId = localStorage.getItem('active_agent_id') || '';
  let mcpMarketState = loadStoredObject('mcp_market_state');
  let skillMarketState = loadStoredObject('skill_market_state');
  let customMcpMarket = loadStoredArray('custom_mcp_market');
  let customSkillMarket = loadStoredArray('custom_skill_market');
  let knowledgeBases = [];
  let selectedKnowledgeBaseId = Number(localStorage.getItem('selected_knowledge_base_id')) || null;
  let kbPollTimer = null;
  let kbPollInFlight = false;
  let lastDocFingerprint = '';
  let persistConversationsTimer = null;
  let chunkPage = 1;
  let activeKbTab = 'documents';
  let apiKbConfigs = [];
  let editingKbModal = null;
  let activeKbRegistry = null;
  const API_KB_CONFIGS_KEY = 'knowledge_api_configs';
  const KB_SELF_ENABLED_KEY = 'knowledge_self_enabled';
  const KB_CREDENTIALS_KEY = 'knowledge_credentials';

  function loadKnowledgeCredentials() {
    return loadStoredObject(KB_CREDENTIALS_KEY);
  }

  function saveKnowledgeCredentialsMap(map) {
    localStorage.setItem(KB_CREDENTIALS_KEY, JSON.stringify(map || {}));
  }

  function getStoredKbCredentials(knowledgeBaseId) {
    const map = loadKnowledgeCredentials();
    const entry = map[String(knowledgeBaseId)] || {};
    return {
      embeddingApiKey: entry.embeddingApiKey || '',
      chromaApiKey: entry.chromaApiKey || '',
    };
  }

  function setStoredKbCredentials(knowledgeBaseId, credentials) {
    if (!knowledgeBaseId) return;
    const map = loadKnowledgeCredentials();
    map[String(knowledgeBaseId)] = {
      embeddingApiKey: credentials?.embeddingApiKey || '',
      chromaApiKey: credentials?.chromaApiKey || '',
    };
    saveKnowledgeCredentialsMap(map);
  }

  function clearStoredKbCredentials(knowledgeBaseId) {
    if (!knowledgeBaseId) return;
    const map = loadKnowledgeCredentials();
    delete map[String(knowledgeBaseId)];
    saveKnowledgeCredentialsMap(map);
  }

  const LOCAL_EMBEDDING_BASE_URL = 'http://127.0.0.1:9997/v1';
  const CLOUD_OPENAI_BASE_URL = 'https://api.openai.com/v1';
  const EMBEDDING_PRESETS = {
    local: [
      { id: 'BGE-M3', model: 'bge-m3', label: 'BGE-M3', baseUrl: LOCAL_EMBEDDING_BASE_URL, dimension: 1024 },
      { id: 'BGE-large-zh', model: 'bge-large-zh-v1.5', label: 'BGE-large-zh', baseUrl: LOCAL_EMBEDDING_BASE_URL, dimension: 1024 },
      { id: 'GTE-Qwen', model: 'gte-qwen2-1.5B-instruct', label: 'GTE-Qwen', baseUrl: LOCAL_EMBEDDING_BASE_URL, dimension: 1024 },
    ],
    cloud: [
      { id: 'text-embedding-3-small', model: 'text-embedding-3-small', label: 'text-embedding-3-small', baseUrl: CLOUD_OPENAI_BASE_URL, dimension: 1536 },
      { id: 'text-embedding-3-large', model: 'text-embedding-3-large', label: 'text-embedding-3-large', baseUrl: CLOUD_OPENAI_BASE_URL, dimension: 3072 },
      { id: 'text-embedding-ada-002', model: 'text-embedding-ada-002', label: 'text-embedding-ada-002', baseUrl: CLOUD_OPENAI_BASE_URL, dimension: 1536 },
    ],
  };

  const NAV_TITLES = {
    model: '模型配置',
    datasource: '数据源接入',
    kb: '知识库',
    mcp: 'MCP 管理',
    skill: 'Skill 管理',
    agent: 'Agent 管理',
    tool: 'Tool 设置',
    api: 'API 设置',
    dataprocess: '数据处理',
    permission: '权限与审计',
    users: '权限与审计',
    authz: '授权管理',
    dataoutput: '数据输出',
      'gateway-usage': '用量统计',
    gateway: 'Gateway 管理',
  };

  const TOOL_SETTINGS_KEY = 'ai_platform_tool_settings';
  const BUILTIN_TOOLS = [
    {
      id: 'list_tables',
      name: 'list_tables',
      title: '列出数据表',
      desc: '列出指定数据源中的表（只读），不确定表名时优先使用',
      source: '数据源',
    },
    {
      id: 'describe_table',
      name: 'describe_table',
      title: '查看表结构',
      desc: '查看指定表的字段结构（只读）',
      source: '数据源',
    },
    {
      id: 'run_readonly_sql',
      name: 'run_readonly_sql',
      title: '执行只读 SQL',
      desc: '在指定数据源执行 SELECT/WITH/SHOW/DESCRIBE/EXPLAIN，禁止写操作',
      source: '数据源',
    },
    {
      id: 'search_knowledge',
      name: 'search_knowledge',
      title: '知识库检索',
      desc: '在对话已选知识库中检索文档片段，回答制度/FAQ/文档类问题',
      source: '知识库',
    },
    {
      id: 'list_pipelines',
      name: 'list_pipelines',
      title: '列出流水线',
      desc: '查看可用数据处理流水线及最近运行状态',
      source: '流水线',
    },
    {
      id: 'run_pipeline',
      name: 'run_pipeline',
      title: '执行流水线',
      desc: '同步执行指定流水线（需开启「允许流水线工具」）',
      source: '流水线',
    },
    {
      id: 'get_pipeline_run',
      name: 'get_pipeline_run',
      title: '查询流水线运行',
      desc: '查询某次或最近一次流水线运行详情',
      source: '流水线',
    },
    {
      id: 'create_pipeline',
      name: 'create_pipeline',
      title: '创建流水线',
      desc: '创建数据处理流水线（可后续补充同步/加工步骤）',
      source: '流水线',
    },
    {
      id: 'create_data_sync',
      name: 'create_data_sync',
      title: '数据同步',
      desc: '源表→目标表同步，支持引擎 sqoop（默认）/ mysql / datax，以及 append/replace',
      source: '流水线',
    },
    {
      id: 'create_data_process',
      name: 'create_data_process',
      title: '数据处理',
      desc: '在指定数据源执行加工 SQL，可立即跑数',
      source: '流水线',
    },
    {
      id: 'schedule_task',
      name: 'schedule_task',
      title: '定时任务',
      desc: '为流水线配置 cron / 执行日期并启停',
      source: '流水线',
    },
    {
      id: 'list_schedules',
      name: 'list_schedules',
      title: '定时任务列表',
      desc: '查看已配置的流水线定时任务',
      source: '流水线',
    },
    {
      id: 'query_pipeline_logs',
      name: 'query_pipeline_logs',
      title: '日志查询',
      desc: '按流水线/状态/关键字/日期查询运行日志',
      source: '流水线',
    },
  ];

  function defaultToolSettings() {
    return {
      enabled: true,
      maxRounds: 6,
      showTraces: true,
      allowMcp: true,
      allowPipeline: true,
      tools: Object.fromEntries(BUILTIN_TOOLS.map((item) => [item.id, true])),
    };
  }

  function loadToolSettings() {
    const defaults = defaultToolSettings();
    try {
      const raw = localStorage.getItem(TOOL_SETTINGS_KEY);
      if (!raw) return defaults;
      const parsed = JSON.parse(raw);
      return {
        ...defaults,
        ...parsed,
        tools: { ...defaults.tools, ...(parsed.tools || {}) },
      };
    } catch (_) {
      return defaults;
    }
  }

  function persistToolSettings(settings) {
    localStorage.setItem(TOOL_SETTINGS_KEY, JSON.stringify(settings));
  }

  let toolSettings = loadToolSettings();

  function getToolConfigPayload() {
    const enabledTools = Object.entries(toolSettings.tools || {})
      .filter(([, on]) => on)
      .map(([id]) => id);
    return {
      enabled: toolSettings.enabled !== false,
      maxRounds: Math.min(10, Math.max(1, Number(toolSettings.maxRounds) || 6)),
      enabledTools,
      allowMcp: Boolean(toolSettings.allowMcp),
      allowPipeline: Boolean(toolSettings.allowPipeline),
    };
  }

  function getEnabledSkillsPayload() {
    return (skillConfigs || [])
      .filter((item) => item && item.enabled !== false)
      .map((item) => ({
        id: item.id || '',
        name: String(item.name || '').trim(),
        description: String(item.description || '').trim(),
        prompt: String(item.prompt || '').trim(),
      }))
      .filter((item) => item.prompt || item.description);
  }

  function persistAgentData() {
    localStorage.setItem('user_agent_configs', JSON.stringify(agentConfigs || []));
    localStorage.setItem('active_agent_id', activeAgentId || '');
  }

  function getActiveAgent() {
    if (!activeAgentId) return null;
    return (agentConfigs || []).find((item) => item.id === activeAgentId && item.enabled !== false) || null;
  }

  function defaultAgentToolPolicy() {
    return {
      enabled: true,
      maxRounds: 6,
      allowMcp: true,
      allowPipeline: true,
    };
  }

  function normalizeAgent(item) {
    const policy = { ...defaultAgentToolPolicy(), ...(item?.toolPolicy || {}) };
    return {
      id: item?.id || ('agent_' + Date.now()),
      name: String(item?.name || '').trim(),
      description: String(item?.description || '').trim(),
      enabled: item?.enabled !== false,
      skillIds: Array.isArray(item?.skillIds) ? item.skillIds.map(String) : [],
      knowledgeBaseIds: Array.isArray(item?.knowledgeBaseIds)
        ? item.knowledgeBaseIds.map(Number).filter((id) => Number.isFinite(id) && id > 0)
        : [],
      dataSourceIds: Array.isArray(item?.dataSourceIds)
        ? item.dataSourceIds.map(Number).filter((id) => Number.isFinite(id) && id > 0)
        : [],
      mcpServerIds: Array.isArray(item?.mcpServerIds) ? item.mcpServerIds.map(String) : [],
      toolPolicy: {
        enabled: policy.enabled !== false,
        maxRounds: Math.min(10, Math.max(1, Number(policy.maxRounds) || 6)),
        allowMcp: Boolean(policy.allowMcp),
        allowPipeline: Boolean(policy.allowPipeline),
      },
      createdAt: item?.createdAt || Date.now(),
    };
  }

  function getSkillsPayloadForAgent(agent) {
    if (!agent) return getEnabledSkillsPayload();
    const idSet = new Set((agent.skillIds || []).map(String));
    if (!idSet.size) return [];
    return (skillConfigs || [])
      .filter((item) => item && item.enabled !== false && idSet.has(String(item.id)))
      .map((item) => ({
        id: item.id || '',
        name: String(item.name || '').trim(),
        description: String(item.description || '').trim(),
        prompt: String(item.prompt || '').trim(),
      }))
      .filter((item) => item.prompt || item.description);
  }

  function getToolConfigPayloadForAgent(agent) {
    const base = getToolConfigPayload();
    if (!agent) return base;
    const policy = agent.toolPolicy || defaultAgentToolPolicy();
    return {
      ...base,
      enabled: policy.enabled !== false,
      maxRounds: Math.min(10, Math.max(1, Number(policy.maxRounds) || base.maxRounds || 6)),
      allowMcp: Boolean(policy.allowMcp),
      allowPipeline: Boolean(policy.allowPipeline),
    };
  }

  function getMcpServersPayloadForAgent(agent) {
    const enabled = (mcpConfigs || []).filter((item) => item && item.enabled !== false && item.mcpJson);
    if (!agent) {
      return enabled.map((item) => ({ name: item.name, config: item.mcpJson }));
    }
    if (!agent.toolPolicy?.allowMcp) return [];
    const idSet = new Set((agent.mcpServerIds || []).map(String));
    const picked = idSet.size ? enabled.filter((item) => idSet.has(String(item.id))) : enabled;
    return picked.map((item) => ({ name: item.name, config: item.mcpJson }));
  }

  function getPermittedChatKnowledgeBaseIds() {
    return knowledgeBases
      .filter((kb) => isKbEnabled('self', kb.id))
      .map((kb) => Number(kb.id))
      .filter((id) => Number.isFinite(id) && id > 0);
  }

  function getPermittedChatDataSourceIds() {
    return (dataSources || [])
      .map((ds) => Number(ds.id))
      .filter((id) => Number.isFinite(id) && id > 0);
  }

  function resolveChatRuntime() {
    const agent = getActiveAgent();
    const model = getActiveModel();
    const permittedKb = new Set(getPermittedChatKnowledgeBaseIds());
    const permittedDs = new Set(getPermittedChatDataSourceIds());
    const chatKbIds = (agent
      ? (agent.knowledgeBaseIds || []).map(Number)
      : getSelectedChatKnowledgeBaseIds()
    ).filter((id) => Number.isFinite(id) && id > 0 && permittedKb.has(id));
    const chatDsIds = (agent
      ? (agent.dataSourceIds || []).map(Number)
      : getSelectedChatDataSourceIds()
    ).filter((id) => Number.isFinite(id) && id > 0 && permittedDs.has(id));
    return {
      agent,
      model,
      chatKbIds,
      chatDsIds,
      skills: getSkillsPayloadForAgent(agent),
      toolConfig: getToolConfigPayloadForAgent(agent),
      mcpServers: getMcpServersPayloadForAgent(agent),
    };
  }


  function renderToolSettingsPanel() {
    const list = document.getElementById('toolBuiltinList');
    const master = document.getElementById('toolEnabledMaster');
    const maxRounds = document.getElementById('toolMaxRounds');
    const showTraces = document.getElementById('toolShowTraces');
    const allowMcp = document.getElementById('toolAllowMcp');
    const allowPipeline = document.getElementById('toolAllowPipeline');
    const summary = document.getElementById('toolBuiltinSummary');
    if (master) master.checked = toolSettings.enabled !== false;
    if (maxRounds) maxRounds.value = String(toolSettings.maxRounds || 6);
    if (showTraces) showTraces.checked = toolSettings.showTraces !== false;
    if (allowMcp) allowMcp.checked = Boolean(toolSettings.allowMcp);
    if (allowPipeline) allowPipeline.checked = Boolean(toolSettings.allowPipeline);

    const enabledCount = BUILTIN_TOOLS.filter((tool) => toolSettings.tools?.[tool.id] !== false).length;
    if (summary) summary.textContent = `${enabledCount} / ${BUILTIN_TOOLS.length} 启用`;
    if (!list) return;

    const keyword = (document.getElementById('toolSearchInput')?.value || '').trim().toLowerCase();
    const sourceFilter = document.getElementById('toolSourceFilter')?.value || '';
    const filtered = BUILTIN_TOOLS.filter((tool) => {
      const hitSource = !sourceFilter || tool.source === sourceFilter;
      if (!hitSource) return false;
      if (!keyword) return true;
      const blob = `${tool.title} ${tool.name} ${tool.desc} ${tool.source}`.toLowerCase();
      return blob.includes(keyword);
    });

    if (!filtered.length) {
      list.innerHTML = '<div class="tool-empty">没有匹配的内置工具</div>';
      return;
    }

    const groups = [];
    const order = ['数据源', '知识库', '流水线'];
    const bySource = new Map();
    filtered.forEach((tool) => {
      if (!bySource.has(tool.source)) bySource.set(tool.source, []);
      bySource.get(tool.source).push(tool);
    });
    order.forEach((source) => {
      if (bySource.has(source)) groups.push([source, bySource.get(source)]);
    });
    bySource.forEach((tools, source) => {
      if (!order.includes(source)) groups.push([source, tools]);
    });

    list.innerHTML = groups.map(([source, tools]) => {
      const enabledInGroup = tools.filter((tool) => toolSettings.tools?.[tool.id] !== false).length;
      const groupKey = encodeURIComponent(source);
      const rows = tools.map((tool) => {
        const on = toolSettings.tools?.[tool.id] !== false;
        return `
          <label class="tool-row ${on ? 'is-on' : 'is-off'}">
            <div class="tool-row-main">
              <div class="tool-row-title">
                <strong>${escapeHtml(tool.title)}</strong>
                <code>${escapeHtml(tool.name)}</code>
              </div>
              <span>${escapeHtml(tool.desc)}</span>
            </div>
            <span class="tool-toggle-state">${on ? '启用' : '停用'}</span>
            <input type="checkbox" data-tool-id="${escapeHtml(tool.id)}" ${on ? 'checked' : ''}>
          </label>`;
      }).join('');
      return `
        <details class="tool-group" data-tool-group="${groupKey}" open>
          <summary class="tool-group-summary">
            <span class="tool-group-left">
              <span class="tool-group-name">${escapeHtml(source)}</span>
              <span class="tool-group-count">${enabledInGroup}/${tools.length}</span>
            </span>
            <span class="tool-group-actions">
              <button type="button" class="tool-group-btn" data-tool-group-action="enable" data-tool-group="${groupKey}">全开</button>
              <button type="button" class="tool-group-btn" data-tool-group-action="disable" data-tool-group="${groupKey}">全关</button>
            </span>
          </summary>
          <div class="tool-group-body">${rows}</div>
        </details>`;
    }).join('');
  }

  function setBuiltinToolsEnabled(predicate, enabled) {
    const next = { ...(toolSettings.tools || {}) };
    BUILTIN_TOOLS.forEach((tool) => {
      if (predicate(tool)) next[tool.id] = enabled;
    });
    toolSettings = { ...toolSettings, tools: next };
    persistToolSettings(toolSettings);
    renderToolSettingsPanel();
  }

  function readToolSettingsFromForm() {
    const tools = { ...(toolSettings.tools || {}) };
    document.querySelectorAll('#toolBuiltinList [data-tool-id]').forEach((input) => {
      tools[input.dataset.toolId] = input.checked;
    });
    const maxRounds = Number(document.getElementById('toolMaxRounds')?.value);
    return {
      enabled: Boolean(document.getElementById('toolEnabledMaster')?.checked),
      maxRounds: Number.isFinite(maxRounds) ? Math.min(10, Math.max(1, maxRounds)) : 6,
      showTraces: Boolean(document.getElementById('toolShowTraces')?.checked),
      allowMcp: Boolean(document.getElementById('toolAllowMcp')?.checked),
      allowPipeline: Boolean(document.getElementById('toolAllowPipeline')?.checked),
      tools,
    };
  }

  function saveToolSettingsFromForm() {
    toolSettings = readToolSettingsFromForm();
    persistToolSettings(toolSettings);
    renderToolSettingsPanel();
    showAppToast('Tool 设置已保存', 'ok');
  }

  function resetToolSettings() {
    toolSettings = defaultToolSettings();
    persistToolSettings(toolSettings);
    renderToolSettingsPanel();
    showAppToast('已恢复默认 Tool 设置', 'ok');
  }

  function initToolPanel() {
    renderToolSettingsPanel();
  }

  const welcomeHTML = messagesEl?.querySelector('.welcome-state')?.outerHTML || '';

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function debounce(fn, wait) {
    let timer = null;
    return function debounced(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function autoResize() {
    if (!queryInput || !charCountEl) return;
    // Keep input height fixed; only refresh character count.
    queryInput.style.height = '';
    const len = queryInput.value.length;
    charCountEl.textContent = len + ' / 2000';
    charCountEl.className = 'char-count' + (len > 2000 ? ' over' : len > 1500 ? ' warn' : '');
  }

  function scrollToBottom() {
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function openSidebar() {
    sidebar?.classList.add('mobile-open');
    sidebarOverlay?.classList.add('visible');
  }

  function closeSidebar() {
    sidebar?.classList.remove('mobile-open');
    sidebarOverlay?.classList.remove('visible');
  }

  function persistModels() {
    localStorage.setItem('configured_models', JSON.stringify(models));
    localStorage.setItem('active_model_id', activeModelId || '');
    window.models = models;
  }

  function updateCurrentModelLabel() {
    const agent = getActiveAgent();
    const active = getActiveModel()
      || models.find((m) => m.id === activeModelId)
      || models.find((m) => m.status === 'connected');
    if (currentModelLabel) currentModelLabel.textContent = active ? (active.displayName || active.name) : '未配置模型';
    const hint = document.querySelector('.input-hint');
    if (hint) {
      if (agent) {
        const modelName = active ? (active.displayName || active.name) : '未绑定模型';
        hint.textContent = '当前 Agent：' + agent.name + ' · 模型：' + modelName;
      } else if (active) {
        hint.textContent = '当前模型：' + (active.displayName || active.name) + ' · ' + (active.providerName || active.provider);
      } else {
        hint.textContent = '请先在配置中心设置并启用模型，或选择一个 Agent';
      }
    }
    syncChatAgentPickerButton();
  }

  function setActiveModel(id) {
    activeModelId = id;
    models.forEach((m) => { m.active = m.id === id; });
    platformModels.forEach((m) => { m.active = m.id === id; });
    persistModels();
    renderModelList();
    updateCurrentModelLabel();
    initOverview();
  }

  // ===== Conversation history =====
  function createConversationTitle(text) {
    const clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return '新建会话';
    return clean.length > 22 ? clean.slice(0, 22) + '…' : clean;
  }

  function persistConversationsNow() {
    conversations.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    conversations = conversations.slice(0, MAX_CONVERSATIONS);
    const slim = conversations.map((item) => ({
      ...item,
      messages: (item.messages || []).map((msg) => ({
        role: msg.role,
        content: msg.content,
        createdAt: msg.createdAt,
        // Keep source metadata light to avoid localStorage thrash.
        sources: Array.isArray(msg.sources)
          ? msg.sources.map((s) => (typeof s === 'string' ? s : {
            document: s.document,
            knowledge_base_id: s.knowledge_base_id,
            knowledge_base_name: s.knowledge_base_name,
            chunk_id: s.chunk_id,
            score: s.score,
            page: s.page,
            sheet: s.sheet,
          }))
          : [],
      })),
    }));
    try {
      localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(slim));
    } catch (error) {
      let removableIndex = conversations.length - 1;
      while (removableIndex >= 0 && conversations.length > 1) {
        if (conversations[removableIndex].id === currentConversationId) {
          removableIndex -= 1;
          continue;
        }
        conversations.splice(removableIndex, 1);
        try {
          localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(conversations));
          break;
        } catch (_) {
          removableIndex = conversations.length - 1;
        }
      }
      console.warn('会话存储空间不足，已清理较早的会话记录。', error);
    }
    if (currentConversationId) {
      localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
    } else {
      localStorage.removeItem(CURRENT_CONVERSATION_KEY);
    }
  }

  function persistConversations(immediate = false) {
    if (immediate) {
      clearTimeout(persistConversationsTimer);
      persistConversationsTimer = null;
      persistConversationsNow();
      return;
    }
    clearTimeout(persistConversationsTimer);
    persistConversationsTimer = setTimeout(() => {
      persistConversationsTimer = null;
      persistConversationsNow();
    }, 400);
  }

  function getCurrentConversation() {
    return conversations.find((item) => item.id === currentConversationId) || null;
  }

  function ensureConversation(firstMessage) {
    let conversation = getCurrentConversation();
    if (conversation) return conversation;

    const now = Date.now();
    conversation = {
      id: 'conversation_' + now + '_' + Math.random().toString(36).slice(2, 8),
      title: createConversationTitle(firstMessage),
      messages: [],
      createdAt: now,
      updatedAt: now,
    };
    conversations.unshift(conversation);
    currentConversationId = conversation.id;
    persistConversations();
    return conversation;
  }

  function saveConversationMessage(role, content, sources, toolTraces = null, thinking = '') {
    const conversation = ensureConversation(role === 'user' ? content : '');
    appendMessageToConversation(conversation.id, role, content, sources, toolTraces, thinking);
    if (reportTitle && conversation.id === currentConversationId) {
      reportTitle.textContent = conversation.title;
    }
  }

  function appendMessageToConversation(conversationId, role, content, sources, toolTraces = null, thinking = '') {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) return null;
    if (conversation.messages.length === 0 && role === 'user') {
      conversation.title = createConversationTitle(content);
    }
    conversation.messages.push({
      role,
      content: String(content || ''),
      sources: Array.isArray(sources) ? sources : [],
      toolTraces: Array.isArray(toolTraces) ? toolTraces : [],
      thinking: String(thinking || ''),
      createdAt: Date.now(),
    });
    conversation.messages = conversation.messages.slice(-MAX_MESSAGES_PER_CONVERSATION);
    conversation.updatedAt = Date.now();
    persistConversations();
    renderConversationList();
    return conversation;
  }

  const pendingChatByConversation = new Map();

  function markConversationPending(conversationId, pending) {
    if (!conversationId) return;
    if (pending) pendingChatByConversation.set(conversationId, { startedAt: Date.now() });
    else pendingChatByConversation.delete(conversationId);
  }

  function isConversationPending(conversationId) {
    return Boolean(conversationId && pendingChatByConversation.has(conversationId));
  }

  function syncSendingStateForCurrentConversation() {
    setSendingState(isConversationPending(currentConversationId));
  }

  function stopKbPolling() {
    if (kbPollTimer) {
      clearTimeout(kbPollTimer);
      kbPollTimer = null;
    }
    kbPollInFlight = false;
  }

  function scheduleKbPolling() {
    stopKbPolling();
    kbPollTimer = setTimeout(async () => {
      kbPollTimer = null;
      if (kbPollInFlight) {
        scheduleKbPolling();
        return;
      }
      kbPollInFlight = true;
      try {
        await loadDocuments({ fromPoll: true });
        if (activeKbTab === 'chunks') await loadChunks();
      } finally {
        kbPollInFlight = false;
      }
    }, 2500);
  }

  function formatConversationTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    return sameDay
      ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  }

  function renderConversationList() {
    if (!reportList) return;
    if (!conversations.length) {
      reportList.innerHTML = '<div class="conversation-empty">暂无历史会话</div>';
      return;
    }
    const items = conversations
      .slice()
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
      .map((item) => `
        <div class="conv-item ${item.id === currentConversationId ? 'active' : ''}${isConversationPending(item.id) ? ' is-pending' : ''}" data-conversation-id="${escapeHtml(item.id)}">
          <span class="conv-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </span>
          <span class="conv-content">
            <span class="conv-title">${escapeHtml(item.title || '新建会话')}${isConversationPending(item.id) ? '<span class="conv-pending-dot" title="正在生成"></span>' : ''}</span>
            <span class="conv-time">${isConversationPending(item.id) ? '生成中…' : formatConversationTime(item.updatedAt)}</span>
          </span>
          <button class="conv-delete" data-action="delete-conversation" title="删除会话">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="m19 6-1 14H6L5 6"/></svg>
          </button>
        </div>`)
      .join('');
    reportList.innerHTML = `
      <div class="conversation-list-header">
        <span>最近会话</span><span>${conversations.length}/${MAX_CONVERSATIONS}</span>
      </div>
      ${items}`;
  }

  function loadConversation(id) {
    const conversation = conversations.find((item) => item.id === id);
    if (!conversation) return;
    currentConversationId = conversation.id;
    currentSources = [];
    messagesEl.innerHTML = '';
    if (!conversation.messages?.length) {
      messagesEl.innerHTML = welcomeHTML;
    } else {
      conversation.messages.forEach((message) => {
        renderMessage(
          message.role,
          message.content,
          message.sources || [],
          false,
          message.toolTraces || [],
          {
            animate: false,
            skipScroll: true,
            thinking: message.thinking || '',
            expandThinking: false,
          }
        );
      });
      scrollToBottom();
    }
    if (reportTitle) reportTitle.textContent = conversation.title || '新建会话';
    localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
    renderConversationList();
    if (isConversationPending(currentConversationId)) {
      renderLoading(currentConversationId);
    }
    syncSendingStateForCurrentConversation();
    closeSidebar();
  }

  function startNewConversation() {
    currentConversationId = null;
    currentSources = [];
    localStorage.removeItem(CURRENT_CONVERSATION_KEY);
    messagesEl.innerHTML = welcomeHTML;
    if (reportTitle) reportTitle.textContent = '新建会话';
    renderConversationList();
    syncSendingStateForCurrentConversation();
  }

  function deleteConversation(id) {
    const conversation = conversations.find((item) => item.id === id);
    if (!conversation) return;
    if (!confirm('确定删除会话「' + (conversation.title || '新建会话') + '」？')) return;
    conversations = conversations.filter((item) => item.id !== id);
    if (currentConversationId === id) {
      currentConversationId = null;
      messagesEl.innerHTML = welcomeHTML;
      if (reportTitle) reportTitle.textContent = '新建会话';
    }
    persistConversations(true);
    renderConversationList();
  }

  // ===== Messages =====
  function splitThinkingContent(content) {
    let cleaned = String(content == null ? '' : content);
    const chunks = [];
    const patterns = [
      /<think>([\s\S]*?)<\/think>/gi,
      /<thinking>([\s\S]*?)<\/thinking>/gi,
      /```thinking\s*([\s\S]*?)```/gi,
    ];
    patterns.forEach((pattern) => {
      cleaned = cleaned.replace(pattern, (_, body) => {
        const text = String(body || '').trim();
        if (text) chunks.push(text);
        return '';
      });
    });
    return {
      answer: cleaned.replace(/\n{3,}/g, '\n\n').trim(),
      thinking: chunks.join('\n\n').trim(),
    };
  }

  function formatToolTraceBody(trace) {
    if (!trace) return '';
    if (!trace.ok) return trace.error || '失败';
    if (trace.result?.sql) {
      return `SQL: ${trace.result.sql}\n行数: ${trace.result.row_count ?? 0}`;
    }
    try {
      return JSON.stringify(trace.result || {}, null, 2).slice(0, 1200);
    } catch (_) {
      return String(trace.result || '');
    }
  }

  function buildThinkingPanel({ thinking = '', toolTraces = [], expanded = false } = {}) {
    const traces = Array.isArray(toolTraces) ? toolTraces : [];
    const thinkingText = String(thinking || '').trim();
    if (!thinkingText && !traces.length) return null;

    const failCount = traces.filter((item) => item && item.ok === false).length;
    const bits = [];
    if (thinkingText) bits.push('推理');
    if (traces.length) bits.push(`${traces.length} 个工具`);
    if (failCount > 0) bits.push(`${failCount} 失败`);

    const panel = document.createElement('details');
    panel.className = 'thinking-panel';
    panel.open = Boolean(expanded);

    const summary = document.createElement('summary');
    summary.className = 'thinking-panel__summary';
    summary.innerHTML = `
      <span class="thinking-panel__icon" aria-hidden="true"></span>
      <span class="thinking-panel__title">思考过程</span>
      <span class="thinking-panel__meta">${escapeHtml(bits.join(' · ') || '点击展开')}</span>
      <span class="thinking-panel__hint">${expanded ? '收起' : '点击展开'}</span>`;
    panel.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'thinking-panel__body';

    if (thinkingText) {
      const thinkBlock = document.createElement('div');
      thinkBlock.className = 'thinking-block';
      thinkBlock.innerHTML = '<div class="thinking-block__label">模型推理</div>';
      const pre = document.createElement('pre');
      pre.textContent = thinkingText;
      thinkBlock.appendChild(pre);
      body.appendChild(thinkBlock);
    }

    if (traces.length) {
      const tools = document.createElement('div');
      tools.className = 'message-tools';
      tools.innerHTML = '<div class="tools-label">工具 / 命令</div>' + traces.map((trace) => {
        const args = trace.arguments ? JSON.stringify(trace.arguments) : '';
        const bodyText = formatToolTraceBody(trace);
        return `<div class="tool-trace ${trace.ok ? 'ok' : 'error'}"><div class="tool-trace__head">${escapeHtml(trace.tool || 'tool')}</div><div class="tool-trace__args">${escapeHtml(args)}</div><div class="tool-trace__body">${escapeHtml(bodyText)}</div></div>`;
      }).join('');
      body.appendChild(tools);
    }

    panel.appendChild(body);
    panel.addEventListener('toggle', () => {
      const hint = summary.querySelector('.thinking-panel__hint');
      if (hint) hint.textContent = panel.open ? '收起' : '点击展开';
    });
    return panel;
  }

  function renderMessage(role, content, sources, shouldPersist = true, toolTraces = null, options = {}) {
    const {
      animate = true,
      skipScroll = false,
      thinking = '',
      expandThinking = false,
    } = options;
    const welcome = document.getElementById('welcomeState');
    if (welcome) welcome.remove();

    const split = role === 'assistant' ? splitThinkingContent(content) : { answer: content, thinking: '' };
    const thinkingText = String(thinking || split.thinking || '').trim();
    const answerText = role === 'assistant' ? (split.answer || String(content || '')) : String(content || '');
    const traces = Array.isArray(toolTraces) ? toolTraces : [];

    const wrapper = document.createElement('div');
    wrapper.className = 'message' + (role === 'user' ? ' user-message' : '') + (animate ? '' : ' no-anim');

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar ' + (role === 'user' ? 'user-avatar' : 'bot-avatar');
    avatar.innerHTML = role === 'user'
      ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
      : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>';

    const msgContent = document.createElement('div');
    msgContent.className = 'message-content';

    if (role === 'assistant' && toolSettings.showTraces !== false) {
      const thinkingPanel = buildThinkingPanel({
        thinking: thinkingText,
        toolTraces: traces,
        expanded: expandThinking,
      });
      if (thinkingPanel) msgContent.appendChild(thinkingPanel);
    }

    const bubble = document.createElement('span');
    bubble.className = 'bubble';
    const textEl = document.createElement('p');
    textEl.textContent = answerText;
    bubble.appendChild(textEl);

    if (sources && sources.length) {
      const src = document.createElement('div');
      src.className = 'message-sources';
      src.innerHTML = '<div class="sources-label">引用来源</div>' +
        sources.map((s) => {
          if (typeof s === 'string') return `<span class="source-chip">${escapeHtml(s)}</span>`;
          const location = s.page ? ` · 第${s.page} 页` : (s.sheet ? ` · ${s.sheet}` : '');
          const score = Number.isFinite(Number(s.score)) ? ` · ${Number(s.score).toFixed(3)}` : '';
          const kbLabel = s.knowledge_base_name ? `${s.knowledge_base_name} · ` : '';
          return `<button class="source-chip" data-source-kb="${escapeHtml(s.knowledge_base_id || '')}" data-source-chunk="${escapeHtml(s.chunk_id || '')}">${escapeHtml(kbLabel + (s.document || '文档'))}${escapeHtml(location + score)}</button>`;
        }).join('');
      bubble.appendChild(src);
    }

    msgContent.appendChild(bubble);
    wrapper.appendChild(avatar);
    wrapper.appendChild(msgContent);
    messagesEl.appendChild(wrapper);
    if (!skipScroll) scrollToBottom();
    if (shouldPersist) {
      saveConversationMessage(role, answerText, sources, traces, thinkingText);
    }
    return wrapper;
  }

  function renderLoading(conversationId = currentConversationId) {
    document.getElementById('loadingIndicator')?.remove();
    const wrapper = document.createElement('div');
    wrapper.className = 'loading-message';
    wrapper.id = 'loadingIndicator';
    if (conversationId) wrapper.dataset.conversationId = conversationId;
    wrapper.innerHTML = `
      <div class="message-avatar bot-avatar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      </div>
      <div class="loading-bubble">
        <div class="loading-bubble-title"><span class="spin" aria-hidden="true"></span>正在生成回复</div>
        <p class="loading-bubble-desc">模型处理中，请稍候…</p>
        <div class="loading-dots" aria-hidden="true"><div class="loading-dot"></div><div class="loading-dot"></div><div class="loading-dot"></div></div>
      </div>`;
    messagesEl.appendChild(wrapper);
    scrollToBottom();
  }

  function removeLoading(conversationId = null) {
    const el = document.getElementById('loadingIndicator');
    if (!el) return;
    if (conversationId && el.dataset.conversationId && el.dataset.conversationId !== conversationId) {
      return;
    }
    el.remove();
  }

  const CHAT_NOTICE_ICONS = {
    info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    warn: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    danger: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
  };

  let chatNoticeActionHandler = null;
  let chatNoticeDismissHandler = null;

  function closeChatNotice(result = false) {
    const modal = document.getElementById('chatNoticeModal');
    if (modal) modal.classList.remove('open');
    const dismiss = chatNoticeDismissHandler;
    chatNoticeActionHandler = null;
    chatNoticeDismissHandler = null;
    if (typeof dismiss === 'function') dismiss(result);
  }

  function showChatNotice(options = {}) {
    const {
      title = '提示',
      subtitle = '',
      message = '',
      metaHtml = '',
      type = 'info',
      actionLabel = '',
      onAction = null,
      onDismiss = null,
      cancelLabel = '知道了',
      danger = false,
    } = options;
    const modal = document.getElementById('chatNoticeModal');
    const dialog = modal?.querySelector('.chat-notice-dialog');
    const iconEl = document.getElementById('chatNoticeIcon');
    const titleEl = document.getElementById('chatNoticeTitle');
    const subtitleEl = document.getElementById('chatNoticeSubtitle');
    const messageEl = document.getElementById('chatNoticeMessage');
    const metaEl = document.getElementById('chatNoticeMeta');
    const actionBtn = document.getElementById('chatNoticeAction');
    const cancelBtn = document.getElementById('chatNoticeCancel');
    if (!modal || !messageEl) {
      showAppToast(message || title, type === 'error' || danger ? 'error' : 'ok');
      return;
    }
    if (titleEl) titleEl.textContent = title;
    if (subtitleEl) {
      subtitleEl.textContent = subtitle || '';
      subtitleEl.hidden = !subtitle;
    }
    messageEl.textContent = message;
    if (metaEl) {
      if (metaHtml) {
        metaEl.hidden = false;
        metaEl.innerHTML = metaHtml;
      } else {
        metaEl.hidden = true;
        metaEl.innerHTML = '';
      }
    }
    if (dialog) dialog.classList.toggle('is-danger', Boolean(danger));
    if (iconEl) {
      const iconType = danger ? 'danger' : (type === 'warn' || type === 'error' ? type : 'info');
      iconEl.className = 'chat-notice-icon' + (iconType === 'info' ? '' : ' ' + (iconType === 'danger' ? 'error' : iconType));
      iconEl.innerHTML = CHAT_NOTICE_ICONS[iconType] || CHAT_NOTICE_ICONS.info;
    }
    if (cancelBtn) cancelBtn.textContent = cancelLabel;
    chatNoticeActionHandler = typeof onAction === 'function' ? onAction : null;
    chatNoticeDismissHandler = typeof onDismiss === 'function' ? onDismiss : null;
    if (actionBtn) {
      const hasAction = Boolean(actionLabel && chatNoticeActionHandler);
      actionBtn.hidden = !hasAction;
      actionBtn.textContent = actionLabel || '确认';
      actionBtn.className = danger ? 'btn-danger' : 'btn-primary';
    }
    modal.classList.add('open');
  }

  function confirmAppDialog(options = {}) {
    return new Promise((resolve) => {
      showChatNotice({
        type: options.type || 'warn',
        danger: options.danger !== false,
        title: options.title || '确认删除',
        subtitle: options.subtitle || '此操作不可撤销',
        message: options.message || '确定继续吗？',
        metaHtml: options.metaHtml || '',
        cancelLabel: options.cancelLabel || '取消',
        actionLabel: options.actionLabel || '删除',
        onAction: () => {},
        onDismiss: (confirmed) => resolve(Boolean(confirmed)),
      });
    });
  }

  function setSendingState(sending) {
    if (!sendBtn) return;
    sendBtn.disabled = sending;
    sendBtn.classList.toggle('is-sending', sending);
    sendBtn.setAttribute('aria-busy', sending ? 'true' : 'false');
  }

  function getActiveModel() {
    return platformModels.find((m) => m.id === activeModelId)
      || models.find((m) => m.id === activeModelId)
      || null;
  }

  function isGatewayModel(model) {
    return Boolean(model && (model.useGateway || model.provider === 'gateway'));
  }

  function buildModelPayload(model) {
    if (!model) return null;
    const gateway = isGatewayModel(model);
    return {
      provider: gateway ? 'gateway' : model.provider,
      providerName: model.providerName || (gateway ? '平台 Gateway' : ''),
      name: model.name,
      displayName: model.displayName || model.name,
      apiKey: gateway ? '' : (model.apiKey || ''),
      baseUrl: gateway ? '' : (model.baseUrl || ''),
      useGateway: gateway,
    };
  }

  function collectChatHistory() {
    const conversation = getCurrentConversation();
    if (conversation?.messages?.length) {
      return conversation.messages
        .filter((item) => item.role === 'user' || item.role === 'assistant')
        .slice(-12)
        .map((item) => ({ role: item.role, content: item.content || '' }));
    }
    const history = [];
    messagesEl?.querySelectorAll('.message').forEach((msg) => {
      const text = msg.querySelector('.bubble p')?.textContent || '';
      if (!text) return;
      history.push({
        role: msg.classList.contains('user-message') ? 'user' : 'assistant',
        content: text,
      });
    });
    return history.slice(-12);
  }

  async function sendMessage() {
    const text = queryInput.value.trim();
    if (!text) return;
    if (text.length > 2000) {
      showChatNotice({
        title: '内容过长',
        subtitle: '请精简后再发送',
        message: '单次输入请控制在 2000 字以内，当前已超出限制。',
        type: 'warn',
      });
      return;
    }
    if (isConversationPending(currentConversationId)) {
      showAppToast('当前会话仍在生成回复，请稍候', 'warn');
      return;
    }

    const runtime = resolveChatRuntime();
    const active = runtime.model;
    if (!active) {
      showChatNotice({
        title: '尚未选择模型',
        subtitle: '发送前需要完成配置',
        message: runtime.agent
          ? '请先在「模型配置」中添加模型并设为当前，再使用 Agent 对话。'
          : '请先在配置中心添加模型，并点击「设为当前」，或选择一个已配置的 Agent。',
        type: 'warn',
        actionLabel: '去配置模型',
        onAction: () => openSettings('model'),
      });
      return;
    }
    if (!isGatewayModel(active) && !active.apiKey) {
      showChatNotice({
        title: '缺少 API Key',
        subtitle: '当前模型未完成鉴权配置',
        message: `模型「${active.displayName || active.name}」尚未填写 API Key。也可在「模型配置」中选择管理员已配置的平台模型（无需 Key）。`,
        type: 'warn',
        actionLabel: '去配置模型',
        onAction: () => openSettings('model'),
      });
      return;
    }

    const history = collectChatHistory();
    const chatKbIds = runtime.chatKbIds;
    const chatDsIds = runtime.chatDsIds;
    queryInput.value = '';
    autoResize();
    renderMessage('user', text, null);
    const requestConversationId = currentConversationId;
    if (!requestConversationId) {
      showAppToast('会话创建失败，请重试', 'error');
      return;
    }
    markConversationPending(requestConversationId, true);
    setSendingState(true);
    renderLoading(requestConversationId);
    try {
      const res = await apiFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          model: buildModelPayload(active),
          history,
          knowledgeBaseIds: chatKbIds,
          knowledgeBases: chatKbIds.map((id) => {
            const creds = getKnowledgeBaseCredentials(id);
            return {
              id,
              embeddingApiKey: resolveEmbeddingApiKey(id),
              chromaApiKey: creds.chromaApiKey || '',
            };
          }),
          dataSourceIds: chatDsIds,
          toolConfig: runtime.toolConfig,
          skills: runtime.skills,
          mcpServers: runtime.mcpServers,
          agentId: runtime.agent?.id || '',
          agentName: runtime.agent?.name || '',
        }),
      });
      const j = await res.json().catch(() => ({}));
      const answer = !res.ok
        ? (j.answer || j.error || ('请求失败（HTTP ' + res.status + '）'))
        : (j.answer || '未返回结果');
      const sources = !res.ok ? [] : (j.sources || []);
      const traces = j.toolTraces || [];
      const split = splitThinkingContent(answer);
      const thinkingText = split.thinking || '';
      const answerText = split.answer || answer;

      appendMessageToConversation(
        requestConversationId,
        'assistant',
        answerText,
        sources,
        traces,
        thinkingText
      );

      const viewingRequest = currentConversationId === requestConversationId;
      if (viewingRequest) {
        removeLoading(requestConversationId);
        currentSources = sources;
        renderMessage('assistant', answerText, sources, false, traces, {
          expandThinking: false,
          thinking: thinkingText,
        });
      } else {
        const conv = conversations.find((item) => item.id === requestConversationId);
        showAppToast(`会话「${conv?.title || '未命名'}」已收到回复`, 'ok');
      }
    } catch (e) {
      const failText = '请求失败：' + (e.message || e);
      appendMessageToConversation(requestConversationId, 'assistant', failText, [], [], '');
      if (currentConversationId === requestConversationId) {
        removeLoading(requestConversationId);
        renderMessage('assistant', failText, [], false);
      }
    } finally {
      markConversationPending(requestConversationId, false);
      syncSendingStateForCurrentConversation();
      if (currentConversationId === requestConversationId) {
        queryInput.focus();
      }
    }
  }

  function exportReport() {
    const msgs = messagesEl.querySelectorAll('.message');
    if (!msgs.length) {
      alert('没有可导出的对话内容');
      return;
    }
    let md = '# AI平台\n\n> 生成时间：' + new Date().toLocaleString('zh-CN') + '\n\n---\n\n';
    msgs.forEach((msg) => {
      const isUser = msg.classList.contains('user-message');
      const text = msg.querySelector('.bubble p')?.textContent || '';
      md += '### ' + (isUser ? '用户' : 'AI平台') + '\n\n' + text + '\n\n';
    });
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'report_' + Date.now() + '.md';
    a.click();
    URL.revokeObjectURL(url);
  }

  // ===== Settings =====
  function switchToPanel(panelId) {
    if (panelId === 'users') {
      openPermissionUsersTab();
      return;
    }
    if (!settingsModal) return;
    if (['agent', 'mcp', 'skill', 'tool'].includes(panelId) && !hasCapability(panelId)) {
      showAppToast('当前账号无权访问该管理模块', 'warn');
      return;
    }
    if (panelId === 'authz' && !isPlatformAdmin()) {
      showAppToast('仅管理员可进入授权管理', 'warn');
      panelId = 'permission';
    }
    if (panelId === 'gateway' && !isPlatformAdmin()) {
      showAppToast('仅管理员可配置逻辑模型与 Gateway 策略', 'warn');
      panelId = 'model';
    }
    const navItems = settingsModal.querySelectorAll('.modal-nav-item');
    const panels = document.querySelectorAll('.modal-panel');
    navItems.forEach((item) => item.classList.toggle('active', item.dataset.panel === panelId));
    panels.forEach((panel) => {
      const id = panel.id.replace('panel-', '');
      panel.classList.toggle('active', id === panelId);
    });
    if (modalTitleEl) modalTitleEl.textContent = NAV_TITLES[panelId] || '设置';
    if (panelId === 'model') { loadPlatformModels().finally(() => renderModelList()); }
    if (panelId === 'gateway-usage') initGatewayUsagePanel();
    if (panelId === 'gateway') initGatewayAdminPanel();
    if (panelId === 'datasource') renderDataSourceList();
    if (panelId === 'dataprocess') {
      loadPipelines();
      loadPipelineRuns();
    }
    if (panelId === 'permission') {
      initPermissionPanel();
    }
    if (panelId === 'authz') {
      initAuthzPanel();
    }
    if (panelId === 'kb') initKnowledgeBasePanel();
    if (panelId === 'mcp') initMcpPanel();
    if (panelId === 'skill') initSkillPanel();
    if (panelId === 'agent') initAgentPanel();
    if (panelId === 'tool') initToolPanel();
  }

  function openSettings(panelId) {
    if (!settingsModal) {
      console.error('settingsModal not found');
      return;
    }
    syncPlatformRoleUi();
    settingsModal.classList.add('open');
    switchToPanel(panelId || 'model');
    closeSidebar();
  }

  function closeSettings() {
    settingsModal?.classList.remove('open');
  }

  function setFieldValue(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }

  function getFieldValue(id) {
    return (document.getElementById(id)?.value || '').trim();
  }

  function renderProviderGrid() {
    const grid = document.getElementById('providerGrid');
    if (!grid) return;
    grid.innerHTML = PROVIDER_PRESETS.map((p) =>
      `<button type="button" class="provider-chip provider-${p.id}" data-provider="${p.id}">${escapeHtml(p.name)}</button>`
    ).join('');
  }

  function syncModelNameCustomVisibility() {
    const select = document.getElementById('modelName');
    const custom = document.getElementById('modelNameCustom');
    if (!select || !custom) return;
    const useCustom = select.value === '__custom__' || selectedProviderId === 'custom';
    custom.hidden = !useCustom;
    if (useCustom) {
      custom.placeholder = selectedProviderId === 'custom'
        ? '输入自定义模型名称'
        : '输入未列出的模型名称';
    }
  }

  function fillModelNameOptions(preset, preferred = '') {
    const select = document.getElementById('modelName');
    const custom = document.getElementById('modelNameCustom');
    const hint = document.getElementById('modelNameHint');
    if (!select) return;
    const models = Array.isArray(preset?.models) ? preset.models.filter(Boolean) : [];
    const isCustomProvider = preset?.id === 'custom';
    if (!preset) {
      select.innerHTML = '<option value="">请先选择厂商</option>';
      select.disabled = true;
      if (custom) { custom.hidden = true; custom.value = ''; }
      if (hint) hint.textContent = '请先选择厂商，再从列表中选择该厂商模型';
      return;
    }
    select.disabled = false;
    if (isCustomProvider || !models.length) {
      select.innerHTML = '<option value="__custom__">自定义输入</option>';
      select.value = '__custom__';
      if (custom) {
        custom.hidden = false;
        custom.value = preferred || '';
      }
      if (hint) hint.textContent = '自定义厂商请手动填写模型名称';
      return;
    }
    const preferredModel = preferred || preset.model || models[0] || '';
    const options = models.map((name) =>
      `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`
    );
    options.push('<option value="__custom__">其他（自定义输入）</option>');
    select.innerHTML = options.join('');
    if (preferredModel && models.includes(preferredModel)) {
      select.value = preferredModel;
      if (custom) { custom.hidden = true; custom.value = ''; }
    } else if (preferredModel) {
      select.value = '__custom__';
      if (custom) { custom.hidden = false; custom.value = preferredModel; }
    } else {
      select.value = models[0];
      if (custom) { custom.hidden = true; custom.value = ''; }
    }
    if (hint) hint.textContent = `已加载 ${preset.name} 常用模型，也可选择「其他」自行填写`;
    syncModelNameCustomVisibility();
  }

  function getSelectedModelName() {
    const selectValue = getFieldValue('modelName');
    if (selectValue === '__custom__' || selectedProviderId === 'custom') {
      return getFieldValue('modelNameCustom');
    }
    return selectValue;
  }

  function selectProvider(id) {
    selectedProviderId = id;
    const preset = PROVIDER_PRESETS.find((p) => p.id === id);
    document.querySelectorAll('#providerGrid .provider-chip').forEach((b) => {
      b.classList.toggle('active', b.dataset.provider === id);
    });
    if (!preset) return;
    const isCustom = preset.id === 'custom';
    setFieldValue('modelProviderName', isCustom ? '' : preset.name);
    setFieldValue('modelBaseUrl', preset.baseUrl);
    fillModelNameOptions(preset, preset.model || '');
    const keyInput = document.getElementById('modelApiKey');
    if (keyInput) keyInput.placeholder = preset.keyHint || 'sk-...';
    showAddModelTest('', '');
  }

  function renderModalTestBanner(el, type, message) {
    if (!el) return;
    if (!message) {
      el.hidden = true;
      el.innerHTML = '';
      el.className = 'add-model-test';
      return;
    }
    const state = type === 'ok' || type === 'error' ? type : 'pending';
    const title = state === 'ok' ? '测试通过' : state === 'error' ? '测试失败' : '测试中';
    const icon = state === 'ok'
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="20 6 9 17 4 12"/></svg>'
      : state === 'error'
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>';
    el.hidden = false;
    el.className = 'add-model-test ' + state;
    el.innerHTML = `
      <span class="add-model-test__icon" aria-hidden="true">${icon}</span>
      <div class="add-model-test__body">
        <strong class="add-model-test__title">${title}</strong>
        <p class="add-model-test__msg">${escapeHtml(message)}</p>
      </div>`;
    requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  function showAddModelTest(type, msg) {
    renderModalTestBanner(document.getElementById('addModelTestResult'), type, msg);
  }

  function showAddDsTest(type, msg) {
    renderModalTestBanner(document.getElementById('addDsTestResult'), type, msg);
  }

  function markSaveReady(buttonId, ready) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.classList.toggle('is-ready', Boolean(ready));
  }

  function resetAddModelForm() {
    selectedProviderId = null;
    ['modelProviderName', 'modelDisplayName', 'modelBaseUrl', 'modelApiKey', 'modelNameCustom'].forEach((id) => setFieldValue(id, ''));
    fillModelNameOptions(null);
    const keyInput = document.getElementById('modelApiKey');
    if (keyInput) keyInput.type = 'password';
    document.querySelectorAll('#providerGrid .provider-chip').forEach((b) => b.classList.remove('active'));
    showAddModelTest('', '');
    markSaveReady('saveModelBtn', false);
  }

  function openAddModel() {
    renderProviderGrid();
    resetAddModelForm();
    addModelModal?.classList.add('open');
  }

  function closeAddModel() {
    addModelModal?.classList.remove('open');
  }

  async function testAddModelConnection() {
    if (!selectedProviderId) { showAddModelTest('error', '请先选择厂商'); return; }
    const modelName = getSelectedModelName();
    if (!modelName) { showAddModelTest('error', '请选择或填写模型名称'); return; }
    if (!getFieldValue('modelBaseUrl') && selectedProviderId !== 'anthropic' && selectedProviderId !== 'google') {
      showAddModelTest('error', '请填写官方连接(Base URL)');
      return;
    }
    if (!getFieldValue('modelApiKey')) { showAddModelTest('error', '请填写API Key'); return; }
    const btn = document.getElementById('testModelBtn');
    if (btn) { btn.disabled = true; btn.textContent = '测试中...'; }
    showAddModelTest('', '正在调用第三方大模型测试连接...');
    try {
      const res = await apiFetch('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: {
            provider: selectedProviderId,
            providerName: getFieldValue('modelProviderName'),
            name: modelName,
            displayName: getFieldValue('modelDisplayName') || modelName,
            apiKey: getFieldValue('modelApiKey'),
            baseUrl: getFieldValue('modelBaseUrl'),
          },
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok || !j.ok) {
        markSaveReady('saveModelBtn', false);
        showAddModelTest('error', j.message || j.error || '连接失败');
      } else {
        markSaveReady('saveModelBtn', true);
        showAddModelTest('ok', '连接成功，可保存该模型' + (j.reply ? '（模型回复：' + j.reply + '）' : ''));
      }
    } catch (e) {
      markSaveReady('saveModelBtn', false);
      showAddModelTest('error', '连接失败：' + (e.message || e));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '测试连接'; }
    }
  }

  function syncDsTypeExtras(type) {
    const kerberos = document.getElementById('dsKerberosGroup');
    const jdbc = document.getElementById('dsJdbcGroup');
    if (kerberos) kerberos.style.display = type === 'hive' || type === 'spark' ? 'block' : 'none';
    if (jdbc) jdbc.style.display = type === 'hive' || type === 'spark' ? 'block' : 'none';
  }

  function resetAddDsForm() {
    ['dsName', 'dsHost', 'dsPort', 'dsDatabase', 'dsUser', 'dsPassword', 'dsExtra', 'dsKerberos', 'dsJdbcUrl'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const typeEl = document.getElementById('dsType');
    if (typeEl) typeEl.value = '';
    const queryOnly = document.getElementById('dsQueryOnly');
    if (queryOnly) queryOnly.checked = true;
    syncDsTypeExtras('');
    const password = document.getElementById('dsPassword');
    if (password) password.placeholder = '????????';
  }

  function fillDsForm(ds) {
    const setVal = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = value == null ? '' : String(value);
    };
    setVal('dsType', ds.type || '');
    setVal('dsName', ds.name || '');
    setVal('dsHost', ds.host || '');
    setVal('dsPort', ds.port || DEFAULT_PORTS[ds.type] || '');
    setVal('dsDatabase', ds.database || '');
    setVal('dsUser', ds.username || ds.user || '');
    setVal('dsPassword', '');
    setVal('dsExtra', ds.extra || '');
    const queryOnly = document.getElementById('dsQueryOnly');
    if (queryOnly) queryOnly.checked = isDsQueryOnly(ds);
    const password = document.getElementById('dsPassword');
    if (password) {
      password.placeholder = ds.has_password ? '已保存密码，留空则不修改' : '????????';
    }
    syncDsTypeExtras(ds.type || '');
  }

  function isDsQueryOnly(ds) {
    if (!ds) return false;
    return ds.query_only === true || ds.query_only === 1;
  }

  function setAddDsModalMode(mode) {
    const title = document.getElementById('addDsModalTitle');
    const subtitle = document.getElementById('addDsModalSubtitle');
    if (mode === 'edit') {
      if (title) title.textContent = '编辑数据源';
      if (subtitle) subtitle.textContent = '修改连接信息后可测试并保存';
    } else {
      if (title) title.textContent = '添加数据源';
      if (subtitle) subtitle.textContent = '保存连接信息，供查询与流水线使用';
    }
  }

  function openAddDs() {
    editingDsId = null;
    resetAddDsForm();
    setAddDsModalMode('add');
    showAddDsTest('', '');
    markSaveReady('saveDsBtn', false);
    addDsModal?.classList.add('open');
  }

  function openEditDs(ds) {
    if (!ds) return;
    editingDsId = ds.id;
    fillDsForm(ds);
    setAddDsModalMode('edit');
    showAddDsTest('', '');
    markSaveReady('saveDsBtn', false);
    addDsModal?.classList.add('open');
  }

  function closeAddDs() {
    addDsModal?.classList.remove('open');
    editingDsId = null;
    showAddDsTest('', '');
    markSaveReady('saveDsBtn', false);
  }

  function getProviderCssClass(p) {
    return 'provider-' + (p || 'custom');
  }


  function mapCatalogToPlatformModels(data) {
    const items = [];
    (data?.routes || []).forEach((r) => {
      items.push({
        id: 'gw:route:' + r.model_id,
        name: r.model_id,
        displayName: '路由 · ' + (r.display_name || r.model_id),
        provider: 'gateway',
        providerName: '平台路由',
        apiKey: '',
        baseUrl: '',
        useGateway: true,
        kind: 'route',
        description: r.description || '',
        status: 'connected',
        active: false,
      });
    });
    (data?.models || []).forEach((m) => {
      items.push({
        id: 'gw:model:' + m.model_id,
        name: m.model_id,
        displayName: m.display_name || m.model_id,
        provider: 'gateway',
        providerName: '平台 · ' + (m.provider_name || 'Gateway'),
        apiKey: '',
        baseUrl: '',
        useGateway: true,
        kind: 'model',
        status: 'connected',
        active: false,
      });
    });
    return items;
  }

  async function loadPlatformModels() {
    try {
      const res = await apiFetch('/api/gateway/v1/catalog');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        platformModels = [];
        return platformModels;
      }
      platformModels = mapCatalogToPlatformModels(data);
      platformModels.forEach((m) => { m.active = m.id === activeModelId; });
      // If user has no usable personal model, auto-select first platform model
      const personalOk = models.some((m) => m.id === activeModelId && m.apiKey);
      const platformOk = platformModels.some((m) => m.id === activeModelId);
      if ((!activeModelId || (!personalOk && !platformOk)) && platformModels.length) {
        activeModelId = platformModels[0].id;
        platformModels.forEach((m) => { m.active = m.id === activeModelId; });
        models.forEach((m) => { m.active = false; });
        localStorage.setItem('active_model_id', activeModelId);
      }
      updateCurrentModelLabel();
      return platformModels;
    } catch (_) {
      platformModels = [];
      return platformModels;
    }
  }

  function renderModelList() {
    if (!modelListEl) return;
    if (!models.length && !platformModels.length) {
      modelListEl.innerHTML = `
        <div class="model-empty">
          <div class="model-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>
          </div>
          <h4>还没有可用模型</h4>
          <p>管理员可在「Gateway 管理」配置平台模型；你也可以点击下方「添加模型」使用自己的 API Key。</p>
        </div>`;
      return;
    }
    modelListEl.innerHTML = '';
    if (platformModels.length) {
      const head = document.createElement('div');
      head.className = 'skill-category-label';
      head.textContent = '平台模型（管理员已配置，无需填写 Key）';
      modelListEl.appendChild(head);
      platformModels.forEach((model) => {
        const isActive = model.id === activeModelId;
        const card = document.createElement('div');
        card.className = 'model-card connected' + (isActive ? ' active-model' : '');
        card.innerHTML = `
          <div class="model-card-header">
            <div class="model-card-left">
              <span class="model-provider-badge provider-custom">${escapeHtml(model.providerName || '平台')}</span>
              <span class="model-card-name">${escapeHtml(model.displayName || model.name)}</span>
            </div>
            <div class="model-card-actions">
              <button class="model-activate-btn ${isActive ? 'is-active' : ''}" data-action="activate-platform" data-id="${escapeHtml(model.id)}" ${isActive ? 'disabled' : ''}>
                <span class="activate-indicator">${isActive ? '✓' : ''}</span>
                ${isActive ? '当前模型' : '设为当前'}
              </button>
            </div>
          </div>
          <div class="model-info-row">
            <span class="model-connection-status connected">
              <span class="status-dot-sm status-ok"></span>
              平台托管
            </span>
            <span class="model-info-divider"></span>
            <span class="model-info-item">${model.kind === 'route' ? '路由' : '逻辑模型'} <b>${escapeHtml(model.name)}</b></span>
            <span class="model-info-divider"></span>
            <span class="model-info-item">Key <b class="secret-status is-set">服务端</b></span>
          </div>
          <div class="model-card-bottom">
            <div class="model-base-url"><span class="endpoint-label">说明</span>${escapeHtml(model.description || '由管理员在 Gateway 管理中维护')}</div>
            <div class="model-secondary-actions">
              <button class="model-test-btn" data-action="test-platform" data-id="${escapeHtml(model.id)}">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>
                测试连接
              </button>
            </div>
          </div>
          <div class="test-result" hidden></div>`;
        modelListEl.appendChild(card);
      });
    }
    if (models.length) {
      const head2 = document.createElement('div');
      head2.className = 'skill-category-label';
      head2.style.marginTop = '14px';
      head2.textContent = '我的模型（需自行填写 API Key）';
      modelListEl.appendChild(head2);
    }
    models.forEach((model) => {
      const isActive = model.id === activeModelId;
      const card = document.createElement('div');
      const statusClass = model.status === 'connected' ? 'connected' : model.status === 'error' ? 'error' : '';
      card.className = 'model-card ' + statusClass + (isActive ? ' active-model' : '');
      const keyStatus = model.apiKey ? '已配置' : '未配置';
      const statusText = model.status === 'connected' ? '已连接' : model.status === 'error' ? '连接失败' : '待测试';
      card.innerHTML = `
        <div class="model-card-header">
          <div class="model-card-left">
            <span class="model-provider-badge ${getProviderCssClass(model.provider)}">${escapeHtml(model.providerName)}</span>
            <span class="model-card-name">${escapeHtml(model.displayName || model.name)}</span>
          </div>
          <div class="model-card-actions">
            <button class="model-activate-btn ${isActive ? 'is-active' : ''}" data-action="activate" data-id="${escapeHtml(model.id)}" ${isActive ? 'disabled' : ''}>
              <span class="activate-indicator">${isActive ? '✓' : ''}</span>
              ${isActive ? '当前模型' : '设为当前'}
            </button>
          </div>
        </div>
        <div class="model-info-row">
          <span class="model-connection-status ${model.status}">
            <span class="status-dot-sm ${model.status === 'connected' ? 'status-ok' : model.status === 'error' ? 'status-error' : 'status-pending'}"></span>
            ${statusText}
          </span>
          <span class="model-info-divider"></span>
          <span class="model-info-item">模型 <b>${escapeHtml(model.name)}</b></span>
          <span class="model-info-divider"></span>
          <span class="model-info-item">Key <b class="secret-status ${model.apiKey ? 'is-set' : ''}">${keyStatus}</b></span>
        </div>
        <div class="model-card-bottom">
          <div class="model-base-url"><span class="endpoint-label">API</span>${escapeHtml(model.baseUrl || '-')}</div>
          <div class="model-secondary-actions">
            <button class="model-test-btn" data-action="test" data-id="${escapeHtml(model.id)}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>
              测试连接
            </button>
            <button class="model-delete-btn" data-action="delete" data-id="${escapeHtml(model.id)}" title="删除模型">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="m19 6-1 14H6L5 6"/><path d="M9 6V4h6v2"/></svg>
            </button>
          </div>
        </div>
        <div class="test-result" hidden></div>`;
      modelListEl.appendChild(card);
    });
  }


  async function testPlatformConnection(modelId) {
    const model = platformModels.find((m) => m.id === modelId);
    if (!model) return;
    const card = modelListEl?.querySelector('.model-test-btn[data-action="test-platform"][data-id="' + modelId + '"]')?.closest('.model-card');
    const resultEl = card?.querySelector('.test-result');
    const testBtn = card?.querySelector('.model-test-btn');
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.className = 'test-result';
      resultEl.textContent = '正在通过 Gateway 测试平台模型...';
    }
    if (testBtn) testBtn.disabled = true;
    try {
      const res = await apiFetch('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: buildModelPayload(model) }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok || !j.ok) {
        if (resultEl) {
          resultEl.className = 'test-result error';
          resultEl.textContent = j.message || j.error || '连接失败';
        }
      } else if (resultEl) {
        resultEl.className = 'test-result ok';
        resultEl.textContent = '连接成功：' + (j.reply || j.message || 'OK');
      }
    } catch (e) {
      if (resultEl) {
        resultEl.className = 'test-result error';
        resultEl.textContent = '连接失败：' + (e.message || e);
      }
    }
    if (testBtn) testBtn.disabled = false;
  }

  async function testConnection(modelId) {
    const model = models.find((m) => m.id === modelId);
    if (!model) return;
    const card = modelListEl?.querySelector(`.model-card .model-test-btn[data-id="${modelId}"]`)?.closest('.model-card');
    const resultEl = card?.querySelector('.test-result');
    const testBtn = card?.querySelector('.model-test-btn');
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.className = 'test-result';
      resultEl.textContent = '正在调用第三方大模型测试连接...';
    }
    if (testBtn) testBtn.disabled = true;
    try {
      const res = await apiFetch('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: buildModelPayload(model) }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok || !j.ok) {
        model.status = 'error';
        persistModels();
        if (resultEl) {
          resultEl.className = 'test-result error';
          resultEl.textContent = j.message || j.error || '连接失败';
        }
      } else {
        model.status = 'connected';
        persistModels();
        if (resultEl) {
          resultEl.className = 'test-result ok';
          resultEl.textContent = '连接成功：' + (j.reply || j.message || 'OK');
        }
      }
    } catch (e) {
      model.status = 'error';
      persistModels();
      if (resultEl) {
        resultEl.className = 'test-result error';
        resultEl.textContent = '连接失败：' + (e.message || e);
      }
    }
    updateCurrentModelLabel();
    renderModelList();
    initOverview();
  }

  function renderDataSourceList() {
    if (!dsListEl) return;
    const search = (document.getElementById('dsSearchInput')?.value || '').toLowerCase();
    const typeFilter = document.getElementById('dsTypeFilter')?.value || '';
    const list = dataSources.filter((ds) => {
      const hitSearch = !search || (ds.name || '').toLowerCase().includes(search) || (ds.host || '').toLowerCase().includes(search);
      const hitType = !typeFilter || ds.type === typeFilter;
      return hitSearch && hitType;
    });
    if (!list.length) {
      dsListEl.innerHTML = '<div class="ds-empty">暂无数据源，点击上方「添加数据源」开始配置</div>';
      return;
    }
    dsListEl.innerHTML = '';
    list.forEach((ds) => {
      const card = document.createElement('div');
      card.className = 'ds-card ' + (ds.status === 'connected' ? 'connected' : ds.status === 'error' ? 'error' : '');
      card.innerHTML = `
        <div class="ds-card-header">
          <div class="ds-card-left">
            <span class="ds-type-badge ds-type-${escapeHtml(ds.type || 'default')}">${escapeHtml((ds.type || '').toUpperCase())}</span>
            <span class="ds-card-name">${escapeHtml(ds.name)}</span>
            <span class="ds-perm-badge ${isDsQueryOnly(ds) ? 'query-only' : 'writable'}">${isDsQueryOnly(ds) ? '仅查询' : '可写入'}</span>
          </div>
          <div class="ds-card-actions">
            <button class="ds-action-btn ds-action-edit" type="button" data-ds-action="edit" data-id="${ds.id}" title="编辑">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
              <span>编辑</span>
            </button>
            <button class="ds-action-btn ds-action-perm ${isDsQueryOnly(ds) ? 'is-active' : ''}" type="button" data-ds-action="toggle-query-only" data-id="${ds.id}" title="${isDsQueryOnly(ds) ? '当前为仅查询，点击可允许写入' : '点击开启仅查询，后续禁止写入'}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              <span>${isDsQueryOnly(ds) ? '仅查询·开' : '仅查询·关'}</span>
            </button>
            <button class="ds-action-btn ds-action-test" type="button" data-ds-action="test" data-id="${ds.id}" title="测试连接">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4"/><path d="M12 18v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/><path d="M4.93 19.07l2.83-2.83"/><path d="M16.24 7.76l2.83-2.83"/></svg>
              <span>测试</span>
            </button>
            <button class="ds-action-btn ds-action-delete" type="button" data-ds-action="delete" data-id="${ds.id}" title="删除">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              <span>删除</span>
            </button>
          </div>
        </div>
        <div class="ds-status-row">
          <span class="ds-host-info">${escapeHtml(ds.host)}:${escapeHtml(ds.port || '')}</span>
          <span class="${ds.status === 'connected' ? 'ds-status-ok' : ds.status === 'error' ? 'ds-status-error' : 'ds-status-idle'}">${ds.status === 'connected' ? '已连接' : ds.status === 'error' ? '失败' : '未测试'}</span>
        </div>
        <div class="ds-info-row">
          <span>库：${escapeHtml(ds.database || '-')}</span>
          <span>用户：${escapeHtml(ds.username || ds.user || '-')}</span>
          <span>权限：${isDsQueryOnly(ds) ? '仅查询（禁止写入）' : '允许写入'}</span>
        </div>`;
      dsListEl.appendChild(card);
    });
  }

  // ===== Knowledge base =====
  function kbDefaultConfig() {
    const localDefault = EMBEDDING_PRESETS.local[0];
    return {
      name: '',
      description: '',
      chunk_mode: 'recursive',
      chunk_size: 500,
      chunk_overlap: 50,
      min_chunk_chars: 50,
      embedding_model: localDefault.model,
      embedding_base_url: localDefault.baseUrl,
      embedding_dimension: localDefault.dimension,
      embedding_batch_size: 100,
      chroma_path: '',
      chroma_collection: 'ai_platform_knowledge',
      top_k: 5,
      score_threshold: 0.5,
    };
  }

  function kbFieldId(prefix, base) {
    if (!prefix) return base;
    return prefix + base.charAt(0).toUpperCase() + base.slice(1);
  }

  function getEmbeddingPresetsByMode(mode) {
    return EMBEDDING_PRESETS[mode === 'cloud' ? 'cloud' : 'local'] || [];
  }

  function resolveEmbeddingPreset(model, mode) {
    const value = (model || '').trim();
    if (!value) return null;
    const lists = mode
      ? getEmbeddingPresetsByMode(mode)
      : [...EMBEDDING_PRESETS.local, ...EMBEDDING_PRESETS.cloud];
    return lists.find((item) => item.id === value || item.model === value || item.label === value) || null;
  }

  function inferEmbeddingDeployMode(baseUrl, model) {
    const preset = resolveEmbeddingPreset(model);
    if (preset) {
      if (EMBEDDING_PRESETS.local.some((item) => item.id === preset.id)) return 'local';
      if (EMBEDDING_PRESETS.cloud.some((item) => item.id === preset.id)) return 'cloud';
    }
    const value = (baseUrl || '').trim().toLowerCase();
    if (!value) return 'local';
    if (value.includes('127.0.0.1') || value.includes('localhost') || value.includes('0.0.0.0')) return 'local';
    return 'cloud';
  }

  function embeddingPresetOptionsHtml(mode, selectedModel) {
    const presets = getEmbeddingPresetsByMode(mode);
    const matched = resolveEmbeddingPreset(selectedModel, mode);
    const isCustom = !matched;
    const options = presets.map((item) =>
      `<option value="${item.id}"${matched && matched.id === item.id ? ' selected' : ''}>${item.label}</option>`
    ).join('');
    return `<option value="__custom__"${isCustom ? ' selected' : ''}>自定义</option>${options}`;
  }

  function refreshEmbeddingPresetOptions(root, prefix = '', { keepSelection = false } = {}) {
    const modeEl = root.querySelector('#' + kbFieldId(prefix, 'embDeployMode'));
    const presetEl = root.querySelector('#' + kbFieldId(prefix, 'embPreset'));
    const modelEl = root.querySelector('#' + kbFieldId(prefix, 'embModel'));
    if (!modeEl || !presetEl) return;
    const mode = modeEl.value === 'cloud' ? 'cloud' : 'local';
    const currentModel = keepSelection ? (modelEl?.value || '') : '';
    const matched = resolveEmbeddingPreset(currentModel, mode);
    presetEl.innerHTML = embeddingPresetOptionsHtml(mode, matched ? matched.model : '');
    if (!matched) {
      const first = getEmbeddingPresetsByMode(mode)[0];
      if (first) presetEl.value = first.id;
    }
  }

  function updateEmbeddingCredentialUi(root, prefix = '') {
    const modeEl = root.querySelector('#' + kbFieldId(prefix, 'embDeployMode'));
    const mode = modeEl?.value === 'cloud' ? 'cloud' : 'local';
    const keyInput = root.querySelector('#' + kbFieldId(prefix, 'embApiKey'));
    const keyLabel = root.querySelector('[data-emb-key-label="' + prefix + '"]');
    const hintEl = root.querySelector('[data-emb-mode-hint="' + prefix + '"]');
    if (keyLabel) {
      keyLabel.innerHTML = mode === 'local'
        ? 'Embedding API Key <span class="form-label-optional">(Xinference 开启鉴权时必填，保存在本机浏览器)</span>'
        : 'Embedding API Key <span class="form-label-optional">(云端必填，保存在本机浏览器)</span>';
    }
    if (keyInput) {
      keyInput.placeholder = mode === 'local'
        ? '在 Xinference 控制台创建 API Key 后填写；未开启鉴权可留空'
        : '填写 OpenAI Embedding API Key';
    }
    if (hintEl) {
      hintEl.textContent = mode === 'local'
        ? '本地 Xinference 3+ 默认开启鉴权：请在 http://127.0.0.1:9997 登录后创建 API Key，填到此处再上传文档。'
        : '云模型调用可选 OpenAI Embedding 模型，需要填写 Base URL 和 API Key。';
    }
  }

  function syncEmbeddingPresetSelect(root, prefix = '') {
    const modeEl = root.querySelector('#' + kbFieldId(prefix, 'embDeployMode'));
    const modelEl = root.querySelector('#' + kbFieldId(prefix, 'embModel'));
    const presetEl = root.querySelector('#' + kbFieldId(prefix, 'embPreset'));
    if (!modeEl || !modelEl || !presetEl) return;
    const mode = modeEl.value === 'cloud' ? 'cloud' : 'local';
    const matched = resolveEmbeddingPreset(modelEl.value.trim(), mode);
    presetEl.value = matched ? matched.id : '__custom__';
    updateEmbeddingCredentialUi(root, prefix);
  }

  function applyEmbeddingPreset(root, prefix = '') {
    const presetEl = root.querySelector('#' + kbFieldId(prefix, 'embPreset'));
    const modelEl = root.querySelector('#' + kbFieldId(prefix, 'embModel'));
    const modeEl = root.querySelector('#' + kbFieldId(prefix, 'embDeployMode'));
    const urlEl = root.querySelector('#' + kbFieldId(prefix, 'embBaseUrl'));
    const dimEl = root.querySelector('#' + kbFieldId(prefix, 'embDim'));
    if (!presetEl || !modelEl || !modeEl) return;
    const mode = modeEl.value === 'cloud' ? 'cloud' : 'local';
    const selected = presetEl.value;
    if (selected === '__custom__') {
      updateEmbeddingCredentialUi(root, prefix);
      return;
    }
    const preset = resolveEmbeddingPreset(selected, mode) || getEmbeddingPresetsByMode(mode)[0];
    if (!preset) return;
    modelEl.value = preset.model;
    if (urlEl) urlEl.value = preset.baseUrl;
    if (dimEl) dimEl.value = preset.dimension;
    updateEmbeddingCredentialUi(root, prefix);
  }

  function applyEmbeddingDeployMode(root, prefix = '') {
    refreshEmbeddingPresetOptions(root, prefix, { keepSelection: false });
    applyEmbeddingPreset(root, prefix);
  }

  function bindKbConfigForm(root, prefix = '', { onEmbTest } = {}) {
    const presetEl = root.querySelector('#' + kbFieldId(prefix, 'embPreset'));
    const modelEl = root.querySelector('#' + kbFieldId(prefix, 'embModel'));
    const modeEl = root.querySelector('#' + kbFieldId(prefix, 'embDeployMode'));
    presetEl?.addEventListener('change', () => applyEmbeddingPreset(root, prefix));
    modelEl?.addEventListener('input', () => syncEmbeddingPresetSelect(root, prefix));
    modeEl?.addEventListener('change', () => applyEmbeddingDeployMode(root, prefix));
    refreshEmbeddingPresetOptions(root, prefix, { keepSelection: true });
    syncEmbeddingPresetSelect(root, prefix);
    updateEmbeddingCredentialUi(root, prefix);
    if (onEmbTest) {
      root.querySelector('[data-kb-action="test-embedding"]')?.addEventListener('click', onEmbTest);
    }
  }

  function renderKbConfigForm(kb, { prefix = '', showBasic = true, showCredentials = false, showEmbTest = false } = {}) {
    const id = (base) => kbFieldId(prefix, base);
    const defaults = kbDefaultConfig();
    const config = { ...defaults, ...kb };
    const deployMode = inferEmbeddingDeployMode(config.embedding_base_url, config.embedding_model);
    const basicSection = showBasic ? `
      <div class="kb-config-group">
        <div class="kb-config-group-title">基本信息</div>
        <label class="form-label" for="${id('kbName')}">名称</label>
        <input class="form-input" id="${id('kbName')}" value="${escapeHtml(config.name || '')}" placeholder="如：产品文档库">
        <label class="form-label" for="${id('kbDescription')}">描述 <span class="form-label-optional">(可选)</span></label>
        <textarea class="form-textarea kb-desc-input" id="${id('kbDescription')}" rows="2" placeholder="简要说明知识库用途">${escapeHtml(config.description || '')}</textarea>
      </div>` : '';

    const credentialsSection = showCredentials ? `
        <label class="form-label" for="${id('embApiKey')}" data-emb-key-label="${prefix}">Embedding API Key <span class="form-label-optional">(Xinference 开启鉴权时必填，保存在本机浏览器)</span></label>
        <input class="form-input" type="password" id="${id('embApiKey')}" placeholder="Xinference API Key；未开启鉴权可留空" autocomplete="off">
        ${showEmbTest ? `<button class="btn-test" type="button" data-kb-action="test-embedding">测试连接</button><div id="${id('embTestResult')}" class="test-result" hidden></div>` : ''}` : '';

    const chromaCredentials = showCredentials ? `
        <label class="form-label" for="${id('chromaApiKey')}">Chroma API Key <span class="form-label-optional">(仅本次页面)</span></label>
        <input class="form-input" type="password" id="${id('chromaApiKey')}" placeholder="留空使用本地 data/chroma">` : '';

    return `
      <div class="kb-config-stack">
        ${basicSection}
        <div class="kb-config-group">
          <div class="kb-config-group-title">检索</div>
          <div class="kb-config-row">
            <div class="kb-config-field">
              <label class="form-label" for="${id('topK')}">Top-K</label>
              <input class="form-input" type="number" id="${id('topK')}" min="1" max="50" value="${config.top_k}">
            </div>
            <div class="kb-config-field">
              <label class="form-label" for="${id('scoreThreshold')}">相似度阈值</label>
              <input class="form-input" type="number" id="${id('scoreThreshold')}" min="0" max="1" step="0.05" value="${config.score_threshold}">
              <p class="kb-config-inline-hint">本地 BGE 常见有效区间约 0.45–0.65；过高会漏召回。</p>
            </div>
          </div>
        </div>
        <div class="kb-config-group">
          <div class="kb-config-group-title">Embedding</div>
          <label class="form-label" for="${id('embDeployMode')}">调用方式</label>
          <select class="form-select" id="${id('embDeployMode')}">
            <option value="local"${deployMode === 'local' ? ' selected' : ''}>本地部署</option>
            <option value="cloud"${deployMode === 'cloud' ? ' selected' : ''}>云模型调用</option>
          </select>
          <label class="form-label" for="${id('embPreset')}">模型预设</label>
          <select class="form-select" id="${id('embPreset')}">${embeddingPresetOptionsHtml(deployMode, config.embedding_model)}</select>
          <label class="form-label" for="${id('embModel')}">模型名称</label>
          <input class="form-input" id="${id('embModel')}" value="${escapeHtml(config.embedding_model)}">
          <p class="kb-config-inline-hint" data-emb-mode-hint="${prefix}"></p>
          <div class="kb-config-row">
            <div class="kb-config-field kb-config-field-wide">
              <label class="form-label" for="${id('embBaseUrl')}">Base URL</label>
              <input class="form-input" id="${id('embBaseUrl')}" value="${escapeHtml(config.embedding_base_url)}">
            </div>
            <div class="kb-config-field">
              <label class="form-label" for="${id('embDim')}">维度</label>
              <input class="form-input" type="number" id="${id('embDim')}" value="${config.embedding_dimension}">
            </div>
          </div>
          ${credentialsSection}
        </div>
        <details class="kb-advanced-details">
          <summary>高级设置</summary>
          <div class="kb-advanced-body">
            <div class="kb-config-group">
              <div class="kb-config-group-title">切片</div>
              <label class="form-label" for="${id('chunkMode')}">模式</label>
              <select class="form-select" id="${id('chunkMode')}">
                <option value="recursive"${config.chunk_mode === 'recursive' ? ' selected' : ''}>递归分割</option>
                <option value="paragraph"${config.chunk_mode === 'paragraph' ? ' selected' : ''}>按段落</option>
                <option value="fixed"${config.chunk_mode === 'fixed' ? ' selected' : ''}>固定长度</option>
              </select>
              <div class="kb-config-row">
                <div class="kb-config-field">
                  <label class="form-label" for="${id('chunkSize')}">切片大小</label>
                  <input class="form-input" type="number" id="${id('chunkSize')}" min="100" value="${config.chunk_size}">
                </div>
                <div class="kb-config-field">
                  <label class="form-label" for="${id('chunkOverlap')}">重叠字符</label>
                  <input class="form-input" type="number" id="${id('chunkOverlap')}" min="0" value="${config.chunk_overlap}">
                </div>
                <div class="kb-config-field">
                  <label class="form-label" for="${id('minChunkChars')}">最小片段</label>
                  <input class="form-input" type="number" id="${id('minChunkChars')}" min="1" value="${config.min_chunk_chars}">
                </div>
              </div>
              <label class="form-label" for="${id('embBatchSize')}">Embedding 批大小</label>
              <input class="form-input" type="number" id="${id('embBatchSize')}" min="1" value="${config.embedding_batch_size}">
            </div>
            <div class="kb-config-group">
              <div class="kb-config-group-title">Chroma</div>
              <label class="form-label" for="${id('chromaPath')}">路径 / URL</label>
              <input class="form-input" id="${id('chromaPath')}" value="${escapeHtml(config.chroma_path)}" placeholder="留空=本地 data/chroma，或 http://host:port">
              <label class="form-label" for="${id('chromaCollection')}">共享 Collection</label>
              <input class="form-input" id="${id('chromaCollection')}" value="${escapeHtml(config.chroma_collection)}">
              ${chromaCredentials}
            </div>
          </div>
        </details>
        ${!showCredentials ? '<p class="kb-config-hint">本地部署会自动带出本机 Base URL；若选择云模型调用，请在创建后到索引配置里补充 API Key。</p>' : '<p class="kb-config-hint">本地部署默认走本机服务；云模型调用必须填写 Base URL 和 API Key。</p>'}
      </div>`;
  }

  function readKbConfigForm(root, prefix = '', { includeBasic = true } = {}) {
    const id = (base) => kbFieldId(prefix, base);
    const fieldValue = (base) => (root.querySelector('#' + id(base))?.value || '').trim();
    const defaults = kbDefaultConfig();
    const numOrDefault = (selector, fallback) => {
      const val = root.querySelector(selector)?.value;
      return val === '' || val == null ? fallback : Number(val);
    };
    const payload = {
      chunk_mode: root.querySelector('#' + id('chunkMode'))?.value || defaults.chunk_mode,
      chunk_size: numOrDefault('#' + id('chunkSize'), defaults.chunk_size),
      chunk_overlap: numOrDefault('#' + id('chunkOverlap'), defaults.chunk_overlap),
      min_chunk_chars: numOrDefault('#' + id('minChunkChars'), defaults.min_chunk_chars),
      embedding_model: fieldValue('embModel') || defaults.embedding_model,
      embedding_base_url: fieldValue('embBaseUrl') || defaults.embedding_base_url,
      embedding_dimension: numOrDefault('#' + id('embDim'), defaults.embedding_dimension),
      embedding_batch_size: numOrDefault('#' + id('embBatchSize'), defaults.embedding_batch_size),
      chroma_path: fieldValue('chromaPath'),
      chroma_collection: fieldValue('chromaCollection') || defaults.chroma_collection,
      top_k: numOrDefault('#' + id('topK'), defaults.top_k),
      score_threshold: numOrDefault('#' + id('scoreThreshold'), defaults.score_threshold),
    };
    if (includeBasic) {
      payload.name = fieldValue('kbName');
      payload.description = fieldValue('kbDescription');
    }
    return payload;
  }

  function loadApiKbConfigs() {
    let configs = loadStoredArray(API_KB_CONFIGS_KEY);
    if (!configs.length) {
      const legacy = loadStoredObject('knowledge_api_config');
      if (legacy.name || legacy.url) {
        configs = [{
          id: 'api-' + Date.now(),
          provider: legacy.provider || 'dify',
          name: legacy.name || '',
          url: legacy.url || '',
          apiKey: legacy.apiKey || '',
          datasetId: legacy.datasetId || '',
          headers: legacy.headers || '',
          enabled: true,
        }];
        localStorage.setItem(API_KB_CONFIGS_KEY, JSON.stringify(configs));
      }
    }
    return configs.map((config) => ({ enabled: true, ...config }));
  }

  function saveApiKbConfigs(configs) {
    localStorage.setItem(API_KB_CONFIGS_KEY, JSON.stringify(configs));
    apiKbConfigs = configs;
  }

  function kbApiProviderLabel(provider) {
    return ({ dify: 'Dify', fastgpt: 'FastGPT', ragflow: 'RagFlow', custom: '自定义 API' })[provider] || provider;
  }

  function renderKbApiConfigForm(config = {}) {
    const value = {
      provider: config.provider || 'dify',
      name: config.name || '',
      url: config.url || '',
      apiKey: config.apiKey || '',
      datasetId: config.datasetId || '',
      headers: config.headers || '',
    };
    return `
      <div class="kb-config-stack">
        <div class="kb-config-group">
          <div class="kb-config-group-title">接口知识库参数</div>
          <div class="kb-config-row">
            <div class="kb-config-field">
              <label class="form-label" for="modalApiProvider">知识库厂商</label>
              <select class="form-select" id="modalApiProvider">
                <option value="dify"${value.provider === 'dify' ? ' selected' : ''}>Dify</option>
                <option value="fastgpt"${value.provider === 'fastgpt' ? ' selected' : ''}>FastGPT</option>
                <option value="ragflow"${value.provider === 'ragflow' ? ' selected' : ''}>RagFlow</option>
                <option value="custom"${value.provider === 'custom' ? ' selected' : ''}>自定义 API</option>
              </select>
            </div>
            <div class="kb-config-field">
              <label class="form-label" for="modalApiName">知识库名称</label>
              <input class="form-input" id="modalApiName" value="${escapeHtml(value.name)}" placeholder="如：企业产品知识库">
            </div>
          </div>
          <label class="form-label" for="modalApiUrl">接口地址</label>
          <input class="form-input" id="modalApiUrl" value="${escapeHtml(value.url)}" placeholder="https://example.com/api/knowledge/search">
          <div class="kb-config-row">
            <div class="kb-config-field">
              <label class="form-label" for="modalApiKey">API Key</label>
              <input class="form-input" type="password" id="modalApiKey" value="${escapeHtml(value.apiKey)}" placeholder="输入接口密钥">
            </div>
            <div class="kb-config-field">
              <label class="form-label" for="modalApiDatasetId">知识库 ID</label>
              <input class="form-input" id="modalApiDatasetId" value="${escapeHtml(value.datasetId)}" placeholder="dataset / collection id">
            </div>
          </div>
          <label class="form-label" for="modalApiHeaders">请求 Header <span class="form-label-optional">(JSON，可选)</span></label>
          <textarea class="form-textarea" id="modalApiHeaders" rows="2" placeholder='{"X-Tenant-Id":"tenant-001"}'>${escapeHtml(value.headers)}</textarea>
        </div>
      </div>`;
  }

  function readKbApiConfigForm() {
    return {
      provider: document.getElementById('modalApiProvider')?.value || 'custom',
      name: getFieldValue('modalApiName'),
      url: getFieldValue('modalApiUrl'),
      apiKey: document.getElementById('modalApiKey')?.value.trim() || '',
      datasetId: getFieldValue('modalApiDatasetId'),
      headers: document.getElementById('modalApiHeaders')?.value.trim() || '',
    };
  }

  function getSelfKbEnabledMap() {
    return loadStoredObject(KB_SELF_ENABLED_KEY) || {};
  }

  function isKbEnabled(type, id) {
    if (type === 'api') {
      const config = apiKbConfigs.find((item) => item.id === id);
      return config?.enabled !== false;
    }
    const map = getSelfKbEnabledMap();
    return map[String(id)] !== false;
  }

  function setKbEnabled(type, id, enabled) {
    if (type === 'api') {
      const configs = loadApiKbConfigs().map((item) => (
        item.id === id ? { ...item, enabled } : item
      ));
      saveApiKbConfigs(configs);
    } else {
      const map = getSelfKbEnabledMap();
      map[String(id)] = enabled;
      localStorage.setItem(KB_SELF_ENABLED_KEY, JSON.stringify(map));
    }
    renderKbConfigRegistry();
    updateChatKnowledgeBaseOptions();
    initOverview();
  }

  function toggleKbRegistryEnabled(type, id) {
    setKbEnabled(type, id, !isKbEnabled(type, id));
  }

  function openKbDetailModal() {
    const kb = knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId);
    const title = document.getElementById('kbDetailModalTitle');
    if (title) title.textContent = kb ? `知识库配置 · ${kb.name}` : '知识库配置';
    kbDetailModal?.classList.add('open');
  }

  function closeKbDetailModal() {
    kbDetailModal?.classList.remove('open');
    stopKbPolling();
    if (selectedKnowledgeBaseId) getKnowledgeBaseCredentials(selectedKnowledgeBaseId);
  }

  function isKbRegistryItemActive(type, id) {
    if (!activeKbRegistry) return false;
    return activeKbRegistry.type === type && String(activeKbRegistry.id) === String(id);
  }

  function renderKbConfigRegistry() {
    const registry = document.getElementById('kbConfigRegistry');
    if (!registry) return;
    apiKbConfigs = loadApiKbConfigs();
    const items = [
      ...apiKbConfigs.map((config) => ({
        type: 'api',
        id: config.id,
        name: config.name || '未命名接口知识库',
        meta: `${kbApiProviderLabel(config.provider)} · ${config.url || '未填写接口地址'}`,
      })),
      ...knowledgeBases.map((kb) => ({
        type: 'self',
        id: kb.id,
        name: kb.name,
        meta: `${kb.document_count} 个文档 · ${kb.chunk_count} 个片段`,
      })),
    ];
    if (!items.length) {
      registry.innerHTML = '<div class="doc-empty-hint">暂无知识库配置，点击右上角「新增知识库」开始。</div>';
      return;
    }
    registry.innerHTML = `
      <div class="kb-registry-list">
        <div class="kb-registry-list-head">
          <span>名称</span>
          <span>类型</span>
          <span>说明</span>
          <span>操作</span>
        </div>
        <div class="kb-registry-rows">
          ${items.map((item) => {
            const active = isKbRegistryItemActive(item.type, item.id);
            const enabled = isKbEnabled(item.type, item.id);
            const typeLabel = item.type === 'api' ? 'API 接口' : '自定义';
            const typeClass = item.type === 'api' ? 'api' : 'self';
            const disabledClass = enabled ? '' : ' disabled-row';
            return `
              <div class="kb-registry-row ${active ? 'active' : ''}${disabledClass}">
                <div class="kb-registry-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
                <div class="kb-registry-type-cell">
                  <span class="kb-type-badge ${typeClass}">${typeLabel}</span>
                </div>
                <div class="kb-registry-meta" title="${escapeHtml(item.meta)}">${escapeHtml(item.meta)}</div>
                <div class="kb-registry-actions">
                  <span class="kb-enabled-status ${enabled ? 'online' : 'offline'}">${enabled ? '生效' : '失效'}</span>
                  <button class="btn-secondary kb-configure-btn" type="button"
                    data-registry-configure="1"
                    data-registry-type="${item.type}"
                    data-registry-id="${escapeHtml(String(item.id))}">配置</button>
                  <button class="btn-secondary kb-toggle-btn" type="button"
                    data-registry-toggle="1"
                    data-registry-type="${item.type}"
                    data-registry-id="${escapeHtml(String(item.id))}">${enabled ? '设为失效' : '设为生效'}</button>
                  <button class="btn-danger kb-delete-btn" type="button"
                    data-registry-delete="1"
                    data-registry-type="${item.type}"
                    data-registry-id="${escapeHtml(String(item.id))}">删除</button>
                </div>
              </div>`;
          }).join('')}
        </div>
      </div>`;
  }

  function setCreateKbModalType(type) {
    const value = type === 'self' ? 'self' : 'api';
    const typeSelect = document.getElementById('createKbType');
    const apiHost = document.getElementById('createKbApiFormHost');
    const selfHost = document.getElementById('createKbSelfFormHost');
    const testBtn = document.getElementById('testCreateKbApi');
    const deleteBtn = document.getElementById('deleteKbConfigBtn');
    if (typeSelect) typeSelect.value = value;
    if (apiHost) apiHost.hidden = value !== 'api';
    if (selfHost) selfHost.hidden = value !== 'self';
    if (testBtn) {
      testBtn.hidden = value !== 'api';
      if (value === 'api') testBtn.removeAttribute('hidden');
    }
    if (deleteBtn) deleteBtn.hidden = !(editingKbModal && editingKbModal.type === 'api' && value === 'api');
    setInlineStatus('createKbModalStatus', '', '');
  }

  function openKbConfigModal(options = {}) {
    const { type = 'api', editId = null } = options;
    editingKbModal = editId ? { type, id: editId } : null;
    const title = document.getElementById('createKbModalTitle');
    const submitBtn = document.getElementById('submitCreateKb');
    const typeSelect = document.getElementById('createKbType');
    const apiHost = document.getElementById('createKbApiFormHost');
    const selfHost = document.getElementById('createKbSelfFormHost');
    if (title) title.textContent = editId ? '编辑知识库配置' : '新增知识库配置';
    if (submitBtn) submitBtn.textContent = editId ? '保存' : (type === 'self' ? '创建' : '保存');
    if (typeSelect) typeSelect.disabled = Boolean(editId);
    if (apiHost) {
      const config = editId && type === 'api'
        ? apiKbConfigs.find((item) => item.id === editId) || {}
        : {};
      apiHost.innerHTML = renderKbApiConfigForm(config);
      bindKbApiConfigForm(apiHost);
    }
    if (selfHost) {
      if (type === 'self') {
        const config = editId
          ? knowledgeBases.find((item) => item.id === Number(editId)) || kbDefaultConfig()
          : kbDefaultConfig();
        selfHost.innerHTML = renderKbConfigForm(config, { prefix: 'create', showBasic: true, showCredentials: false });
        bindKbConfigForm(selfHost, 'create');
        syncEmbeddingPresetSelect(selfHost, 'create');
      } else {
        selfHost.innerHTML = '';
      }
    }
    setCreateKbModalType(type);
    createKbModal?.classList.add('open');
    if (type === 'api') document.getElementById('modalApiName')?.focus();
    else document.getElementById('createKbName')?.focus();
  }

  function closeCreateKbModal() {
    createKbModal?.classList.remove('open');
    editingKbModal = null;
    activeKbRegistry = null;
    const typeSelect = document.getElementById('createKbType');
    if (typeSelect) typeSelect.disabled = false;
    setInlineStatus('createKbModalStatus', '', '');
    renderKbConfigRegistry();
  }

  function kbApiProviderHint(provider) {
    return ({
      dify: '建议填写 Dify API 根地址，例如 https://api.dify.ai/v1',
      fastgpt: '建议填写 FastGPT 知识库接口完整地址',
      ragflow: '建议填写 RagFlow API 根地址，例如 http://host/api/v1',
      custom: '填写可访问的 HTTP(S) 检索接口地址',
    })[provider] || '填写可访问的 HTTP(S) 接口地址';
  }

  function bindKbApiConfigForm(root) {
    const providerEl = root?.querySelector('#modalApiProvider') || document.getElementById('modalApiProvider');
    const urlEl = root?.querySelector('#modalApiUrl') || document.getElementById('modalApiUrl');
    if (!providerEl || providerEl.dataset.bound === '1') return;
    providerEl.dataset.bound = '1';
    const syncHint = () => {
      if (urlEl) urlEl.placeholder = kbApiProviderHint(providerEl.value || 'custom');
    };
    providerEl.addEventListener('change', syncHint);
    syncHint();
  }

  async function testCreateKbApiConnection() {
    const value = readKbApiConfigForm();
    const statusEl = document.getElementById('createKbModalStatus');
    const btn = document.getElementById('testCreateKbApi');
    if (!/^https?:\/\//i.test(value.url || '')) {
      setInlineStatus('createKbModalStatus', '请输入有效的 HTTP(S) 接口地址', 'error');
      showAppToast('请先填写有效的接口地址', 'warn');
      statusEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      document.getElementById('modalApiUrl')?.focus();
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = '测试中...';
    }
    setInlineStatus('createKbModalStatus', '正在测试接口连接...', '');
    statusEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    try {
      const data = await knowledgeApi('/api-config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: value.provider || 'custom',
          url: value.url,
          api_key: value.apiKey || '',
          dataset_id: value.datasetId || '',
          headers: value.headers || '',
        }),
      });
      const message = data.message || '连接成功';
      if (data.ok) {
        setInlineStatus('createKbModalStatus', message, 'ok');
        showAppToast(message, 'ok');
      } else {
        setInlineStatus('createKbModalStatus', message, 'error');
        showAppToast(message, 'warn');
      }
    } catch (error) {
      const message = error.message || '连接失败';
      setInlineStatus('createKbModalStatus', message, 'error');
      showAppToast(message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '测试连接';
      }
    }
  }

  async function submitKbConfigModal() {
    const type = document.getElementById('createKbType')?.value === 'self' ? 'self' : 'api';
    const submitBtn = document.getElementById('submitCreateKb');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '保存中...';
    }
    try {
      if (type === 'api') {
        const value = readKbApiConfigForm();
        if (!value.name || !value.url) {
          setInlineStatus('createKbModalStatus', '请填写知识库名称和接口地址', 'error');
          return;
        }
        const configs = loadApiKbConfigs();
        if (editingKbModal?.type === 'api' && editingKbModal.id) {
          const index = configs.findIndex((item) => item.id === editingKbModal.id);
          if (index >= 0) configs[index] = { ...configs[index], ...value };
        } else {
          configs.push({ id: 'api-' + Date.now(), enabled: true, ...value });
        }
        saveApiKbConfigs(configs);
        closeCreateKbModal();
        renderKbConfigRegistry();
        initOverview();
        return;
      }

      const host = document.getElementById('createKbSelfFormHost');
      const payload = readKbConfigForm(host, 'create', { includeBasic: true });
      if (!payload.name) {
        setInlineStatus('createKbModalStatus', '请填写知识库名称', 'error');
        document.getElementById('createKbName')?.focus();
        return;
      }
      const created = await knowledgeApi('', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      closeCreateKbModal();
      activeKbTab = 'documents';
      activeKbRegistry = { type: 'self', id: created.id };
      await loadKnowledgeBases(created.id, { openDetailModal: true });
    } catch (error) {
      setInlineStatus('createKbModalStatus', error.message || '保存失败', 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        const currentType = document.getElementById('createKbType')?.value === 'self' ? 'self' : 'api';
        submitBtn.textContent = editingKbModal ? '保存' : (currentType === 'self' ? '创建' : '保存');
      }
    }
  }

  async function deleteApiKbConfig() {
    if (!editingKbModal || editingKbModal.type !== 'api') return;
    const config = apiKbConfigs.find((item) => item.id === editingKbModal.id);
    if (!config) return;
    const ok = await confirmAppDialog({
      title: '删除接口知识库',
      subtitle: '配置将被永久移除',
      message: '删除后将无法在对话中继续选用该接口知识库，确认继续？',
      metaHtml: `即将删除：<strong>${escapeHtml(config.name || '未命名')}</strong>`,
      actionLabel: '确认删除',
    });
    if (!ok) return;
    const configs = loadApiKbConfigs().filter((item) => item.id !== editingKbModal.id);
    saveApiKbConfigs(configs);
    closeCreateKbModal();
    renderKbConfigRegistry();
    initOverview();
    showAppToast('接口知识库已删除', 'ok');
  }

  async function configureKbRegistryItem(type, id) {
    activeKbRegistry = { type, id };
    if (type === 'api') {
      selectedKnowledgeBaseId = null;
      renderKbConfigRegistry();
      openKbConfigModal({ type: 'api', editId: id });
      return;
    }
    await selectKnowledgeBase(Number(id));
    activeKbTab = 'documents';
    renderKbConfigRegistry();
    openKbDetailModal();
  }

  async function deleteKbRegistryItem(type, id) {
    if (type === 'api') {
      const config = apiKbConfigs.find((item) => item.id === id);
      if (!config) return;
      const ok = await confirmAppDialog({
        title: '删除接口知识库',
        subtitle: '配置将被永久移除',
        message: '删除后将无法在对话中继续选用该接口知识库，确认继续？',
        metaHtml: `即将删除：<strong>${escapeHtml(config.name || '未命名')}</strong>`,
        actionLabel: '确认删除',
      });
      if (!ok) return;
      saveApiKbConfigs(loadApiKbConfigs().filter((item) => item.id !== id));
      if (activeKbRegistry?.type === 'api' && activeKbRegistry.id === id) activeKbRegistry = null;
      renderKbConfigRegistry();
      initOverview();
      showAppToast('接口知识库已删除', 'ok');
      return;
    }
    const kb = knowledgeBases.find((item) => item.id === Number(id));
    if (!kb) return;
    const ok = await confirmAppDialog({
      title: '删除知识库',
      subtitle: '文档与向量将一并清除',
      message: '将删除该知识库下的全部文档、切片与向量索引，此操作不可恢复。',
      metaHtml: `即将删除：<strong>${escapeHtml(kb.name)}</strong>`,
      actionLabel: '确认删除',
    });
    if (!ok) return;
    selectedKnowledgeBaseId = kb.id;
    closeKbDetailModal();
    try {
      const credentials = getKnowledgeBaseCredentials();
      await knowledgeApi('/' + kb.id, {
        method: 'DELETE',
        headers: { 'X-Chroma-Api-Key': credentials.chromaApiKey },
      });
      const enabledMap = getSelfKbEnabledMap();
      delete enabledMap[String(kb.id)];
      localStorage.setItem(KB_SELF_ENABLED_KEY, JSON.stringify(enabledMap));
      clearStoredKbCredentials(kb.id);
      selectedKnowledgeBaseId = null;
      activeKbRegistry = null;
      localStorage.removeItem('selected_knowledge_base_id');
      await loadKnowledgeBases();
      showAppToast('知识库已删除', 'ok');
    } catch (error) {
      showAppToast('删除失败：' + (error.message || error), 'error');
    }
  }

  async function handleKbRegistryClick(type, id) {
    await configureKbRegistryItem(type, id);
  }

  function setKnowledgeMode(mode) {
    if (mode === 'self' && selectedKnowledgeBaseId) {
      openKbDetailModal();
      return;
    }
    if (mode === 'self' && !knowledgeBases.length) loadKnowledgeBases();
  }

  async function knowledgeApi(path, options = {}) {
    const response = await apiFetch('/api/knowledge-bases' + path, options);
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.error || ('请求失败（HTTP ' + response.status + '）'));
    }
    return data;
  }

  function normalizeServiceBase(url) {
    const value = (url || '').trim().replace(/\/+$/, '');
    if (!value) return '';
    return value.replace(/\/embeddings$/, '');
  }

  function getKnowledgeBaseById(knowledgeBaseId = selectedKnowledgeBaseId) {
    return knowledgeBases.find((item) => item.id === Number(knowledgeBaseId)) || null;
  }

  function readKbCredentialsFromUi(knowledgeBaseId = selectedKnowledgeBaseId) {
    const id = Number(knowledgeBaseId) || 0;
    const stored = getStoredKbCredentials(id);
    if (id && id === selectedKnowledgeBaseId) {
      const embeddingInput = document.getElementById('embApiKey');
      const chromaInput = document.getElementById('chromaApiKey');
      if (embeddingInput || chromaInput) {
        const next = {
          embeddingApiKey: embeddingInput?.value.trim() || stored.embeddingApiKey || '',
          chromaApiKey: chromaInput?.value.trim() || stored.chromaApiKey || '',
        };
        setStoredKbCredentials(id, next);
        return next;
      }
    }
    return stored;
  }

  function resolveEmbeddingApiKey(knowledgeBaseId = selectedKnowledgeBaseId) {
    const explicit = readKbCredentialsFromUi(knowledgeBaseId).embeddingApiKey;
    if (explicit) return explicit;

    const kb = getKnowledgeBaseById(knowledgeBaseId);
    const baseUrl = document.getElementById('embBaseUrl')?.value?.trim()
      || kb?.embedding_base_url
      || LOCAL_EMBEDDING_BASE_URL;
    const model = document.getElementById('embModel')?.value?.trim() || kb?.embedding_model || '';
    // Local Xinference may run without auth; never invent a fake Bearer token.
    if (inferEmbeddingDeployMode(baseUrl, model) === 'local') return '';

    const active = getActiveModel();
    if (!kb || !active?.apiKey) return '';

    const embeddingBase = normalizeServiceBase(baseUrl);
    const chatBase = normalizeServiceBase(active.baseUrl);
    if (chatBase && embeddingBase === chatBase) return active.apiKey;
    if (!chatBase && embeddingBase === CLOUD_OPENAI_BASE_URL && active.provider === 'openai') {
      return active.apiKey;
    }
    return '';
  }

  function getEmbeddingKeyHint(knowledgeBaseId = selectedKnowledgeBaseId) {
    const kb = getKnowledgeBaseById(knowledgeBaseId);
    const baseUrl = kb?.embedding_base_url || LOCAL_EMBEDDING_BASE_URL;
    const isLocal = inferEmbeddingDeployMode(baseUrl, kb?.embedding_model || '') === 'local';
    if (isLocal) {
      return `本地 Embedding 服务已开启鉴权，请填写有效的 API Key（当前地址：${baseUrl}）。可在 Xinference 控制台创建 Key；若未开鉴权可留空。`;
    }
    return `请填写与 Embedding 服务匹配的 API Key（当前地址：${baseUrl}）。聊天模型的 Key 仅在双方 Base URL 一致时才会自动复用。`;
  }

  function isLocalEmbeddingConfig(knowledgeBaseId = selectedKnowledgeBaseId) {
    const kb = getKnowledgeBaseById(knowledgeBaseId);
    const baseUrl = document.getElementById('embBaseUrl')?.value?.trim()
      || kb?.embedding_base_url
      || LOCAL_EMBEDDING_BASE_URL;
    const model = document.getElementById('embModel')?.value?.trim() || kb?.embedding_model || '';
    return inferEmbeddingDeployMode(baseUrl, model) === 'local';
  }

  async function probeLocalEmbeddingAuthRequired(baseUrl) {
    const raw = (baseUrl || LOCAL_EMBEDDING_BASE_URL).trim().replace(/\/+$/, '');
    const root = raw.replace(/\/v1$/i, '');
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(`${root}/v1/cluster/auth`, {
        method: 'GET',
        signal: controller.signal,
      });
      if (!response.ok) return null;
      const data = await response.json();
      return Boolean(data?.auth);
    } catch (_) {
      return null;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function switchKbDetailTab(tabName) {
    activeKbTab = tabName;
    document.querySelectorAll('[data-live-kb-tab]').forEach((item) => {
      item.classList.toggle('active', item.dataset.liveKbTab === tabName);
    });
    document.querySelectorAll('[data-live-kb-panel]').forEach((item) => {
      item.classList.toggle('active', item.dataset.liveKbPanel === tabName);
    });
    if (tabName === 'chunks') loadChunks();
  }

  async function ensureEmbeddingApiKey(knowledgeBaseId = selectedKnowledgeBaseId) {
    const key = resolveEmbeddingApiKey(knowledgeBaseId);
    if (key) return key;

    const local = isLocalEmbeddingConfig(knowledgeBaseId);
    if (local) {
      const kb = getKnowledgeBaseById(knowledgeBaseId);
      const baseUrl = document.getElementById('embBaseUrl')?.value?.trim()
        || kb?.embedding_base_url
        || LOCAL_EMBEDDING_BASE_URL;
      const authRequired = await probeLocalEmbeddingAuthRequired(baseUrl);
      if (authRequired === false) return '';
    }

    alert(getEmbeddingKeyHint(knowledgeBaseId));
    switchKbDetailTab('settings');
    document.getElementById('embApiKey')?.focus();
    return null;
  }

  function getKnowledgeBaseCredentials(knowledgeBaseId = selectedKnowledgeBaseId) {
    const stored = readKbCredentialsFromUi(knowledgeBaseId);
    return {
      embeddingApiKey: resolveEmbeddingApiKey(knowledgeBaseId),
      chromaApiKey: stored.chromaApiKey || '',
    };
  }

  function loadStoredChatKnowledgeBaseIds() {
    try {
      const raw = localStorage.getItem('chat_knowledge_base_ids');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          return parsed.map(Number).filter((id) => Number.isFinite(id) && id > 0);
        }
      }
    } catch (_) { /* ignore */ }
    const legacy = Number(localStorage.getItem('chat_knowledge_base_id') || 0);
    return legacy > 0 ? [legacy] : [];
  }

  function saveSelectedChatKnowledgeBaseIds(ids) {
    const normalized = [...new Set((ids || []).map(Number).filter((id) => Number.isFinite(id) && id > 0))];
    localStorage.setItem('chat_knowledge_base_ids', JSON.stringify(normalized));
    if (normalized.length === 1) localStorage.setItem('chat_knowledge_base_id', String(normalized[0]));
    else localStorage.removeItem('chat_knowledge_base_id');
    return normalized;
  }

  function getSelectedChatKnowledgeBaseIds() {
    const list = document.getElementById('chatKbPickerList');
    if (!list) return loadStoredChatKnowledgeBaseIds();
    return [...list.querySelectorAll('input[type="checkbox"][data-kb-id]:checked')]
      .map((input) => Number(input.dataset.kbId))
      .filter((id) => Number.isFinite(id) && id > 0);
  }

  function syncChatKbPickerButton(ids = getSelectedChatKnowledgeBaseIds()) {
    const btn = document.getElementById('chatKbPickerBtn');
    if (!btn) return;
    const permitted = getPermittedChatKnowledgeBaseIds();
    if (!permitted.length) {
      btn.textContent = '暂无知识库权限';
      btn.title = '当前账号没有可访问的知识库';
      return;
    }
    if (!ids.length) {
      btn.textContent = '请选择知识库';
      btn.title = '列表已按你的权限过滤';
      return;
    }
    const names = ids
      .map((id) => knowledgeBases.find((kb) => Number(kb.id) === Number(id))?.name)
      .filter(Boolean);
    if (ids.length === 1) {
      btn.textContent = names[0] || `知识库 #${ids[0]}`;
    } else {
      btn.textContent = `已选 ${ids.length} 个知识库`;
    }
    btn.title = names.length ? names.join('、') : `已选 ${ids.length} 个知识库`;
  }

  function updateChatKnowledgeBaseOptions() {
    const list = document.getElementById('chatKbPickerList');
    if (!list) return;
    const enabled = knowledgeBases.filter((kb) => isKbEnabled('self', kb.id));
    const permittedIds = enabled.map((kb) => Number(kb.id)).filter((id) => Number.isFinite(id) && id > 0);
    let selected = loadStoredChatKnowledgeBaseIds().filter((id) => permittedIds.includes(id));
    // 无历史选择时，默认勾选当前用户有权限的全部知识库
    if (!selected.length && permittedIds.length) {
      selected = permittedIds.slice();
    }
    const selectedSet = new Set(selected);
    if (!enabled.length) {
      list.innerHTML = '<div class="chat-kb-picker-empty">暂无知识库权限</div>';
      saveSelectedChatKnowledgeBaseIds([]);
      syncChatKbPickerButton([]);
      return;
    }
    list.innerHTML = enabled.map((kb) => `
      <label class="chat-kb-picker-item">
        <input type="checkbox" data-kb-id="${kb.id}"${selectedSet.has(Number(kb.id)) ? ' checked' : ''}>
        <span>${escapeHtml(kb.name)}</span>
      </label>`).join('');
    const ids = getSelectedChatKnowledgeBaseIds();
    saveSelectedChatKnowledgeBaseIds(ids);
    syncChatKbPickerButton(ids);
  }

  function bindChatKbPicker() {
    const picker = document.getElementById('chatKbPicker');
    const btn = document.getElementById('chatKbPickerBtn');
    const menu = document.getElementById('chatKbPickerMenu');
    const list = document.getElementById('chatKbPickerList');
    if (!picker || !btn || !menu || picker.dataset.bound) return;
    picker.dataset.bound = '1';

    const closeMenu = () => { menu.hidden = true; };

    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      document.getElementById('chatDsPickerMenu') && (document.getElementById('chatDsPickerMenu').hidden = true);
      document.getElementById('chatAgentPickerMenu') && (document.getElementById('chatAgentPickerMenu').hidden = true);
    });
    menu.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', closeMenu);

    list?.addEventListener('change', (event) => {
      const input = event.target.closest('input[type="checkbox"][data-kb-id]');
      if (!input) return;
      const ids = getSelectedChatKnowledgeBaseIds();
      saveSelectedChatKnowledgeBaseIds(ids);
      syncChatKbPickerButton(ids);
    });
  }

  function loadStoredChatDataSourceIds() {
    try {
      const raw = localStorage.getItem('chat_data_source_ids');
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed)
        ? parsed.map(Number).filter((id) => Number.isFinite(id) && id > 0)
        : [];
    } catch (_) {
      return [];
    }
  }

  function saveSelectedChatDataSourceIds(ids) {
    const normalized = [...new Set((ids || []).map(Number).filter((id) => Number.isFinite(id) && id > 0))];
    localStorage.setItem('chat_data_source_ids', JSON.stringify(normalized));
    return normalized;
  }

  function getSelectedChatDataSourceIds() {
    const list = document.getElementById('chatDsPickerList');
    if (!list) return loadStoredChatDataSourceIds();
    return [...list.querySelectorAll('input[type="checkbox"][data-ds-id]:checked')]
      .map((input) => Number(input.dataset.dsId))
      .filter((id) => Number.isFinite(id) && id > 0);
  }

  function syncChatDsPickerButton(ids = getSelectedChatDataSourceIds()) {
    const btn = document.getElementById('chatDsPickerBtn');
    if (!btn) return;
    const permitted = getPermittedChatDataSourceIds();
    if (!permitted.length) {
      btn.textContent = '暂无数据源权限';
      btn.title = '当前账号没有可访问的数据源';
      return;
    }
    if (!ids.length) {
      btn.textContent = '请选择数据源';
      btn.title = '列表已按你的权限过滤';
      return;
    }
    const names = ids
      .map((id) => dataSources.find((ds) => Number(ds.id) === Number(id))?.name)
      .filter(Boolean);
    btn.textContent = ids.length === 1 ? (names[0] || `数据源 #${ids[0]}`) : `已选 ${ids.length} 个数据源`;
    btn.title = names.length ? names.join('、') : btn.textContent;
  }

  function updateChatDataSourceOptions() {
    const list = document.getElementById('chatDsPickerList');
    if (!list) return;
    const permittedIds = getPermittedChatDataSourceIds();
    let selected = loadStoredChatDataSourceIds().filter((id) => permittedIds.includes(id));
    if (!selected.length && permittedIds.length) {
      selected = permittedIds.slice();
    }
    const selectedSet = new Set(selected);
    if (!dataSources.length) {
      list.innerHTML = '<div class="chat-kb-picker-empty">暂无数据源权限</div>';
      saveSelectedChatDataSourceIds([]);
      syncChatDsPickerButton([]);
      return;
    }
    list.innerHTML = dataSources.map((ds) => `
      <label class="chat-kb-picker-item">
        <input type="checkbox" data-ds-id="${ds.id}"${selectedSet.has(Number(ds.id)) ? ' checked' : ''}>
        <span>${escapeHtml(ds.name)} <small style="color:var(--text-muted)">(${escapeHtml(ds.type)} · ${isDsQueryOnly(ds) ? '仅查询' : '可写入'})</small></span>
      </label>`).join('');
    const ids = getSelectedChatDataSourceIds();
    saveSelectedChatDataSourceIds(ids);
    syncChatDsPickerButton(ids);
  }

  function bindChatDsPicker() {
    const picker = document.getElementById('chatDsPicker');
    const btn = document.getElementById('chatDsPickerBtn');
    const menu = document.getElementById('chatDsPickerMenu');
    const list = document.getElementById('chatDsPickerList');
    if (!picker || !btn || !menu || picker.dataset.bound) return;
    picker.dataset.bound = '1';

    const closeMenu = () => { menu.hidden = true; };
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      document.getElementById('chatKbPickerMenu') && (document.getElementById('chatKbPickerMenu').hidden = true);
      document.getElementById('chatAgentPickerMenu') && (document.getElementById('chatAgentPickerMenu').hidden = true);
    });
    menu.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', closeMenu);

    list?.addEventListener('change', (event) => {
      const input = event.target.closest('input[type="checkbox"][data-ds-id]');
      if (!input) return;
      const ids = getSelectedChatDataSourceIds();
      saveSelectedChatDataSourceIds(ids);
      syncChatDsPickerButton(ids);
    });
  }

  async function loadKnowledgeBases(selectId, { openDetailModal = false } = {}) {
    try {
      knowledgeBases = await knowledgeApi('');
      updateChatKnowledgeBaseOptions();
      apiKbConfigs = loadApiKbConfigs();
      renderKbConfigRegistry();
      const requested = Number(selectId) || selectedKnowledgeBaseId;
      const selected = knowledgeBases.find((kb) => kb.id === requested);
      if (selected && selectId) {
        await selectKnowledgeBase(selected.id);
        if (openDetailModal) openKbDetailModal();
      } else if (!selectId) {
        selectedKnowledgeBaseId = null;
        activeKbRegistry = null;
      }
      initOverview();
    } catch (error) {
      const registry = document.getElementById('kbConfigRegistry');
      if (registry) registry.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  async function selectKnowledgeBase(id) {
    const kb = knowledgeBases.find((item) => item.id === Number(id));
    if (!kb) return;
    if (selectedKnowledgeBaseId) getKnowledgeBaseCredentials(selectedKnowledgeBaseId);
    selectedKnowledgeBaseId = kb.id;
    activeKbRegistry = { type: 'self', id: kb.id };
    localStorage.setItem('selected_knowledge_base_id', String(kb.id));
    chunkPage = 1;
    renderKbConfigRegistry();
    renderKnowledgeBaseDetail(kb);
    await Promise.all([loadDocuments(), loadChunks()]);
  }

  function renderKnowledgeBaseDetail(kb) {
    const detail = document.getElementById('kbDetailPane');
    if (!detail) return;
    const tabClass = (name) => (activeKbTab === name ? 'active' : '');
    detail.innerHTML = `
      <div class="kb-detail-header">
        <div><h3>${escapeHtml(kb.name)}</h3><p>${escapeHtml(kb.description || '未填写描述')}</p></div>
        <div class="kb-detail-actions">
          <span id="kbSaveStatus" class="kb-save-status" hidden></span>
          <button class="btn-secondary" data-kb-action="save" id="kbSaveBtn">保存配置</button>
        </div>
      </div>
      <div class="kb-sub-nav">
        <button class="kb-sub-nav-item ${tabClass('documents')}" data-live-kb-tab="documents">文档</button>
        <button class="kb-sub-nav-item ${tabClass('chunks')}" data-live-kb-tab="chunks">片段</button>
        <button class="kb-sub-nav-item ${tabClass('settings')}" data-live-kb-tab="settings">索引配置</button>
        <button class="kb-sub-nav-item ${tabClass('retrieval')}" data-live-kb-tab="retrieval">检索测试</button>
      </div>
      <div class="kb-live-tabs">
        <section class="kb-live-tab ${tabClass('documents')}" data-live-kb-panel="documents">
          <div class="kb-section">
            <div class="kb-section-title">文档与索引状态</div>
            <div id="docList" class="doc-list"><div class="doc-empty-hint">加载中...</div></div>
            <div class="kb-doc-actions">
              <button class="btn-add-model" id="addDocBtn" type="button">上传文档</button>
              <button class="btn-secondary" id="addDocTextBtn" type="button">录入文本</button>
              <button class="btn-secondary" id="addDocUrlBtn" type="button">录入网页</button>
            </div>
            <input type="file" id="docFileInput" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.pptx" hidden>
            <small class="kb-help">支持上传文件、粘贴文本，或输入公开网页 URL 自动抓取正文并索引。</small>
          </div>
        </section>
        <section class="kb-live-tab ${tabClass('chunks')}" data-live-kb-panel="chunks">
          <div class="kb-section">
            <div class="kb-section-title">片段浏览</div>
            <div class="kb-search-row">
              <input class="form-input" id="chunkSearch" placeholder="搜索片段内容">
              <button class="btn-secondary" data-kb-action="search-chunks">搜索</button>
            </div>
            <div id="chunkList"></div>
            <div id="chunkPagination" class="chunk-pagination"></div>
          </div>
        </section>
        <section class="kb-live-tab ${tabClass('settings')}" data-live-kb-panel="settings">
          ${renderKbConfigForm(kb, { showBasic: true, showCredentials: true, showEmbTest: true })}
        </section>
        <section class="kb-live-tab ${tabClass('retrieval')}" data-live-kb-panel="retrieval">
          <div class="kb-section">
            <div class="kb-section-title">检索测试</div>
            <textarea class="form-textarea" id="retrievalQuery" placeholder="输入要检索的问题"></textarea>
            <button class="btn-primary" data-kb-action="retrieve">开始检索</button>
            <div id="retrievalResults" class="retrieval-results"></div>
          </div>
        </section>
      </div>`;
    bindKbConfigForm(detail, '');
    syncEmbeddingPresetSelect(detail);
    const credentials = getStoredKbCredentials(kb.id);
    const embApiKey = document.getElementById('embApiKey');
    const chromaApiKey = document.getElementById('chromaApiKey');
    if (embApiKey) embApiKey.value = credentials.embeddingApiKey || '';
    if (chromaApiKey) chromaApiKey.value = credentials.chromaApiKey || '';
  }

  function openCreateKbModal() {
    openKbConfigModal({ type: 'api' });
  }

  function createKnowledgeBase() {
    openKbConfigModal({ type: 'self' });
  }

  async function submitCreateKnowledgeBase() {
    await submitKbConfigModal();
  }

  function knowledgeBaseFormPayload() {
    const detail = document.getElementById('kbDetailPane');
    if (!detail) return readKbConfigForm(document, '', { includeBasic: true });
    return readKbConfigForm(detail, '', { includeBasic: true });
  }

  function showAppToast(message, type = 'ok', duration = 3200) {
    const host = document.getElementById('appToastHost');
    if (!host) return;
    const toast = document.createElement('div');
    const tone = type === 'error' ? 'error' : type === 'warn' ? 'warn' : 'ok';
    toast.className = 'app-toast ' + tone;
    toast.textContent = message;
    host.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    window.setTimeout(() => {
      toast.classList.remove('show');
      window.setTimeout(() => toast.remove(), 220);
    }, duration);
  }

  function openDpTab(tabName) {
    const panel = document.getElementById('panel-dataprocess');
    const btn = panel?.querySelector(`[data-dp-tab="${tabName}"]`);
    if (btn) btn.click();
  }

  function summarizePipelineRun(run) {
    const steps = Array.isArray(run?.step_runs) ? run.step_runs : [];
    const totalRows = steps.reduce((sum, step) => sum + (Number(step.row_count) || 0), 0);
    const stepLines = steps.map((step) => {
      const rows = Number(step.row_count) || 0;
      const msg = step.message ? ` · ${escapeHtml(step.message)}` : '';
      return `${escapeHtml(step.step_name || '步骤')} [${escapeHtml(step.step_type || '-')}] ${escapeHtml(step.status || '-')} · ${rows} 行${msg}`;
    });
    return { steps, totalRows, stepLines };
  }

  function setKbSaveStatus(message, type = 'ok') {
    const status = document.getElementById('kbSaveStatus');
    if (!status) return;
    status.hidden = !message;
    status.textContent = message || '';
    status.className = 'kb-save-status' + (type ? ' ' + type : '');
  }

  async function saveKnowledgeBase() {
    if (!selectedKnowledgeBaseId) return;
    const currentTab = activeKbTab;
    const saveBtn = document.getElementById('kbSaveBtn');
    // Persist credential fields before re-render; API calls still use resolveEmbeddingApiKey().
    readKbCredentialsFromUi(selectedKnowledgeBaseId);
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';
    }
    setKbSaveStatus('正在保存...', '');
    try {
      await knowledgeApi('/' + selectedKnowledgeBaseId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(knowledgeBaseFormPayload()),
      });
      activeKbTab = currentTab || 'settings';
      await loadKnowledgeBases(selectedKnowledgeBaseId);
      if (!document.getElementById('kbDetailModal')?.classList.contains('open')) {
        openKbDetailModal();
      }
      setKbSaveStatus('已保存', 'ok');
      showAppToast('配置已保存。新配置将在后续上传或重试索引时生效。', 'ok');
      window.setTimeout(() => setKbSaveStatus('', 'ok'), 2500);
    } catch (error) {
      setKbSaveStatus('保存失败', 'error');
      showAppToast('保存失败：' + (error.message || '未知错误'), 'error');
    } finally {
      const btn = document.getElementById('kbSaveBtn');
      if (btn) {
        btn.disabled = false;
        btn.textContent = '保存配置';
      }
    }
  }

  async function deleteKnowledgeBase() {
    const kb = knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId);
    if (!kb) return;
    const ok = await confirmAppDialog({
      title: '删除知识库',
      subtitle: '文档与向量将一并清除',
      message: '将删除该知识库下的全部文档、切片与向量索引，此操作不可恢复。',
      metaHtml: `即将删除：<strong>${escapeHtml(kb.name)}</strong>`,
      actionLabel: '确认删除',
    });
    if (!ok) return;
    try {
      const credentials = getKnowledgeBaseCredentials();
      await knowledgeApi('/' + kb.id, {
        method: 'DELETE',
        headers: { 'X-Chroma-Api-Key': credentials.chromaApiKey },
      });
      selectedKnowledgeBaseId = null;
      activeKbRegistry = null;
      clearStoredKbCredentials(kb.id);
      localStorage.removeItem('selected_knowledge_base_id');
      closeKbDetailModal();
      await loadKnowledgeBases();
      showAppToast('知识库已删除', 'ok');
    } catch (error) {
      showAppToast('删除失败：' + (error.message || error), 'error');
    }
  }

  async function loadDocuments(options = {}) {
    if (!selectedKnowledgeBaseId) return;
    const list = document.getElementById('docList');
    try {
      const documents = await knowledgeApi('/' + selectedKnowledgeBaseId + '/documents');
      if (!list) return;
      const fingerprint = documents.map((doc) => `${doc.id}:${doc.status}:${doc.chunk_count}:${doc.error || ''}`).join('|');
      if (!(options.fromPoll && fingerprint === lastDocFingerprint)) {
        lastDocFingerprint = fingerprint;
        list.innerHTML = documents.length ? documents.map((doc) => `
          <div class="doc-item">
            <div class="doc-info">
              <div class="doc-name">${escapeHtml(doc.filename)}</div>
              <div class="doc-meta">${formatFileSize(doc.size)} · ${doc.chunk_count} 个片段${doc.error ? ' · ' + escapeHtml(doc.error) : ''}</div>
            </div>
            <span class="kb-status ${escapeHtml(doc.status)}">${statusLabel(doc.status)}</span>
            <div class="doc-actions">
              ${doc.status === 'failed' ? `<button class="doc-action-btn" data-doc-action="retry" data-id="${doc.id}">重试</button>` : ''}
              <button class="doc-action-btn danger" data-doc-action="delete" data-id="${doc.id}">删除</button>
            </div>
          </div>`).join('') : '<div class="doc-empty-hint">暂未上传文档。</div>';
      }
      const processing = documents.some((doc) => doc.status === 'pending' || doc.status === 'processing');
      if (processing) {
        scheduleKbPolling();
      } else {
        const wasPolling = !!kbPollTimer || options.fromPoll;
        stopKbPolling();
        if (wasPolling) {
          // Light refresh: update registry counts without remounting the whole detail pane.
          try {
            knowledgeBases = await knowledgeApi('');
            renderKbConfigRegistry();
            updateChatKnowledgeBaseOptions();
          } catch (_) { /* ignore */ }
        }
      }
    } catch (error) {
      if (list) list.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  function statusLabel(status) {
    return ({ pending: '等待上', processing: '处理上', completed: '已完成', failed: '失败' })[status] || status;
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  async function uploadDocuments(files) {
    if (!selectedKnowledgeBaseId || !files?.length) return;
    const embeddingApiKey = await ensureEmbeddingApiKey();
    if (embeddingApiKey === null) return;
    const credentials = getKnowledgeBaseCredentials();
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      form.append('embedding_api_key', embeddingApiKey || '');
      form.append('chroma_api_key', credentials.chromaApiKey);
      try {
        await knowledgeApi('/' + selectedKnowledgeBaseId + '/documents', { method: 'POST', body: form });
      } catch (error) {
        alert(file.name + ' 上传失败：' + error.message);
      }
    }
    await loadDocuments();
  }

  async function retryDocument(documentId) {
    const embeddingApiKey = await ensureEmbeddingApiKey();
    if (embeddingApiKey === null) return;
    const credentials = getKnowledgeBaseCredentials();
    const form = new FormData();
    form.append('embedding_api_key', embeddingApiKey || '');
    form.append('chroma_api_key', credentials.chromaApiKey);
    try {
      await knowledgeApi(`/${selectedKnowledgeBaseId}/documents/${documentId}/retry`, { method: 'POST', body: form });
      await loadDocuments();
    } catch (error) {
      alert('重试失败：' + error.message);
    }
  }

  async function deleteDocument(documentId) {
    const ok = await confirmAppDialog({
      title: '删除文档',
      subtitle: '相关向量将同步移除',
      message: '确定删除该文档及其已索引的向量片段吗？删除后不可恢复。',
      actionLabel: '确认删除',
    });
    if (!ok) return;
    try {
      const credentials = getKnowledgeBaseCredentials();
      await knowledgeApi(`/${selectedKnowledgeBaseId}/documents/${documentId}`, {
        method: 'DELETE',
        headers: { 'X-Chroma-Api-Key': credentials.chromaApiKey },
      });
      await Promise.all([loadDocuments(), loadChunks()]);
      showAppToast('文档已删除', 'ok');
    } catch (error) {
      showAppToast('删除失败：' + (error.message || error), 'error');
    }
  }

  async function loadChunks(targetChunkId) {
    if (!selectedKnowledgeBaseId) return;
    const list = document.getElementById('chunkList');
    if (!list) return;
    const search = document.getElementById('chunkSearch')?.value.trim() || '';
    try {
      const data = await knowledgeApi(`/${selectedKnowledgeBaseId}/chunks?page=${chunkPage}&page_size=10&search=${encodeURIComponent(search)}`);
      list.innerHTML = data.items.length ? data.items.map((chunk) => `
        <article class="chunk-card ${Number(targetChunkId) === chunk.id ? 'highlight' : ''}" data-chunk-id="${chunk.id}">
          <header>${escapeHtml(chunk.document_name)} · #${chunk.position + 1}${chunk.metadata.page ? ' · 第' + chunk.metadata.page + ' 页' : ''}${chunk.metadata.sheet ? ' · ' + escapeHtml(chunk.metadata.sheet) : ''}</header>
          <p>${escapeHtml(chunk.content)}</p>
        </article>`).join('') : '<div class="doc-empty-hint">没有匹配的片段</div>';
      const pages = Math.max(1, Math.ceil(data.total / data.page_size));
      const pagination = document.getElementById('chunkPagination');
      if (pagination) pagination.innerHTML = `
        <button class="btn-secondary" data-chunk-page="${Math.max(1, chunkPage - 1)}" ${chunkPage <= 1 ? 'disabled' : ''}>上一页</button>
        <span>${chunkPage} / ${pages}（${data.total} 条）</span>
        <button class="btn-secondary" data-chunk-page="${Math.min(pages, chunkPage + 1)}" ${chunkPage >= pages ? 'disabled' : ''}>下一页</button>`;
      document.querySelector('.chunk-card.highlight')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (error) {
      list.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  async function testEmbeddingConnection() {
    const result = document.getElementById('embTestResult');
    if (result) {
      result.hidden = false;
      result.textContent = '准备测试...';
      result.className = 'test-result';
    }
    const payload = knowledgeBaseFormPayload();
    if (!selectedKnowledgeBaseId) {
      if (result) {
        result.textContent = '请先保存知识库后再测试 Embedding';
        result.className = 'test-result error';
      }
      showAppToast('请先保存知识库后再测试', 'warn');
      return;
    }
    const isLocal = inferEmbeddingDeployMode(payload.embedding_base_url, payload.embedding_model) === 'local';
    let embeddingApiKey = resolveEmbeddingApiKey() || '';
    if (!embeddingApiKey) {
      if (isLocal) {
        if (result) result.textContent = '正在检测本地 Embedding 服务...';
        const authRequired = await probeLocalEmbeddingAuthRequired(payload.embedding_base_url);
        if (authRequired !== false) {
          const hint = getEmbeddingKeyHint();
          if (result) {
            result.textContent = hint;
            result.className = 'test-result error';
          }
          alert(hint);
          document.getElementById('embApiKey')?.focus();
          return;
        }
      } else {
        embeddingApiKey = await ensureEmbeddingApiKey();
        if (embeddingApiKey === null) {
          if (result) {
            result.textContent = '请先填写 Embedding API Key';
            result.className = 'test-result error';
          }
          return;
        }
      }
    }
    const form = new FormData();
    form.append('embedding_api_key', embeddingApiKey);
    form.append('embedding_model', payload.embedding_model || '');
    form.append('embedding_base_url', payload.embedding_base_url || '');
    if (payload.embedding_dimension != null) {
      form.append('embedding_dimension', String(payload.embedding_dimension));
    }
    if (result) { result.hidden = false; result.textContent = '测试中...'; result.className = 'test-result'; }
    try {
      const data = await knowledgeApi(`/${selectedKnowledgeBaseId}/embedding/test`, { method: 'POST', body: form });
      if (result) { result.textContent = '连接成功，向量维度：' + data.dimension; result.className = 'test-result success'; }
      showAppToast('Embedding 连接成功', 'ok');
    } catch (error) {
      if (result) { result.textContent = error.message; result.className = 'test-result error'; }
      showAppToast(error.message || 'Embedding 测试失败', 'error');
    }
  }

  async function runRetrievalTest() {
    const query = document.getElementById('retrievalQuery')?.value.trim();
    const result = document.getElementById('retrievalResults');
    if (!query || !result) return;
    const credentials = getKnowledgeBaseCredentials();
    const configuredThreshold = Number(document.getElementById('scoreThreshold')?.value);
    const threshold = Number.isFinite(configuredThreshold) ? configuredThreshold : 0.5;
    const topK = Number(document.getElementById('topK')?.value) || 5;
    result.innerHTML = '<div class="doc-empty-hint">检索中...</div>';

    const requestRetrieve = async (scoreThreshold) => knowledgeApi(`/${selectedKnowledgeBaseId}/retrieve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        embedding_api_key: credentials.embeddingApiKey,
        chroma_api_key: credentials.chromaApiKey,
        top_k: topK,
        score_threshold: scoreThreshold,
      }),
    });

    const renderHits = (items, { nearMiss = false } = {}) => {
      if (!items.length) {
        result.innerHTML = '<div class="doc-empty-hint">没有检索到相关片段</div>';
        return;
      }
      const tip = nearMiss
        ? `<div class="doc-empty-hint">未达到阈值 ${threshold.toFixed(2)}（最高 ${(Math.max(...items.map((i) => Number(i.score))) || 0).toFixed(4)}）。下列为最相近结果，可下调「相似度阈值」后保存。</div>`
        : '';
      result.innerHTML = tip + items.map((item) => {
        const score = Number(item.score);
        const pass = score >= threshold;
        return `
        <article class="retrieval-card${pass ? '' : ' near-miss'}">
          <header>${escapeHtml(item.document)} · 相似度 ${score.toFixed(4)}${pass ? '' : '（未达阈值）'}</header>
          <p>${escapeHtml(item.content)}</p>
        </article>`;
      }).join('');
    };

    try {
      const data = await requestRetrieve(threshold);
      if (data.results.length) {
        renderHits(data.results);
        return;
      }
      const fallback = await requestRetrieve(0);
      renderHits(fallback.results || [], { nearMiss: true });
    } catch (error) {
      result.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  function initKnowledgeBasePanel() {
    const panel = document.getElementById('panel-kb');
    if (!panel) return;
    loadKnowledgeBases();

    if (panel.dataset.kbBound) return;
    panel.dataset.kbBound = '1';
    document.getElementById('addKbConfigBtn')?.addEventListener('click', () => openKbConfigModal({ type: 'api' }));
    document.getElementById('closeCreateKb')?.addEventListener('click', closeCreateKbModal);
    document.getElementById('cancelCreateKb')?.addEventListener('click', closeCreateKbModal);
    document.getElementById('submitCreateKb')?.addEventListener('click', submitKbConfigModal);
    document.getElementById('testCreateKbApi')?.addEventListener('click', testCreateKbApiConnection);
    document.getElementById('deleteKbConfigBtn')?.addEventListener('click', deleteApiKbConfig);
    document.getElementById('createKbType')?.addEventListener('change', (event) => {
      const type = event.target.value === 'self' ? 'self' : 'api';
      const selfHost = document.getElementById('createKbSelfFormHost');
      if (type === 'self' && selfHost && !selfHost.innerHTML.trim()) {
        selfHost.innerHTML = renderKbConfigForm(kbDefaultConfig(), { prefix: 'create', showBasic: true, showCredentials: false });
        bindKbConfigForm(selfHost, 'create');
        syncEmbeddingPresetSelect(selfHost, 'create');
      }
      const submitBtn = document.getElementById('submitCreateKb');
      if (submitBtn && !editingKbModal) submitBtn.textContent = type === 'self' ? '创建' : '保存';
      setCreateKbModalType(type);
    });
    document.getElementById('kbConfigRegistry')?.addEventListener('click', (event) => {
      const configureBtn = event.target.closest('[data-registry-configure]');
      if (configureBtn) {
        configureKbRegistryItem(configureBtn.dataset.registryType, configureBtn.dataset.registryId);
        return;
      }
      const toggleBtn = event.target.closest('[data-registry-toggle]');
      if (toggleBtn) {
        toggleKbRegistryEnabled(toggleBtn.dataset.registryType, toggleBtn.dataset.registryId);
        return;
      }
      const deleteBtn = event.target.closest('[data-registry-delete]');
      if (deleteBtn) {
        deleteKbRegistryItem(deleteBtn.dataset.registryType, deleteBtn.dataset.registryId);
      }
    });
    document.getElementById('closeKbDetail')?.addEventListener('click', closeKbDetailModal);
    document.getElementById('closeAddKbText')?.addEventListener('click', closeKbTextModal);
    document.getElementById('cancelAddKbText')?.addEventListener('click', closeKbTextModal);
    document.getElementById('saveKbTextBtn')?.addEventListener('click', submitKbTextDocument);
    document.getElementById('kbTextContent')?.addEventListener('input', updateKbTextCount);
    document.getElementById('addKbTextModal')?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeKbTextModal();
    });
    document.getElementById('closeAddKbUrl')?.addEventListener('click', closeKbUrlModal);
    document.getElementById('cancelAddKbUrl')?.addEventListener('click', closeKbUrlModal);
    document.getElementById('saveKbUrlBtn')?.addEventListener('click', submitKbUrlDocument);
    document.getElementById('addKbUrlModal')?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeKbUrlModal();
    });
    kbDetailModal?.addEventListener('click', (event) => {
      const tab = event.target.closest('[data-live-kb-tab]');
      if (tab) {
        switchKbDetailTab(tab.dataset.liveKbTab);
        return;
      }
      const action = event.target.closest('[data-kb-action]')?.dataset.kbAction;
      if (action === 'save') saveKnowledgeBase();
      if (action === 'delete') deleteKnowledgeBase();
      if (action === 'search-chunks') { chunkPage = 1; loadChunks(); }
      if (action === 'test-embedding') testEmbeddingConnection();
      if (action === 'retrieve') runRetrievalTest();
      const docAction = event.target.closest('[data-doc-action]');
      if (docAction?.dataset.docAction === 'retry') retryDocument(Number(docAction.dataset.id));
      if (docAction?.dataset.docAction === 'delete') deleteDocument(Number(docAction.dataset.id));
      const pageButton = event.target.closest('[data-chunk-page]');
      if (pageButton && !pageButton.disabled) { chunkPage = Number(pageButton.dataset.chunkPage); loadChunks(); }
      if (event.target.closest('#addDocBtn')) document.getElementById('docFileInput')?.click();
      if (event.target.closest('#addDocTextBtn')) openKbTextModal();
      if (event.target.closest('#addDocUrlBtn')) openKbUrlModal();
    });
    kbDetailModal?.addEventListener('change', (event) => {
      if (event.target.id === 'docFileInput') uploadDocuments(event.target.files);
    });
  }

  function openKbTextModal() {
    if (!selectedKnowledgeBaseId) return;
    const title = document.getElementById('kbTextTitle');
    const content = document.getElementById('kbTextContent');
    const count = document.getElementById('kbTextCount');
    if (title) title.value = '';
    if (content) content.value = '';
    if (count) count.textContent = '0 字';
    document.getElementById('addKbTextModal')?.classList.add('open');
    window.setTimeout(() => content?.focus(), 50);
  }

  function closeKbTextModal() {
    document.getElementById('addKbTextModal')?.classList.remove('open');
  }

  function updateKbTextCount() {
    const content = document.getElementById('kbTextContent')?.value || '';
    const count = document.getElementById('kbTextCount');
    if (count) count.textContent = `${content.length.toLocaleString('zh-CN')} 字`;
  }

  async function submitKbTextDocument() {
    if (!selectedKnowledgeBaseId) return;
    const title = document.getElementById('kbTextTitle')?.value.trim() || '';
    const content = document.getElementById('kbTextContent')?.value.trim() || '';
    if (!content) {
      showAppToast('请填写文本内容', 'warn');
      document.getElementById('kbTextContent')?.focus();
      return;
    }
    const embeddingApiKey = await ensureEmbeddingApiKey();
    if (embeddingApiKey === null) return;
    const credentials = getKnowledgeBaseCredentials();
    const form = new FormData();
    form.append('title', title);
    form.append('content', content);
    form.append('embedding_api_key', embeddingApiKey || '');
    form.append('chroma_api_key', credentials.chromaApiKey || '');
    const saveBtn = document.getElementById('saveKbTextBtn');
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = '提交中...';
    }
    try {
      await knowledgeApi(`/${selectedKnowledgeBaseId}/documents/text`, { method: 'POST', body: form });
      closeKbTextModal();
      showAppToast('文本已提交，正在索引', 'ok');
      await loadDocuments();
    } catch (error) {
      showAppToast('录入失败：' + (error.message || error), 'error');
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存并索引';
      }
    }
  }

  function openKbUrlModal() {
    if (!selectedKnowledgeBaseId) return;
    const url = document.getElementById('kbUrlInput');
    const title = document.getElementById('kbUrlTitle');
    if (url) url.value = '';
    if (title) title.value = '';
    document.getElementById('addKbUrlModal')?.classList.add('open');
    window.setTimeout(() => url?.focus(), 50);
  }

  function closeKbUrlModal() {
    document.getElementById('addKbUrlModal')?.classList.remove('open');
  }

  async function submitKbUrlDocument() {
    if (!selectedKnowledgeBaseId) return;
    const url = document.getElementById('kbUrlInput')?.value.trim() || '';
    const title = document.getElementById('kbUrlTitle')?.value.trim() || '';
    if (!url) {
      showAppToast('请填写网页地址', 'warn');
      document.getElementById('kbUrlInput')?.focus();
      return;
    }
    if (!/^https?:\/\//i.test(url)) {
      showAppToast('请使用 http:// 或 https:// 开头的地址', 'warn');
      return;
    }
    const embeddingApiKey = await ensureEmbeddingApiKey();
    if (embeddingApiKey === null) return;
    const credentials = getKnowledgeBaseCredentials();
    const form = new FormData();
    form.append('url', url);
    form.append('title', title);
    form.append('embedding_api_key', embeddingApiKey || '');
    form.append('chroma_api_key', credentials.chromaApiKey || '');
    const saveBtn = document.getElementById('saveKbUrlBtn');
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = '抓取中...';
    }
    try {
      await knowledgeApi(`/${selectedKnowledgeBaseId}/documents/url`, { method: 'POST', body: form });
      closeKbUrlModal();
      showAppToast('网页已提交，正在索引', 'ok');
      await loadDocuments();
    } catch (error) {
      showAppToast('网页录入失败：' + (error.message || error), 'error');
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '抓取并索引';
      }
    }
  }

  function setInlineStatus(id, message, type) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = message;
    el.className = 'inline-status' + (type ? ' ' + type : '');
  }

  // ===== MCP management and market =====
  let editingMcpId = null;
  let verifiedMcpSignature = '';

  function getMcpFormSignature() {
    return (document.getElementById('mcpName')?.value.trim() || '') + '\n'
      + (document.getElementById('mcpJson')?.value.trim() || '');
  }

  function setMcpTestResult(type, message) {
    renderModalTestBanner(document.getElementById('mcpTestResult'), type, message);
  }

  function updateMcpStatusOptions() {
    document.querySelectorAll('#addMcpModal .status-option').forEach((option) => {
      option.classList.toggle('active', Boolean(option.querySelector('input:checked')));
    });
  }

  function invalidateMcpVerification() {
    verifiedMcpSignature = '';
    const saveButton = document.getElementById('saveMcpBtn');
    if (saveButton) saveButton.disabled = true;
    markSaveReady('saveMcpBtn', false);
    setMcpTestResult('', '');
  }

  function normalizeLegacyMcpConfig(item) {
    if (item?.mcpJson && typeof item.mcpJson === 'object') return item.mcpJson;
    if (item?.endpoint) {
      if (/^https?:\/\//i.test(item.endpoint)) {
        return { mcpServers: { [item.name || 'mcp-server']: { url: item.endpoint } } };
      }
      return { mcpServers: { [item.name || 'mcp-server']: { command: item.endpoint } } };
    }
    return { mcpServers: { 'my-server': { url: 'http://localhost:3000/mcp' } } };
  }

  function openMcpModal(item = null) {
    editingMcpId = item?.id || null;
    verifiedMcpSignature = '';
    const name = document.getElementById('mcpName');
    const description = document.getElementById('mcpDescription');
    const jsonEditor = document.getElementById('mcpJson');
    const title = document.getElementById('mcpModalTitle');
    if (title) title.textContent = item ? '修改 MCP 服务器' : '添加 MCP 服务器';
    if (name) name.value = item?.name || '';
    if (description) description.value = item?.description || '';
    if (jsonEditor) jsonEditor.value = JSON.stringify(normalizeLegacyMcpConfig(item), null, 2);
    readMcpCredFieldsFromJson();
    const enabledValue = item?.enabled === false ? 'false' : 'true';
    const radio = document.querySelector(`#addMcpModal input[name="mcpEnabled"][value="${enabledValue}"]`);
    if (radio) radio.checked = true;
    updateMcpStatusOptions();
    setMcpTestResult('', '');
    const saveButton = document.getElementById('saveMcpBtn');
    if (saveButton) saveButton.disabled = true;
    markSaveReady('saveMcpBtn', false);
    document.getElementById('addMcpModal')?.classList.add('open');
    window.setTimeout(() => {
      const tokenInput = document.getElementById('mcpTushareToken');
      if (item?.marketId === 'tushare' || item?.name === 'tushare') tokenInput?.focus();
      else name?.focus();
    }, 50);
  }

  function closeMcpModal() {
    document.getElementById('addMcpModal')?.classList.remove('open');
    editingMcpId = null;
    verifiedMcpSignature = '';
    setMcpTestResult('', '');
    markSaveReady('saveMcpBtn', false);
  }

  async function testMcpConnection() {
    applyMcpCredFieldsToJson();
    const name = document.getElementById('mcpName')?.value.trim() || '';
    const source = document.getElementById('mcpJson')?.value.trim() || '';
    if (!name) {
      setMcpTestResult('error', '请填写MCP 名称');
      return;
    }
    let config;
    try {
      config = JSON.parse(source);
    } catch (error) {
      setMcpTestResult('error', 'mcp.json 格式错误，' + error.message);
      return;
    }
    if (!config || Array.isArray(config) || typeof config !== 'object') {
      setMcpTestResult('error', 'mcp.json 顶层必须明JSON 对象');
      return;
    }
    const entry = getPrimaryMcpServer(config);
    const server = entry?.[1] || {};
    if (String(entry?.[0] || name).toLowerCase().includes('tushare') || String(server.url || '').includes('/mcp/tushare')) {
      if (!String(server.token || '').trim()) {
        setMcpTestResult('error', '请填写 Tushare Token（保存在 MCP 配置中）');
        document.getElementById('mcpTushareToken')?.focus();
        return;
      }
    }
    const button = document.getElementById('testMcpBtn');
    if (button) {
      button.disabled = true;
      button.textContent = '连接中...';
    }
    setMcpTestResult('', '正在校验配置并连接 MCP 服务...');
    try {
      const response = await apiFetch('/api/mcp/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, config }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        verifiedMcpSignature = '';
        document.getElementById('saveMcpBtn').disabled = true;
        markSaveReady('saveMcpBtn', false);
        setMcpTestResult('error', result.message || result.error || 'MCP 连接失败');
        return;
      }
      verifiedMcpSignature = getMcpFormSignature();
      document.getElementById('saveMcpBtn').disabled = false;
      markSaveReady('saveMcpBtn', true);
      setMcpTestResult('ok', (result.message || 'MCP 连接成功') + '，现在可以点击「保存」');
    } catch (error) {
      verifiedMcpSignature = '';
      document.getElementById('saveMcpBtn').disabled = true;
      markSaveReady('saveMcpBtn', false);
      setMcpTestResult('error', '连接失败：' + (error.message || error));
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = '校验并测试连接';
      }
    }
  }

  function saveMcpFromModal() {
    applyMcpCredFieldsToJson();
    if (!verifiedMcpSignature || verifiedMcpSignature !== getMcpFormSignature()) {
      setMcpTestResult('error', '配置已变化，请重新测试连接');
      document.getElementById('saveMcpBtn').disabled = true;
      return;
    }
    const name = document.getElementById('mcpName').value.trim();
    const description = document.getElementById('mcpDescription').value.trim();
    const mcpJson = JSON.parse(document.getElementById('mcpJson').value);
    const enabled = document.querySelector('#addMcpModal input[name="mcpEnabled"]:checked')?.value !== 'false';
    const existing = mcpConfigs.find((item) => item.id === editingMcpId);
    const value = {
      ...(existing || {}),
      id: existing?.id || 'mcp_' + Date.now(),
      name,
      description,
      mcpJson,
      enabled,
      connectionStatus: 'connected',
      source: existing?.source || 'custom',
      marketId: existing?.marketId,
      testedAt: new Date().toISOString(),
    };
    if (existing) {
      Object.assign(existing, value);
    } else {
      mcpConfigs.push(value);
    }
    persistMcpData();
    closeMcpModal();
    initMcpPanel();
    initOverview();
  }

  function persistMcpData() {
    localStorage.setItem('user_mcp_configs', JSON.stringify(mcpConfigs));
    localStorage.setItem('mcp_market_state', JSON.stringify(mcpMarketState));
    localStorage.setItem('custom_mcp_market', JSON.stringify(customMcpMarket));
  }

  function getMcpMarketPreset(marketId, fallbackName = '') {
    if (marketId === 'tushare') {
      const origin = window.location.origin || 'http://127.0.0.1:8000';
      return {
        name: 'tushare',
        description: 'Tushare Pro（Token / 代理在 MCP 配置中填写）',
        mcpJson: {
          mcpServers: {
            tushare: {
              url: `${origin}/mcp/tushare`,
              token: '',
              proxy: '',
            },
          },
        },
      };
    }
    return {
      name: fallbackName || marketId,
      description: '',
      mcpJson: null,
    };
  }

  function getPrimaryMcpServer(config) {
    const servers = config?.mcpServers;
    if (!servers || typeof servers !== 'object') return null;
    const entries = Object.entries(servers);
    if (!entries.length) return null;
    const named = entries.find(([key]) => key === 'tushare');
    return named || entries[0];
  }

  function readMcpCredFieldsFromJson() {
    const editor = document.getElementById('mcpJson');
    const tokenInput = document.getElementById('mcpTushareToken');
    const proxyInput = document.getElementById('mcpTushareProxy');
    if (!editor || !tokenInput || !proxyInput) return;
    try {
      const config = JSON.parse(editor.value || '{}');
      const entry = getPrimaryMcpServer(config);
      const server = entry?.[1] || {};
      const headers = server.headers && typeof server.headers === 'object' ? server.headers : {};
      tokenInput.value = server.token || headers['X-Tushare-Token'] || '';
      proxyInput.value = server.proxy || headers['X-Tushare-Proxy'] || '';
    } catch {
      /* ignore parse errors while typing */
    }
  }

  function applyMcpCredFieldsToJson() {
    const editor = document.getElementById('mcpJson');
    const tokenInput = document.getElementById('mcpTushareToken');
    const proxyInput = document.getElementById('mcpTushareProxy');
    if (!editor || !tokenInput || !proxyInput) return false;
    let config;
    try {
      config = JSON.parse(editor.value || '{}');
    } catch {
      return false;
    }
    if (!config.mcpServers || typeof config.mcpServers !== 'object') {
      config.mcpServers = {};
    }
    let entry = getPrimaryMcpServer(config);
    if (!entry) {
      const origin = window.location.origin || 'http://127.0.0.1:8000';
      config.mcpServers.tushare = { url: `${origin}/mcp/tushare` };
      entry = ['tushare', config.mcpServers.tushare];
    }
    const [key, server] = entry;
    const next = { ...(server || {}) };
    const token = tokenInput.value.trim();
    const proxy = proxyInput.value.trim();
    if (token) next.token = token;
    else delete next.token;
    if (proxy) next.proxy = proxy;
    else delete next.proxy;
    if (next.headers && typeof next.headers === 'object') {
      const headers = { ...next.headers };
      delete headers['X-Tushare-Token'];
      delete headers['X-Tushare-Proxy'];
      if (Object.keys(headers).length) next.headers = headers;
      else delete next.headers;
    }
    config.mcpServers[key] = next;
    editor.value = JSON.stringify(config, null, 2);
    return true;
  }

  function renderMcpList() {
    const list = document.getElementById('mcpList');
    if (!list) return;
    if (!mcpConfigs.length) {
      list.innerHTML = '<div class="doc-empty-hint">暂无 MCP，可自行添加或从下方市场安装。</div>';
      return;
    }
    list.innerHTML = mcpConfigs.map((item) => `
      <div class="integration-row">
        <div class="integration-main">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.description || item.endpoint || '市场安装')}</span>
        </div>
        <span class="connection-badge ${item.connectionStatus === 'connected' ? 'connected' : ''}">${item.connectionStatus === 'connected' ? '连接通过' : '未校验'}</span>
        <span class="integration-status ${item.enabled === false ? 'offline' : 'online'}">${item.enabled === false ? '失效' : '生效'}</span>
        <div class="integration-actions">
          <button data-mcp-action="toggle" data-id="${escapeHtml(item.id)}">${item.enabled === false ? '设为生效' : '设为失效'}</button>
          <button data-mcp-action="edit" data-id="${escapeHtml(item.id)}">修改</button>
          <button class="danger" data-mcp-action="delete" data-id="${escapeHtml(item.id)}">删除</button>
        </div>
      </div>`).join('');
  }

  function appendCustomMcpMarketCards() {
    const grid = document.getElementById('mcpMarketGrid');
    if (!grid) return;
    grid.querySelectorAll('[data-custom-market="mcp"]').forEach((node) => node.remove());
    customMcpMarket.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'mcp-market-card';
      card.dataset.customMarket = 'mcp';
      card.dataset.marketId = item.id;
      card.innerHTML = `
        <div class="mcp-market-icon">?? /div>
        <div class="mcp-market-name">${escapeHtml(item.name)}</div>
        <div class="mcp-market-desc">${escapeHtml(item.description || '管理员发布的 MCP')}</div>
        <div class="mcp-market-tags"><span class="tag">${escapeHtml(item.type || '自定义')}</span></div>
        <button class="btn-install-mcp" data-mcp="${escapeHtml(item.id)}">安装</button>`;
      grid.appendChild(card);
    });
  }

  function renderMcpMarket() {
    appendCustomMcpMarketCards();
    const panel = document.getElementById('panel-mcp');
    const role = document.getElementById('mcpRoleMode')?.value || 'user';
    panel?.querySelectorAll('.market-admin-only').forEach((el) => { el.hidden = role !== 'admin'; });
    document.querySelectorAll('#mcpMarketGrid .mcp-market-card').forEach((card, index) => {
      const install = card.querySelector('.btn-install-mcp');
      const id = card.dataset.marketId || install?.dataset.mcp || ('mcp_' + index);
      card.dataset.marketId = id;
      const state = mcpMarketState[id] || {};
      const nameEl = card.querySelector('.mcp-market-name');
      const descEl = card.querySelector('.mcp-market-desc');
      if (state.name && nameEl) nameEl.textContent = state.name;
      if (state.description && descEl) descEl.textContent = state.description;
      const offline = state.status === 'offline';
      card.classList.toggle('market-offline', offline);
      card.hidden = role === 'user' && offline;
      if (install) {
        const installed = mcpConfigs.some((item) => item.marketId === id);
        install.hidden = role === 'admin';
        install.disabled = installed;
        install.textContent = installed ? '已安装' : '安装';
      }
      card.querySelector('.admin-market-actions')?.remove();
      if (role === 'admin') {
        const actions = document.createElement('div');
        actions.className = 'admin-market-actions';
        actions.innerHTML = `
          <button data-market-action="edit" data-market-type="mcp" data-id="${escapeHtml(id)}">修改</button>
          <button data-market-action="toggle" data-market-type="mcp" data-id="${escapeHtml(id)}">${offline ? '上线' : '下线'}</button>`;
        card.appendChild(actions);
      }
    });
  }

  function initMcpPanel() {
    renderMcpList();
    renderMcpMarket();
  }

  // ===== Skill management and market =====
  let editingSkillId = null;

  function persistSkillData() {
    localStorage.setItem('user_skill_configs', JSON.stringify(skillConfigs));
    localStorage.setItem('skill_market_state', JSON.stringify(skillMarketState));
    localStorage.setItem('custom_skill_market', JSON.stringify(customSkillMarket));
  }

  function updateSkillStatusOptions() {
    document.querySelectorAll('#addSkillModal .status-option').forEach((option) => {
      const input = option.querySelector('input');
      option.classList.toggle('active', Boolean(input?.checked));
    });
  }

  function openSkillModal(item = null) {
    editingSkillId = item?.id || null;
    const title = document.getElementById('skillModalTitle');
    const name = document.getElementById('skillName');
    const description = document.getElementById('skillDescription');
    const prompt = document.getElementById('skillPrompt');
    if (title) title.textContent = item ? '编辑 Skill' : '新建 Skill';
    if (name) name.value = item?.name || '';
    if (description) description.value = item?.description || '';
    if (prompt) prompt.value = item?.prompt || '';
    const enabledValue = item?.enabled === false ? 'false' : 'true';
    const radio = document.querySelector(`#addSkillModal input[name="skillEnabled"][value="${enabledValue}"]`);
    if (radio) radio.checked = true;
    updateSkillStatusOptions();
    document.getElementById('addSkillModal')?.classList.add('open');
    window.setTimeout(() => name?.focus(), 50);
  }

  function closeSkillModal() {
    document.getElementById('addSkillModal')?.classList.remove('open');
    editingSkillId = null;
  }

  function saveSkillFromModal() {
    const name = document.getElementById('skillName')?.value.trim() || '';
    if (!name) {
      showAppToast('请填写 Skill 名称', 'warn');
      document.getElementById('skillName')?.focus();
      return;
    }
    const description = document.getElementById('skillDescription')?.value.trim() || '';
    const prompt = document.getElementById('skillPrompt')?.value.trim() || '';
    if (!prompt) {
      showAppToast('请填写 Skill Prompt / 执行说明，否则无法在对话中生效', 'warn');
      document.getElementById('skillPrompt')?.focus();
      return;
    }
    if (prompt.length < 20) {
      showAppToast('执行说明过短，请补充角色、步骤或校验要求（至少约 20 字）', 'warn');
      document.getElementById('skillPrompt')?.focus();
      return;
    }
    const enabled = document.querySelector('#addSkillModal input[name="skillEnabled"]:checked')?.value !== 'false';
    const existing = skillConfigs.find((entry) => entry.id === editingSkillId);
    if (existing) {
      existing.name = name;
      existing.description = description;
      existing.prompt = prompt;
      existing.enabled = enabled;
    } else {
      skillConfigs.push({
        id: 'skill_' + Date.now(),
        name,
        description,
        prompt,
        enabled,
        source: 'custom',
        createdAt: Date.now(),
      });
    }
    persistSkillData();
    closeSkillModal();
    initSkillPanel();
    initOverview();
    showAppToast(existing ? 'Skill 已更新' : 'Skill 已创建', 'ok');
  }

  function renderSkillList() {
    const list = document.getElementById('skillList');
    if (!list) return;
    if (!skillConfigs.length) {
      list.innerHTML = '<div class="doc-empty-hint">暂无 Skill，可自行创建或从下方市场安装。</div>';
      return;
    }
    list.innerHTML = skillConfigs.map((item) => `
      <div class="integration-row">
        <div class="integration-main">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.description || item.prompt || '自定义Skill')}</span>
        </div>
        <span class="integration-status ${item.enabled === false ? 'offline' : 'online'}">${item.enabled === false ? '已停用' : '已启用'}</span>
        <div class="integration-actions">
          <button data-skill-action="toggle" data-id="${escapeHtml(item.id)}">${item.enabled === false ? '启用' : '停用'}</button>
          <button data-skill-action="edit" data-id="${escapeHtml(item.id)}">修改</button>
          <button class="danger" data-skill-action="delete" data-id="${escapeHtml(item.id)}">删除</button>
        </div>
      </div>`).join('');
  }

  function appendCustomSkillMarketCards() {
    const grid = document.querySelector('#panel-skill .skill-market-grid');
    if (!grid) return;
    grid.querySelectorAll('[data-custom-market="skill"]').forEach((node) => node.remove());
    customSkillMarket.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'skill-market-card';
      card.dataset.customMarket = 'skill';
      card.dataset.marketId = item.id;
      card.innerHTML = `
        <div class="skill-market-header"><span class="skill-market-icon">?? /span><span class="skill-market-name">${escapeHtml(item.name)}</span></div>
        <div class="skill-market-desc">${escapeHtml(item.description || '管理员发布的 Skill')}</div>
        <div class="skill-market-tags"><span class="tag">${escapeHtml(item.category || '自定义')}</span></div>
        <div class="skill-market-meta">v${escapeHtml(item.version || '1.0')} · 作者：官方</div>
        <button class="btn-install-skill" data-skill="${escapeHtml(item.id)}">安装</button>`;
      grid.appendChild(card);
    });
  }

  function renderSkillMarket() {
    appendCustomSkillMarketCards();
    const panel = document.getElementById('panel-skill');
    const role = document.getElementById('skillRoleMode')?.value || 'user';
    panel?.querySelectorAll('.market-admin-only').forEach((el) => { el.hidden = role !== 'admin'; });
    document.querySelectorAll('#panel-skill .skill-market-card').forEach((card, index) => {
      const install = card.querySelector('.btn-install-skill');
      const id = card.dataset.marketId || install?.dataset.skill || ('skill_' + index);
      card.dataset.marketId = id;
      const state = skillMarketState[id] || {};
      const nameEl = card.querySelector('.skill-market-name');
      const descEl = card.querySelector('.skill-market-desc');
      if (state.name && nameEl) nameEl.textContent = state.name;
      if (state.description && descEl) descEl.textContent = state.description;
      const offline = state.status === 'offline';
      card.classList.toggle('market-offline', offline);
      card.hidden = role === 'user' && offline;
      if (install) {
        const installed = skillConfigs.some((item) => item.marketId === id);
        install.hidden = role === 'admin';
        install.disabled = installed;
        install.textContent = installed ? '已安装' : '安装';
      }
      card.querySelector('.admin-market-actions')?.remove();
      if (role === 'admin') {
        const actions = document.createElement('div');
        actions.className = 'admin-market-actions';
        actions.innerHTML = `
          <button data-market-action="edit" data-market-type="skill" data-id="${escapeHtml(id)}">修改</button>
          <button data-market-action="toggle" data-market-type="skill" data-id="${escapeHtml(id)}">${offline ? '上线' : '下线'}</button>`;
        card.appendChild(actions);
      }
    });
  }

  function ensureMarketSkillPrompts() {
    let changed = false;
    (skillConfigs || []).forEach((item) => {
      if (!item || item.source !== 'market' || !item.marketId) return;
      const preset = SKILL_MARKET_PROMPTS[item.marketId];
      if (preset && !(item.prompt || '').trim()) {
        item.prompt = preset;
        changed = true;
      }
    });
    if (changed) persistSkillData();
  }

  function initSkillPanel() {
    ensureMarketSkillPrompts();
    renderSkillList();
    renderSkillMarket();
  }

  // ===== Agent management =====
  let editingAgentId = null;

  function updateAgentStatusOptions() {
    document.querySelectorAll('#addAgentModal .status-option').forEach((option) => {
      const input = option.querySelector('input');
      option.classList.toggle('active', Boolean(input?.checked));
    });
  }

  function syncAgentBindCount(containerId, countId, selectedSize, total) {
    const el = document.getElementById(countId);
    if (!el) return;
    el.textContent = total ? `${selectedSize}/${total}` : '0';
  }

  function renderAgentBindCheckboxes(containerId, items, selectedIds, valueKey, labelFn, countId) {
    const root = document.getElementById(containerId);
    if (!root) return;
    const selected = new Set((selectedIds || []).map(String));
    if (!items.length) {
      root.innerHTML = '<div class="agent-bind-empty">暂无可用项，请先到对应面板配置</div>';
      if (countId) syncAgentBindCount(containerId, countId, 0, 0);
      return;
    }
    root.innerHTML = items.map((item) => {
      const value = String(item[valueKey]);
      const label = labelFn(item);
      const on = selected.has(value);
      return `<label class="agent-bind-chip${on ? ' is-on' : ''}"><input type="checkbox" value="${escapeHtml(value)}"${on ? ' checked' : ''}><span>${escapeHtml(label)}</span></label>`;
    }).join('');
    if (countId) syncAgentBindCount(containerId, countId, selected.size, items.length);
    root.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.addEventListener('change', () => {
        const chip = input.closest('.agent-bind-chip');
        chip?.classList.toggle('is-on', input.checked);
        const checked = root.querySelectorAll('input[type="checkbox"]:checked').length;
        if (countId) syncAgentBindCount(containerId, countId, checked, items.length);
      });
    });
  }

  function readAgentBindIds(containerId) {
    const root = document.getElementById(containerId);
    if (!root) return [];
    return [...root.querySelectorAll('input[type="checkbox"]:checked')].map((el) => el.value);
  }

  function fillAgentModalOptions(agent = null) {
    const hint = document.getElementById('agentModelInheritHint');
    if (hint) {
      const active = getActiveModel();
      hint.textContent = active
        ? (`当前：${active.displayName || active.name}（随模型配置变更）`)
        : '尚未设置当前模型，请先到「模型配置」添加并设为当前';
      hint.classList.toggle('is-warn', !active);
    }
    renderAgentBindCheckboxes('agentSkillBindList', skillConfigs || [], agent?.skillIds || [], 'id', (item) => item.name || item.id, 'agentSkillCount');
    renderAgentBindCheckboxes(
      'agentKbBindList',
      knowledgeBases || [],
      agent?.knowledgeBaseIds || [],
      'id',
      (item) => item.name || ('知识库 #' + item.id),
      'agentKbCount'
    );
    renderAgentBindCheckboxes(
      'agentDsBindList',
      dataSources || [],
      agent?.dataSourceIds || [],
      'id',
      (item) => item.name || ('数据源 #' + item.id),
      'agentDsCount'
    );
    renderAgentBindCheckboxes('agentMcpBindList', mcpConfigs || [], agent?.mcpServerIds || [], 'id', (item) => item.name || item.id, 'agentMcpCount');
  }

  function openAgentModal(item = null) {
    editingAgentId = item?.id || null;
    const agent = item ? normalizeAgent(item) : null;
    const title = document.getElementById('agentModalTitle');
    if (title) title.textContent = item ? '编辑 Agent' : '新建 Agent';
    const name = document.getElementById('agentName');
    const description = document.getElementById('agentDescription');
    if (name) name.value = agent?.name || '';
    if (description) description.value = agent?.description || '';
    fillAgentModalOptions(agent);
    const policy = agent?.toolPolicy || defaultAgentToolPolicy();
    const toolEnabled = document.getElementById('agentToolEnabled');
    const allowMcp = document.getElementById('agentAllowMcp');
    const allowPipeline = document.getElementById('agentAllowPipeline');
    const maxRounds = document.getElementById('agentMaxRounds');
    if (toolEnabled) toolEnabled.checked = policy.enabled !== false;
    if (allowMcp) allowMcp.checked = Boolean(policy.allowMcp);
    if (allowPipeline) allowPipeline.checked = Boolean(policy.allowPipeline);
    if (maxRounds) maxRounds.value = String(policy.maxRounds || 6);
    const enabledValue = agent?.enabled === false ? 'false' : 'true';
    const radio = document.querySelector(`#addAgentModal input[name="agentEnabled"][value="${enabledValue}"]`);
    if (radio) radio.checked = true;
    updateAgentStatusOptions();
    document.getElementById('addAgentModal')?.classList.add('open');
    window.setTimeout(() => name?.focus(), 50);
  }

  function closeAgentModal() {
    document.getElementById('addAgentModal')?.classList.remove('open');
    editingAgentId = null;
  }

  function saveAgentFromModal() {
    const name = document.getElementById('agentName')?.value.trim() || '';
    if (!name) {
      showAppToast('请填写 Agent 名称', 'warn');
      document.getElementById('agentName')?.focus();
      return;
    }
    const payload = normalizeAgent({
      id: editingAgentId || ('agent_' + Date.now()),
      name,
      description: document.getElementById('agentDescription')?.value.trim() || '',
      enabled: document.querySelector('#addAgentModal input[name="agentEnabled"]:checked')?.value !== 'false',
      skillIds: readAgentBindIds('agentSkillBindList'),
      knowledgeBaseIds: readAgentBindIds('agentKbBindList').map(Number),
      dataSourceIds: readAgentBindIds('agentDsBindList').map(Number),
      mcpServerIds: readAgentBindIds('agentMcpBindList'),
      toolPolicy: {
        enabled: document.getElementById('agentToolEnabled')?.checked !== false,
        allowMcp: Boolean(document.getElementById('agentAllowMcp')?.checked),
        allowPipeline: Boolean(document.getElementById('agentAllowPipeline')?.checked),
        maxRounds: Number(document.getElementById('agentMaxRounds')?.value) || 6,
      },
      createdAt: agentConfigs.find((entry) => entry.id === editingAgentId)?.createdAt || Date.now(),
    });
    const existing = agentConfigs.find((entry) => entry.id === editingAgentId);
    if (existing) {
      Object.assign(existing, payload);
    } else {
      agentConfigs.push(payload);
    }
    persistAgentData();
    closeAgentModal();
    initAgentPanel();
    updateChatAgentOptions();
    updateCurrentModelLabel();
    showAppToast(existing ? 'Agent 已更新' : 'Agent 已创建', 'ok');
  }

  function renderAgentList() {
    const list = document.getElementById('agentList');
    const summary = document.getElementById('agentListSummary');
    if (!list) return;
    const keyword = (document.getElementById('agentSearchInput')?.value || '').trim().toLowerCase();
    const all = agentConfigs || [];
    const filtered = all.filter((item) => {
      if (!keyword) return true;
      const blob = `${item.name || ''} ${item.description || ''}`.toLowerCase();
      return blob.includes(keyword);
    });
    if (summary) {
      const activeName = getActiveAgent()?.name;
      summary.textContent = all.length
        ? (`共 ${all.length} 个` + (activeName ? ` · 对话中：${activeName}` : ' · 请在对话页选用'))
        : '保存后请到对话页顶部选择要使用的 Agent';
    }
    if (!filtered.length) {
      list.innerHTML = all.length
        ? '<div class="agent-empty"><strong>没有匹配的 Agent</strong><span>试试其他关键词</span></div>'
        : '<div class="agent-empty"><div class="agent-empty-icon" aria-hidden="true">◇</div><strong>还没有 Agent</strong><span>创建 Agent 后，对话将自动使用模型配置中的当前模型</span></div>';
      return;
    }
    list.innerHTML = filtered.map((item) => {
      const activeModel = getActiveModel();
      const modelName = activeModel
        ? (`模型：${activeModel.displayName || activeModel.name}`)
        : '模型：沿用当前配置';
      const chips = [
        { label: modelName, tone: activeModel ? 'model' : 'soft' },
        (item.skillIds || []).length ? { label: `Skill ${item.skillIds.length}`, tone: 'soft' } : null,
        (item.knowledgeBaseIds || []).length ? { label: `知识库 ${item.knowledgeBaseIds.length}`, tone: 'soft' } : null,
        (item.dataSourceIds || []).length ? { label: `数据源 ${item.dataSourceIds.length}`, tone: 'soft' } : null,
        (item.mcpServerIds || []).length ? { label: `MCP ${item.mcpServerIds.length}`, tone: 'soft' } : null,
        item.toolPolicy?.enabled === false ? { label: '无工具', tone: 'warn' } : null,
      ].filter(Boolean);
      const active = item.id === activeAgentId;
      const disabled = item.enabled === false;
      return `
      <article class="agent-card${active ? ' is-active' : ''}${disabled ? ' is-disabled' : ''}">
        <div class="agent-card-top">
          <div class="agent-card-title-wrap">
            <h4 class="agent-card-title">${escapeHtml(item.name)}</h4>
            <div class="agent-card-badges">
              ${active ? '<span class="agent-badge agent-badge-active">对话中</span>' : ''}
              <span class="agent-badge ${disabled ? 'agent-badge-off' : 'agent-badge-on'}">${disabled ? '已停用' : '已启用'}</span>
            </div>
          </div>
          <p class="agent-card-desc">${escapeHtml(item.description || '未填写说明')}</p>
        </div>
        <div class="agent-card-chips">
          ${chips.map((chip) => `<span class="agent-chip agent-chip-${chip.tone}">${escapeHtml(chip.label)}</span>`).join('')}
        </div>
        <div class="agent-card-actions">
          <button type="button" class="agent-action-primary" data-agent-action="edit" data-id="${escapeHtml(item.id)}">编辑</button>
          <button type="button" data-agent-action="toggle" data-id="${escapeHtml(item.id)}">${disabled ? '启用' : '停用'}</button>
          <button type="button" class="danger" data-agent-action="delete" data-id="${escapeHtml(item.id)}">删除</button>
        </div>
      </article>`;
    }).join('');
  }

  function initAgentPanel() {
    renderAgentList();
  }

  function syncChatAgentPickerButton() {
    const btn = document.getElementById('chatAgentPickerBtn');
    if (!btn) return;
    const enabled = (agentConfigs || []).filter((item) => item && item.enabled !== false);
    const agent = getActiveAgent();
    if (!enabled.length) {
      btn.textContent = '暂无 Agent';
      btn.title = '请先在配置中心启用 Agent';
      return;
    }
    if (!agent) {
      btn.textContent = '请选择 Agent';
      btn.title = '选择已启用的 Agent';
      return;
    }
    btn.textContent = 'Agent：' + agent.name;
    btn.title = agent.description || agent.name;
  }

  function updateChatAgentOptions() {
    const list = document.getElementById('chatAgentPickerList');
    if (!list) return;
    const enabled = (agentConfigs || []).filter((item) => item && item.enabled !== false);
    if (!enabled.some((item) => item.id === activeAgentId)) {
      activeAgentId = enabled.length ? enabled[0].id : '';
      persistAgentData();
    }
    if (!enabled.length) {
      list.innerHTML = '<div class="chat-kb-picker-empty">暂无可用 Agent</div>';
      syncChatAgentPickerButton();
      return;
    }
    list.innerHTML = enabled.map((item) => `
      <label class="chat-kb-picker-item">
        <input type="radio" name="chatAgentPick" value="${escapeHtml(item.id)}"${item.id === activeAgentId ? ' checked' : ''}>
        <span>${escapeHtml(item.name)}</span>
      </label>`).join('');
    syncChatAgentPickerButton();
  }

  function setActiveAgent(id) {
    activeAgentId = id || '';
    persistAgentData();
    updateChatAgentOptions();
    updateCurrentModelLabel();
    initAgentPanel();
  }

  function bindChatAgentPicker() {
    const picker = document.getElementById('chatAgentPicker');
    const btn = document.getElementById('chatAgentPickerBtn');
    const menu = document.getElementById('chatAgentPickerMenu');
    if (!picker || !btn || !menu || picker.dataset.bound) return;
    picker.dataset.bound = '1';
    const closeMenu = () => { menu.hidden = true; };
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      const kbMenu = document.getElementById('chatKbPickerMenu');
      const dsMenu = document.getElementById('chatDsPickerMenu');
      if (kbMenu) kbMenu.hidden = true;
      if (dsMenu) dsMenu.hidden = true;
    });
    menu.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', closeMenu);
    menu.addEventListener('change', (event) => {
      const input = event.target.closest('input[name="chatAgentPick"]');
      if (!input || !input.value) return;
      setActiveAgent(input.value);
      closeMenu();
    });
  }

  function initOverview() {
    // Overview panel removed; keep no-op for existing call sites.
  }

  // Expose for inline onclick in HTML


  async function gatewayAdminApi(path, options = {}) {
    const res = await apiFetch('/api/gateway/v1/admin' + path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === 'string'
        ? data.detail
        : (data.detail?.message || data.message || `请求失败 (${res.status})`);
      throw new Error(detail);
    }
    return data;
  }

  let gatewayAdminProvidersCache = [];

  async function loadGatewayAdminProviders() {
    const box = document.getElementById('gatewayAdminProvidersList');
    const select = document.getElementById('gwModelProvider');
    const data = await gatewayAdminApi('/providers');
    gatewayAdminProvidersCache = data.items || [];
    if (select) {
      select.innerHTML = gatewayAdminProvidersCache.map((p) =>
        `<option value="${p.id}">${escapeHtml(p.name)} (${escapeHtml(p.adapter)})${p.has_api_key ? '' : ' · 缺Key'}</option>`
      ).join('') || '<option value="">暂无厂商</option>';
    }
    if (!box) return;
    if (!gatewayAdminProvidersCache.length) {
      box.innerHTML = '<div class="doc-empty-hint">暂无厂商，启动种子应已写入 deepseek/qwen/openai/anthropic</div>';
      return;
    }
    box.innerHTML = gatewayAdminProvidersCache.map((p) => `
      <div class="authz-perm-row" data-provider-id="${p.id}">
        <div class="authz-perm-row__body">
          <div class="authz-perm-row__title">
            <span class="authz-perm-type">${escapeHtml(p.adapter)}</span>
            <strong>${escapeHtml(p.name)}</strong>
          </div>
          <div class="authz-perm-row__meta">
            <span class="authz-chip">${p.has_api_key ? '已配置 Key' : '未配置 Key'}</span>
            <span>${escapeHtml(p.base_url || '-')}</span>
          </div>
          <div class="authz-grant-form__row" style="margin-top:8px">
            <div class="form-group" style="grid-column:1/-1">
              <input class="form-input" data-provider-key="${p.id}" type="password" placeholder="粘贴新 API Key（留空不改）" autocomplete="off">
            </div>
          </div>
        </div>
        <div class="authz-perm-row__actions">
          <button type="button" class="btn-secondary" data-provider-save="${p.id}">保存 Key</button>
        </div>
      </div>`).join('');
  }

  async function loadGatewayAdminModels() {
    const box = document.getElementById('gatewayAdminModelsList');
    if (!box) return;
    box.innerHTML = '<div class="doc-empty-hint">加载中…</div>';
    const data = await gatewayAdminApi('/models');
    const items = data.items || [];
    if (!items.length) {
      box.innerHTML = '<div class="doc-empty-hint">暂无逻辑模型，请在上方表单新增</div>';
      return;
    }
    box.innerHTML = items.map((m) => `
      <div class="authz-perm-row">
        <div class="authz-perm-row__body">
          <div class="authz-perm-row__title">
            <span class="authz-perm-type">模型</span>
            <strong>${escapeHtml(m.display_name || m.model_id)}</strong>
          </div>
          <div class="authz-perm-row__meta">
            <span class="authz-chip">${escapeHtml(m.model_id)}</span>
            <span>${escapeHtml(m.provider_name || '')} → ${escapeHtml(m.upstream_model || '')}</span>
            <span class="authz-chip">${m.is_active ? '启用' : '停用'}</span>
          </div>
        </div>
        <div class="authz-perm-row__actions">
          <button type="button" class="btn-secondary danger" data-model-del="${m.id}">删除</button>
        </div>
      </div>`).join('');
  }

  async function loadGatewayAdminRoutes() {
    const box = document.getElementById('gatewayAdminRoutesList');
    if (!box) return;
    box.innerHTML = '<div class="doc-empty-hint">加载中…</div>';
    const data = await gatewayAdminApi('/routes');
    const items = data.items || [];
    if (!items.length) {
      box.innerHTML = '<div class="doc-empty-hint">暂无路由策略</div>';
      return;
    }
    box.innerHTML = items.map((r) => `
      <div class="authz-perm-row">
        <div class="authz-perm-row__body">
          <div class="authz-perm-row__title">
            <span class="authz-perm-type">路由</span>
            <strong>${escapeHtml(r.name)}</strong>
          </div>
          <div class="authz-perm-row__meta">
            <span>${escapeHtml(r.description || '')}</span>
            <span class="authz-chip">${escapeHtml((r.model_ids || []).join(' → ') || '-')}</span>
            <span class="authz-chip">${r.is_active ? '启用' : '停用'}</span>
          </div>
        </div>
      </div>`).join('');
  }

  async function refreshGatewayAdminAll() {
    if (!isPlatformAdmin()) return;
    try {
      await loadGatewayAdminProviders();
      await loadGatewayAdminModels();
      await loadGatewayAdminRoutes();
    } catch (error) {
      showAppToast(error.message || '加载 Gateway 配置失败', 'error');
    }
  }

  function initGatewayAdminPanel() {
    if (!isPlatformAdmin()) {
      showAppToast('仅管理员可配置逻辑模型与 Gateway 策略', 'warn');
      switchToPanel('model');
      return;
    }
    refreshGatewayAdminAll();
    const root = document.getElementById('panel-gateway');
    if (root && !root.dataset.bound) {
      root.dataset.bound = '1';
      root.querySelectorAll('[data-gateway-tab]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const tab = btn.dataset.gatewayTab;
          root.querySelectorAll('[data-gateway-tab]').forEach((el) => el.classList.toggle('active', el === btn));
          ['models', 'routes', 'providers'].forEach((name) => {
            const pane = document.getElementById('gateway-tab-' + name);
            if (!pane) return;
            const on = name === tab;
            pane.hidden = !on;
            pane.classList.toggle('active', on);
          });
        });
      });
      document.getElementById('gatewayAdminRefreshModelsBtn')?.addEventListener('click', () => loadGatewayAdminModels().catch((e) => showAppToast(e.message, 'error')));
      document.getElementById('gatewayAdminRefreshRoutesBtn')?.addEventListener('click', () => loadGatewayAdminRoutes().catch((e) => showAppToast(e.message, 'error')));
      document.getElementById('gatewayAdminRefreshProvidersBtn')?.addEventListener('click', () => loadGatewayAdminProviders().catch((e) => showAppToast(e.message, 'error')));
      document.getElementById('gwModelCreateBtn')?.addEventListener('click', async () => {
        try {
          const model_id = document.getElementById('gwModelId')?.value?.trim();
          const display_name = document.getElementById('gwModelDisplay')?.value?.trim() || model_id;
          const provider_id = Number(document.getElementById('gwModelProvider')?.value || 0);
          const upstream_model = document.getElementById('gwModelUpstream')?.value?.trim() || model_id;
          if (!model_id || !provider_id) {
            showAppToast('请填写逻辑 ID 并选择厂商', 'warn');
            return;
          }
          await gatewayAdminApi('/models', {
            method: 'POST',
            body: JSON.stringify({ model_id, display_name, provider_id, upstream_model }),
          });
          showAppToast('逻辑模型已创建', 'ok');
          document.getElementById('gwModelId').value = '';
          document.getElementById('gwModelDisplay').value = '';
          document.getElementById('gwModelUpstream').value = '';
          await loadGatewayAdminModels();
        } catch (error) {
          showAppToast(error.message || '创建失败', 'error');
        }
      });
      document.getElementById('gwRouteCreateBtn')?.addEventListener('click', async () => {
        try {
          const name = document.getElementById('gwRouteName')?.value?.trim();
          const description = document.getElementById('gwRouteDesc')?.value?.trim() || '';
          const model_ids = String(document.getElementById('gwRouteModels')?.value || '')
            .split(/[,，\s]+/)
            .map((x) => x.trim())
            .filter(Boolean);
          if (!name || !model_ids.length) {
            showAppToast('请填写策略名与至少一个逻辑模型', 'warn');
            return;
          }
          // create or patch existing by name
          const existing = (await gatewayAdminApi('/routes')).items || [];
          const hit = existing.find((r) => r.name === name);
          if (hit) {
            await gatewayAdminApi('/routes/' + hit.id, {
              method: 'PATCH',
              body: JSON.stringify({ description, model_ids, is_active: true }),
            });
            showAppToast('路由策略已更新', 'ok');
          } else {
            await gatewayAdminApi('/routes', {
              method: 'POST',
              body: JSON.stringify({ name, description, model_ids }),
            });
            showAppToast('路由策略已创建', 'ok');
          }
          await loadGatewayAdminRoutes();
        } catch (error) {
          showAppToast(error.message || '保存路由失败', 'error');
        }
      });
      document.getElementById('gatewayAdminModelsList')?.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-model-del]');
        if (!btn) return;
        if (!confirm('确认删除该逻辑模型？')) return;
        try {
          await gatewayAdminApi('/models/' + btn.getAttribute('data-model-del'), { method: 'DELETE' });
          showAppToast('已删除', 'ok');
          await loadGatewayAdminModels();
        } catch (error) {
          showAppToast(error.message || '删除失败', 'error');
        }
      });
      document.getElementById('gatewayAdminProvidersList')?.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-provider-save]');
        if (!btn) return;
        const id = btn.getAttribute('data-provider-save');
        const input = document.querySelector(`[data-provider-key="${id}"]`);
        const api_key = input?.value?.trim() || '';
        if (!api_key) {
          showAppToast('请先粘贴 API Key', 'warn');
          return;
        }
        try {
          await gatewayAdminApi('/providers/' + id, {
            method: 'PATCH',
            body: JSON.stringify({ api_key }),
          });
          if (input) input.value = '';
          showAppToast('厂商 Key 已保存', 'ok');
          await loadGatewayAdminProviders();
        } catch (error) {
          showAppToast(error.message || '保存失败', 'error');
        }
      });
    }
  }

  // usage panel kept

  async function loadGatewayUsage() {
    const box = document.getElementById('gatewayUsageList');
    if (!box) return;
    const groupBy = document.getElementById('gatewayUsageGroupBy')?.value || 'model';
    box.innerHTML = '<div class="doc-empty-hint">加载中…</div>';
    try {
      const res = await apiFetch('/api/gateway/v1/usage?group_by=' + encodeURIComponent(groupBy));
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof data.detail === 'string'
          ? data.detail
          : (data.detail?.message || data.message || `加载失败 (${res.status})`);
        throw new Error(detail);
      }
      const items = data?.items || [];
      if (!items.length) {
        box.innerHTML = '<div class="doc-empty-hint">暂无用量记录。发起对话或测试连接后将出现在此。</div>';
        return;
      }
      const keyName = groupBy === 'user' ? 'user_id' : (groupBy === 'source' ? 'source' : (groupBy === 'day' ? 'day' : 'model_id'));
      box.innerHTML = items.map((row) => `
        <div class="authz-perm-row">
          <div class="authz-perm-row__body">
            <div class="authz-perm-row__title">
              <span class="authz-perm-type">${escapeHtml(groupBy)}</span>
              <strong>${escapeHtml(String(row[keyName] ?? '-'))}</strong>
            </div>
            <div class="authz-perm-row__meta">
              <span class="authz-chip">调用 ${Number(row.calls || 0)}</span>
              <span class="authz-chip">tokens ${Number(row.total_tokens || 0)}</span>
              <span class="authz-chip">¥ ${Number(row.cost_cny || 0).toFixed(4)}</span>
            </div>
          </div>
        </div>`).join('');
    } catch (error) {
      box.innerHTML = `<div class="doc-empty-hint">${escapeHtml(error.message || '加载失败')}</div>`;
    }
  }

  function initGatewayUsagePanel() {
    loadGatewayUsage();
    const refresh = document.getElementById('gatewayUsageRefreshBtn');
    const group = document.getElementById('gatewayUsageGroupBy');
    if (refresh && !refresh.dataset.bound) {
      refresh.dataset.bound = '1';
      refresh.addEventListener('click', loadGatewayUsage);
    }
    if (group && !group.dataset.bound) {
      group.dataset.bound = '1';
      group.addEventListener('change', loadGatewayUsage);
    }
  }

  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.switchToPanel = switchToPanel;

  // ===== Event bindings =====
  mobileMenuBtn?.addEventListener('click', openSidebar);
  sidebarOverlay?.addEventListener('click', closeSidebar);
  sendBtn?.addEventListener('click', sendMessage);
  queryInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  queryInput?.addEventListener('input', autoResize);

  document.getElementById('closeChatNotice')?.addEventListener('click', () => closeChatNotice(false));
  document.getElementById('chatNoticeCancel')?.addEventListener('click', () => closeChatNotice(false));
  document.getElementById('chatNoticeAction')?.addEventListener('click', () => {
    const action = chatNoticeActionHandler;
    closeChatNotice(true);
    if (action) action();
  });

  newReportBtn?.addEventListener('click', () => {
    startNewConversation();
    queryInput?.focus();
    closeSidebar();
  });

  messagesEl?.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (chip?.dataset.q) {
      queryInput.value = chip.dataset.q;
      autoResize();
      sendMessage();
      return;
    }
    const source = e.target.closest('[data-source-chunk]');
    if (source) {
      openSettings('kb');
      const knowledgeBaseId = Number(source.dataset.sourceKb) || getSelectedChatKnowledgeBaseIds()[0];
      if (knowledgeBaseId) {
        selectKnowledgeBase(knowledgeBaseId).then(() => {
          openKbDetailModal();
          const chunksTab = document.querySelector('[data-live-kb-tab="chunks"]');
          chunksTab?.click();
          loadChunks(Number(source.dataset.sourceChunk));
        });
      }
    }
  });

  bindChatKbPicker();
  bindChatDsPicker();
  loadDataSourcesFromApi();
  reportList?.addEventListener('click', (e) => {
    const item = e.target.closest('.conv-item');
    if (!item) return;
    const id = item.dataset.conversationId;
    if (e.target.closest('[data-action="delete-conversation"]')) {
      e.stopPropagation();
      deleteConversation(id);
      return;
    }
    loadConversation(id);
  });

  document.getElementById('toolSettings')?.addEventListener('click', () => openSettings());

  settingsBtn?.addEventListener('click', () => openSettings());
  document.getElementById('closeModal')?.addEventListener('click', closeSettings);

  settingsModal?.querySelectorAll('.modal-nav-item').forEach((item) => {
    item.addEventListener('click', () => switchToPanel(item.dataset.panel));
  });

  document.getElementById('saveToolSettingsBtn')?.addEventListener('click', saveToolSettingsFromForm);
  document.getElementById('toolResetBtn')?.addEventListener('click', resetToolSettings);
  document.getElementById('toolEnableAllBtn')?.addEventListener('click', () => {
    setBuiltinToolsEnabled(() => true, true);
    showAppToast('已全部启用内置工具', 'ok');
  });
  document.getElementById('toolDisableAllBtn')?.addEventListener('click', () => {
    setBuiltinToolsEnabled(() => true, false);
    showAppToast('已全部停用内置工具', 'ok');
  });
  document.getElementById('toolSearchInput')?.addEventListener('input', debounce(renderToolSettingsPanel, 160));
  document.getElementById('toolSourceFilter')?.addEventListener('change', renderToolSettingsPanel);
  document.getElementById('toolBuiltinList')?.addEventListener('click', (event) => {
    const groupBtn = event.target.closest('[data-tool-group-action]');
    if (!groupBtn) return;
    event.preventDefault();
    event.stopPropagation();
    const source = decodeURIComponent(groupBtn.dataset.toolGroup || '');
    const enable = groupBtn.dataset.toolGroupAction === 'enable';
    setBuiltinToolsEnabled((tool) => tool.source === source, enable);
    showAppToast(`${source}工具已${enable ? '全部启用' : '全部停用'}`, 'ok');
  });
  document.getElementById('toolBuiltinList')?.addEventListener('change', (event) => {
    const input = event.target.closest('[data-tool-id]');
    if (!input) return;
    const row = input.closest('.tool-row');
    const state = row?.querySelector('.tool-toggle-state');
    if (state) state.textContent = input.checked ? '启用' : '停用';
    row?.classList.toggle('is-on', input.checked);
    row?.classList.toggle('is-off', !input.checked);
    // Keep summary in sync before save
    const draft = readToolSettingsFromForm();
    const enabledCount = BUILTIN_TOOLS.filter((tool) => draft.tools?.[tool.id] !== false).length;
    const summary = document.getElementById('toolBuiltinSummary');
    if (summary) summary.textContent = `${enabledCount} / ${BUILTIN_TOOLS.length} 启用`;
    const group = input.closest('.tool-group');
    if (group) {
      const countEl = group.querySelector('.tool-group-count');
      const boxes = [...group.querySelectorAll('[data-tool-id]')];
      const onCount = boxes.filter((box) => box.checked).length;
      if (countEl) countEl.textContent = `${onCount}/${boxes.length}`;
    }
  });

  document.getElementById('mcpRoleMode')?.addEventListener('change', renderMcpMarket);
  document.getElementById('skillRoleMode')?.addEventListener('change', renderSkillMarket);

  document.getElementById('addMcpBtn')?.addEventListener('click', () => openMcpModal());
  document.getElementById('closeAddMcp')?.addEventListener('click', closeMcpModal);
  document.getElementById('cancelAddMcp')?.addEventListener('click', closeMcpModal);
  document.getElementById('testMcpBtn')?.addEventListener('click', testMcpConnection);
  document.getElementById('saveMcpBtn')?.addEventListener('click', saveMcpFromModal);
  document.getElementById('formatMcpJsonBtn')?.addEventListener('click', () => {
    const editor = document.getElementById('mcpJson');
    try {
      editor.value = JSON.stringify(JSON.parse(editor.value), null, 2);
      invalidateMcpVerification();
    } catch (error) {
      setMcpTestResult('error', 'mcp.json 格式错误，' + error.message);
    }
  });
  document.querySelectorAll('#addMcpModal input[name="mcpEnabled"]').forEach((radio) => {
    radio.addEventListener('change', updateMcpStatusOptions);
  });
  ['mcpName', 'mcpJson'].forEach((id) => {
    document.getElementById(id)?.addEventListener('input', invalidateMcpVerification);
  });

  document.getElementById('mcpList')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-mcp-action]');
    if (!button) return;
    const item = mcpConfigs.find((entry) => entry.id === button.dataset.id);
    if (!item) return;
    if (button.dataset.mcpAction === 'toggle') item.enabled = item.enabled === false;
    if (button.dataset.mcpAction === 'edit') {
      openMcpModal(item);
      return;
    }
    if (button.dataset.mcpAction === 'delete') {
      if (!confirm('确定删除 MCP「' + item.name + '」？')) return;
      mcpConfigs = mcpConfigs.filter((entry) => entry.id !== item.id);
    }
    persistMcpData();
    initMcpPanel();
    initOverview();
  });

  document.getElementById('mcpMarketGrid')?.addEventListener('click', (event) => {
    const install = event.target.closest('.btn-install-mcp');
    if (install && !install.disabled) {
      const card = install.closest('.mcp-market-card');
      const id = card.dataset.marketId || install.dataset.mcp;
      const name = card.querySelector('.mcp-market-name')?.textContent.trim() || id;
      const description = card.querySelector('.mcp-market-desc')?.textContent.trim() || '';
      const preset = getMcpMarketPreset(id, name);
      if (id === 'tushare' && preset.mcpJson) {
        openMcpModal({
          id: 'mcp_' + Date.now(),
          marketId: id,
          name: preset.name || name,
          description: preset.description || description,
          mcpJson: preset.mcpJson,
          enabled: true,
          source: 'market',
        });
        showAppToast('请填写 Tushare Token 与可选代理，测试通过后保存', 'ok');
        return;
      }
      mcpConfigs.push({
        id: 'installed_' + Date.now(),
        marketId: id,
        name: preset.name || name,
        description: preset.description || description,
        mcpJson: preset.mcpJson,
        enabled: true,
        connectionStatus: preset.mcpJson ? 'connected' : '',
        source: 'market',
        testedAt: preset.mcpJson ? new Date().toISOString() : undefined,
      });
      persistMcpData();
      initMcpPanel();
      initOverview();
      showAppToast(
        preset.mcpJson
          ? `已安装「${preset.name || name}」`
          : `已安装「${name}」（需自行补充 mcp.json）`,
        preset.mcpJson ? 'ok' : 'warn',
      );
      return;
    }
    const adminButton = event.target.closest('[data-market-action][data-market-type="mcp"]');
    if (!adminButton) return;
    const id = adminButton.dataset.id;
    const state = mcpMarketState[id] || {};
    if (adminButton.dataset.marketAction === 'toggle') {
      state.status = state.status === 'offline' ? 'online' : 'offline';
    } else {
      const card = adminButton.closest('.mcp-market-card');
      const name = prompt('市场名称', state.name || card.querySelector('.mcp-market-name')?.textContent || '');
      if (!name) return;
      state.name = name.trim();
      state.description = (prompt('功能说明', state.description || card.querySelector('.mcp-market-desc')?.textContent || '') || '').trim();
    }
    mcpMarketState[id] = state;
    persistMcpData();
    renderMcpMarket();
  });

  document.getElementById('addMcpMarketBtn')?.addEventListener('click', () => {
    const name = prompt('发布删MCP 市场：名称');
    if (!name) return;
    customMcpMarket.push({
      id: 'market_mcp_' + Date.now(),
      name: name.trim(),
      description: (prompt('功能说明') || '').trim(),
      type: (prompt('类型', 'API') || 'API').trim(),
    });
    persistMcpData();
    renderMcpMarket();
  });

  document.getElementById('addSkillBtn')?.addEventListener('click', () => openSkillModal());
  document.getElementById('closeAddSkill')?.addEventListener('click', closeSkillModal);
  document.getElementById('cancelAddSkill')?.addEventListener('click', closeSkillModal);
  document.getElementById('saveSkillBtn')?.addEventListener('click', saveSkillFromModal);

  document.getElementById('addAgentBtn')?.addEventListener('click', () => openAgentModal());
  document.getElementById('closeAddAgent')?.addEventListener('click', closeAgentModal);
  document.getElementById('cancelAddAgent')?.addEventListener('click', closeAgentModal);
  document.getElementById('saveAgentBtn')?.addEventListener('click', saveAgentFromModal);
  document.getElementById('addAgentModal')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closeAgentModal();
  });
  document.querySelectorAll('#addAgentModal input[name="agentEnabled"]').forEach((radio) => {
    radio.addEventListener('change', updateAgentStatusOptions);
  });
  document.getElementById('agentSearchInput')?.addEventListener('input', renderAgentList);
  document.getElementById('agentList')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-agent-action]');
    if (!button) return;
    const item = agentConfigs.find((entry) => entry.id === button.dataset.id);
    if (!item) return;
    const action = button.dataset.agentAction;
    if (action === 'toggle') item.enabled = item.enabled === false;
    if (action === 'edit') {
      openAgentModal(item);
      return;
    }
    if (action === 'delete') {
      if (!confirm('确定删除 Agent「' + item.name + '」？')) return;
      agentConfigs = agentConfigs.filter((entry) => entry.id !== item.id);
      if (activeAgentId === item.id) activeAgentId = '';
    }
    persistAgentData();
    initAgentPanel();
    updateChatAgentOptions();
    updateCurrentModelLabel();
  });
  document.getElementById('addSkillModal')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closeSkillModal();
  });
  document.querySelectorAll('#addSkillModal input[name="skillEnabled"]').forEach((radio) => {
    radio.addEventListener('change', updateSkillStatusOptions);
  });

  document.getElementById('skillList')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-skill-action]');
    if (!button) return;
    const item = skillConfigs.find((entry) => entry.id === button.dataset.id);
    if (!item) return;
    if (button.dataset.skillAction === 'toggle') item.enabled = item.enabled === false;
    if (button.dataset.skillAction === 'edit') {
      openSkillModal(item);
      return;
    }
    if (button.dataset.skillAction === 'delete') {
      if (!confirm('确定删除 Skill「' + item.name + '」？')) return;
      skillConfigs = skillConfigs.filter((entry) => entry.id !== item.id);
    }
    persistSkillData();
    initSkillPanel();
    initOverview();
  });

  document.getElementById('panel-skill')?.addEventListener('click', (event) => {
    const install = event.target.closest('.btn-install-skill');
    if (install && !install.disabled) {
      const card = install.closest('.skill-market-card');
      const id = card.dataset.marketId || install.dataset.skill;
      const marketPrompt = SKILL_MARKET_PROMPTS[id] || '';
      skillConfigs.push({
        id: 'installed_skill_' + Date.now(),
        marketId: id,
        name: card.querySelector('.skill-market-name')?.textContent.trim() || id,
        description: card.querySelector('.skill-market-desc')?.textContent.trim() || '',
        prompt: marketPrompt,
        enabled: true,
        source: 'market',
      });
      persistSkillData();
      initSkillPanel();
      initOverview();
      return;
    }
    const adminButton = event.target.closest('[data-market-action][data-market-type="skill"]');
    if (!adminButton) return;
    const id = adminButton.dataset.id;
    const state = skillMarketState[id] || {};
    if (adminButton.dataset.marketAction === 'toggle') {
      state.status = state.status === 'offline' ? 'online' : 'offline';
    } else {
      const card = adminButton.closest('.skill-market-card');
      const name = prompt('市场名称', state.name || card.querySelector('.skill-market-name')?.textContent || '');
      if (!name) return;
      state.name = name.trim();
      state.description = (prompt('功能说明', state.description || card.querySelector('.skill-market-desc')?.textContent || '') || '').trim();
    }
    skillMarketState[id] = state;
    persistSkillData();
    renderSkillMarket();
  });

  document.getElementById('addSkillMarketBtn')?.addEventListener('click', () => {
    const name = prompt('发布删Skill 市场：名称');
    if (!name) return;
    customSkillMarket.push({
      id: 'market_skill_' + Date.now(),
      name: name.trim(),
      description: (prompt('功能说明') || '').trim(),
      category: (prompt('分类', '数据分析') || '数据分析').trim(),
      version: (prompt('版本', '1.0') || '1.0').trim(),
    });
    persistSkillData();
    renderSkillMarket();
  });

  document.getElementById('addModelBtn')?.addEventListener('click', openAddModel);
  document.getElementById('closeAddModel')?.addEventListener('click', closeAddModel);
  document.getElementById('cancelAddModel')?.addEventListener('click', closeAddModel);

  document.getElementById('providerGrid')?.addEventListener('click', (e) => {
    const chip = e.target.closest('.provider-chip');
    if (chip) selectProvider(chip.dataset.provider);
  });

  (function bindSecretInputs() {
    const lockEvents = ['copy', 'cut', 'dragstart'];
    document.querySelectorAll('#modelApiKey, .secret-input').forEach((input) => {
      input.type = 'password';
      lockEvents.forEach((evt) => {
        input.addEventListener(evt, (e) => {
          e.preventDefault();
          showAppToast('API Key 不可复制或显示', 'warn');
        });
      });
      input.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'x' || e.key === 'C' || e.key === 'X')) {
          e.preventDefault();
          showAppToast('API Key 不可复制或显示', 'warn');
        }
      });
    });
  })();

  document.getElementById('testModelBtn')?.addEventListener('click', testAddModelConnection);
  document.getElementById('modelName')?.addEventListener('change', () => {
    syncModelNameCustomVisibility();
    markSaveReady('saveModelBtn', false);
    showAddModelTest('', '');
  });
  document.getElementById('modelNameCustom')?.addEventListener('input', () => {
    markSaveReady('saveModelBtn', false);
  });

  document.getElementById('saveModelBtn')?.addEventListener('click', () => {
    if (!selectedProviderId) { showAddModelTest('error', '请先选择厂商'); return; }
    const providerName = getFieldValue('modelProviderName');
    const name = getSelectedModelName();
    const displayName = getFieldValue('modelDisplayName') || name;
    const apiKey = getFieldValue('modelApiKey');
    const baseUrl = getFieldValue('modelBaseUrl');
    if (!providerName) { showAddModelTest('error', '请填写供应商名称'); return; }
    if (!name) { showAddModelTest('error', '请选择或填写模型名称'); return; }
    if (!baseUrl) { showAddModelTest('error', '请填写官方连接(Base URL)'); return; }

    const wasEmpty = models.length === 0;
    const model = {
      id: 'model_' + Date.now(),
      provider: selectedProviderId,
      providerName,
      name,
      displayName,
      apiKey,
      baseUrl,
      status: 'pending',
      active: false,
    };
    models.push(model);
    if (wasEmpty) {
      activeModelId = model.id;
      model.active = true;
    }
    persistModels();
    closeAddModel();
    renderModelList();
    updateCurrentModelLabel();
    initOverview();
  });

  modelListEl?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const id = btn.dataset.id;
    const action = btn.dataset.action;
    if (action === 'activate-platform') {
      setActiveModel(id);
      showAppToast('已切换到平台模型', 'ok');
      return;
    }
    if (action === 'test-platform') {
      testPlatformConnection(id);
      return;
    }
    if (action === 'activate') {
      setActiveModel(id);
    }
    if (action === 'test') testConnection(id);
    if (action === 'delete') {
      const model = models.find((m) => m.id === id);
      if (!confirm('确定删除模型「' + (model?.displayName || model?.name || '') + '」？')) return;
      models = models.filter((m) => m.id !== id);
      if (activeModelId === id) {
        activeModelId = models[0]?.id || platformModels[0]?.id || null;
        models.forEach((m) => { m.active = m.id === activeModelId; });
        platformModels.forEach((m) => { m.active = m.id === activeModelId; });
      }
      persistModels();
      renderModelList();
      updateCurrentModelLabel();
      initOverview();
    }
  });

  document.getElementById('addDsBtn')?.addEventListener('click', openAddDs);
  document.getElementById('closeAddDs')?.addEventListener('click', closeAddDs);
  document.getElementById('cancelAddDs')?.addEventListener('click', closeAddDs);

  document.getElementById('dsType')?.addEventListener('change', (e) => {
    const type = e.target.value;
    const port = document.getElementById('dsPort');
    if (port && DEFAULT_PORTS[type]) port.value = DEFAULT_PORTS[type];
    syncDsTypeExtras(type);
  });

  document.getElementById('saveDsBtn')?.addEventListener('click', async () => {
    const type = document.getElementById('dsType')?.value;
    const name = document.getElementById('dsName')?.value.trim();
    const host = document.getElementById('dsHost')?.value.trim();
    if (!type || !name || !host) {
      showAddDsTest('error', '请填写类型、名称和 Host');
      return;
    }
    const payload = {
      type,
      name,
      host,
      port: document.getElementById('dsPort')?.value || DEFAULT_PORTS[type] || '',
      database: document.getElementById('dsDatabase')?.value.trim() || '',
      username: document.getElementById('dsUser')?.value.trim() || '',
      password: document.getElementById('dsPassword')?.value || '',
      extra: document.getElementById('dsExtra')?.value.trim() || '',
      query_only: Boolean(document.getElementById('dsQueryOnly')?.checked),
    };
    const btn = document.getElementById('saveDsBtn');
    if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }
    try {
      const isEdit = Boolean(editingDsId);
      if (isEdit) {
        await datasourceApi('/' + editingDsId, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        await datasourceApi('', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      closeAddDs();
      await loadDataSourcesFromApi();
      showAppToast(isEdit ? '数据源已更新' : '数据源已保存', 'ok');
    } catch (error) {
      showAddDsTest('error', '保存失败：' + (error.message || error));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '保存'; }
    }
  });

  document.getElementById('testDsBtn')?.addEventListener('click', async () => {
    const type = document.getElementById('dsType')?.value;
    const host = document.getElementById('dsHost')?.value.trim();
    if (!type || !host) {
      showAddDsTest('error', '请先填写类型和 Host');
      return;
    }
    const btn = document.getElementById('testDsBtn');
    if (btn) { btn.disabled = true; btn.textContent = '测试中...'; }
    markSaveReady('saveDsBtn', false);
    showAddDsTest('', '正在测试数据源连接...');
    try {
      await datasourceApi('/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type,
          host,
          port: document.getElementById('dsPort')?.value || '',
          database: document.getElementById('dsDatabase')?.value.trim() || '',
          username: document.getElementById('dsUser')?.value.trim() || '',
          password: document.getElementById('dsPassword')?.value || '',
          extra: document.getElementById('dsExtra')?.value.trim() || '',
        }),
      });
      markSaveReady('saveDsBtn', true);
      showAddDsTest('ok', '连接成功，可以保存该数据源');
    } catch (error) {
      markSaveReady('saveDsBtn', false);
      showAddDsTest('error', '连接失败：' + (error.message || error));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '测试连接'; }
    }
  });

  document.getElementById('dsSearchInput')?.addEventListener('input', debounce(renderDataSourceList, 180));
  document.getElementById('dsTypeFilter')?.addEventListener('change', renderDataSourceList);

  dsListEl?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-ds-action]');
    if (!btn) return;
    const id = btn.dataset.id;
    const action = btn.dataset.dsAction;
    if (action === 'edit') {
      const ds = dataSources.find((d) => String(d.id) === String(id));
      openEditDs(ds);
      return;
    }
    if (action === 'toggle-query-only') {
      const ds = dataSources.find((d) => String(d.id) === String(id));
      if (!ds) return;
      const nextOnly = !isDsQueryOnly(ds);
      const label = btn.querySelector('span');
      try {
        btn.disabled = true;
        btn.classList.add('is-loading');
        if (label) label.textContent = '更新中';
        await datasourceApi('/' + id, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query_only: nextOnly }),
        });
        await loadDataSourcesFromApi();
        showAppToast(
          nextOnly
            ? `「${ds.name}」已设为仅查询，后续不可写入`
            : `「${ds.name}」已允许写入`,
          'ok'
        );
      } catch (error) {
        showAppToast('权限更新失败：' + (error.message || error), 'error');
      } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
      }
      return;
    }
    if (action === 'delete') {
      const ds = dataSources.find((d) => String(d.id) === String(id));
      if (!confirm('确定删除数据源「' + (ds?.name || id) + '」？')) return;
      try {
        btn.disabled = true;
        await datasourceApi('/' + id, { method: 'DELETE' });
        await loadDataSourcesFromApi();
        showAppToast('数据源已删除', 'ok');
      } catch (error) {
        showAppToast('删除失败：' + (error.message || error), 'error');
      } finally {
        btn.disabled = false;
      }
      return;
    }
    if (action === 'test') {
      const label = btn.querySelector('span');
      try {
        btn.disabled = true;
        btn.classList.add('is-loading');
        if (label) label.textContent = '测试中';
        await datasourceApi('/' + id + '/test', { method: 'POST' });
        await loadDataSourcesFromApi();
        showAppToast('数据源连接成功', 'ok');
      } catch (error) {
        await loadDataSourcesFromApi();
        showAppToast('连接失败：' + (error.message || error), 'error');
      } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        if (label) label.textContent = '测试';
      }
    }
  });

  // Sub-nav toggles inside panels (kb / dataprocess / permission / dataoutput)
  document.querySelectorAll('[data-kb-tab], [data-dp-tab], [data-perm-tab], [data-do-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = ['kb', 'dp', 'perm', 'do'].find((k) => btn.dataset[k + 'Tab']);
      if (!key) return;
      const tab = btn.dataset[key + 'Tab'];
      const parent = btn.closest('.modal-panel') || btn.parentElement?.parentElement;
      parent?.querySelectorAll('.kb-sub-nav-item, .perm-tab').forEach((b) => {
        if (b.dataset[key + 'Tab']) b.classList.toggle('active', b === btn);
      });
      btn.parentElement?.querySelectorAll('[data-' + key + '-tab]').forEach((b) => {
        b.classList.toggle('active', b === btn);
      });
      const root = btn.closest('.modal-panel') || document;
      root.querySelectorAll('[id^="' + key + '-tab-"]').forEach((panel) => {
        panel.classList.toggle('active', panel.id === key + '-tab-' + tab);
      });
      if (key === 'dp' && tab === 'logs') loadPipelineRuns();
      if (key === 'dp' && tab === 'tasks') loadPipelines();
      if (key === 'perm' && tab === 'approval') loadApprovalList();
      if (key === 'perm' && tab === 'users') initUsersPanel();
      if (key === 'perm' && tab === 'audit') renderApprovalAuditList();
    });
  });

  // ===== Permission / pipeline approval / users =====
  const APPROVAL_AUDIT_KEY = 'ai_platform_approval_audit';

  function getPlatformRole() {
    return (currentAuthUser?.role === 'admin') ? 'admin' : 'user';
  }

  function isPlatformAdmin() {
    return getPlatformRole() === 'admin';
  }

  function defaultCapabilities(all = false) {
    return { agent: !!all, mcp: !!all, skill: !!all, tool: !!all };
  }

  function normalizeCapabilities(raw, asAdmin = false) {
    const base = defaultCapabilities(asAdmin);
    const src = raw && typeof raw === 'object' ? raw : {};
    return {
      agent: asAdmin ? true : Boolean(src.agent),
      mcp: asAdmin ? true : Boolean(src.mcp),
      skill: asAdmin ? true : Boolean(src.skill),
      tool: asAdmin ? true : Boolean(src.tool),
    };
  }

  function getUserCapabilities() {
    if (isPlatformAdmin()) return defaultCapabilities(true);
    return normalizeCapabilities(currentAuthUser?.capabilities || {});
  }

  function hasCapability(name) {
    const caps = getUserCapabilities();
    return Boolean(caps?.[name]);
  }

  function isAuthzCapabilityType(rtype) {
    return ['capability_agent', 'capability_mcp', 'capability_skill', 'capability_tool'].includes(String(rtype || ''));
  }

  function authzResourceTypeLabel(rtype) {
    const map = {
      knowledge_base: '知识库',
      datasource: '数据源',
      capability_agent: 'Agent 管理',
      capability_mcp: 'MCP 管理',
      capability_skill: 'Skill 管理',
      capability_tool: 'Tool 设置',
    };
    return map[rtype] || rtype || '资源';
  }


  function syncPlatformRoleUi() {
    const role = getPlatformRole();
    const hint = document.getElementById('approvalAdminHint');
    const nameEl = document.getElementById('permUserName');
    const metaEl = document.getElementById('permUserMeta');
    const badge = document.getElementById('permRoleBadge');
    if (nameEl) nameEl.textContent = currentAuthUser
      ? (currentAuthUser.display_name || currentAuthUser.username)
      : '未登录';
    if (metaEl) {
      metaEl.textContent = currentAuthUser
        ? (`账号：${currentAuthUser.username} · ${role === 'admin' ? '可审批流水线与管理用户' : '可使用平台能力，不可审批/管用户'}`)
        : '请先登录';
    }
    if (badge) {
      badge.textContent = role === 'admin' ? '管理员' : '普通用户';
      badge.classList.toggle('is-admin', role === 'admin');
    }
    const settingsName = document.getElementById('settingsUserName');
    const settingsRole = document.getElementById('settingsUserRole');
    if (settingsName) {
      settingsName.textContent = currentAuthUser
        ? (currentAuthUser.display_name || currentAuthUser.username)
        : '未登录';
    }
    if (settingsRole) {
      settingsRole.textContent = currentAuthUser
        ? (role === 'admin' ? '管理员' : '普通用户')
        : '-';
    }
    if (hint) {
      hint.hidden = role === 'admin';
      hint.textContent = role === 'admin'
        ? ''
        : '当前为普通用户，仅可查看审批列表；批准 / 驳回需管理员账号。';
    }
    document.getElementById('panel-permission')?.classList.toggle('is-admin', role === 'admin');
    document.querySelectorAll('[data-admin-only="1"]').forEach((el) => {
      el.hidden = role !== 'admin';
    });
    const caps = getUserCapabilities();
    ['agent', 'mcp', 'skill', 'tool'].forEach((key) => {
      const panel = document.getElementById('panel-' + key);
      if (panel) panel.hidden = !caps[key];
      document.querySelectorAll(`[data-panel="${key}"]`).forEach((el) => {
        el.hidden = !caps[key];
      });
    });
    if (role !== 'admin' && document.getElementById('panel-authz')?.classList.contains('active')) {
      switchToPanel('permission');
    }
    const activePanel = document.querySelector('.modal-panel.active')?.id || '';
    const activeKey = activePanel.replace(/^panel-/, '');
    if (['agent', 'mcp', 'skill', 'tool'].includes(activeKey) && !caps[activeKey]) {
      switchToPanel('model');
    }
    try { window.dispatchEvent(new CustomEvent('ai-platform-auth-changed')); } catch (_) {}
  }

  function showLoginOverlay(message = '') {
    const overlay = document.getElementById('loginOverlay');
    const err = document.getElementById('loginError');
    if (err) {
      err.hidden = !message;
      err.textContent = message || '';
    }
    overlay?.classList.add('open');
    overlay?.setAttribute('aria-hidden', 'false');
    document.body.classList.add('login-required');
    window.setTimeout(() => document.getElementById('loginUsername')?.focus(), 50);
  }

  function hideLoginOverlay() {
    const overlay = document.getElementById('loginOverlay');
    overlay?.classList.remove('open');
    overlay?.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('login-required');
    const err = document.getElementById('loginError');
    if (err) { err.hidden = true; err.textContent = ''; }
  }

  function showChangePasswordOverlay(message = '') {
    hideLoginOverlay();
    const overlay = document.getElementById('changePasswordOverlay');
    const err = document.getElementById('changePasswordError');
    const usernameEl = document.getElementById('changePasswordUsername');
    const roleEl = document.getElementById('changePasswordUserRole');
    const username = currentAuthUser?.username || currentAuthUser?.display_name || '-';
    const roleRaw = (currentAuthUser?.role || '').toString().trim().toLowerCase();
    const roleLabel = roleRaw === 'admin' ? '管理员' : (roleRaw ? '普通用户' : '-');
    if (usernameEl) usernameEl.textContent = username;
    if (roleEl) roleEl.textContent = roleLabel;
    if (err) {
      err.hidden = !message;
      err.textContent = message || '';
    }
    overlay?.classList.add('open');
    overlay?.setAttribute('aria-hidden', 'false');
    document.body.classList.add('login-required');
    window.setTimeout(() => document.getElementById('changePasswordCurrent')?.focus(), 50);
  }

  function hideChangePasswordOverlay() {
    const overlay = document.getElementById('changePasswordOverlay');
    overlay?.classList.remove('open');
    overlay?.setAttribute('aria-hidden', 'true');
    if (!document.getElementById('loginOverlay')?.classList.contains('open')) {
      document.body.classList.remove('login-required');
    }
    const err = document.getElementById('changePasswordError');
    if (err) { err.hidden = true; err.textContent = ''; }
    ['changePasswordCurrent', 'changePasswordNew', 'changePasswordConfirm'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
  }

  async function submitChangePassword() {
    const currentPassword = document.getElementById('changePasswordCurrent')?.value || '';
    const newPassword = document.getElementById('changePasswordNew')?.value || '';
    const confirm = document.getElementById('changePasswordConfirm')?.value || '';
    const err = document.getElementById('changePasswordError');
    const btn = document.getElementById('changePasswordSubmitBtn');
    if (!currentPassword || !newPassword) {
      if (err) { err.hidden = false; err.textContent = '请填写当前密码和新密码'; }
      return;
    }
    if (newPassword.length < 6) {
      if (err) { err.hidden = false; err.textContent = '新密码至少 6 位'; }
      return;
    }
    if (newPassword !== confirm) {
      if (err) { err.hidden = false; err.textContent = '两次输入的新密码不一致'; }
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '提交中...'; }
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatAuthError(data.detail, data.error || '修改密码失败'));
      }
      // Confirm server cleared the force-change flag before entering the app.
      const me = await refreshAuthUser();
      if (me?.must_change_password) {
        throw new Error('密码已提交，但服务器仍要求改密，请刷新后重试或联系管理员');
      }
      currentAuthUser = me || data.user || currentAuthUser;
      if (currentAuthUser) currentAuthUser.must_change_password = false;
      hideChangePasswordOverlay();
      syncPlatformRoleUi();
      await hydrateWorkspaceFromServer();
      showAppToast('密码已更新', 'ok');
      loadKnowledgeBases();
      loadDataSourcesFromApi();
    } catch (error) {
      if (err) {
        err.hidden = false;
        err.textContent = error.message || '修改密码失败';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '确认修改'; }
    }
  }

  async function refreshAuthUser() {
    const token = getAuthToken();
    if (!token) {
      currentAuthUser = null;
      return null;
    }
    try {
      const res = await fetch('/api/auth/me', { headers: authHeaders() });
      if (!res.ok) {
        setAuthToken('');
        currentAuthUser = null;
        return null;
      }
      currentAuthUser = await res.json();
      return currentAuthUser;
    } catch (_) {
      currentAuthUser = null;
      return null;
    }
  }

  function collectWorkspaceSettingsFromLocal() {
    const settings = {};
    WORKSPACE_LS_KEYS.forEach((key) => {
      const raw = localStorage.getItem(key);
      if (raw == null) return;
      try {
        settings[key] = JSON.parse(raw);
      } catch (_) {
        settings[key] = raw;
      }
    });
    return settings;
  }

  function writeWorkspaceSettingsToLocal(settings) {
    workspaceHydrated = false;
    try {
      WORKSPACE_LS_KEYS.forEach((key) => nativeLocalStorageRemoveItem(key));
      Object.entries(settings || {}).forEach(([key, value]) => {
        if (!WORKSPACE_LS_KEYS.has(key) || value == null) return;
        if (typeof value === 'string') nativeLocalStorageSetItem(key, value);
        else nativeLocalStorageSetItem(key, JSON.stringify(value));
      });
    } finally {
      workspaceHydrated = true;
    }
  }

  function clearLocalWorkspaceCache() {
    workspaceHydrated = false;
    clearTimeout(workspaceSyncTimer);
    workspaceSyncTimer = null;
    WORKSPACE_LS_KEYS.forEach((key) => nativeLocalStorageRemoveItem(key));
  }

  function applyWorkspaceToMemory() {
    models = loadModels();
    window.models = models;
    activeModelId = localStorage.getItem('active_model_id') || (models.find((m) => m.active)?.id) || null;
    mcpConfigs = loadStoredArray('user_mcp_configs');
    skillConfigs = loadStoredArray('user_skill_configs');
    agentConfigs = loadStoredArray('user_agent_configs').map((item) => {
      if (!item || typeof item !== 'object') return item;
      const next = { ...item };
      delete next.modelId;
      return next;
    });
    activeAgentId = localStorage.getItem('active_agent_id') || '';
    mcpMarketState = loadStoredObject('mcp_market_state');
    skillMarketState = loadStoredObject('skill_market_state');
    customMcpMarket = loadStoredArray('custom_mcp_market');
    customSkillMarket = loadStoredArray('custom_skill_market');
    selectedKnowledgeBaseId = Number(localStorage.getItem('selected_knowledge_base_id')) || null;
    apiKbConfigs = typeof loadApiKbConfigs === 'function' ? loadApiKbConfigs() : loadStoredArray(API_KB_CONFIGS_KEY);
    toolSettings = loadToolSettings();
    conversations = loadConversations();
    currentConversationId = localStorage.getItem(CURRENT_CONVERSATION_KEY) || null;
    renderConversationList();
    if (currentConversationId && getCurrentConversation()) {
      loadConversation(currentConversationId);
    } else {
      startNewConversation();
    }
    updateCurrentModelLabel();
    if (typeof updateChatAgentOptions === 'function') updateChatAgentOptions();
    if (typeof renderModelList === 'function') renderModelList();
    if (typeof renderToolSettingsPanel === 'function') renderToolSettingsPanel();
    if (typeof renderMcpList === 'function') renderMcpList();
    if (typeof renderSkillList === 'function') renderSkillList();
    if (typeof renderAgentList === 'function') renderAgentList();
  }

  async function flushWorkspaceToServer() {
    if (!getAuthToken()) return;
    if (workspaceSyncInFlight) {
      workspaceSyncQueued = true;
      return;
    }
    workspaceSyncInFlight = true;
    try {
      const settings = collectWorkspaceSettingsFromLocal();
      const res = await apiFetch('/api/workspace', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        console.warn('workspace sync failed', data.detail || res.status);
      }
    } catch (error) {
      console.warn('workspace sync failed', error);
    } finally {
      workspaceSyncInFlight = false;
      if (workspaceSyncQueued) {
        workspaceSyncQueued = false;
        scheduleWorkspaceSync();
      }
    }
  }

  async function hydrateWorkspaceFromServer() {
    try {
      const res = await apiFetch('/api/workspace');
      if (!res.ok) return false;
      const data = await res.json();
      if (data.empty) {
        workspaceHydrated = true;
        await flushWorkspaceToServer();
        applyWorkspaceToMemory();
        return true;
      }
      writeWorkspaceSettingsToLocal(data.settings || {});
      applyWorkspaceToMemory();
      return true;
    } catch (error) {
      console.warn('workspace hydrate failed', error);
      workspaceHydrated = true;
      return false;
    }
  }

  async function ensureAuthenticated() {
    const user = await refreshAuthUser();
    syncPlatformRoleUi();
    if (!user) {
      showLoginOverlay();
      await refreshRegisterAvailability();
      return false;
    }
    if (user.must_change_password) {
      showChangePasswordOverlay('首次登录请先修改密码后再使用平台功能');
      return false;
    }
    hideChangePasswordOverlay();
    hideLoginOverlay();
    await hydrateWorkspaceFromServer();
    return true;
  }

  let authMode = 'login';
  let publicRegisterEnabled = true;

  function formatAuthError(detail, fallback) {
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item.msg || item.detail || String(item)).join('；');
    }
    return fallback;
  }

  function setAuthMode(mode) {
    authMode = mode === 'register' ? 'register' : 'login';
    const loginPane = document.getElementById('authLoginPane');
    const registerPane = document.getElementById('authRegisterPane');
    const title = document.getElementById('loginTitle');
    const subtitle = document.getElementById('loginSubtitle');
    const btn = document.getElementById('loginSubmitBtn');
    const err = document.getElementById('loginError');
    document.querySelectorAll('[data-auth-mode]').forEach((el) => {
      el.classList.toggle('active', el.dataset.authMode === authMode);
    });
    if (loginPane) loginPane.hidden = authMode !== 'login';
    if (registerPane) registerPane.hidden = authMode !== 'register';
    if (title) title.textContent = authMode === 'register' ? '注册 AI 平台账号' : '登录 AI 平台';
    if (subtitle) {
      subtitle.textContent = authMode === 'register'
        ? '注册后自动登录，账号角色为普通用户'
        : '使用账号密码进入系统；新用户可注册普通账号';
    }
    if (btn) btn.textContent = authMode === 'register' ? '注册并登录' : '登录';
    if (err) { err.hidden = true; err.textContent = ''; }
    window.setTimeout(() => {
      const focusId = authMode === 'register' ? 'registerUsername' : 'loginUsername';
      document.getElementById(focusId)?.focus();
    }, 30);
  }

  async function refreshRegisterAvailability() {
    const registerBtn = document.getElementById('authModeRegisterBtn');
    const hint = document.getElementById('registerHint');
    try {
      const res = await fetch('/api/auth/register-status');
      const data = await res.json().catch(() => ({}));
      publicRegisterEnabled = res.ok ? Boolean(data.enabled) : true;
    } catch (_) {
      publicRegisterEnabled = true;
    }
    if (registerBtn) {
      registerBtn.disabled = !publicRegisterEnabled;
      registerBtn.title = publicRegisterEnabled ? '' : '管理员已关闭公开注册';
    }
    if (hint) {
      hint.textContent = publicRegisterEnabled
        ? '注册成功后自动登录，角色为普通用户'
        : '当前未开放公开注册，请联系管理员创建账号';
    }
    if (!publicRegisterEnabled && authMode === 'register') setAuthMode('login');
  }

  async function completeAuthSession(data, username) {
    setAuthToken(data.token || '');
    currentAuthUser = data.user || null;
    const pwd = document.getElementById('loginPassword');
    const rp = document.getElementById('registerPassword');
    const rpc = document.getElementById('registerPasswordConfirm');
    if (pwd) pwd.value = '';
    if (rp) rp.value = '';
    if (rpc) rpc.value = '';
    hideLoginOverlay();
    syncPlatformRoleUi();
    if (currentAuthUser?.must_change_password) {
      showChangePasswordOverlay('首次登录请先修改密码后再使用平台功能');
      return;
    }
    await hydrateWorkspaceFromServer();
    showAppToast(`欢迎，${currentAuthUser?.display_name || username}`, 'ok');
    if (document.getElementById('panel-permission')?.classList.contains('active')) {
      initPermissionPanel();
    }
    loadKnowledgeBases();
    loadDataSourcesFromApi();
  }

  async function submitLogin() {
    if (authMode === 'register') {
      await submitRegister();
      return;
    }
    const username = document.getElementById('loginUsername')?.value.trim() || '';
    const password = document.getElementById('loginPassword')?.value || '';
    const err = document.getElementById('loginError');
    const btn = document.getElementById('loginSubmitBtn');
    if (!username || !password) {
      if (err) { err.hidden = false; err.textContent = '请输入用户名和密码'; }
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '登录中...'; }
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatAuthError(data.detail, data.error || '登录失败'));
      }
      await completeAuthSession(data, username);
    } catch (error) {
      if (err) {
        err.hidden = false;
        err.textContent = error.message || '登录失败';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '登录'; }
    }
  }

  function validateUsernameInput(username) {
    const value = String(username || '').trim();
    if (!value) return '请填写用户名';
    if (/\s/.test(value)) return '用户名不能包含空格';
    if (value.length < 2) return '用户名至少 2 个字符';
    if (value.length > 64) return '用户名最多 64 个字符';
    if (!/^[\u4e00-\u9fffA-Za-z0-9_\-.]+$/.test(value)) {
      return '用户名仅支持中文、字母、数字及 _ - .';
    }
    if (!/^[\u4e00-\u9fffA-Za-z]/.test(value)) return '用户名需以中文或字母开头';
    if (/^[0-9_\-.]+$/.test(value)) return '用户名不能为纯数字';
    return '';
  }

  async function submitRegister() {
    const username = document.getElementById('registerUsername')?.value.trim() || '';
    const displayName = document.getElementById('registerDisplayName')?.value.trim() || '';
    const password = document.getElementById('registerPassword')?.value || '';
    const confirm = document.getElementById('registerPasswordConfirm')?.value || '';
    const err = document.getElementById('loginError');
    const btn = document.getElementById('loginSubmitBtn');
    if (!publicRegisterEnabled) {
      if (err) { err.hidden = false; err.textContent = '当前未开放公开注册'; }
      return;
    }
    const usernameError = validateUsernameInput(username);
    if (usernameError) {
      if (err) { err.hidden = false; err.textContent = usernameError; }
      return;
    }
    if (!password) {
      if (err) { err.hidden = false; err.textContent = '请填写密码'; }
      return;
    }
    if (password.length < 6) {
      if (err) { err.hidden = false; err.textContent = '密码至少 6 位'; }
      return;
    }
    if (password !== confirm) {
      if (err) { err.hidden = false; err.textContent = '两次输入的密码不一致'; }
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '注册中...'; }
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password,
          display_name: displayName,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatAuthError(data.detail, data.error || '注册失败'));
      }
      await completeAuthSession(data, username);
      showAppToast('注册成功', 'ok');
    } catch (error) {
      if (err) {
        err.hidden = false;
        err.textContent = error.message || '注册失败';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = authMode === 'register' ? '注册并登录' : '登录'; }
    }
  }

  async function logoutCurrentUser() {
    try {
      await flushWorkspaceToServer();
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (_) { /* ignore */ }
    setAuthToken('');
    currentAuthUser = null;
    clearLocalWorkspaceCache();
    models = [];
    activeModelId = null;
    mcpConfigs = [];
    skillConfigs = [];
    agentConfigs = [];
    activeAgentId = '';
    conversations = [];
    currentConversationId = null;
    toolSettings = defaultToolSettings();
    apiKbConfigs = [];
    closeSettings();
    syncPlatformRoleUi();
    renderConversationList();
    startNewConversation();
    updateCurrentModelLabel();
    showLoginOverlay('已退出登录');
    setAuthMode('login');
    refreshRegisterAvailability();
  }

  let editingUserId = null;

  async function loadUserManageList() {
    const list = document.getElementById('userManageList');
    if (!list) return;
    if (!isPlatformAdmin()) {
      list.innerHTML = '<div class="doc-empty-hint">仅管理员可管理用户</div>';
      return;
    }
    try {
      const res = await apiFetch('/api/auth/users');
      const rows = await res.json().catch(() => []);
      if (!res.ok) throw new Error(rows.detail || '加载失败');
      if (!Array.isArray(rows) || !rows.length) {
        list.innerHTML = '<div class="doc-empty-hint">暂无用户</div>';
        return;
      }
      list.innerHTML = rows.map((item) => `
        <div class="integration-row">
          <div class="integration-main">
            <strong>${escapeHtml(item.display_name || item.username)}</strong>
            <span>${escapeHtml(item.username)} · ${item.role === 'admin' ? '管理员' : '普通用户'}${item.is_active ? '' : ' · 已停用'}</span>
          </div>
          <span class="integration-status ${item.is_active ? 'online' : 'offline'}">${item.is_active ? '启用' : '停用'}</span>
          <div class="integration-actions">
            <button data-user-action="edit" data-id="${item.id}">编辑</button>
            <button data-user-action="toggle" data-id="${item.id}">${item.is_active ? '停用' : '启用'}</button>
            <button class="danger" data-user-action="delete" data-id="${item.id}">删除</button>
          </div>
        </div>`).join('');
    } catch (error) {
      list.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message || error)}</div>`;
    }
  }

  function openUserModal(user = null) {
    editingUserId = user?.id || null;
    document.getElementById('userModalTitle').textContent = user ? '编辑用户' : '新建用户';
    document.getElementById('editingUserId').value = user?.id || '';
    const username = document.getElementById('userUsername');
    if (username) {
      username.value = user?.username || '';
      username.disabled = Boolean(user);
    }
    document.getElementById('userDisplayName').value = user?.display_name || '';
    document.getElementById('userRole').value = user?.role === 'admin' ? 'admin' : 'user';
    document.getElementById('userPassword').value = '';
    document.getElementById('userPassword').placeholder = user ? '留空表示不修改密码' : '至少 6 位';
    const confirmInput = document.getElementById('userPasswordConfirm');
    const confirmGroup = document.getElementById('userPasswordConfirmGroup');
    if (confirmInput) confirmInput.value = '';
    if (confirmGroup) confirmGroup.hidden = false;
    const help = document.getElementById('userPasswordHelp');
    if (help) {
      help.textContent = user
        ? '填写密码即重置该用户密码；留空则不改密码。'
        : '新建用户必须设置初始密码。';
    }
    document.getElementById('addUserModal')?.classList.add('open');
  }

  function closeUserModal() {
    document.getElementById('addUserModal')?.classList.remove('open');
    editingUserId = null;
  }

  async function saveUserFromModal() {
    const username = document.getElementById('userUsername')?.value.trim() || '';
    const displayName = document.getElementById('userDisplayName')?.value.trim() || '';
    const role = document.getElementById('userRole')?.value || 'user';
    const password = document.getElementById('userPassword')?.value || '';
    if (!editingUserId && !username) {
      showAppToast('请填写用户名', 'warn');
      return;
    }
    if (!editingUserId) {
      const usernameError = validateUsernameInput(username);
      if (usernameError) {
        showAppToast(usernameError, 'warn');
        return;
      }
    }
    if (!editingUserId && password.length < 6) {
      showAppToast('密码至少 6 位', 'warn');
      return;
    }
    if (password) {
      const confirm = document.getElementById('userPasswordConfirm')?.value || '';
      if (password !== confirm) {
        showAppToast('两次输入的密码不一致', 'warn');
        return;
      }
      if (password.length < 6) {
        showAppToast('密码至少 6 位', 'warn');
        return;
      }
    }
    try {
      if (editingUserId) {
        const body = { display_name: displayName, role };
        if (password) body.password = password;
        const res = await apiFetch('/api/auth/users/' + editingUserId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || '更新失败');
      } else {
        const res = await apiFetch('/api/auth/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            password,
            display_name: displayName,
            role,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || '创建失败');
      }
      closeUserModal();
      await loadUserManageList();
      showAppToast('用户已保存', 'ok');
    } catch (error) {
      showAppToast(error.message || '保存失败', 'error');
    }
  }

  function appendApprovalAudit(entry) {
    let list = [];
    try {
      list = JSON.parse(localStorage.getItem(APPROVAL_AUDIT_KEY) || '[]') || [];
    } catch (_) {
      list = [];
    }
    list.unshift({
      ...entry,
      at: new Date().toISOString(),
      role: getPlatformRole(),
      user: currentAuthUser?.username || '',
    });
    localStorage.setItem(APPROVAL_AUDIT_KEY, JSON.stringify(list.slice(0, 200)));
  }

  function pipelineStatusMeta(status) {
    const value = (status || 'draft').toLowerCase();
    if (value === 'pending_approval' || value === 'pending') {
      return { label: '待审批', className: 'pending' };
    }
    if (value === 'rejected') return { label: '已驳回', className: 'rejected' };
    if (value === 'active') return { label: '已生效', className: 'active' };
    if (value === 'draft') return { label: '草稿', className: 'draft' };
    return { label: status || '未知', className: 'draft' };
  }

  async function loadApprovalList() {
    const list = document.getElementById('approvalList');
    const countEl = document.getElementById('approvalPendingCount');
    if (!list) return;
    syncPlatformRoleUi();
    const filter = document.getElementById('approvalStatusFilter')?.value;
    const statusQuery = filter == null ? 'pending_approval' : filter;
    try {
      const path = statusQuery ? ('?status=' + encodeURIComponent(statusQuery)) : '';
      const rows = await pipelineApi(path);
      const pendingAll = await pipelineApi('?status=pending_approval');
      const pendingCount = Array.isArray(pendingAll) ? pendingAll.length : 0;
      if (countEl) {
        countEl.textContent = String(pendingCount);
        countEl.dataset.count = String(pendingCount);
      }
      if (!rows.length) {
        list.innerHTML = `
          <div class="perm-empty">
            <div class="perm-empty-icon" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            </div>
            <h4>暂无相关任务</h4>
            <p>会话中创建的流水线会出现在待审批列表。</p>
          </div>`;
        return;
      }
      const admin = isPlatformAdmin();
      list.innerHTML = rows.map((p) => {
        const st = pipelineStatusMeta(p.status);
        const kind = inferPipelineKind(p);
        const canAct = admin && (p.status === 'pending_approval' || p.status === 'pending' || p.status === 'rejected' || p.status === 'draft');
        return `
          <article class="approval-card is-${st.className}">
            <div class="approval-card-mark" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <div class="approval-card-main">
              <div class="approval-card-title">
                <strong>${escapeHtml(p.name)}</strong>
                <span class="approval-status ${st.className}">${st.label}</span>
                <span class="dp-kind-badge ${pipelineKindMeta(kind).className}">${pipelineKindMeta(kind).label}</span>
              </div>
              <p>${escapeHtml(p.description || '无描述')}</p>
              <div class="approval-card-chips">
                <span class="approval-chip">ID ${p.id}</span>
                <span class="approval-chip">步骤 ${(p.steps || []).length}</span>
                <span class="approval-chip">${escapeHtml(p.schedule_note || '来源未知')}</span>
              </div>
            </div>
            <div class="approval-card-actions">
              <button class="approval-action-btn view" type="button" data-approval-action="view" data-id="${p.id}">查看</button>
              ${canAct ? `<button class="approval-action-btn approve" type="button" data-approval-action="approve" data-id="${p.id}">批准</button>` : ''}
              ${canAct ? `<button class="approval-action-btn reject" type="button" data-approval-action="reject" data-id="${p.id}">驳回</button>` : ''}
            </div>
          </article>`;
      }).join('');
    } catch (error) {
      list.innerHTML = `<div class="perm-empty"><h4>加载失败</h4><p class="error-text">${escapeHtml(error.message || error)}</p></div>`;
    }
  }

  function renderApprovalAuditList() {
    const list = document.getElementById('auditList');
    if (!list) return;
    let rows = [];
    try {
      rows = JSON.parse(localStorage.getItem(APPROVAL_AUDIT_KEY) || '[]') || [];
    } catch (_) {
      rows = [];
    }
    const keyword = String(document.getElementById('auditSearchInput')?.value || '').trim().toLowerCase();
    if (keyword) {
      rows = rows.filter((item) => {
        const hay = `${item.action || ''} ${item.detail || ''} ${item.role || ''}`.toLowerCase();
        return hay.includes(keyword);
      });
    }
    if (!rows.length) {
      list.innerHTML = `
        <div class="perm-empty">
          <div class="perm-empty-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <h4>暂无审批审计记录</h4>
          <p>批准或驳回任务后，操作会记录在这里。</p>
        </div>`;
      return;
    }
    list.innerHTML = rows.map((item) => {
      const action = String(item.action || '审批');
      const tone = /驳回|reject/i.test(action) ? 'is-reject' : (/批准|approve/i.test(action) ? 'is-approve' : '');
      const when = item.at ? new Date(item.at).toLocaleString() : '';
      return `
        <div class="audit-item ${tone}">
          <span class="audit-item-dot" aria-hidden="true"></span>
          <div class="audit-item-card">
            <div class="audit-item-main">
              <strong>${escapeHtml(action)}</strong>
              <span>${escapeHtml(item.detail || '')}</span>
            </div>
            <div class="audit-item-meta">
              <span>${escapeHtml(when)}</span>
              <span>${escapeHtml(item.role === 'admin' ? '管理员' : (item.role || '用户'))}</span>
            </div>
          </div>
        </div>`;
    }).join('');
  }



  let authzOptions = { users: [], groups: [], knowledge_bases: [], datasources: [] };
  let authzGroupsCache = [];
  let authzGrantsCache = [];
  let authzBound = false;
  let authzEditingGroupId = null;
  let authzSelectedMemberIds = new Set();

  async function authzApi(path = '', options = {}) {
    const response = await apiFetch('/api/authz' + path, options);
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      let message = data.error || data.message || ('请求失败（HTTP ' + response.status + '）');
      if (typeof detail === 'string') message = detail;
      else if (Array.isArray(detail)) message = detail.map((x) => x.msg || x.detail || String(x)).join('；');
      throw new Error(message);
    }
    return data;
  }

  function authzItemLabel(item, kind) {
    if (!item || typeof item !== 'object') return '';
    if (kind === 'user') {
      const name = item.display_name || item.username || (item.id != null ? ('#' + item.id) : '');
      return item.username && item.display_name && item.display_name !== item.username
        ? `${name}（${item.username}）`
        : name;
    }
    return item.name || item.display_name || item.username || (item.id != null ? ('#' + item.id) : '');
  }

  function authzItemMeta(item, kind) {
    if (!item) return '';
    if (kind === 'user') return `ID ${item.id} · ${item.role === 'admin' ? '管理员' : '普通用户'}`;
    if (kind === 'group') return `ID ${item.id}`;
    return `ID ${item.id}`;
  }

  function closeAllAuthzPickers(exceptId = '') {
    ['authzGrantResourcePanel', 'authzGrantGranteePanel', 'authzLookupSubjectPanel'].forEach((id) => {
      if (exceptId && id === exceptId) return;
      const el = document.getElementById(id);
      if (el) el.hidden = true;
    });
  }

  function renderSearchPickerList({
    listEl,
    items,
    keyword,
    selectedId,
    kind,
    onPick,
  }) {
    if (!listEl) return;
    const q = String(keyword || '').trim().toLowerCase();
    const filtered = (items || []).filter((item) => {
      if (!q) return true;
      const hay = `${authzItemLabel(item, kind)} ${item.username || ''} ${item.name || ''} ${item.id}`.toLowerCase();
      return hay.includes(q);
    });
    if (!filtered.length) {
      listEl.innerHTML = '<div class="search-picker__empty">无匹配项，请调整关键字</div>';
      return;
    }
    listEl.innerHTML = filtered.map((item) => {
      const active = String(item.id) === String(selectedId || '');
      return `
        <button type="button" class="search-picker__item ${active ? 'is-active' : ''}" data-id="${item.id}">
          <strong>${escapeHtml(authzItemLabel(item, kind))}</strong>
          <span>${escapeHtml(authzItemMeta(item, kind))}</span>
        </button>`;
    }).join('');
    listEl.querySelectorAll('[data-id]').forEach((btn) => {
      btn.addEventListener('click', () => onPick(Number(btn.getAttribute('data-id'))));
    });
  }

  function setPickerValue({ hiddenId, triggerId, item, kind, emptyText }) {
    const hidden = document.getElementById(hiddenId);
    const trigger = document.getElementById(triggerId);
    const valid = item && typeof item === 'object' && item.id != null;
    if (hidden) hidden.value = valid ? String(item.id) : '';
    if (trigger) {
      trigger.textContent = valid ? (authzItemLabel(item, kind) || emptyText) : emptyText;
      trigger.classList.toggle('is-empty', !valid);
    }
  }

  function syncAuthzGrantResourceTypeUi() {
    const rtype = document.getElementById('authzGrantResourceType')?.value || 'knowledge_base';
    const isCap = isAuthzCapabilityType(rtype);
    const pickGroup = document.getElementById('authzGrantResourcePickGroup');
    const picker = document.getElementById('authzResourcePicker');
    const hint = document.getElementById('authzGrantCapabilityHint');
    const hidden = document.getElementById('authzGrantResourceId');
    const trigger = document.getElementById('authzGrantResourceTrigger');
    if (pickGroup) pickGroup.classList.toggle('is-capability', isCap);
    if (picker) picker.hidden = isCap;
    if (hint) hint.hidden = !isCap;
    if (isCap) {
      if (hidden) hidden.value = '0';
      if (trigger) {
        trigger.textContent = authzResourceTypeLabel(rtype);
        trigger.classList.remove('is-empty');
      }
      closeAllAuthzPickers();
    } else if (hidden && hidden.value === '0') {
      hidden.value = '';
      if (trigger) {
        trigger.textContent = '搜索并选择资源';
        trigger.classList.add('is-empty');
      }
    }
  }

  function getAuthzResourceItems() {
    const rtype = document.getElementById('authzGrantResourceType')?.value || 'knowledge_base';
    return rtype === 'datasource' ? (authzOptions.datasources || []) : (authzOptions.knowledge_bases || []);
  }

  function getAuthzGranteeItems() {
    const gtype = document.getElementById('authzGrantGranteeType')?.value || 'user';
    return gtype === 'group' ? (authzOptions.groups || []) : (authzOptions.users || []);
  }

  function refreshAuthzResourcePicker(keyword = '') {
    const items = getAuthzResourceItems();
    const selectedId = document.getElementById('authzGrantResourceId')?.value || '';
    const selected = items.find((x) => String(x.id) === String(selectedId));
    const kind = 'resource';
    setPickerValue({
      hiddenId: 'authzGrantResourceId',
      triggerId: 'authzGrantResourceTrigger',
      item: selected,
      kind,
      emptyText: '点击搜索并选择资源',
    });
    renderSearchPickerList({
      listEl: document.getElementById('authzGrantResourceList'),
      items,
      keyword,
      selectedId,
      kind,
      onPick: (id) => {
        const item = items.find((x) => Number(x.id) === Number(id));
        setPickerValue({
          hiddenId: 'authzGrantResourceId',
          triggerId: 'authzGrantResourceTrigger',
          item,
          kind,
          emptyText: '点击搜索并选择资源',
        });
        closeAllAuthzPickers();
      },
    });
  }

  function refreshAuthzGranteePicker(keyword = '') {
    const gtype = document.getElementById('authzGrantGranteeType')?.value || 'user';
    const items = getAuthzGranteeItems();
    const selectedId = document.getElementById('authzGrantGranteeId')?.value || '';
    const selected = items.find((x) => String(x.id) === String(selectedId));
    const kind = gtype === 'group' ? 'group' : 'user';
    setPickerValue({
      hiddenId: 'authzGrantGranteeId',
      triggerId: 'authzGrantGranteeTrigger',
      item: selected,
      kind,
      emptyText: gtype === 'group' ? '点击搜索并选择用户组' : '点击搜索并选择用户',
    });
    renderSearchPickerList({
      listEl: document.getElementById('authzGrantGranteeList'),
      items,
      keyword,
      selectedId,
      kind,
      onPick: (id) => {
        const item = items.find((x) => Number(x.id) === Number(id));
        setPickerValue({
          hiddenId: 'authzGrantGranteeId',
          triggerId: 'authzGrantGranteeTrigger',
          item,
          kind,
          emptyText: gtype === 'group' ? '点击搜索并选择用户组' : '点击搜索并选择用户',
        });
        closeAllAuthzPickers();
      },
    });
  }

  function refreshAuthzGrantSelectors() {
    // Reset selected values when type changes.
    const resourceHidden = document.getElementById('authzGrantResourceId');
    const granteeHidden = document.getElementById('authzGrantGranteeId');
    if (resourceHidden) resourceHidden.value = '';
    if (granteeHidden) granteeHidden.value = '';
    const resourceSearch = document.getElementById('authzGrantResourceSearch');
    const granteeSearch = document.getElementById('authzGrantGranteeSearch');
    if (resourceSearch) resourceSearch.value = '';
    if (granteeSearch) granteeSearch.value = '';
    refreshAuthzResourcePicker('');
    refreshAuthzGranteePicker('');
    syncAuthzGrantResourceTypeUi();
  }

  async function loadAuthzOptions() {
    authzOptions = await authzApi('/options');
    refreshAuthzResourcePicker(document.getElementById('authzGrantResourceSearch')?.value || '');
    refreshAuthzGranteePicker(document.getElementById('authzGrantGranteeSearch')?.value || '');
  }

  function renderAuthzGroups(keyword = '') {
    const list = document.getElementById('authzGroupList');
    if (!list) return;
    const q = String(keyword || '').trim().toLowerCase();
    const rows = (authzGroupsCache || []).filter((g) => {
      if (!q) return true;
      return `${g.name || ''} ${g.description || ''}`.toLowerCase().includes(q);
    });
    if (!rows.length) {
      if (authzGroupsCache.length) {
        list.innerHTML = '<div class="doc-empty-hint">无匹配用户组</div>';
      } else {
        list.innerHTML = `
          <div class="authz-group-empty">
            <strong>还没有用户组</strong>
            <span>创建用户组并添加成员后，可在「资源授权」中一次性授权给整组。</span>
            <button type="button" class="btn-primary" id="authzCreateGroupEmptyBtn">新建用户组</button>
          </div>`;
        document.getElementById('authzCreateGroupEmptyBtn')?.addEventListener('click', createAuthzGroup);
      }
      return;
    }
    list.innerHTML = rows.map((g) => {
      const name = g.name || ('组 #' + g.id);
      const initial = Array.from(String(name))[0] || 'G';
      const desc = (g.description || '').trim() || '暂无描述';
      const count = Number(g.member_count || 0);
      return `
      <div class="authz-group-card" data-group-id="${g.id}">
        <div class="authz-group-card__top">
          <div class="authz-group-card__avatar" aria-hidden="true">${escapeHtml(initial)}</div>
          <div class="authz-group-card__body">
            <strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong>
            <p title="${escapeHtml(desc)}">${escapeHtml(desc)}</p>
          </div>
        </div>
        <div class="authz-group-card__meta">
          <span class="authz-chip">${count} 名成员</span>
          <span class="authz-chip is-muted">ID ${g.id}</span>
        </div>
        <div class="authz-group-card__actions">
          <button type="button" class="btn-secondary" data-authz-edit-group="${g.id}">编辑</button>
          <button type="button" class="btn-secondary danger" data-authz-del-group="${g.id}">删除</button>
        </div>
      </div>`;
    }).join('');
  }

  async function loadAuthzGroups() {
    const list = document.getElementById('authzGroupList');
    if (!list) return;
    list.innerHTML = '<div class="doc-empty-hint">加载中...</div>';
    try {
      authzGroupsCache = await authzApi('/groups');
      renderAuthzGroups(document.getElementById('authzGroupSearchInput')?.value || '');
    } catch (error) {
      list.innerHTML = `<div class="doc-empty-hint">${escapeHtml(error.message || '加载失败')}</div>`;
    }
  }

  function renderAuthzGrants(keyword = '') {
    const list = document.getElementById('authzGrantList');
    if (!list) return;
    const q = String(keyword || '').trim().toLowerCase();
    const rows = (authzGrantsCache || []).filter((g) => {
      if (!q) return true;
      const hay = `${g.resource_type || ''} ${g.resource_name || ''} ${g.grantee_type || ''} ${g.grantee_name || ''}`.toLowerCase();
      return hay.includes(q);
    });
    if (!rows.length) {
      list.innerHTML = `<div class="doc-empty-hint">${authzGrantsCache.length ? '无匹配授权记录' : '暂无授权记录'}</div>`;
      return;
    }
    list.innerHTML = rows.map((g) => {
      const rlabel = authzResourceTypeLabel(g.resource_type);
      const glabel = g.grantee_type === 'group' ? '用户组' : '用户';
      const plabel = g.permission === 'manage' ? '管理' : '使用';
      return `
      <div class="authz-perm-row" data-grant-id="${g.id}">
        <div class="authz-perm-row__body">
          <div class="authz-perm-row__title">
            <span class="authz-perm-type">${escapeHtml(rlabel)}</span>
            <strong>${escapeHtml(g.resource_name || '')}</strong>
          </div>
          <div class="authz-perm-row__meta">
            <span>授权给 ${escapeHtml(glabel)}「${escapeHtml(g.grantee_name || '')}」</span>
            <span class="authz-chip">${escapeHtml(plabel)}</span>
          </div>
        </div>
        <div class="authz-perm-row__actions">
          <button type="button" class="btn-secondary danger" data-authz-del-grant="${g.id}">撤销</button>
        </div>
      </div>`;
    }).join('');
  }

  async function loadAuthzGrants() {
    const list = document.getElementById('authzGrantList');
    if (!list) return;
    list.innerHTML = '<div class="doc-empty-hint">加载中...</div>';
    try {
      authzGrantsCache = await authzApi('/grants');
      renderAuthzGrants(document.getElementById('authzGrantSearchInput')?.value || '');
    } catch (error) {
      list.innerHTML = `<div class="doc-empty-hint">${escapeHtml(error.message || '加载失败')}</div>`;
    }
  }

  function updateAuthzMemberHint() {
    const hint = document.getElementById('authzGroupMemberHint');
    if (hint) hint.textContent = `已选 ${authzSelectedMemberIds.size} 人`;
  }

  function renderAuthzMemberChecklist(keyword = '') {
    const list = document.getElementById('authzGroupMemberList');
    if (!list) return;
    const q = String(keyword || '').trim().toLowerCase();
    const users = (authzOptions.users || []).filter((u) => {
      if (!q) return true;
      const hay = `${u.display_name || ''} ${u.username || ''} ${u.id}`.toLowerCase();
      return hay.includes(q);
    });
    if (!users.length) {
      list.innerHTML = '<div class="search-picker__empty">无匹配用户</div>';
      updateAuthzMemberHint();
      return;
    }
    list.innerHTML = users.map((u) => {
      const checked = authzSelectedMemberIds.has(Number(u.id)) ? 'checked' : '';
      return `
        <label class="member-check-item">
          <input type="checkbox" data-member-id="${u.id}" ${checked}>
          <span class="member-check-meta">
            <strong>${escapeHtml(u.display_name || u.username || ('#' + u.id))}</strong>
            <span>${escapeHtml(u.username || '')} · ${u.role === 'admin' ? '管理员' : '普通用户'}</span>
          </span>
        </label>`;
    }).join('');
    list.querySelectorAll('input[data-member-id]').forEach((input) => {
      input.addEventListener('change', () => {
        const id = Number(input.getAttribute('data-member-id'));
        if (input.checked) authzSelectedMemberIds.add(id);
        else authzSelectedMemberIds.delete(id);
        updateAuthzMemberHint();
      });
    });
    updateAuthzMemberHint();
  }

  function openAuthzGroupModal(group = null) {
    authzEditingGroupId = group?.id || null;
    document.getElementById('authzGroupModalTitle').textContent = group ? '编辑用户组' : '新建用户组';
    document.getElementById('editingAuthzGroupId').value = group?.id || '';
    document.getElementById('authzGroupName').value = group?.name || '';
    document.getElementById('authzGroupDesc').value = group?.description || '';
    document.getElementById('authzGroupMemberSearch').value = '';
    const err = document.getElementById('authzGroupModalError');
    if (err) { err.hidden = true; err.textContent = ''; }
    authzSelectedMemberIds = new Set((group?.member_ids || []).map((x) => Number(x)));
    renderAuthzMemberChecklist('');
    document.getElementById('authzGroupModal')?.classList.add('open');
    window.setTimeout(() => document.getElementById('authzGroupName')?.focus(), 40);
  }

  function closeAuthzGroupModal() {
    document.getElementById('authzGroupModal')?.classList.remove('open');
    authzEditingGroupId = null;
  }

  async function createAuthzGroup() {
    await loadAuthzOptions();
    openAuthzGroupModal(null);
  }

  async function editAuthzGroup(groupId) {
    await loadAuthzOptions();
    const group = (authzGroupsCache || []).find((g) => Number(g.id) === Number(groupId))
      || (await authzApi('/groups')).find((g) => Number(g.id) === Number(groupId));
    if (!group) {
      showAppToast('用户组不存在', 'warn');
      return;
    }
    openAuthzGroupModal(group);
  }

  async function saveAuthzGroupModal() {
    const name = document.getElementById('authzGroupName')?.value.trim() || '';
    const description = document.getElementById('authzGroupDesc')?.value.trim() || '';
    const err = document.getElementById('authzGroupModalError');
    const btn = document.getElementById('saveAuthzGroupBtn');
    if (!name) {
      if (err) { err.hidden = false; err.textContent = '请填写组名'; }
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }
    try {
      let groupId = authzEditingGroupId;
      if (groupId) {
        await authzApi('/groups/' + groupId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, description }),
        });
      } else {
        const created = await authzApi('/groups', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, description }),
        });
        groupId = created.id;
      }
      await authzApi('/groups/' + groupId + '/members', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: [...authzSelectedMemberIds] }),
      });
      closeAuthzGroupModal();
      showAppToast('用户组已保存', 'ok');
      await loadAuthzOptions();
      await loadAuthzGroups();
    } catch (error) {
      if (err) {
        err.hidden = false;
        err.textContent = error.message || '保存失败';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '保存'; }
    }
  }

  async function deleteAuthzGroup(groupId) {
    if (!window.confirm('确定删除该用户组？相关组授权也会一并删除。')) return;
    try {
      await authzApi('/groups/' + groupId, { method: 'DELETE' });
      showAppToast('用户组已删除', 'ok');
      await loadAuthzOptions();
      await loadAuthzGroups();
      await loadAuthzGrants();
    } catch (error) {
      showAppToast(error.message || '删除失败', 'error');
    }
  }

  async function submitAuthzGrant() {
    const resource_type = document.getElementById('authzGrantResourceType')?.value;
    const isCap = isAuthzCapabilityType(resource_type);
    const resource_id = isCap ? 0 : Number(document.getElementById('authzGrantResourceId')?.value || 0);
    const grantee_type = document.getElementById('authzGrantGranteeType')?.value;
    const grantee_id = Number(document.getElementById('authzGrantGranteeId')?.value || 0);
    if (!resource_type || !grantee_type || !grantee_id || (!isCap && !resource_id)) {
      showAppToast(isCap ? '请完整选择能力与授权对象' : '请完整选择资源与授权对象', 'warn');
      return;
    }
    try {
      await authzApi('/grants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resource_type,
          resource_id,
          grantee_type,
          grantee_id,
          permission: isCap ? 'manage' : 'use',
        }),
      });
      showAppToast('授权成功', 'ok');
      const resourceHidden = document.getElementById('authzGrantResourceId');
      const granteeHidden = document.getElementById('authzGrantGranteeId');
      if (!isCap && resourceHidden) resourceHidden.value = '';
      if (granteeHidden) granteeHidden.value = '';
      syncAuthzGrantResourceTypeUi();
      if (!isCap) refreshAuthzResourcePicker(document.getElementById('authzGrantResourceSearch')?.value || '');
      refreshAuthzGranteePicker(document.getElementById('authzGrantGranteeSearch')?.value || '');
      await loadAuthzGrants();
    } catch (error) {
      showAppToast(error.message || '授权失败', 'error');
    }
  }

  async function deleteAuthzGrant(grantId) {
    if (!window.confirm('确认撤销该授权？')) return false;
    try {
      await authzApi('/grants/' + grantId, { method: 'DELETE' });
      showAppToast('已撤销', 'ok');
      await loadAuthzGrants();
      return true;
    } catch (error) {
      showAppToast(error.message || '撤销失败', 'error');
      return false;
    }
  }


  function getAuthzLookupSubjectItems() {
    const stype = document.getElementById('authzLookupSubjectType')?.value || 'user';
    return stype === 'group' ? (authzOptions.groups || []) : (authzOptions.users || []);
  }

  function refreshAuthzLookupSubjectPicker(keyword = '') {
    const stype = document.getElementById('authzLookupSubjectType')?.value || 'user';
    const items = getAuthzLookupSubjectItems();
    const selectedId = document.getElementById('authzLookupSubjectId')?.value || '';
    const selected = items.find((x) => String(x.id) === String(selectedId));
    const kind = stype === 'group' ? 'group' : 'user';
    setPickerValue({
      hiddenId: 'authzLookupSubjectId',
      triggerId: 'authzLookupSubjectTrigger',
      item: selected,
      kind,
      emptyText: stype === 'group' ? '搜索并选择用户组' : '搜索并选择用户',
    });
    renderSearchPickerList({
      listEl: document.getElementById('authzLookupSubjectList'),
      items,
      keyword,
      selectedId,
      kind,
      onPick: (id) => {
        const item = items.find((x) => Number(x.id) === Number(id));
        setPickerValue({
          hiddenId: 'authzLookupSubjectId',
          triggerId: 'authzLookupSubjectTrigger',
          item,
          kind,
          emptyText: stype === 'group' ? '搜索并选择用户组' : '搜索并选择用户',
        });
        closeAllAuthzPickers();
      },
    });
  }

  function resetAuthzLookupResult(message = '请选择用户或用户组后点击「查询权限」。') {
    const box = document.getElementById('authzLookupResult');
    if (box) box.innerHTML = `<div class="doc-empty-hint">${escapeHtml(message)}</div>`;
  }

  function clearAuthzLookupForm() {
    const hidden = document.getElementById('authzLookupSubjectId');
    if (hidden) hidden.value = '';
    const search = document.getElementById('authzLookupSubjectSearch');
    if (search) search.value = '';
    refreshAuthzLookupSubjectPicker('');
    resetAuthzLookupResult();
  }

  function renderAuthzLookupResult(payload) {
    const box = document.getElementById('authzLookupResult');
    if (!box) return;
    const subject = payload?.subject || {};
    const items = Array.isArray(payload?.items) ? payload.items : [];
    const groups = Array.isArray(payload?.groups) ? payload.groups : [];
    const isUser = subject.type === 'user';
    const typeLabel = isUser ? '用户' : '用户组';
    const name = subject.name || ('#' + (subject.id || ''));
    const chips = [
      `<span class="authz-chip">${escapeHtml(typeLabel)}</span>`,
      `<span class="authz-chip is-muted">共 ${items.length} 项</span>`,
    ];
    if (isUser && subject.username) {
      chips.push(`<span class="authz-chip is-muted">@${escapeHtml(subject.username)}</span>`);
    }
    if (subject.is_admin) {
      chips.push('<span class="authz-chip is-admin">管理员</span>');
    }
    if (!isUser && subject.member_count != null) {
      chips.push(`<span class="authz-chip is-muted">${Number(subject.member_count)} 名成员</span>`);
    }
    if (isUser && groups.length) {
      chips.push(`<span class="authz-chip is-muted">所属组 ${groups.length}</span>`);
    }

    const note = payload?.note
      ? `<div class="authz-lookup-note">${escapeHtml(payload.note)}</div>`
      : '';

    let listHtml;
    if (!items.length) {
      listHtml = '<div class="doc-empty-hint">未查询到权限记录</div>';
    } else {
      listHtml = items.map((item) => {
        const rlabel = authzResourceTypeLabel(item.resource_type);
        const plabel = item.permission === 'manage' ? '管理' : '使用';
        const source = item.source || 'direct';
        const sourceClass = source === 'owner' ? 'is-owner' : (source === 'group' ? 'is-group' : 'is-direct');
        const sourceLabel = item.source_label || source;
        const revokeBtn = item.grant_id
          ? `<button type="button" class="btn-secondary danger" data-authz-del-grant="${item.grant_id}">撤销</button>`
          : '';
        return `
          <div class="authz-perm-row" data-grant-id="${item.grant_id || ''}">
            <div class="authz-perm-row__body">
              <div class="authz-perm-row__title">
                <span class="authz-perm-type">${escapeHtml(rlabel)}</span>
                <strong>${escapeHtml(item.resource_name || '')}</strong>
              </div>
              <div class="authz-perm-row__meta">
                <span class="authz-chip">${escapeHtml(plabel)}</span>
                <span class="authz-source ${sourceClass}">${escapeHtml(sourceLabel)}</span>
              </div>
            </div>
            <div class="authz-perm-row__actions">${revokeBtn}</div>
          </div>`;
      }).join('');
      listHtml = `<div class="authz-perm-list">${listHtml}</div>`;
    }

    box.innerHTML = `
      <div class="authz-lookup-summary">
        <strong>${escapeHtml(name)}</strong>
        ${chips.join('')}
      </div>
      ${note}
      ${listHtml}`;
  }

  async function queryAuthzPermissions() {
    const subject_type = document.getElementById('authzLookupSubjectType')?.value || 'user';
    const subject_id = Number(document.getElementById('authzLookupSubjectId')?.value || 0);
    const btn = document.getElementById('authzLookupSubmitBtn');
    if (!subject_id) {
      showAppToast('请先选择用户或用户组', 'warn');
      return;
    }
    const box = document.getElementById('authzLookupResult');
    if (box) box.innerHTML = '<div class="doc-empty-hint">查询中...</div>';
    if (btn) { btn.disabled = true; btn.textContent = '查询中...'; }
    try {
      const qs = new URLSearchParams({
        subject_type,
        subject_id: String(subject_id),
      });
      const payload = await authzApi('/permissions?' + qs.toString());
      renderAuthzLookupResult(payload);
    } catch (error) {
      resetAuthzLookupResult(error.message || '查询失败');
      showAppToast(error.message || '查询失败', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '查询权限'; }
    }
  }

  function bindAuthzPanelEvents() {
    if (authzBound) return;
    authzBound = true;
    document.querySelectorAll('[data-authz-tab]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.authzTab;
        document.querySelectorAll('[data-authz-tab]').forEach((el) => el.classList.toggle('active', el === btn));
        const groupsTab = document.getElementById('authz-tab-groups');
        const grantsTab = document.getElementById('authz-tab-grants');
        const lookupTab = document.getElementById('authz-tab-lookup');
        if (groupsTab) { groupsTab.hidden = tab !== 'groups'; groupsTab.classList.toggle('active', tab === 'groups'); }
        if (grantsTab) { grantsTab.hidden = tab !== 'grants'; grantsTab.classList.toggle('active', tab === 'grants'); }
        if (lookupTab) { lookupTab.hidden = tab !== 'lookup'; lookupTab.classList.toggle('active', tab === 'lookup'); }
        if (tab === 'groups') loadAuthzGroups();
        if (tab === 'grants') { loadAuthzOptions(); }
        if (tab === 'lookup') {
          loadAuthzOptions().then(() => {
            refreshAuthzLookupSubjectPicker(document.getElementById('authzLookupSubjectSearch')?.value || '');
            return loadAuthzGrants();
          });
        }
      });
    });

    document.getElementById('authzCreateGroupBtn')?.addEventListener('click', createAuthzGroup);
    document.getElementById('authzRefreshGroupsBtn')?.addEventListener('click', loadAuthzGroups);
    document.getElementById('authzRefreshGrantsBtn')?.addEventListener('click', () => loadAuthzOptions().then(loadAuthzGrants));
    document.getElementById('authzGrantSubmitBtn')?.addEventListener('click', submitAuthzGrant);
    document.getElementById('authzGrantResourceType')?.addEventListener('change', () => {
      syncAuthzGrantResourceTypeUi();
      if (!isAuthzCapabilityType(document.getElementById('authzGrantResourceType')?.value)) {
        refreshAuthzGrantSelectors();
      }
    });
    document.getElementById('authzGrantGranteeType')?.addEventListener('change', () => {
      const granteeHidden = document.getElementById('authzGrantGranteeId');
      if (granteeHidden) granteeHidden.value = '';
      const granteeSearch = document.getElementById('authzGrantGranteeSearch');
      if (granteeSearch) granteeSearch.value = '';
      refreshAuthzGranteePicker('');
    });

    document.getElementById('authzGrantResourceTrigger')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('authzGrantResourcePanel');
      const open = panel && !panel.hidden;
      closeAllAuthzPickers();
      if (panel) panel.hidden = open;
      if (!open) {
        refreshAuthzResourcePicker(document.getElementById('authzGrantResourceSearch')?.value || '');
        document.getElementById('authzGrantResourceSearch')?.focus();
      }
    });
    document.getElementById('authzGrantGranteeTrigger')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('authzGrantGranteePanel');
      const open = panel && !panel.hidden;
      closeAllAuthzPickers();
      if (panel) panel.hidden = open;
      if (!open) {
        refreshAuthzGranteePicker(document.getElementById('authzGrantGranteeSearch')?.value || '');
        document.getElementById('authzGrantGranteeSearch')?.focus();
      }
    });
    document.getElementById('authzGrantResourceSearch')?.addEventListener('input', (e) => {
      refreshAuthzResourcePicker(e.target.value || '');
    });
    document.getElementById('authzGrantGranteeSearch')?.addEventListener('input', (e) => {
      refreshAuthzGranteePicker(e.target.value || '');
    });
    document.getElementById('authzGrantResourcePanel')?.addEventListener('click', (e) => e.stopPropagation());
    document.getElementById('authzGrantGranteePanel')?.addEventListener('click', (e) => e.stopPropagation());
    document.addEventListener('click', () => closeAllAuthzPickers());

    document.getElementById('authzGroupSearchInput')?.addEventListener('input', (e) => {
      renderAuthzGroups(e.target.value || '');
    });
    document.getElementById('authzGrantSearchInput')?.addEventListener('input', (e) => {
      renderAuthzGrants(e.target.value || '');
    });

    document.getElementById('authzGroupList')?.addEventListener('click', (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      const editId = t.getAttribute('data-authz-edit-group');
      const did = t.getAttribute('data-authz-del-group');
      if (editId) editAuthzGroup(editId);
      if (did) deleteAuthzGroup(did);
    });
    document.getElementById('authzGrantList')?.addEventListener('click', (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      const gid = t.getAttribute('data-authz-del-grant');
      if (gid) deleteAuthzGrant(gid);
    });
    document.getElementById('authzLookupResult')?.addEventListener('click', async (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      const gid = t.getAttribute('data-authz-del-grant');
      if (!gid) return;
      const ok = await deleteAuthzGrant(gid);
      if (ok) await queryAuthzPermissions();
    });

    document.getElementById('authzLookupSubjectType')?.addEventListener('change', () => {
      const hidden = document.getElementById('authzLookupSubjectId');
      if (hidden) hidden.value = '';
      const search = document.getElementById('authzLookupSubjectSearch');
      if (search) search.value = '';
      refreshAuthzLookupSubjectPicker('');
      resetAuthzLookupResult();
    });
    document.getElementById('authzLookupSubjectTrigger')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('authzLookupSubjectPanel');
      const open = panel && !panel.hidden;
      closeAllAuthzPickers();
      if (panel) panel.hidden = open;
      if (!open) {
        refreshAuthzLookupSubjectPicker(document.getElementById('authzLookupSubjectSearch')?.value || '');
        document.getElementById('authzLookupSubjectSearch')?.focus();
      }
    });
    document.getElementById('authzLookupSubjectSearch')?.addEventListener('input', (e) => {
      refreshAuthzLookupSubjectPicker(e.target.value || '');
    });
    document.getElementById('authzLookupSubjectPanel')?.addEventListener('click', (e) => e.stopPropagation());
    document.getElementById('authzLookupSubmitBtn')?.addEventListener('click', queryAuthzPermissions);
    document.getElementById('authzLookupResetBtn')?.addEventListener('click', clearAuthzLookupForm);

    document.getElementById('closeAuthzGroupModal')?.addEventListener('click', closeAuthzGroupModal);
    document.getElementById('cancelAuthzGroupModal')?.addEventListener('click', closeAuthzGroupModal);
    document.getElementById('saveAuthzGroupBtn')?.addEventListener('click', saveAuthzGroupModal);
    document.getElementById('authzGroupMemberSearch')?.addEventListener('input', (e) => {
      renderAuthzMemberChecklist(e.target.value || '');
    });
    document.getElementById('authzGroupModal')?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeAuthzGroupModal();
    });
  }

  function initAuthzPanel() {
    if (!isPlatformAdmin()) {
      showAppToast('仅管理员可进入授权管理', 'warn');
      switchToPanel('permission');
      return;
    }
    bindAuthzPanelEvents();
    const activeTab = document.querySelector('#panel-authz [data-authz-tab].active')?.dataset.authzTab || 'groups';
    loadAuthzOptions().then(() => {
      if (activeTab === 'grants') return;
      if (activeTab === 'lookup') {
        refreshAuthzLookupSubjectPicker(document.getElementById('authzLookupSubjectSearch')?.value || '');
        return loadAuthzGrants();
      }
      return loadAuthzGroups();
    }).catch((error) => showAppToast(error.message || '加载授权数据失败', 'error'));
  }

  function initPermissionPanel() {
    syncPlatformRoleUi();
    const activeTab = document.querySelector('#panel-permission .perm-tab.active')?.dataset.permTab || 'approval';
    if (activeTab === 'approval') loadApprovalList();
    if (activeTab === 'users') initUsersPanel();
    if (activeTab === 'audit') renderApprovalAuditList();
  }

  function openPermissionUsersTab() {
    switchToPanel('permission');
    const btn = document.querySelector('#panel-permission [data-perm-tab="users"]');
    if (btn instanceof HTMLElement) btn.click();
    else initUsersPanel();
  }

  function refreshAccountProfileCard() {
    const usernameEl = document.getElementById('accountUsername');
    const roleEl = document.getElementById('accountUserRole');
    const username = currentAuthUser?.username || currentAuthUser?.display_name || '-';
    const roleRaw = (currentAuthUser?.role || '').toString().trim().toLowerCase();
    const roleLabel = roleRaw === 'admin' ? '管理员' : (roleRaw ? '普通用户' : '-');
    if (usernameEl) usernameEl.textContent = username;
    if (roleEl) roleEl.textContent = roleLabel;
  }

  async function submitAccountPasswordChange() {
    const currentPassword = document.getElementById('accountPasswordCurrent')?.value || '';
    const newPassword = document.getElementById('accountPasswordNew')?.value || '';
    const confirm = document.getElementById('accountPasswordConfirm')?.value || '';
    const err = document.getElementById('accountPasswordError');
    const btn = document.getElementById('accountPasswordSubmitBtn');
    if (!currentPassword || !newPassword) {
      if (err) { err.hidden = false; err.textContent = '请填写当前密码和新密码'; }
      return;
    }
    if (newPassword.length < 6) {
      if (err) { err.hidden = false; err.textContent = '新密码至少 6 位'; }
      return;
    }
    if (newPassword !== confirm) {
      if (err) { err.hidden = false; err.textContent = '两次输入的新密码不一致'; }
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '提交中...'; }
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatAuthError(data.detail, data.error || '修改密码失败'));
      }
      const me = await refreshAuthUser();
      currentAuthUser = me || data.user || currentAuthUser;
      if (currentAuthUser) currentAuthUser.must_change_password = false;
      ['accountPasswordCurrent', 'accountPasswordNew', 'accountPasswordConfirm'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      if (err) { err.hidden = true; err.textContent = ''; }
      refreshAccountProfileCard();
      syncPlatformRoleUi();
      showAppToast('密码已更新', 'ok');
    } catch (error) {
      if (err) {
        err.hidden = false;
        err.textContent = error.message || '修改密码失败';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '修改密码'; }
    }
  }

  function initUsersPanel() {
    syncPlatformRoleUi();
    refreshAccountProfileCard();
    const adminSection = document.getElementById('usersAdminSection');
    if (adminSection) adminSection.hidden = !isPlatformAdmin();
    if (isPlatformAdmin()) loadUserManageList();
  }

  // ===== Pipelines (A/B → C → D) =====
  let pipelines = [];
  let pipelineDraftSteps = [];
  const pipelineModal = document.getElementById('pipelineModal');

  async function pipelineApi(path = '', options = {}) {
    const response = await apiFetch('/api/pipelines' + path, options);
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      let message = data.error || data.message || ('请求失败（HTTP ' + response.status + '）');
      if (typeof detail === 'string') message = detail;
      else if (Array.isArray(detail)) message = detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
      throw new Error(message);
    }
    return data;
  }

  function dsOptionsHtml(selectedId, options = {}) {
    const { writableOnly = false } = options;
    const selected = selectedId == null ? '' : String(selectedId);
    return '<option value="">选择数据源</option>' + dataSources.map((ds) => {
      const queryOnly = isDsQueryOnly(ds);
      const disabled = writableOnly && queryOnly ? ' disabled' : '';
      const label = `${escapeHtml(ds.name)} (${escapeHtml(ds.type)}${queryOnly ? ' · 仅查询' : ' · 可写入'})`;
      return `<option value="${ds.id}"${String(ds.id) === selected ? ' selected' : ''}${disabled}>${label}</option>`;
    }).join('');
  }

  function renderPipelineStepEditors() {
    const host = document.getElementById('pipelineStepsHost');
    if (!host) return;
    if (!pipelineDraftSteps.length) {
      host.innerHTML = '<div class="doc-empty-hint">暂无步骤，请添加 transfer（跨库搬运）或 execute（库内 SQL）。</div>';
      return;
    }
    host.innerHTML = pipelineDraftSteps.map((step, index) => {
      const isTransfer = (step.step_type || 'execute') === 'transfer';
      const isQuery = step.step_type === 'query';
      const writeTargetOptions = dsOptionsHtml(
        isTransfer ? step.target_datasource_id : step.datasource_id,
        { writableOnly: !isQuery }
      );
      return `
        <div class="pipeline-step-card" data-step-index="${index}">
          <div class="kb-config-row">
            <div class="kb-config-field">
              <label class="form-label">步骤名称</label>
              <input class="form-input" data-step-field="name" value="${escapeHtml(step.name || '')}">
            </div>
            <div class="kb-config-field">
              <label class="form-label">类型</label>
              <select class="form-select" data-step-field="step_type">
                <option value="transfer"${isTransfer ? ' selected' : ''}>transfer 跨库抽取装载</option>
                <option value="execute"${!isTransfer && !isQuery ? ' selected' : ''}>execute 库内执行</option>
                <option value="query"${isQuery ? ' selected' : ''}>query 只读查询</option>
              </select>
            </div>
          </div>
          <div class="kb-config-row">
            <div class="kb-config-field">
              <label class="form-label">${isTransfer ? '源数据源' : '数据源'}</label>
              <select class="form-select" data-step-field="datasource_id">${isTransfer || isQuery ? dsOptionsHtml(step.datasource_id) : writeTargetOptions}</select>
            </div>
            <div class="kb-config-field" style="${isTransfer ? '' : 'display:none'}">
              <label class="form-label">目标数据源</label>
              <select class="form-select" data-step-field="target_datasource_id">${dsOptionsHtml(step.target_datasource_id, { writableOnly: true })}</select>
            </div>
          </div>
          <div class="kb-config-row" style="${isTransfer ? '' : 'display:none'}">
            <div class="kb-config-field">
              <label class="form-label">同步引擎</label>
              <select class="form-select" data-step-field="sync_engine">
                <option value="sqoop"${(step.sync_engine || 'sqoop') === 'sqoop' ? ' selected' : ''}>Sqoop（默认）</option>
                <option value="mysql"${step.sync_engine === 'mysql' ? ' selected' : ''}>MySQL / 应用内</option>
                <option value="datax"${step.sync_engine === 'datax' ? ' selected' : ''}>DataX</option>
              </select>
            </div>
            <div class="kb-config-field">
              <label class="form-label">目标表</label>
              <input class="form-input" data-step-field="target_table" value="${escapeHtml(step.target_table || '')}" placeholder="stg_from_a">
            </div>
          </div>
          <div class="kb-config-row" style="${isTransfer ? '' : 'display:none'}">
            <div class="kb-config-field">
              <label class="form-label">写入模式</label>
              <select class="form-select" data-step-field="write_mode">
                <option value="append"${step.write_mode === 'append' ? ' selected' : ''}>append 追加</option>
                <option value="replace"${step.write_mode !== 'append' ? ' selected' : ''}>replace 覆盖</option>
              </select>
            </div>
            <div class="kb-config-field">
              <label class="form-label">说明</label>
              <div class="form-help" style="margin:8px 0 0">未安装 Sqoop/DataX 时会自动回退到应用内 MySQL 同步，并在执行日志中提示。</div>
            </div>
          </div>
          <label class="form-label">SQL</label>
          <textarea class="form-textarea" data-step-field="sql_text" rows="3" placeholder="SELECT ...">${escapeHtml(step.sql_text || '')}</textarea>
          <div style="margin-top:8px;text-align:right">
            <button class="btn-danger" type="button" data-remove-step="${index}">删除步骤</button>
          </div>
        </div>`;
    }).join('');
  }

  function readPipelineDraftStepsFromDom() {
    const host = document.getElementById('pipelineStepsHost');
    if (!host) return pipelineDraftSteps;
    const cards = [...host.querySelectorAll('.pipeline-step-card')];
    return cards.map((card, index) => {
      const get = (name) => card.querySelector(`[data-step-field="${name}"]`);
      const num = (value) => {
        const n = Number(value);
        return Number.isFinite(n) && n > 0 ? n : null;
      };
      return {
        name: get('name')?.value.trim() || `步骤${index + 1}`,
        step_type: get('step_type')?.value || 'execute',
        datasource_id: num(get('datasource_id')?.value),
        target_datasource_id: num(get('target_datasource_id')?.value),
        target_table: get('target_table')?.value.trim() || '',
        write_mode: get('write_mode')?.value || 'append',
        sync_engine: get('sync_engine')?.value || 'sqoop',
        sql_text: get('sql_text')?.value || '',
        enabled: true,
        position: index,
      };
    });
  }

  function inferPipelineKind(pipeline) {
    const steps = pipeline?.steps || [];
    if (!steps.length) return 'pipeline';
    const types = new Set(steps.map((s) => (s.step_type || 'execute').toLowerCase()));
    if (types.size === 1 && types.has('transfer')) return 'sync';
    if (types.size === 1 && (types.has('execute') || types.has('query'))) return 'process';
    return 'pipeline';
  }

  function pipelineKindMeta(kind) {
    if (kind === 'sync') return { label: '数据同步', className: 'is-sync' };
    if (kind === 'process') return { label: '数据处理', className: 'is-process' };
    return { label: '综合流水线', className: 'is-pipeline' };
  }

  function updateDpStats() {
    const row = document.getElementById('dpStatRow');
    if (!row) return;
    const scheduled = pipelines.filter((p) => p.schedule_cron || p.schedule_exec_date || p.schedule_enabled).length;
    const success = pipelines.filter((p) => p.last_run_status === 'success').length;
    row.innerHTML = `
      <span>任务 <strong>${pipelines.length}</strong></span>
      <span>已调度 <strong>${scheduled}</strong></span>
      <span>最近成功 <strong>${success}</strong></span>`;
  }

  function openPipelineModal(pipeline = null, preset = null) {
    document.getElementById('pipelineEditId').value = pipeline?.id || '';
    const titleMap = {
      sync: pipeline ? '编辑数据同步' : '新建数据同步',
      process: pipeline ? '编辑数据处理' : '新建数据处理',
    };
    const kind = preset || (pipeline ? inferPipelineKind(pipeline) : 'pipeline');
    document.getElementById('pipelineModalTitle').textContent =
      titleMap[kind] || (pipeline ? '编辑流水线任务' : '新建流水线任务');
    const subtitle = document.getElementById('pipelineModalSubtitle');
    if (subtitle) {
      subtitle.textContent = kind === 'sync'
        ? '配置源表、目标表、同步引擎（默认 Sqoop）与写入方式'
        : kind === 'process'
          ? '配置库内加工 SQL'
          : '编排同步、加工与多步骤任务';
    }
    document.getElementById('pipelineName').value = pipeline?.name || '';
    document.getElementById('pipelineDesc').value = pipeline?.description || '';
    const cronEl = document.getElementById('pipelineScheduleCron');
    const dateEl = document.getElementById('pipelineExecDate');
    const enabledEl = document.getElementById('pipelineScheduleEnabled');
    if (cronEl) cronEl.value = pipeline?.schedule_cron || '';
    if (dateEl) dateEl.value = pipeline?.schedule_exec_date || '';
    if (enabledEl) enabledEl.checked = Boolean(pipeline?.schedule_enabled);

    if (pipeline?.steps?.length) {
      pipelineDraftSteps = pipeline.steps.map((step, index) => ({
        name: step.name || `步骤${index + 1}`,
        step_type: step.step_type || 'execute',
        datasource_id: step.datasource_id,
        target_datasource_id: step.target_datasource_id,
        target_table: step.target_table || '',
        write_mode: step.write_mode || 'append',
        sync_engine: step.sync_engine || (step.step_type === 'transfer' ? 'sqoop' : 'sqoop'),
        sql_text: step.sql_text || '',
        enabled: step.enabled !== false,
        position: index,
      }));
    } else if (preset === 'sync') {
      pipelineDraftSteps = [{
        name: '数据同步',
        step_type: 'transfer',
        datasource_id: null,
        target_datasource_id: null,
        target_table: '',
        write_mode: 'append',
        sync_engine: 'sqoop',
        sql_text: 'SELECT * FROM source_table WHERE 1=1',
        enabled: true,
        position: 0,
      }];
    } else if (preset === 'process') {
      pipelineDraftSteps = [{
        name: '数据处理',
        step_type: 'execute',
        datasource_id: null,
        target_datasource_id: null,
        target_table: '',
        write_mode: 'append',
        sync_engine: 'sqoop',
        sql_text: '-- 加工 SQL，可用 {exec_date}\n',
        enabled: true,
        position: 0,
      }];
    } else {
      pipelineDraftSteps = [{
        name: '1. A库抽取到C',
        step_type: 'transfer',
        datasource_id: null,
        target_datasource_id: null,
        target_table: 'stg_from_a',
        write_mode: 'replace',
        sync_engine: 'sqoop',
        sql_text: 'SELECT * FROM source_table LIMIT 1000',
        enabled: true,
        position: 0,
      }];
    }
    renderPipelineStepEditors();
    pipelineModal?.classList.add('open');
  }

  function closePipelineModal() {
    pipelineModal?.classList.remove('open');
  }

  async function loadPipelines() {
    try {
      pipelines = await pipelineApi('');
      renderPipelineList();
      updateDpStats();
    } catch (error) {
      const list = document.getElementById('taskList');
      if (list) list.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderPipelineList() {
    const list = document.getElementById('taskList');
    if (!list) return;
    const search = (document.getElementById('taskSearchInput')?.value || '').trim().toLowerCase();
    const typeFilter = document.getElementById('taskTypeFilter')?.value || '';
    const scheduleFilter = document.getElementById('taskScheduleFilter')?.value || '';
    const rows = pipelines.filter((p) => {
      const kind = inferPipelineKind(p);
      const text = `${p.name || ''} ${p.description || ''}`.toLowerCase();
      const hitSearch = !search || text.includes(search);
      const hitType = !typeFilter || kind === typeFilter;
      const hasSchedule = Boolean(p.schedule_cron || p.schedule_exec_date || p.schedule_enabled);
      const hitSchedule = !scheduleFilter
        || (scheduleFilter === 'scheduled' && hasSchedule)
        || (scheduleFilter === 'enabled' && p.schedule_enabled);
      return hitSearch && hitType && hitSchedule;
    });
    if (!rows.length) {
      list.innerHTML = `
        <div class="dp-empty">
          <h4>还没有流水线任务</h4>
          <p>可用上方快捷入口创建「数据同步」「数据处理」或空白/模板流水线。</p>
        </div>`;
      return;
    }
    list.innerHTML = rows.map((p) => {
      const kind = inferPipelineKind(p);
      const meta = pipelineKindMeta(kind);
      const lifecycle = pipelineStatusMeta(p.status);
      const status = p.last_run_status || 'idle';
      const statusClass = status === 'success' ? 'ok' : status === 'failed' ? 'error' : status === 'running' ? 'running' : 'idle';
      const statusText = status === 'success' ? '最近成功' : status === 'failed' ? '最近失败' : status === 'running' ? '运行中' : '未运行';
      const steps = p.steps || [];
      const stepChips = steps.slice(0, 4).map((s) =>
        `<span class="dp-step-chip">${escapeHtml((s.step_type || 'step') + ' · ' + (s.name || '步骤'))}</span>`
      ).join('') + (steps.length > 4 ? `<span class="dp-step-chip">+${steps.length - 4}</span>` : '');
      const scheduleBits = [];
      if (p.schedule_enabled) scheduleBits.push('定时已启用');
      if (p.schedule_cron) scheduleBits.push('cron ' + p.schedule_cron);
      if (p.schedule_exec_date) scheduleBits.push('日期 ' + p.schedule_exec_date);
      const engines = [...new Set(steps.map((s) => (s.sync_engine || '').toLowerCase()).filter(Boolean))];
      if (engines.length) scheduleBits.push('引擎 ' + engines.join('/'));
      const canRun = (p.status || '').toLowerCase() === 'active';
      return `
        <article class="pipeline-task-card ${meta.className}">
          <div class="pipeline-task-top">
            <div class="pipeline-task-main">
              <div class="pipeline-task-title-row">
                <span class="dp-kind-badge ${meta.className}">${meta.label}</span>
                <span class="approval-status ${lifecycle.className}">${lifecycle.label}</span>
                <strong>${escapeHtml(p.name)}</strong>
                <span class="dp-run-status ${statusClass}">${statusText}</span>
              </div>
              <p class="pipeline-task-desc">${escapeHtml(p.description || '无描述')}</p>
              <div class="pipeline-task-steps">${stepChips || '<span class="dp-step-chip">暂无步骤</span>'}</div>
              ${scheduleBits.length ? `<div class="pipeline-task-schedule">${escapeHtml(scheduleBits.join(' · '))}</div>` : ''}
            </div>
            <div class="pipeline-card-actions">
              <button class="ds-action-btn ds-action-test" type="button" data-pipe-action="run" data-id="${p.id}" ${canRun ? '' : 'disabled title="待审批通过后才可执行"'}>
                <span>${canRun ? '执行' : '待审批'}</span>
              </button>
              <button class="ds-action-btn ds-action-edit" type="button" data-pipe-action="edit" data-id="${p.id}">
                <span>编辑</span>
              </button>
              <button class="ds-action-btn ds-action-delete" type="button" data-pipe-action="delete" data-id="${p.id}">
                <span>删除</span>
              </button>
            </div>
          </div>
        </article>`;
    }).join('');
  }

  async function loadPipelineRuns() {
    const list = document.getElementById('execLogList');
    if (!list) return;
    const status = document.getElementById('execStatusFilter')?.value || '';
    const keyword = (document.getElementById('execLogSearchInput')?.value || '').trim().toLowerCase();
    try {
      const runs = await pipelineApi('/runs?limit=50' + (status ? ('&status=' + encodeURIComponent(status)) : ''));
      const filtered = runs.filter((run) => {
        if (!keyword) return true;
        const blob = `${run.pipeline_name || ''} ${run.log_text || ''} ${run.error || ''}`.toLowerCase();
        return blob.includes(keyword);
      });
      if (!filtered.length) {
        list.innerHTML = '<div class="doc-empty-hint">暂无执行记录</div>';
        return;
      }
      list.innerHTML = filtered.map((run) => `
        <div class="exec-log-card">
          <div class="pipeline-card-head">
            <div>
              <div class="pipeline-card-name">#${run.id} ${escapeHtml(run.pipeline_name || '')}</div>
              <div class="pipeline-card-meta">状态：${escapeHtml(run.status)} · 触发：${escapeHtml(run.trigger || 'manual')}${run.error ? ' · ' + escapeHtml(run.error) : ''}</div>
            </div>
            <span class="dp-run-status ${run.status === 'success' ? 'ok' : run.status === 'failed' ? 'error' : 'running'}">${escapeHtml(run.status)}</span>
          </div>
          <pre>${escapeHtml(run.log_text || '无日志')}</pre>
          ${(run.step_runs || []).map((s) =>
            `<div class="tool-trace ${s.status === 'success' ? 'ok' : (s.status === 'failed' ? 'error' : '')}">${escapeHtml(s.step_name)} [${escapeHtml(s.step_type)}] ${escapeHtml(s.status)} rows=${s.row_count || 0}\n${escapeHtml(s.message || '')}</div>`
          ).join('')}
        </div>`).join('');
    } catch (error) {
      list.innerHTML = `<div class="doc-empty-hint error-text">${escapeHtml(error.message)}</div>`;
    }
  }

  async function createAbcdTemplate() {
    try {
      const name = 'A+B→C→D 示例流水线_' + Date.now().toString().slice(-4);
      const pipeline = await pipelineApi('/templates/abcd?name=' + encodeURIComponent(name), { method: 'POST' });
      await loadPipelines();
      openPipelineModal(pipeline);
      showAppToast('已创建模板，请补齐各步骤数据源与 SQL', 'ok');
    } catch (error) {
      alert('创建模板失败：' + (error.message || error));
    }
  }

  document.getElementById('addTaskBtn')?.addEventListener('click', () => openPipelineModal(null));
  document.getElementById('dpQuickSyncBtn')?.addEventListener('click', () => openPipelineModal(null, 'sync'));
  document.getElementById('dpQuickProcessBtn')?.addEventListener('click', () => openPipelineModal(null, 'process'));
  document.getElementById('createAbcdTplBtn')?.addEventListener('click', createAbcdTemplate);
  document.getElementById('closePipelineModal')?.addEventListener('click', closePipelineModal);
  document.getElementById('cancelPipelineModal')?.addEventListener('click', closePipelineModal);
  document.getElementById('addPipelineStepBtn')?.addEventListener('click', () => {
    pipelineDraftSteps = readPipelineDraftStepsFromDom();
    pipelineDraftSteps.push({
      name: `步骤${pipelineDraftSteps.length + 1}`,
      step_type: 'execute',
      datasource_id: null,
      target_datasource_id: null,
      target_table: '',
      write_mode: 'append',
      sync_engine: 'sqoop',
      sql_text: '',
      enabled: true,
      position: pipelineDraftSteps.length,
    });
    renderPipelineStepEditors();
  });
  document.getElementById('pipelineStepsHost')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-remove-step]');
    if (!btn) return;
    pipelineDraftSteps = readPipelineDraftStepsFromDom();
    pipelineDraftSteps.splice(Number(btn.dataset.removeStep), 1);
    renderPipelineStepEditors();
  });
  document.getElementById('pipelineStepsHost')?.addEventListener('change', (e) => {
    if (e.target?.dataset?.stepField === 'step_type') {
      pipelineDraftSteps = readPipelineDraftStepsFromDom();
      renderPipelineStepEditors();
    }
  });
  document.getElementById('savePipelineBtn')?.addEventListener('click', async () => {
    const id = document.getElementById('pipelineEditId')?.value;
    const name = document.getElementById('pipelineName')?.value.trim();
    if (!name) { alert('请填写流水线名称'); return; }
    const payload = {
      name,
      description: document.getElementById('pipelineDesc')?.value.trim() || '',
      status: 'active',
      schedule_cron: document.getElementById('pipelineScheduleCron')?.value.trim() || '',
      schedule_exec_date: document.getElementById('pipelineExecDate')?.value.trim() || '',
      schedule_enabled: Boolean(document.getElementById('pipelineScheduleEnabled')?.checked),
      steps: readPipelineDraftStepsFromDom(),
    };
    try {
      if (id) {
        await pipelineApi('/' + id, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        await pipelineApi('', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      closePipelineModal();
      await loadPipelines();
      showAppToast('流水线任务已保存', 'ok');
    } catch (error) {
      alert('保存失败：' + (error.message || error));
    }
  });
  document.getElementById('taskList')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-pipe-action]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const action = btn.dataset.pipeAction;
    const pipeline = pipelines.find((p) => Number(p.id) === id);
    const label = btn.querySelector('span');
    if (action === 'edit') {
      try {
        const detail = await pipelineApi('/' + id);
        openPipelineModal(detail);
      } catch (error) {
        alert(error.message || error);
      }
    }
    if (action === 'delete') {
      if (!confirm('确定删除流水线任务「' + (pipeline?.name || id) + '」？')) return;
      try {
        await pipelineApi('/' + id, { method: 'DELETE' });
        await loadPipelines();
        showAppToast('已删除', 'ok');
      } catch (error) {
        alert(error.message || error);
      }
    }
    if (action === 'run') {
      const kindMeta = (() => {
        const steps = pipeline?.steps || [];
        if (steps.some((s) => (s.step_type || '') === 'transfer') && steps.some((s) => (s.step_type || '') === 'execute')) {
          return '综合流水线';
        }
        if (steps.length && steps.every((s) => (s.step_type || '') === 'transfer')) return '数据同步';
        if (steps.length && steps.every((s) => (s.step_type || '') === 'execute')) return '数据处理';
        return '流水线任务';
      })();
      const stepCount = (pipeline?.steps || []).length;
      const ok = await confirmAppDialog({
        danger: false,
        type: 'info',
        title: '立即执行任务',
        subtitle: '将按当前步骤配置真实跑数',
        message: '确认后会马上执行该任务。若包含写入步骤，请确认目标库权限与 SQL 无误。',
        metaHtml: `任务：<strong>${escapeHtml(pipeline?.name || String(id))}</strong><br>类型：${escapeHtml(kindMeta)} · 步骤 ${stepCount} 个`,
        cancelLabel: '取消',
        actionLabel: '立即执行',
      });
      if (!ok) return;
      btn.disabled = true;
      if (label) label.textContent = '执行中';
      try {
        const run = await pipelineApi('/' + id + '/run', { method: 'POST' });
        const summary = summarizePipelineRun(run);
        const empty = run.status === 'success' && summary.totalRows === 0;
        if (run.status === 'success') {
          showAppToast(
            empty
              ? `执行完成，但合计 0 行（未写入数据）`
              : `执行成功 · 合计 ${summary.totalRows} 行`,
            empty ? 'warn' : 'ok',
            empty ? 5200 : 3600
          );
        } else {
          showAppToast('执行结束：' + (run.status || 'unknown'), 'error');
        }
        await loadPipelines();
        await loadPipelineRuns();
        openDpTab('logs');
        showChatNotice({
          danger: false,
          type: run.status !== 'success' ? 'error' : (empty ? 'warn' : 'info'),
          title: empty ? '执行完成，但没有数据' : (run.status === 'success' ? '执行成功' : '执行结束'),
          subtitle: empty
            ? '请检查源 SQL、执行日期过滤与目标表配置'
            : `状态：${run.status || '-'} · 合计 ${summary.totalRows} 行`,
          message: empty
            ? '任务没有报错，但各步骤影响行数均为 0。常见原因：源查询条件过严、执行日期无匹配、目标库仅查询权限导致未写入，或 SQL 本身未命中数据。'
            : '已根据步骤配置完成执行，可在「执行日志」中查看明细。',
          metaHtml: summary.stepLines.length
            ? summary.stepLines.map((line) => `<div>${line}</div>`).join('')
            : `运行 #${escapeHtml(String(run.id || ''))} · 暂无步骤明细`,
          cancelLabel: '关闭',
          actionLabel: '查看执行日志',
          onAction: () => openDpTab('logs'),
        });
      } catch (error) {
        showAppToast('执行失败：' + (error.message || error), 'error');
      } finally {
        btn.disabled = false;
        if (label) label.textContent = '执行';
      }
    }
  });
  document.getElementById('taskSearchInput')?.addEventListener('input', debounce(renderPipelineList, 180));
  document.getElementById('taskTypeFilter')?.addEventListener('change', renderPipelineList);
  document.getElementById('taskScheduleFilter')?.addEventListener('change', renderPipelineList);
  document.getElementById('refreshExecLogBtn')?.addEventListener('click', loadPipelineRuns);
  document.getElementById('execStatusFilter')?.addEventListener('change', loadPipelineRuns);
  document.getElementById('execLogSearchInput')?.addEventListener('input', debounce(loadPipelineRuns, 200));

  document.getElementById('platformRoleToggle')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.perm-role-opt');
    if (!btn) return;
    const role = btn.dataset.role === 'admin' ? 'admin' : 'user';
    setPlatformRole(role);
    loadApprovalList();
    showAppToast(role === 'admin' ? '已切换为管理员，可审批任务' : '已切换为普通用户', 'ok');
  });
  document.getElementById('refreshApprovalBtn')?.addEventListener('click', loadApprovalList);
  document.getElementById('approvalStatusFilter')?.addEventListener('change', loadApprovalList);
  document.getElementById('auditSearchInput')?.addEventListener('input', debounce(renderApprovalAuditList, 180));
  document.getElementById('exportAuditBtn')?.addEventListener('click', () => {
    let rows = [];
    try {
      rows = JSON.parse(localStorage.getItem(APPROVAL_AUDIT_KEY) || '[]') || [];
    } catch (_) {
      rows = [];
    }
    if (!rows.length) {
      showAppToast('暂无审计记录可导出', 'warn');
      return;
    }
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'approval-audit.json';
    a.click();
    URL.revokeObjectURL(url);
    showAppToast('审计日志已导出', 'ok');
  });
  document.getElementById('addTenantBtn')?.addEventListener('click', () => {
    showAppToast('租户管理能力预留中', 'warn');
  });
  document.getElementById('savePermBtn')?.addEventListener('click', () => {
    showAppToast('请先选择租户后再保存权限', 'warn');
  });
  document.getElementById('approvalList')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-approval-action]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const action = btn.dataset.approvalAction;
    const pipeline = (await pipelineApi('').catch(() => [])).find((p) => Number(p.id) === id);
    if (action === 'view') {
      try {
        const detail = await pipelineApi('/' + id);
        openSettings('dataprocess');
        openPipelineModal(detail);
      } catch (error) {
        showAppToast(error.message || error, 'error');
      }
      return;
    }
    if (!isPlatformAdmin()) {
      showAppToast('需要管理员权限才能审批', 'warn');
      return;
    }
    if (action === 'approve') {
      const ok = await confirmAppDialog({
        danger: false,
        type: 'info',
        title: '批准流水线任务',
        subtitle: '批准后任务将立即生效并可执行',
        message: '确认批准该会话创建的流水线任务？',
        metaHtml: `任务：<strong>${escapeHtml(pipeline?.name || String(id))}</strong>`,
        cancelLabel: '取消',
        actionLabel: '批准生效',
      });
      if (!ok) return;
      try {
        await pipelineApi('/' + id + '/approve', { method: 'POST' });
        appendApprovalAudit({
          action: '批准',
          detail: `批准流水线 #${id} ${pipeline?.name || ''}`,
        });
        showAppToast('已批准，任务已生效', 'ok');
        await loadApprovalList();
        await loadPipelines();
      } catch (error) {
        showAppToast('批准失败：' + (error.message || error), 'error');
      }
      return;
    }
    if (action === 'reject') {
      const ok = await confirmAppDialog({
        danger: true,
        title: '驳回流水线任务',
        subtitle: '驳回后不可执行，可再次编辑后重新审批',
        message: '确认驳回该任务？',
        metaHtml: `任务：<strong>${escapeHtml(pipeline?.name || String(id))}</strong>`,
        cancelLabel: '取消',
        actionLabel: '确认驳回',
      });
      if (!ok) return;
      try {
        await pipelineApi('/' + id + '/reject?reason=' + encodeURIComponent('管理员驳回'), { method: 'POST' });
        appendApprovalAudit({
          action: '驳回',
          detail: `驳回流水线 #${id} ${pipeline?.name || ''}`,
        });
        showAppToast('已驳回', 'ok');
        await loadApprovalList();
        await loadPipelines();
      } catch (error) {
        showAppToast('驳回失败：' + (error.message || error), 'error');
      }
    }
  });
  syncPlatformRoleUi();

  document.addEventListener('visibilitychange', () => {
    document.documentElement.dataset.hidden = document.hidden ? '1' : '0';
    if (document.hidden) persistConversations(true);
  });
  window.addEventListener('beforeunload', () => persistConversations(true));

  document.getElementById('loginSubmitBtn')?.addEventListener('click', () => {
    if (authMode === 'register') submitRegister();
    else submitLogin();
  });
  document.getElementById('loginPassword')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitLogin();
  });
  document.getElementById('loginUsername')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('loginPassword')?.focus();
  });
  document.getElementById('registerPasswordConfirm')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitRegister();
  });
  document.getElementById('registerPassword')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('registerPasswordConfirm')?.focus();
  });
  document.getElementById('registerUsername')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('registerDisplayName')?.focus();
  });
  document.querySelectorAll('[data-auth-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      setAuthMode(btn.dataset.authMode);
    });
  });
  setAuthMode('login');
  refreshRegisterAvailability();
  document.getElementById('changePasswordSubmitBtn')?.addEventListener('click', submitChangePassword);
  document.getElementById('changePasswordConfirm')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitChangePassword();
  });
  document.getElementById('changePasswordNew')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('changePasswordConfirm')?.focus();
  });
  document.getElementById('settingsLogoutBtn')?.addEventListener('click', logoutCurrentUser);
  document.getElementById('refreshUsersBtn')?.addEventListener('click', () => loadUserManageList());
  document.getElementById('accountPasswordSubmitBtn')?.addEventListener('click', submitAccountPasswordChange);
  document.getElementById('accountPasswordConfirm')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitAccountPasswordChange();
  });
  document.getElementById('addUserBtn')?.addEventListener('click', () => openUserModal());
  document.getElementById('closeAddUser')?.addEventListener('click', closeUserModal);
  document.getElementById('cancelAddUser')?.addEventListener('click', closeUserModal);
  document.getElementById('saveUserBtn')?.addEventListener('click', saveUserFromModal);
  document.getElementById('addUserModal')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closeUserModal();
  });
  document.getElementById('userManageList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-user-action]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const action = btn.dataset.userAction;
    try {
      if (action === 'edit') {
        const res = await apiFetch('/api/auth/users');
        const rows = await res.json();
        const user = (rows || []).find((item) => item.id === id);
        if (user) openUserModal(user);
        return;
      }
      if (action === 'toggle') {
        const resList = await apiFetch('/api/auth/users');
        const rows = await resList.json();
        const user = (rows || []).find((item) => item.id === id);
        if (!user) return;
        const res = await apiFetch('/api/auth/users/' + id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: !user.is_active }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || '操作失败');
        await loadUserManageList();
        return;
      }
      if (action === 'delete') {
        if (!confirm('确定删除该用户？')) return;
        const res = await apiFetch('/api/auth/users/' + id, { method: 'DELETE' });
        if (!res.ok && res.status !== 204) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || '删除失败');
        }
        await loadUserManageList();
      }
    } catch (error) {
      showAppToast(error.message || '操作失败', 'error');
    }
  });

  renderConversationList();
  if (currentConversationId && getCurrentConversation()) {
    loadConversation(currentConversationId);
  } else {
    startNewConversation();
  }
  updateCurrentModelLabel();
  bindChatAgentPicker();
  updateChatAgentOptions();
  ensureAuthenticated().then((ok) => {
    if (!ok) return;
    loadKnowledgeBases();
    loadDataSourcesFromApi();
    loadPlatformModels().then(() => {
      renderModelList();
      updateCurrentModelLabel();
    });
  });
  autoResize();
  queryInput?.focus();

  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.switchToPanel = switchToPanel;
  window.models = models;
  window.__AI_PLATFORM__ = {
    openSettings,
    closeSettings,
    switchToPanel,
    get models() { return models; },
    get renderModelList() { return typeof renderModelList === 'function' ? renderModelList : null; },
    get renderDataSourceList() { return typeof renderDataSourceList === 'function' ? renderDataSourceList : null; },
    get loadDataSourcesFromApi() { return typeof loadDataSourcesFromApi === 'function' ? loadDataSourcesFromApi : null; },
    get initKnowledgeBasePanel() { return typeof initKnowledgeBasePanel === 'function' ? initKnowledgeBasePanel : null; },
    get initMcpPanel() { return typeof initMcpPanel === 'function' ? initMcpPanel : null; },
    get initSkillPanel() { return typeof initSkillPanel === 'function' ? initSkillPanel : null; },
    get initAgentPanel() { return typeof initAgentPanel === 'function' ? initAgentPanel : null; },
    get initToolPanel() { return typeof initToolPanel === 'function' ? initToolPanel : null; },
    get loadPipelines() { return typeof loadPipelines === 'function' ? loadPipelines : null; },
    get initPermissionPanel() { return typeof initPermissionPanel === 'function' ? initPermissionPanel : null; },
    get initUsersPanel() { return typeof initUsersPanel === 'function' ? initUsersPanel : null; },
    get initAuthzPanel() { return typeof initAuthzPanel === 'function' ? initAuthzPanel : null; },
    get initGatewayAdminPanel() { return typeof initGatewayAdminPanel === 'function' ? initGatewayAdminPanel : null; },
    get initGatewayUsagePanel() { return typeof initGatewayUsagePanel === 'function' ? initGatewayUsagePanel : null; },
    openPermissionUsersTab,
    isPlatformAdmin,
    hasCapability,
    getUserCapabilities,
  };
}

export default initApp;
