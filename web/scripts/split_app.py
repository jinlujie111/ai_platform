# -*- coding: utf-8 -*-
"""Split web/app.js into ES modules with a shared bag + identifier rewrite."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
OUT = ROOT / "src" / "legacy"

# Original 1-based line ranges (inclusive), content inside DOMContentLoaded
SECTIONS = [
    ("setup", 4, 596),
    ("chat", 597, 1260),
    ("models_settings", 1261, 1691),
    ("knowledge", 1692, 3219),
    ("mcp", 3220, 3464),
    ("skill", 3465, 3627),
    ("events_core", 3628, 4198),
    ("permission", 4199, 4374),
    ("pipelines", 4375, 5043),
]

# Do not rewrite these to shared.*
KEEP = {
    "shared",
    "window",
    "document",
    "localStorage",
    "JSON",
    "Date",
    "Math",
    "Number",
    "String",
    "Array",
    "Object",
    "Promise",
    "Map",
    "Set",
    "Error",
    "parseInt",
    "parseFloat",
    "isNaN",
    "encodeURIComponent",
    "decodeURIComponent",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
    "requestAnimationFrame",
    "fetch",
    "URL",
    "Blob",
    "FormData",
    "FileReader",
    "console",
    "alert",
    "confirm",
    "prompt",
    "navigator",
    "location",
    "history",
    "Boolean",
    "undefined",
    "null",
    "true",
    "false",
    "this",
    "arguments",
    "event",
    "e",
    "err",
    "error",
    "item",
    "entry",
    "btn",
    "el",
    "res",
    "data",
    "json",
    "text",
    "name",
    "id",
    "type",
    "value",
    "key",
    "msg",
    "row",
    "rows",
    "list",
    "card",
    "panel",
    "tab",
    "index",
    "i",
    "j",
    "n",
    "ok",
    "html",
    "node",
    "nodes",
    "opts",
    "options",
    "config",
    "payload",
    "result",
    "results",
    "status",
    "label",
    "title",
    "message",
    "content",
    "role",
    "path",
    "url",
    "body",
    "headers",
    "method",
    "signal",
    "AbortController",
    "Intl",
    "RegExp",
    "Map",
}


def extract_body(text: str) -> list[str]:
    lines = text.splitlines()
    start = 3
    end = len(lines) - 1
    body = lines[start:end]
    out = []
    for line in body:
        out.append(line[2:] if line.startswith("  ") else line)
    return out


def hoist_to_shared(text: str) -> tuple[str, set[str]]:
    names: set[str] = set()

    def fn_repl(m: re.Match) -> str:
        names.add(m.group(1))
        return f"shared.{m.group(1)} = function {m.group(1)}("

    text = re.sub(
        r"^function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        fn_repl,
        text,
        flags=re.M,
    )

    def let_repl(m: re.Match) -> str:
        names.add(m.group(1))
        return f"shared.{m.group(1)} ="

    text = re.sub(
        r"^(?:let|const|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
        let_repl,
        text,
        flags=re.M,
    )
    return text, names


def rewrite_idents(text: str, names: set[str]) -> str:
    """Replace bare shared-owned identifiers with shared.name (skip strings/comments roughly)."""
    # Sort longer names first
    ordered = sorted(names - KEEP, key=len, reverse=True)
    if not ordered:
        return text

    # Protect string literals and comments with placeholders
    slots: list[str] = []

    def stash(m: re.Match) -> str:
        slots.append(m.group(0))
        return f"__SLOT_{len(slots) - 1}__"

    masked = re.sub(
        r"(`(?:\\.|[^`])*`)|('(?:\\.|[^'\\])*')|(\"(?:\\.|[^\"\\])*\")|(/\*[\s\S]*?\*/)|(//[^\n]*)",
        stash,
        text,
    )

    for name in ordered:
        # skip if already shared.name
        pattern = re.compile(rf"(?<![.\\w]){re.escape(name)}(?![\\w:])")

        def repl(m: re.Match, n=name) -> str:
            # don't touch `shared.n` left side already rewritten - lookbehind handles .
            return f"shared.{n}"

        masked = pattern.sub(repl, masked)

    # undo accidental shared.shared.
    masked = masked.replace("shared.shared.", "shared.")

    def unstash(m: re.Match) -> str:
        return slots[int(m.group(1))]

    return re.sub(r"__SLOT_(\d+)__", unstash, masked)


def wrap_section(name: str, lines: list[str]) -> str:
    body = "\n".join(("  " + ln) if ln else "" for ln in lines)
    return f"""/** Auto-generated section: {name} */
import {{ shared }} from './shared.js';

export function install_{name}() {{
{body}
}}
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = APP_JS.read_text(encoding="utf-8")
    body_lines = extract_body(raw)
    body_text = "\n".join(body_lines)
    hoisted, names = hoist_to_shared(body_text)
    rewritten = rewrite_idents(hoisted, names)
    converted = rewritten.splitlines()

    (OUT / "shared.js").write_text(
        """/** Shared mutable bag for legacy feature modules */
export const shared = {};

export function getShared() {
  return shared;
}
""",
        encoding="utf-8",
    )

    for name, start_1, end_1 in SECTIONS:
        chunk = converted[start_1 - 4 : end_1 - 3]
        (OUT / f"{name}.js").write_text(wrap_section(name, chunk), encoding="utf-8")
        print(f"wrote {name}.js ({len(chunk)} lines) names~{len(names)}")

    installs = ",\n  ".join(f"install_{n}" for n, _, _ in SECTIONS)
    imports = "\n".join(
        f"import {{ install_{n} }} from './{n}.js';" for n, _, _ in SECTIONS
    )
    (OUT / "initApp.js").write_text(
        f"""{imports}
import {{ shared }} from './shared.js';

/**
 * Boot the legacy application (call when DOM is ready).
 */
export function initApp() {{
  const installers = [
  {installs}
  ];
  for (const install of installers) install();

  window.openSettings = shared.openSettings;
  window.closeSettings = shared.closeSettings;
  window.switchToPanel = shared.switchToPanel;
  window.models = shared.models;
  window.__AI_PLATFORM__ = shared;
  return shared;
}}

export {{ shared }};
""",
        encoding="utf-8",
    )

    # panel loaders for Vite dynamic import (phase 2)
    (OUT / "panels.js").write_text(
        """/** Lazy panel initializers for settings hub */
import { shared } from './shared.js';

export const panelLoaders = {
  model: async () => {
    shared.renderModelList?.();
  },
  datasource: async () => {
    await shared.loadDataSourcesFromApi?.();
    shared.renderDataSourceList?.();
  },
  kb: async () => {
    shared.initKnowledgeBasePanel?.();
  },
  mcp: async () => {
    shared.initMcpPanel?.();
  },
  skill: async () => {
    shared.initSkillPanel?.();
  },
  tool: async () => {
    shared.initToolPanel?.();
  },
  dataprocess: async () => {
    await shared.loadPipelines?.();
  },
  permission: async () => {
    shared.initPermissionPanel?.();
  },
  api: async () => {},
  dataoutput: async () => {},
};

export async function loadPanel(panelId) {
  const loader = panelLoaders[panelId];
  if (loader) await loader();
}
""",
        encoding="utf-8",
    )
    print("names collected:", len(names))
    print("done ->", OUT)


if __name__ == "__main__":
    main()
