# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"c:\jinlujie\code\ai_platform\web\src\legacy\initApp.js")
text = p.read_text(encoding="utf-8")

# NAV title
text = text.replace(
    "      'gateway-usage': '用量统计',\n  };",
    "      'gateway-usage': '用量统计',\n    gateway: 'Gateway 管理',\n  };",
)

# switchToPanel gates and hooks
text = text.replace(
    """    if (panelId === 'authz' && !isPlatformAdmin()) {
      showAppToast('仅管理员可进入授权管理', 'warn');
      panelId = 'permission';
    }
""",
    """    if (panelId === 'authz' && !isPlatformAdmin()) {
      showAppToast('仅管理员可进入授权管理', 'warn');
      panelId = 'permission';
    }
    if (panelId === 'gateway' && !isPlatformAdmin()) {
      showAppToast('仅管理员可配置逻辑模型与 Gateway 策略', 'warn');
      panelId = 'model';
    }
""",
)

text = text.replace(
    "    if (panelId === 'model') { renderModelList(); loadGatewayModels(); }\n    if (panelId === 'gateway-usage') initGatewayUsagePanel();\n",
    "    if (panelId === 'model') renderModelList();\n    if (panelId === 'gateway-usage') initGatewayUsagePanel();\n    if (panelId === 'gateway') initGatewayAdminPanel();\n",
)

# Replace old loadGatewayModels block through gatewayModelsRefreshBtn listener
start = text.find("  async function loadGatewayModels()")
end = text.find("  window.openSettings = openSettings;")
if start < 0 or end < 0:
    raise SystemExit(f"markers not found start={start} end={end}")

new_fn = r'''
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
'''

# Keep loadGatewayUsage and initGatewayUsagePanel from old block
usage_start = text.find("  async function loadGatewayUsage()", start)
if usage_start < 0:
    raise SystemExit("loadGatewayUsage not found")
# extract from usage_start to end (before window.openSettings)
usage_part = text[usage_start:end]
# remove the old gatewayModelsRefreshBtn listener if present at end of usage_part
usage_part = re.sub(
    r"\n  document\.getElementById\('gatewayModelsRefreshBtn'\)\?\.addEventListener\('click', loadGatewayModels\);\n*",
    "\n",
    usage_part,
)

text = text[:start] + new_fn + "\n" + usage_part + text[end:]

# exports
text = text.replace(
    "    get loadGatewayModels() { return typeof loadGatewayModels === 'function' ? loadGatewayModels : null; },\n"
    "    get initGatewayUsagePanel() { return typeof initGatewayUsagePanel === 'function' ? initGatewayUsagePanel : null; },\n",
    "    get initGatewayAdminPanel() { return typeof initGatewayAdminPanel === 'function' ? initGatewayAdminPanel : null; },\n"
    "    get initGatewayUsagePanel() { return typeof initGatewayUsagePanel === 'function' ? initGatewayUsagePanel : null; },\n",
)

# SettingsNav select gate for gateway
nav = Path(r"c:\jinlujie\code\ai_platform\web\src\components\SettingsNav.vue")
nav_text = nav.read_text(encoding="utf-8")
if "panelId === 'gateway'" not in nav_text:
    nav_text = nav_text.replace(
        "  if (panelId === 'authz' && !isAdmin.value) return;\n",
        "  if (panelId === 'authz' && !isAdmin.value) return;\n"
        "  if (panelId === 'gateway' && !isAdmin.value) return;\n",
    )
    nav.write_text(nav_text, encoding="utf-8")

p.write_text(text, encoding="utf-8")
print("initApp + SettingsNav patched")
