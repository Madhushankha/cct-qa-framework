"""Convert legacy `<CASE>_report.html` bundles into canonical Result runs.

The pre-framework runners (SOC / ANC / BAG / NON-MVP) emitted one self-contained HTML
report per test case. Everything the canonical Result schema needs is present in that
HTML — meta table, verdict badge, checks table, reasoning, KPIs and the full transcript —
so this parses it back out into `<CASE>.result.json` files a real run dir can hold.

Deliberately does NOT invent data: fields the legacy HTML never carried (seed checkpoints,
DDS pin) are emitted empty/false rather than guessed, so downstream metrics stay honest.

Usage:
    python tools/convert_legacy_reports.py <legacy_dir> <out_run_dir> --feed soc [--env int]

Then run the normal pipeline over <out_run_dir>:
    python -m core.cli evidence <out_run_dir>
    python -m core.cli metrics  <out_run_dir>
    python -m core.cli analyze  <out_run_dir>
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime

# ── tiny HTML helpers (reports are machine-generated and uniform; no bs4 dependency) ──
_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    """Strip tags/entities and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s or ""))).strip()


def _meta(doc: str) -> dict:
    """The `<table class="meta">` renders label/value pairs as alternating <td>s."""
    m = re.search(r'<table class="meta">(.*?)</table>', doc, re.S)
    out: dict[str, str] = {}
    if not m:
        return out
    for row in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        for i in range(0, len(cells) - 1, 2):
            if cells[i]:
                out[cells[i]] = cells[i + 1]
    return out


def _kpis(doc: str) -> dict:
    """`<span class="kpi"><b>VALUE</b>LABEL</span>` -> {label: value}."""
    out = {}
    for blk in re.findall(r'<span class="kpi"[^>]*>(.*?)</span>', doc, re.S):
        b = re.search(r"<b[^>]*>(.*?)</b>", blk, re.S)
        if b:
            out[_text(blk.replace(b.group(0), ""))] = _text(b.group(1))
    return out


def _checks(doc: str) -> list:
    """The Check/Expected/Actual/Result table -> canonical verdict.checks."""
    m = re.search(r"<tr><th>Check</th>.*?</table>", doc, re.S)
    if not m:
        return []
    checks = []
    for row in re.findall(r"<tr>(?!<th)(.*?)</tr>", m.group(0), re.S):
        c = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(c) >= 4 and c[0]:
            checks.append({"name": c[0], "expected": c[1], "actual": c[2],
                           "pass": c[3].upper().startswith(("PASS", "✅", "OK"))})
    return checks


def _transcript(doc: str) -> list:
    """The `Transcript (N messages …)` table -> canonical [{role,text,ts,note}].

    Speaker is identified by the emoji marker, not by words: the legacy reports label the bot
    "🤖 Ask AC (CRT) ⏱ 31s" (no "bot"/"assistant" anywhere) and the customer "🧑 Customer".
    The renderer also appends the step note to the message as "… note: <note>"; that note is
    split back out because evalkit's stage detectors key off it.
    """
    m = re.search(r"<h2>Transcript.*?</table>", doc, re.S)
    if not m:
        return []
    turns = []
    for row in re.findall(r"<tr>(?!<th)(.*?)</tr>", m.group(0), re.S):
        c = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(c) < 3:
            continue
        ts, who, msg = _text(c[0]), _text(c[1]), _text(c[2])
        if not msg:
            continue
        low = who.lower()
        if "🤖" in who or "bot" in low or "assistant" in low or "ask ac" in low:
            role = "assistant"
        elif "🧑" in who or "customer" in low or "user" in low:
            role = "customer"
        else:
            continue
        note = None
        nm = re.search(r"\bnote:\s*(.+)$", msg)
        if nm:
            note = nm.group(1).strip()
            msg = msg[:nm.start()].strip()
        tsm = re.search(r"\d{4}-\d{2}-\d{2}T[\d:]+Z?", ts)
        turns.append({"role": role, "text": msg, "ts": tsm.group(0) if tsm else None, "note": note})
    return turns


def _num(s: str, default=0.0) -> float:
    m = re.search(r"[-+]?\d*\.?\d+", s or "")
    return float(m.group(0)) if m else default


