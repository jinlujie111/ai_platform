# -*- coding: utf-8 -*-
"""Wire platform Gateway catalog into chat model selection."""
from pathlib import Path
import re

p = Path(r"c:\jinlujie\code\ai_platform\web\src\legacy\initApp.js")
text = p.read_text(encoding="utf-8")

# 1) After models/activeModelId init, add platformModels
needle = "  let activeModelId = localStorage.getItem('active_model_id') || (models.find((m) => m.active)?.id) || null;"
if "let platformModels" not in text:
    text = text.replace(
        needle,
        needle + "\n  let platformModels = []; // admin-configured gateway models/routes (no user key)",
        1,
    )

# 2) getActiveModel includes platform
text = text.replace(
    """  function getActiveModel() {
    return models.find((m) => m.id === activeModelId) || null;
  }
""",
    """  function getActiveModel() {
    return platformModels.find((m) => m.id === activeModelId)
      || models.find((m) => m.id === activeModelId)
      || null;
  }

  function isGatewayModel(model) {
    return Boolean(model && (model.useGateway || model.provider === 'gateway'));
  }
""",
)

# 3) buildModelPayload
text = text.replace(
    """  function buildModelPayload(model) {
    if (!model) return null;
    return {
      provider: model.provider,
      providerName: model.providerName,
      name: model.name,
      displayName: model.displayName || model.name,
      apiKey: model.apiKey || '',
      baseUrl: model.baseUrl || '',
    };
  }
""",
    """  function buildModelPayload(model) {
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
""",
)

# 4) sendMessage apiKey check
text = text.replace(
    """    if (!active.apiKey) {
      showChatNotice({
        title: '缺少 API Key',
        subtitle: '当前模型未完成鉴权配置',
        message: `模型「${active.displayName || active.name}」尚未填写 API Key，请先在配置中心补全后再发送。`,
        type: 'warn',
        actionLabel: '去填写 Key',
        onAction: () => openSettings('model'),
      });
      return;
    }
""",
    """    if (!isGatewayModel(active) && !active.apiKey) {
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
""",
)

# 5) updateCurrentModelLabel - already uses getActiveModel which we fixed

# 6) setActiveModel should not require model in models array for platform
text = text.replace(
    """  function setActiveModel(id) {
    activeModelId = id;
    models.forEach((m) => { m.active = m.id === id; });
    persistModels();
    renderModelList();
    updateCurrentModelLabel();
    initOverview();
  }
""",
    """  function setActiveModel(id) {
    activeModelId = id;
    models.forEach((m) => { m.active = m.id === id; });
    platformModels.forEach((m) => { m.active = m.id === id; });
    persistModels();
    renderModelList();
    updateCurrentModelLabel();
    initOverview();
  }
""",
)

# 7) Insert loadPlatformModels + rewrite renderModelList start
load_fn = r'''
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

'''

if "async function loadPlatformModels" not in text:
    text = text.replace("  function renderModelList() {", load_fn + "  function renderModelList() {", 1)

# 8) Replace renderModelList body to include platform section
old_render = """  function renderModelList() {
    if (!modelListEl) return;
    if (!models.length) {
      modelListEl.innerHTML = `
        <div class="model-empty">
          <div class="model-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>
          </div>
          <h4>还没有配置任何模型</h4>
          <p>点击下方「添加模型」接入你的第一个大模型，选择厂商并填写API Key，即可测试连接并设为生效。</p>
        </div>`;
      return;
    }
    modelListEl.innerHTML = '';
    models.forEach((model) => {
"""

new_render = """  function renderModelList() {
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
"""

if old_render not in text:
    raise SystemExit('renderModelList block not found')
text = text.replace(old_render, new_render, 1)

# 9) Event delegation for activate-platform / test-platform - find modelListEl click handler
# Search for data-action="activate"
if "activate-platform" not in text:
    # Find the activate handler
    m = re.search(r"if \(action === 'activate'\) \{[\s\S]{0,200}?setActiveModel", text)
    if not m:
        # try alternate patterns around modelListEl click
        pass
    # Insert before activate handling in click listener
    text = text.replace(
        "if (action === 'activate') {",
        """if (action === 'activate-platform') {
      setActiveModel(id);
      showAppToast('已切换到平台模型', 'ok');
      return;
    }
    if (action === 'test-platform') {
      testPlatformConnection(id);
      return;
    }
    if (action === 'activate') {""",
        1,
    )

# 10) Add testPlatformConnection after testConnection function
if "async function testPlatformConnection" not in text:
    test_fn = r'''
  async function testPlatformConnection(modelId) {
    const model = platformModels.find((m) => m.id === modelId);
    if (!model) return;
    const card = modelListEl?.querySelector(`[data-action="test-platform"][data-id="${CSS.escape(modelId)}"]`)?.closest('.model-card');
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

'''
    text = text.replace("  async function testConnection(modelId) {", test_fn + "  async function testConnection(modelId) {", 1)

# 11) Call loadPlatformModels on auth success and when opening model panel
text = text.replace(
    "    if (panelId === 'model') renderModelList();\n",
    "    if (panelId === 'model') { loadPlatformModels().finally(() => renderModelList()); }\n",
    1,
)

# ensureAuthenticated then load
if "loadPlatformModels()" not in text[text.find("ensureAuthenticated"):text.find("ensureAuthenticated")+500]:
    text = text.replace(
        """  ensureAuthenticated().then((ok) => {
    if (!ok) return;
    loadKnowledgeBases();
    loadDataSourcesFromApi();
  });
""",
        """  ensureAuthenticated().then((ok) => {
    if (!ok) return;
    loadKnowledgeBases();
    loadDataSourcesFromApi();
    loadPlatformModels().then(() => {
      renderModelList();
      updateCurrentModelLabel();
    });
  });
""",
        1,
    )

# Fix CSS.escape for older browsers - use simpler selector
text = text.replace(
    'modelListEl?.querySelector(`[data-action="test-platform"][data-id="${CSS.escape(modelId)}"]`)?.closest(\'.model-card\')',
    'modelListEl?.querySelector(\'.model-test-btn[data-action="test-platform"][data-id="\' + modelId + \'"]\')?.closest(\'.model-card\')',
)

p.write_text(text, encoding="utf-8")
print("frontend patched")

# index.html hint
html = Path(r"c:\jinlujie\code\ai_platform\web\index.html")
ht = html.read_text(encoding="utf-8")
ht2 = ht.replace(
    "配置你的个人模型（API Key / Base URL）。调用经 AI Gateway 统一限流与记账；平台逻辑模型由管理员在「Gateway 管理」中维护。",
    "上方可选用管理员配置的平台模型（无需 Key）；也可自行添加个人模型。调用统一经 AI Gateway。",
)
if ht2 != ht:
    html.write_text(ht2, encoding="utf-8")
    print("index desc updated")
else:
    print("index desc unchanged")
