# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"c:\jinlujie\code\ai_platform\web\index.html")
text = p.read_text(encoding="utf-8")
marker = '<div class="modal-panel active" id="panel-model">'
if marker not in text:
    raise SystemExit("panel-model not found")
if 'id="panel-gateway-usage"' in text:
    print("already patched")
    raise SystemExit(0)

old_end = """          <button class=\"btn-add-model\" id=\"addModelBtn\">
            <svg width=\"13\" height=\"13\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><line x1=\"12\" y1=\"5\" x2=\"12\" y2=\"19\"/><line x1=\"5\" y1=\"12\" x2=\"19\" y2=\"12\"/></svg>
            添加自定义模型
          </button>
        </div>
"""
if old_end not in text:
    raise SystemExit("addModelBtn block not found")

insert = """          <button class=\"btn-add-model\" id=\"addModelBtn\">
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

        <!-- ========== Gateway 用量 ========== -->
        <div class=\"modal-panel\" id=\"panel-gateway-usage\">
          <div class=\"panel-desc\">查看 AI Gateway 调用用量与估算费用（按模型 / 用户 / 来源聚合）。</div>
          <div class=\"perm-panel-card\">
            <div class=\"perm-panel-head\">
              <div>
                <h3>用量统计</h3>
                <p>数据来自 usage_ledger；普通用户仅看本人，管理员可看全站。</p>
              </div>
              <div class=\"perm-toolbar\">
                <select class=\"form-select\" id=\"gatewayUsageGroupBy\" style=\"min-width:120px\">
                  <option value=\"model\">按模型</option>
                  <option value=\"user\">按用户</option>
                  <option value=\"source\">按来源</option>
                  <option value=\"day\">按日</option>
                </select>
                <button class=\"btn-secondary\" id=\"gatewayUsageRefreshBtn\" type=\"button\">刷新</button>
              </div>
            </div>
            <div id=\"gatewayUsageList\" class=\"authz-perm-list\">
              <div class=\"doc-empty-hint\">加载中…</div>
            </div>
          </div>
        </div>
"""
text = text.replace(old_end, insert, 1)
text = text.replace(
    "配置 AI 大模型，设置 API Key 并测试连接。",
    "配置 AI 大模型，设置 API Key 并测试连接。调用已统一经 AI Gateway（限流 / 记账）。",
    1,
)
p.write_text(text, encoding="utf-8")
print("index.html patched")
