"""Manifest engine core (ported from contrail feeds/base.py): a tiny {{ }} formula language with
date helpers, ordered identity evaluation, and JSON dot-path mutation. Feed-agnostic — every feed
renders through this + a manifest, so a new feed is a template dir + manifest, not Python."""
from __future__ import annotations

import datetime
import re

_VAR_RE = re.compile(r"\$([A-Za-z_]\w*)")
_TPL_RE = re.compile(r"\{\{(.+?)\}\}")
_IDX_RE = re.compile(r"^(.*)\[(\d+|\*)\]$")


def eval_formula(expr: str, ctx: dict, now: datetime.datetime) -> str:
    def _one(m):
        body = m.group(1).strip()
        body = _VAR_RE.sub(lambda v: repr(str(ctx.get(v.group(1), ""))), body)
        helpers = {
            "today": lambda: now.date().isoformat(),
            "date": lambda off: (now.date() + datetime.timedelta(days=off)).isoformat(),
        }
        return str(eval(body, {"__builtins__": {}}, helpers))  # noqa: S307 — whitelisted helpers only
    return _TPL_RE.sub(_one, expr)


def evaluate_identity(spec: dict, ctx0: dict, now: datetime.datetime) -> dict:
    ctx = dict(ctx0)
    for key, formula in spec.items():
        name = key[1:] if key.startswith("$") else key
        ctx[name] = eval_formula(str(formula), ctx, now)
    return ctx


def set_dotpath(root, path: str, value) -> bool:
    parts, targets = path.split("."), [root]
    for i, part in enumerate(parts):
        key, idx, m = part, None, _IDX_RE.match(part)
        if m:
            key, idx = m.group(1), m.group(2)
        nxt, last = [], i == len(parts) - 1
        for t in targets:
            if not isinstance(t, dict) or key not in t:
                continue
            child = t[key]
            if idx is None:
                if last:
                    t[key] = value; nxt.append(True)
                else:
                    nxt.append(child)
            else:
                items = range(len(child)) if idx == "*" else [int(idx)]
                for j in items:
                    if not isinstance(child, list) or j >= len(child):
                        continue
                    if last:
                        child[j] = value; nxt.append(True)
                    else:
                        nxt.append(child[j])
        targets = nxt
    return any(t is True for t in targets)