def _canon_decision(raw: str) -> str:
    """Free-text actual decision -> the canonical taxonomy term.

    The legacy checks table holds prose ("NO_DETERMINATION (case created for manual review)",
    "No SoC eligibility determination made"). evalkit's normalize_status only uppercases, so
    feeding it prose produces one confusion-matrix label per phrasing — 19 junk labels for SOC.
    Collapse to the head term here; the full prose is preserved in verdict.checks[].actual.
    """
    if not raw or not raw.strip():
        # evalkit's own sentinel for "no status" — better than an empty confusion-matrix label
        return "UNKNOWN"
    s = re.sub(r"\s+", " ", raw).strip().upper()
    if re.search(r"NO[_ ]DETERMINATION|NO SOC ELIGIBILITY|NOT? DETERMIN", s):
        return "NO_DETERMINATION"
    if re.search(r"\bESCALAT", s):
        return "ESCALATED"
    if re.search(r"\bPENDING\b", s):
        return "PENDING"
    if re.search(r"\b(NOT[_ ]ELIGIBLE|INELIGIBLE)\b", s):
        return "NOT_ELIGIBLE"
    if re.search(r"\bELIGIBLE\b", s):
        return "ELIGIBLE"
    # non-eligibility feeds (baggage / non-MVP / ancillary) describe the outcome in prose
    if re.search(r"MANUAL[_ ]?(REVIEW|ROUTING)|ROUTED TO MANUAL", s):
        return "MANUAL_REVIEW"
    if re.search(r"REDIRECT", s):
        return "REDIRECTED"
    if re.search(r"END[_ ]?FLOW|ENDED THE FLOW", s):
        return "END_FLOW"
    if re.search(r"POLICY[_ ]INFO|GENERAL POLICY|SHOWED POLICY", s):
        return "POLICY_INFO"
    head = re.sub(r"[^A-Z0-9]+", "_", re.split(r"[(,;]| - ", s)[0].strip()).strip("_")
    # a short token is a real status ("BAGGAGE", "NON_MVP"); anything longer was a sentence,
    # and a truncated sentence makes a useless confusion-matrix label — say UNKNOWN instead
    return head if head and head.count("_") <= 2 and len(head) <= 24 else "UNKNOWN"


# Only these indicate the harness itself aborted. NOTE: the legacy bundles put
# "Bot returned only its greeting" in the Result cell of EVERY case including passing ones,
# so it carries no signal and must not be treated as an error — doing so grades an entire
# run as "Harness FAIL" / infra and zeroes the pass rate.
_HARNESS_ERR = re.compile(r"max_turns|timed?\s*out|timeout|traceback|exception|crashed", re.I)


def _split_expected(v: str) -> tuple:
    """"NOT_ELIGIBLE · SoC-APPR-NE-01 · CAD 400" -> (status, system_code, amount|None)."""
    parts = [p.strip() for p in (v or "").split("·")]
    status = parts[0] if parts else ""
    code = parts[1] if len(parts) > 1 else ""
    amount = None
    if len(parts) > 2 and parts[2]:
        am = re.search(r"([A-Z]{3})\s*([\d.]+)", parts[2])
        if am:
            amount = {"currency": am.group(1), "value": float(am.group(2))}
    return status, code, amount


def convert_one(path: str, feed: str, env: str, product: str, run_id: str) -> dict | None:
    doc = open(path, encoding="utf-8", errors="replace").read()
    meta, kpi = _meta(doc), _kpis(doc)

    case_id = meta.get("Test Case") or os.path.basename(path).replace("_report.html", "")
    if not case_id:
        return None

    pnr_raw = meta.get("PNR / pnr_id", "")
    pnr, pnr_id = ([p.strip() for p in pnr_raw.split("/")] + [""])[:2] if pnr_raw else ("", "")
    exp_status, exp_code, exp_amount = _split_expected(meta.get("Expected", ""))

    # verdict: the badge is the authoritative PASS/FAIL; decision comes from the checks table
    badge = re.search(r'class="badge"[^>]*>([A-Z]+)', doc)
    passed = bool(badge and badge.group(1).upper() == "PASS")
    checks = _checks(doc)
    decision = _canon_decision(next(
        (c["actual"] for c in checks
         if "determination" in c["name"].lower() or "categor" in c["name"].lower()), ""))
    reasoning = ""
    rm = re.search(r"<summary>Reasoning</summary>\s*<pre[^>]*>(.*?)</pre>", doc, re.S)
    if rm:
        reasoning = _text(rm.group(1))

    started = meta.get("Started", "") or ""
    date = started[:10] if re.match(r"\d{4}-\d{2}-\d{2}", started) else datetime.utcnow().strftime("%Y-%m-%d")
    regime = ""
    if "/" in meta.get("Route / Regime", ""):
        regime = meta["Route / Regime"].split("/")[-1].strip()

    result_txt = meta.get("Result", "")
    # a genuine harness abort (see _HARNESS_ERR) — and never for a case that passed
    error = result_txt if (_HARNESS_ERR.search(result_txt) and not passed) else None

    return {
        "schema_version": "1.0",
        "scenario_id": f"{product}.{env}.{feed}.{case_id}",
        "run": {"product": product, "env": env, "feed": feed, "date": date, "run_id": run_id,
                "started": started or f"{date}T00:00:00Z",
                "duration_s": _num(kpi.get("total duration", "0"))},
        "case": {"test_case": case_id, "pnr": pnr, "pnr_id": pnr_id,
                 "passenger": meta.get("Passenger", ""), "regime": regime,
                 "expected_status": exp_status, "expected_system_code": exp_code,
                 "expected_amount": exp_amount, "flags": [], "third_party": False},
        # legacy reports carried no seed verification — say so rather than claim it passed
        "seed": {"verified": False, "checkpoints": [], "dds": None},
        "auth": {"otp_fetched": str(kpi.get("OTP fetched", "")).lower() == "true",
                 "contact_id": meta.get("ContactId") or None},
        "verdict": {"decision": decision, "amount": None,
                    "reached_determination": decision not in ("", "UNKNOWN", "NO_DETERMINATION"),
                    "matches_expected": passed, "checks": checks, "reasoning": reasoning},
        "harness": {"error": error, "error_bucket": "harness_abort" if error else None},
        "transcript": _transcript(doc),
        "evidence": {"chat_html": None, "evidence_html": f"{case_id}.evidence.html"},
    }


