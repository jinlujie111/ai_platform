# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"c:\jinlujie\code\ai_platform\web\src\legacy\initApp.js")
text = p.read_text(encoding="utf-8")

if "function initGatewayUsagePanel" in text:
    print("gateway UI already in initApp")
else:
    helper = r'''
  async function loadGatewayModels() {
    const box = document.getElementById('gatewayModelsList');
    if (!box) return;
    box.innerHTML = '<div class="doc-empty-hint">加载中…</div>';
    try {
      const data = await apiFetch('/api/gateway/v1/models');
      const models = data?.models || [];
      const routes = data?.routes || [];
      if (!models.length && !routes.length) {
        box.innerHTML = '<div class="doc-empty-hint">暂无逻辑模型。管理员可通过 /api/gateway/v1/admin/* 配置。</div>';
        return;
      }
      const modelRows = models.map((m) => `
        <div class="authz-perm-row">
          <div class="authz-perm-row__body">
            <div class="authz-perm-row__title">
              <span class="authz-perm-type">模型</span>
              <strong>${escapeHtml(m.display_name || m.model_id)}</strong>
            </div>
            <div class="authz-perm-row__meta">
              <span class="authz-chip">${escapeHtml(m.model_id)}</span>
            </div>
          </div>
        </div>`).join('');
      const routeRows = routes.map((r) => `
        <div class="authz-perm-row">
          <div class="authz-perm-row__body">
            <div class="authz-perm-row__title">
              <span class="authz-perm-type">路由</span>
              <strong>${escapeHtml(r.name)}</strong>
            </div>
            <div class="authz-perm-row__meta">
              <span>${escapeHtml(r.description || '')}</span>
              <span class="authz-chip">${escapeHtml((r.model_ids || []).join(' → ') || '-')}</span>
            </div>
          </div>
        </div>`).join('');
      box.innerHTML = modelRows + routeRows;
    } catch (error) {
      box.innerHTML = `<div class="doc-empty-hint">${escapeHtml(error.message || '加载失败')}</div>`;
    }
  }

  async function loadGatewayUsage() {
    const box = document.getElementById('gatewayUsageList');
    if (!box) return;
    const groupBy = document.getElementById('gatewayUsageGroupBy')?.value || 'model';
    box.innerHTML = '<div class="doc-empty-hint">加载中…</div>';
    try {
      const data = await apiFetch('/api/gateway/v1/usage?group_by=' + encodeURIComponent(groupBy));
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

  document.getElementById('gatewayModelsRefreshBtn')?.addEventListener('click', loadGatewayModels);

'''
    anchor = "  window.openSettings = openSettings;"
    if anchor not in text:
        raise SystemExit("anchor not found")
    text = text.replace(anchor, helper + "\n" + anchor, 1)

# switchToPanel hooks
if "if (panelId === 'gateway-usage')" not in text:
    text = text.replace(
        "    if (panelId === 'model') renderModelList();\n",
        "    if (panelId === 'model') { renderModelList(); loadGatewayModels(); }\n"
        "    if (panelId === 'gateway-usage') initGatewayUsagePanel();\n",
        1,
    )

# exports
if "loadGatewayModels" not in text.split("window.__AI_PLATFORM__")[-1]:
    text = text.replace(
        "    get initAuthzPanel() { return typeof initAuthzPanel === 'function' ? initAuthzPanel : null; },\n",
        "    get initAuthzPanel() { return typeof initAuthzPanel === 'function' ? initAuthzPanel : null; },\n"
        "    get loadGatewayModels() { return typeof loadGatewayModels === 'function' ? loadGatewayModels : null; },\n"
        "    get initGatewayUsagePanel() { return typeof initGatewayUsagePanel === 'function' ? initGatewayUsagePanel : null; },\n",
        1,
    )

# NAV_TITLES if present
if "NAV_TITLES" in text and "gateway-usage" not in text[text.find("NAV_TITLES"):text.find("NAV_TITLES")+800]:
    import re
    m = re.search(r"const NAV_TITLES = \{([^}]*)\}", text)
    if m:
        block = m.group(0)
        if "gateway-usage" not in block:
            text = text.replace(block, block[:-1] + "    'gateway-usage': '用量统计',\n  }", 1)

p.write_text(text, encoding="utf-8")
print("initApp.js patched")
