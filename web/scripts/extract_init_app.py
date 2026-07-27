# -*- coding: utf-8 -*-
"""Extract app.js body into working ES module + lightweight panel stubs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS_SRC = ROOT / "src" / "legacy" / "_source_app_body.txt"
OUT = ROOT / "src" / "legacy"
OUT.mkdir(parents=True, exist_ok=True)

# Prefer regenerating body from original backup if present; else from git history path
ORIG = ROOT / "_app.js.bak"
if not ORIG.exists():
    # Try to recover from initApp if we overwrote app.js — use initApp body extraction inverse
    # Prefer scripts reading from repo: look for app.js.bak or reconstruct from initApp
    pass

# Read original monolith from git if needed
import subprocess

def load_original_app() -> str:
    bak = ROOT / "app.js.full.bak"
    if bak.exists():
        return bak.read_text(encoding="utf-8")
    try:
        out = subprocess.check_output(
            ["git", "show", "HEAD:web/app.js"],
            cwd=str(ROOT.parent),
            stderr=subprocess.DEVNULL,
        )
        text = out.decode("utf-8")
        if "DOMContentLoaded" in text and len(text) > 10000:
            return text
    except Exception:
        pass
    # Fall back: strip export wrapper from existing initApp
    init = (OUT / "initApp.js").read_text(encoding="utf-8")
    return init

raw = load_original_app()
if "export function initApp" in raw[:200]:
    # already initApp — extract between first { after initApp and last }
    start = raw.find("export function initApp()")
    start = raw.find("{", start) + 1
    # drop trailing window assignments block we added — keep full function body as-is for regenerate
    body_lines = raw[start:].rsplit("window.openSettings", 1)[0].splitlines()
    # remove one indent level
    body = []
    for ln in body_lines:
        if ln.startswith("  "):
            body.append(ln[2:])
        elif ln.strip() == "":
            body.append("")
        else:
            body.append(ln)
    # trim trailing blank/brace leftovers
    while body and body[-1].strip() in {"", "}"}:
        if body[-1].strip() == "}":
            body.pop()
            break
        body.pop()
else:
    lines = raw.splitlines()
    body = [(ln[2:] if ln.startswith("  ") else ln) for ln in lines[3:-1]]

PARTS = [
    ("setup", 0, 593),
    ("chat", 593, 1257),
    ("models_settings", 1257, 1688),
    ("knowledge", 1688, 3216),
    ("mcp", 3216, 3461),
    ("skill", 3461, 3624),
    ("events_core", 3624, 4195),
    ("permission", 4195, 4371),
    ("pipelines", 4371, len(body)),
]

body_indented = "\n".join(("  " + ln) if ln else "" for ln in body)

(OUT / "initApp.js").write_text(
    f'''/**
 * Legacy application bootstrap (extracted from original web/app.js).
 * Feature slices: ./parts/*.js (stubs for Vite code-splitting).
 */
export function initApp() {{
{body_indented}

  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.switchToPanel = switchToPanel;
  window.models = models;
  window.__AI_PLATFORM__ = {{
    openSettings,
    closeSettings,
    switchToPanel,
    get models() {{ return models; }},
    get renderModelList() {{ return typeof renderModelList === 'function' ? renderModelList : null; }},
    get renderDataSourceList() {{ return typeof renderDataSourceList === 'function' ? renderDataSourceList : null; }},
    get loadDataSourcesFromApi() {{ return typeof loadDataSourcesFromApi === 'function' ? loadDataSourcesFromApi : null; }},
    get initKnowledgeBasePanel() {{ return typeof initKnowledgeBasePanel === 'function' ? initKnowledgeBasePanel : null; }},
    get initMcpPanel() {{ return typeof initMcpPanel === 'function' ? initMcpPanel : null; }},
    get initSkillPanel() {{ return typeof initSkillPanel === 'function' ? initSkillPanel : null; }},
    get initToolPanel() {{ return typeof initToolPanel === 'function' ? initToolPanel : null; }},
    get loadPipelines() {{ return typeof loadPipelines === 'function' ? loadPipelines : null; }},
    get initPermissionPanel() {{ return typeof initPermissionPanel === 'function' ? initPermissionPanel : null; }},
  }};
}}

export default initApp;
''',
    encoding="utf-8",
)

parts_dir = OUT / "parts"
parts_dir.mkdir(exist_ok=True)
for name, a, b in PARTS:
    n = max(0, b - a)
    (parts_dir / f"{name}.js").write_text(
        f'''/** Feature part stub: {name} (~{n} lines in legacy initApp) */
export const partId = '{name}';
export const lineCount = {n};
export default {{ partId, lineCount }};
''',
        encoding="utf-8",
    )
    print(f"stub {name}: {n}")

(OUT / "panels.js").write_text(
    '''/** Panel lazy-load helpers (Vite code-splitting + API hooks) */

export const panelLoaders = {
  model: () => import('./parts/models_settings.js'),
  datasource: () => import('./parts/models_settings.js'),
  kb: () => import('./parts/knowledge.js'),
  mcp: () => import('./parts/mcp.js'),
  skill: () => import('./parts/skill.js'),
  tool: () => import('./parts/setup.js'),
  dataprocess: () => import('./parts/pipelines.js'),
  permission: () => import('./parts/permission.js'),
  api: async () => ({ partId: 'api' }),
  dataoutput: async () => ({ partId: 'dataoutput' }),
};

export async function prefetchPanel(panelId) {
  const loader = panelLoaders[panelId];
  if (loader) await loader();
}

export async function activatePanel(panelId, api = window.__AI_PLATFORM__) {
  await prefetchPanel(panelId);
  if (!api) return;
  switch (panelId) {
    case 'model':
      api.renderModelList?.();
      break;
    case 'datasource':
      await api.loadDataSourcesFromApi?.();
      api.renderDataSourceList?.();
      break;
    case 'kb':
      api.initKnowledgeBasePanel?.();
      break;
    case 'mcp':
      api.initMcpPanel?.();
      break;
    case 'skill':
      api.initSkillPanel?.();
      break;
    case 'tool':
      api.initToolPanel?.();
      break;
    case 'dataprocess':
      await api.loadPipelines?.();
      break;
    case 'permission':
      api.initPermissionPanel?.();
      break;
    default:
      break;
  }
}
''',
    encoding="utf-8",
)

print("OK initApp lines", len(body))
''',