def _write_index(run_dir: str, feed: str, run_id: str) -> None:
    """Run landing page. The legacy index.html links `<CASE>_report.html`, which no longer
    exists after the rename to `<CASE>.evidence.html`, so build a fresh one."""
    rows, npass = [], 0
    for fn in sorted(f for f in os.listdir(run_dir) if f.endswith(".result.json")):
        d = json.load(open(os.path.join(run_dir, fn), encoding="utf-8"))
        cid = d["case"]["test_case"]
        ok = d["verdict"]["matches_expected"]
        npass += bool(ok)
        rows.append(
            f'<tr><td><a href="{html.escape(cid)}.evidence.html">{html.escape(cid)}</a></td>'
            f'<td>{html.escape(d["case"]["expected_status"] or "")}</td>'
            f'<td>{html.escape(d["verdict"]["decision"] or "")}</td>'
            f'<td class="{"p" if ok else "f"}">{"PASS" if ok else "FAIL"}</td></tr>')
    total = len(rows)
    doc = f"""<!doctype html><meta charset="utf-8"><title>{feed.upper()} — {run_id}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1a2330;background:#fafbfc}}
table{{border-collapse:collapse;width:100%;margin-top:12px}}td,th{{border:1px solid #dde3ea;padding:7px 9px;
text-align:left;font-size:13px}}th{{background:#0b3d6b;color:#fff}}.p{{color:#0a7d33;font-weight:700}}
.f{{color:#b00020;font-weight:700}}.k{{display:inline-block;background:#fff;border:1px solid #dde3ea;
border-radius:8px;padding:8px 16px;margin:4px 8px 0 0}}.k b{{font-size:20px;display:block;color:#0b3d6b}}
</style><h1>{feed.upper()} — test execution</h1><p>run <code>{html.escape(run_id)}</code></p>
<span class="k"><b>{total}</b>cases</span><span class="k"><b>{npass}</b>passed</span>
<span class="k"><b>{total - npass}</b>failed</span>
<span class="k"><b>{(npass / total * 100 if total else 0):.1f}%</b>pass rate</span>
<table><tr><th>Test case</th><th>Expected</th><th>Actual</th><th>Result</th></tr>
{chr(10).join(rows)}</table>"""
    with open(os.path.join(run_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(doc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("legacy_dir")
    ap.add_argument("out_run_dir")
    ap.add_argument("--feed", required=True)
    ap.add_argument("--env", default="int")
    ap.add_argument("--product", default="brove")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()

    run_id = a.run_id or f"{a.feed}_legacy_{datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')}"
    os.makedirs(a.out_run_dir, exist_ok=True)

    reports = sorted(f for f in os.listdir(a.legacy_dir) if f.endswith("_report.html"))
    ok = skipped = 0
    for fn in reports:
        src = os.path.join(a.legacy_dir, fn)
        rec = convert_one(src, a.feed, a.env, a.product, run_id)
        if not rec:
            skipped += 1
            continue
        cid = rec["case"]["test_case"]
        with open(os.path.join(a.out_run_dir, f"{cid}.result.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
        # the legacy HTML *is* the per-case evidence — carry it over under the framework's name
        with open(src, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        with open(os.path.join(a.out_run_dir, f"{cid}.evidence.html"), "w", encoding="utf-8") as fh:
            fh.write(body)
        ok += 1

    _write_index(a.out_run_dir, a.feed, run_id)
    print(f"[{a.feed}] converted {ok} case(s)"
          + (f", skipped {skipped}" if skipped else "") + f" -> {a.out_run_dir} (run_id={run_id})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
