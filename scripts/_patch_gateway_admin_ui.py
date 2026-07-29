# -*- coding: utf-8 -*-
"""Move Gateway logical models to admin-only panel."""
from pathlib import Path

# --- index.html ---
html = Path(r"c:\jinlujie\code\ai_platform\web\index.html")
text = html.read_text(encoding="utf-8")

old_block = """          <button class=\"btn-add-model\" id=\"addModelBtn\">
            <svg width=\"13\" height=\"13\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><line x1=\"12\" y1=\"5\" x2=\"12\" y2=\"19\"/><line x1=\"5\" y1=\"12\" x2=\"19\" y2=\"12\"/></svg>
            添加自定义模型
          </button>
          <div class=\"perm-panel-card\" style=\"margin-top:16px\">
            <div class=\"perm-panel-head\">
              <div>
                <h3>Gateway 逻辑模型</h3>
                <p>服务端托管的逻辑模型与路由（default / cheap / quality）。管理员可通过 Gateway Admin API 维护。</p>
              </div>
              <button class=\"btn-secondary\" id=\"gatewayModelsRefreshBtn\" type=\"button\">刷新</button>
            </div>
            <div id=\"gatewayModelsList\" class=\"authz-perm-list\">
              <div class=\"doc-empty-hint\">打开面板后加载…</div>
            </div>
          </div>
        </div>
"""

new_model_end = """          <button class=\"btn-add-model\" id=\"addModelBtn\">
            <svg width=\"13\" height=\"13\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><line x1=\"12\" y1=\"5\" x2=\"12\" y2=\"19\"/><line x1=\"5\" y1=\"12\" x2=\"19\" y2=\"12\"/></svg>
            添加自定义模型
          </button>
        </div>
"""

if old_block not in text:
    raise SystemExit("gateway block in model panel not found")
text = text.replace(old_block, new_model_end, 1)

# simplify model panel desc
text = text.replace(
    "配置 AI 大模型，设置 API Key 并测试连接。调用已统一经 AI Gateway（限流 / 记账）。",
    "配置你的个人模型（API Key / Base URL）。调用经 AI Gateway 统一限流与记账；平台逻辑模型由管理员在「Gateway 管理」中维护。",
    1,
)

gateway_panel = """
        <!-- ========== Gateway 管理（仅管理员） ========== -->
        <div class=\"modal-panel\" id=\"panel-gateway\" data-admin-only=\"1\" hidden>
          <div class=\"panel-desc\">管理员配置平台逻辑模型、厂商密钥与 Gateway 路由策略。普通用户无此权限，聊天仍可使用自己的「模型配置」。</div>

          <nav class=\"perm-tabs\" aria-label=\"Gateway 管理\">
            <button class=\"perm-tab active\" data-gateway-tab=\"models\" type=\"button\">逻辑模型</button>
            <button class=\"perm-tab\" data-gateway-tab=\"routes\" type=\"button\">路由策略</button>
            <button class=\"perm-tab\" data-gateway-tab=\"providers\" type=\"button\">厂商密钥</button>
          </nav>

          <div class=\"kb-tab-content active\" id=\"gateway-tab-models\">
            <div class=\"perm-panel-card\">
              <div class=\"perm-panel-head\">
                <div>
                  <h3>逻辑模型</h3>
                  <p>平台级 model_id → 上游模型；用户侧可只认逻辑名或路由名。</p>
                </div>
                <div class=\"perm-toolbar\">
                  <button class=\"btn-secondary\" id=\"gatewayAdminRefreshModelsBtn\" type=\"button\">刷新</button>
                </div>
              </div>
              <div class=\"authz-grant-form\" style=\"margin-bottom:12px\">
                <div class=\"authz-grant-form__row\">
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwModelId\">逻辑 ID</label>
                    <input class=\"form-input\" id=\"gwModelId\" placeholder=\"deepseek-chat\">
                  </div>
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwModelDisplay\">显示名</label>
                    <input class=\"form-input\" id=\"gwModelDisplay\" placeholder=\"DeepSeek Chat\">
                  </div>
                </div>
                <div class=\"authz-grant-form__row\">
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwModelProvider\">厂商</label>
                    <select class=\"form-select\" id=\"gwModelProvider\"></select>
                  </div>
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwModelUpstream\">上游模型名</label>
                    <input class=\"form-input\" id=\"gwModelUpstream\" placeholder=\"deepseek-chat\">
                  </div>
                </div>
                <div class=\"authz-grant-form__actions\">
                  <button class=\"btn-primary\" id=\"gwModelCreateBtn\" type=\"button\">新增逻辑模型</button>
                </div>
              </div>
              <div id=\"gatewayAdminModelsList\" class=\"authz-perm-list\">
                <div class=\"doc-empty-hint\">加载中…</div>
              </div>
            </div>
          </div>

          <div class=\"kb-tab-content\" id=\"gateway-tab-routes\" hidden>
            <div class=\"perm-panel-card\">
              <div class=\"perm-panel-head\">
                <div>
                  <h3>路由策略</h3>
                  <p>如 cheap / quality / default：按顺序尝试逻辑模型（失败可 fallback）。</p>
                </div>
                <button class=\"btn-secondary\" id=\"gatewayAdminRefreshRoutesBtn\" type=\"button\">刷新</button>
              </div>
              <div class=\"authz-grant-form\" style=\"margin-bottom:12px\">
                <div class=\"authz-grant-form__row\">
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwRouteName\">策略名</label>
                    <input class=\"form-input\" id=\"gwRouteName\" placeholder=\"cheap\">
                  </div>
                  <div class=\"form-group\">
                    <label class=\"form-label\" for=\"gwRouteDesc\">说明</label>
                    <input class=\"form-input\" id=\"gwRouteDesc\" placeholder=\"低成本优先\">
                  </div>
                </div>
                <div class=\"form-group\">
                  <label class=\"form-label\" for=\"gwRouteModels\">逻辑模型列表（逗号分隔，靠前优先）</label>
                  <input class=\"form-input\" id=\"gwRouteModels\" placeholder=\"deepseek-chat, qwen-turbo\">
                </div>
                <div class=\"authz-grant-form__actions\">
                  <button class=\"btn-primary\" id=\"gwRouteCreateBtn\" type=\"button\">新增 / 覆盖策略</button>
                </div>
              </div>
              <div id=\"gatewayAdminRoutesList\" class=\"authz-perm-list\">
                <div class=\"doc-empty-hint\">加载中…</div>
              </div>
            </div>
          </div>

          <div class=\"kb-tab-content\" id=\"gateway-tab-providers\" hidden>
            <div class=\"perm-panel-card\">
              <div class=\"perm-panel-head\">
                <div>
                  <h3>厂商密钥</h3>
                  <p>服务端加密存储；配置后逻辑模型 / 路由即可不依赖用户个人 Key。</p>
                </div>
                <button class=\"btn-secondary\" id=\"gatewayAdminRefreshProvidersBtn\" type=\"button\">刷新</button>
              </div>
              <div id=\"gatewayAdminProvidersList\" class=\"authz-perm-list\">
                <div class=\"doc-empty-hint\">加载中…</div>
              </div>
            </div>
          </div>
        </div>

"""

marker = '        <!-- ========== Gateway 用量 ========== -->'
if marker not in text:
    raise SystemExit("usage panel marker not found")
text = text.replace(marker, gateway_panel + marker, 1)
html.write_text(text, encoding="utf-8")
print("index.html ok")
