# -*- coding: utf-8 -*-
from pathlib import Path
p = Path(r"c:\jinlujie\code\ai_platform\web\index.html")
t = p.read_text(encoding="utf-8")
# Fix possible mojibake around panel-model desc
bad_markers = ["维护�?", "维护�"]
fixed = False
for b in bad_markers:
    if b in t:
        # replace whole corrupted desc line content by locating panel-model desc
        import re
        t2, n = re.subn(
            r'(<div class="modal-panel active" id="panel-model">\s*<div class="panel-desc">)(.*?)(</div>)',
            r'\1配置你的个人模型（API Key / Base URL）。调用经 AI Gateway 统一限流与记账；平台逻辑模型由管理员在「Gateway 管理」中维护。\3',
            t,
            count=1,
            flags=re.S,
        )
        if n:
            t = t2
            fixed = True
            break
if not fixed and "Gateway 管理」中维护" not in t:
    import re
    t2, n = re.subn(
        r'(<div class="modal-panel active" id="panel-model">\s*<div class="panel-desc">)(.*?)(</div>)',
        r'\1配置你的个人模型（API Key / Base URL）。调用经 AI Gateway 统一限流与记账；平台逻辑模型由管理员在「Gateway 管理」中维护。\3',
        t,
        count=1,
        flags=re.S,
    )
    t = t2
    fixed = n > 0
p.write_text(t, encoding="utf-8")
# verify
idx = t.find('id="panel-model"')
print(t[idx:idx+220])
print("fixed", fixed)
