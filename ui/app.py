"""Air Canada Test Data Management & Execution UI — a local stdlib web app over the framework.

Reads the registry (products/envs/flows), the gap-doc catalog (test cases), the seeded fixtures
(created test data), and the execution results (reports) — and drives seeding + execution as
background jobs. NO backend changes: everything here is read-only over the existing framework plus
subprocess calls to the existing CLIs (`seed.cli.run_seed_all`, `core.cli run/metrics/analyze`).

Run:  python -m ui.app   ->  http://127.0.0.1:8770/
Start it from a shell with AWS_PROFILE / DDS_API_KEY / MAILINATOR_TOKEN exported so seed/run work.

Covers (from the requirements): product/env/type/flow selection, catalog filtering, multi-select
seeding with a confirmation summary + live status, a created-test-data screen, execution, a
report/evidence review screen, and a dashboard. SIT vs UAT is a selectable type (UAT gap docs are
what the framework currently loads; SIT is wired as a future doc set).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SEED_ROOT = ROOT / "runs" / "seed"
RESULTS_ROOT = ROOT / "results"
REG = ROOT / "core" / "registry"

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()

_FLOW_LABELS = {"fd": "Flight Disruption", "soc": "Standards of Care", "nc": "Name Correction",
                "anc": "Ancillaries", "baggage": "Baggage", "bookingchange": "Booking Change",
                "seatchange": "Seat Change", "nonmvp": "Non-MVP"}
_CLASS_STATUS = {"EL": "ELIGIBLE", "DB": "ELIGIBLE", "NE": "NOT_ELIGIBLE",
                 "ND": "NO_DETERMINATION", "PE": "PENDING"}


def _kind_filter(kind: str):
    """Return a predicate over a file NAME for a download `kind`: all / evidence / quality / reports."""
    if kind == "evidence":
        return lambda n: n.endswith(".evidence.html")
    if kind == "quality":
        return lambda n: n.endswith(".quality.html")
    if kind == "reports":  # the HTML reports, not the raw result JSON
        return lambda n: n.endswith(".html")
    return lambda n: True  # all


# ── registry / catalog (read-only over the framework) ─────────────────────────
def _registry() -> dict:
    def _ids(sub):
        d = REG / sub
        return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []
    feeds = _ids("feeds")
    return {"products": _ids("products"), "envs": _ids("envs"),
            "flows": [{"id": f, "label": _FLOW_LABELS.get(f, f.upper())} for f in feeds],
            "types": ["UAT", "SIT"]}


def _gapdoc_detail(feed_desc) -> dict:
    """case_id -> the rich gap-doc description (the card's data-search spec: DDS code, trip-tracer
    promise/actual/delay, controllability, dashboard expectation). Read straight from the gap-doc HTML
    so the Test Cases tab shows exactly what the UAT doc specifies for each case."""
    import re
    import html as _html
    out: dict = {}
    for doc in ([feed_desc.gap_doc] if getattr(feed_desc, "gap_doc", None) else []) + list(getattr(feed_desc, "gap_docs", []) or []):
        try:
            raw = Path(ROOT / doc if not Path(doc).is_absolute() else doc).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            try:
                raw = Path(doc).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
        for cid, attrs in re.findall(r'<section class="card" id="([A-Za-z0-9_]+)"([^>]*)>', raw):
            m = re.search(r'data-search="([^"]*)"', attrs)
            if m:
                txt = _html.unescape(m.group(1))
                # the data-search starts with "<id> <name> <detail>"; keep it as the human detail
                out[cid] = re.sub(r"\s+", " ", txt).strip()
    return out


def _catalog(product: str, env: str, feed: str) -> list:
    """Test cases for a product/env/flow, from the gap-doc catalog, enriched with the full UAT gap-doc
    detail (name, expected, scenario spec, intent) plus data + exec status."""
    from core.registry import resolve
    from catalog.parser import load_catalog
    from seed.dds_pin import parse_system_code
    try:
        fd = resolve(product, env, feed).feed
        cat = load_catalog(fd)
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    seeded = _seeded_case_ids(feed, product, env)
    executed = _executed_case_status(feed, product, env)
    detail = _gapdoc_detail(fd)
    rows = []
    for c in cat.cases:
        sc = c.system_code or c.seed.system_code or ""
        _, cls = parse_system_code(sc)
        status = (c.verdict or c.seed.status or _CLASS_STATUS.get(cls, "")).upper()
        amt = c.seed.amount or {}
        rows.append({
            "id": c.id, "name": c.title, "status": status, "system_code": sc,
            "amount": f"{amt.get('currency','')} {amt.get('value','')}".strip() if amt else "",
            "regime": c.regime, "group": (c.seed.extras or {}).get("group", ""),
            "scenario": (c.seed.extras or {}).get("scenario", ""),
            "third_party": bool(c.third_party),
            "intent": c.customer_intent or "",
            "expected_transcript": [{"role": t.get("role"), "text": t.get("text")} for t in (c.expected_transcript or [])][:8],
            "detail": detail.get(c.id, ""),
            "route": c.seed.route or "",
            "data_status": "Seeded" if c.id in seeded else "No Data",
            "exec_status": executed.get(c.id, "Not Run"),
        })
    return rows


def _seeded_case_ids(feed, product, env) -> set:
    ids = set()
    prefix = f"{feed}_{product}_{env}_"
    if SEED_ROOT.is_dir():
        for d in SEED_ROOT.iterdir():
            if not d.is_dir() or not (d.name.startswith(prefix) or feed in d.name):
                continue
            for m in d.glob("*/meta.json"):
                try:
                    ids.add(json.loads(m.read_text(encoding="utf-8")).get("case_id"))
                except Exception:
                    pass
    return ids


def _executed_case_status(feed, product, env) -> dict:
    """case_id -> most-recent exec status (Passed/Failed) across result folders for this cell."""
    out = {}
    if not RESULTS_ROOT.is_dir():
        return out
    for datedir in sorted(RESULTS_ROOT.iterdir()):
        for run in sorted(datedir.iterdir()) if datedir.is_dir() else []:
            if not run.is_dir() or feed not in run.name:
                continue
            for res in run.glob("*.result.json"):
                try:
                    d = json.loads(res.read_text(encoding="utf-8"))
                    if d.get("run", {}).get("feed") != feed:
                        continue
                    out[d["case"]["test_case"]] = "Passed" if d["verdict"]["matches_expected"] else "Failed"
                except Exception:
                    pass
    return out


# ── created test data ─────────────────────────────────────────────────────────
def _testdata(feed: str, product: str, env: str) -> list:
    rows = []
    prefix = f"{feed}_{product}_{env}_"
    if not SEED_ROOT.is_dir():
        return rows
    for d in sorted(SEED_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or not (d.name.startswith(prefix) or (feed in d.name and product in d.name)):
            continue
        for m in sorted(d.glob("*/meta.json")):
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except Exception:
                continue
            ts = int(m.stat().st_mtime)
            rows.append({
                "data_id": meta.get("locator"), "case_id": meta.get("case_id"),
                "pnr_id": meta.get("pnr_id"), "product": product, "flow": feed, "env": env,
                "passenger": f"{meta.get('first','')} {meta.get('surname','')}".strip(),
                "system_code": meta.get("system_code"), "date": meta.get("date"),
                "created_utc": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "set": d.name, "status": "Available",
            })
    return rows


# ── reports ───────────────────────────────────────────────────────────────────
def _report_runs(feed: str) -> list:
    out = []
    if not RESULTS_ROOT.is_dir():
        return out
    for datedir in sorted(RESULTS_ROOT.iterdir(), reverse=True):
        for run in sorted(datedir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if datedir.is_dir() else []:
            if not run.is_dir() or (feed and feed not in run.name):
                continue
            results = list(run.glob("*.result.json"))
            if not results:
                continue
            p = f = 0
            for r in results:
                try:
                    ok = json.loads(r.read_text(encoding="utf-8"))["verdict"]["matches_expected"]
                    p, f = (p + 1, f) if ok else (p, f + 1)
                except Exception:
                    pass
            out.append({"name": run.name, "path": str(run.relative_to(ROOT)).replace("\\", "/"),
                        "cases": len(results), "passed": p, "failed": f,
                        "has_index": (run / "index.html").exists(),
                        "has_metrics": (run / "metrics" / "report.html").exists(),
                        "utc": datetime.fromtimestamp(run.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    return out


def _analytics(run_rel: str) -> dict:
    """Metrics (trajectory funnel + decision/error mix) + analysis (grades, clusters) for one run —
    read from the run's metrics/metrics.json + analysis/analysis.json when the pipeline produced them,
    else computed on the fly from the result set so the tab always has something to show."""
    run = (ROOT / run_rel).resolve()
    if not str(run).startswith(str(RESULTS_ROOT.resolve())) or not run.is_dir():
        return {"error": "run not found"}
    out: dict = {"name": run.name, "has_metrics": (run / "metrics" / "report.html").exists()}
    mp = run / "metrics" / "metrics.json"
    if mp.exists():
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
            out["stage_coverage"] = m.get("trajectory", {}).get("stage_coverage", {})
            out["anomaly_rates"] = m.get("trajectory", {}).get("anomaly_rates", {})
        except Exception:
            pass
    ap = run / "analysis" / "analysis.json"
    if ap.exists():
        try:
            a = json.loads(ap.read_text(encoding="utf-8"))
            out["findings"] = a.get("findings", {})
            out["clusters"] = a.get("clusters", [])
        except Exception:
            pass
    # always-present roll-ups computed straight from the results (decision + grade mix)
    from analysis.grade import grade as _grade
    dec: dict = {}
    grd: dict = {}
    for res in run.glob("*.result.json"):
        try:
            d = json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            continue
        dec[d["verdict"]["decision"]] = dec.get(d["verdict"]["decision"], 0) + 1
        g = _grade(d)["grade"]
        grd[g] = grd.get(g, 0) + 1
    out["decisions"] = dec
    out["grades"] = grd
    return out


def _run_cases(run_rel: str) -> list:
    run = (ROOT / run_rel).resolve()
    out = []
    if not str(run).startswith(str(RESULTS_ROOT.resolve())) or not run.is_dir():
        return out
    for res in sorted(run.glob("*.result.json")):
        try:
            d = json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            continue
        cid = d["case"]["test_case"]
        out.append({
            "id": cid, "result": "Passed" if d["verdict"]["matches_expected"] else "Failed",
            "expected": d["case"]["expected_status"], "actual": d["verdict"]["decision"],
            "system_code": d["case"].get("expected_system_code", ""),
            "evidence": f"{run_rel}/{cid}.evidence.html" if (run / f"{cid}.evidence.html").exists() else None,
            "quality": f"{run_rel}/{cid}.quality.html" if (run / f"{cid}.quality.html").exists() else None,
        })
    return out


# ── dashboard ─────────────────────────────────────────────────────────────────
def _dashboard(product: str, env: str, feed: str) -> dict:
    cat = _catalog(product, env, feed)
    if cat and cat[0].get("error"):
        return {"error": cat[0]["error"]}
    total = len(cat)
    seeded = sum(1 for c in cat if c["data_status"] == "Seeded")
    passed = sum(1 for c in cat if c["exec_status"] == "Passed")
    failed = sum(1 for c in cat if c["exec_status"] == "Failed")
    not_run = sum(1 for c in cat if c["exec_status"] == "Not Run")
    by_status: dict = {}
    for c in cat:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    return {"total": total, "seeded": seeded, "no_data": total - seeded,
            "seed_pct": round(100 * seeded / total) if total else 0,
            "passed": passed, "failed": failed, "not_run": not_run,
            "pass_pct": round(100 * passed / (passed + failed)) if (passed + failed) else 0,
            "by_status": by_status}


# ── seed / run jobs ───────────────────────────────────────────────────────────
def _job(job_id, kind):
    with _JOBS_LOCK:
        return dict(_JOBS.get(job_id) or {"status": "unknown"})


def _seed_job(job_id, product, env, feed, ids):
    def push(line):
        with _JOBS_LOCK:
            _JOBS[job_id]["log"].append(line.rstrip("\n"))
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    clone = f"runs/seed/{feed}_{product}_{env}_{stamp}"
    code = (f"from seed.cli import run_seed_all;"
            f"run_seed_all('{product}','{env}','{feed}',clone_dir='{clone}',verify=True,"
            f"only={json.dumps(ids)},workers=8)")
    _exec(job_id, [sys.executable, "-c", code], push, {"clone": clone, "total": len(ids)})
    with _JOBS_LOCK:
        _JOBS[job_id]["clone"] = clone


def _run_job(job_id, product, env, feed, clone, pipeline):
    def push(line):
        with _JOBS_LOCK:
            _JOBS[job_id]["log"].append(line.rstrip("\n"))
    cmd = [sys.executable, "-m", "core.cli", "run", product, env, feed, "--fixtures", clone,
           "--conc", "8", "--otp-conc", "4"]
    rc = _exec(job_id, cmd, push, {})
    with _JOBS_LOCK:
        run_dir = _JOBS[job_id].get("run_dir")
    if pipeline and rc == 0 and run_dir:
        _exec(job_id, [sys.executable, "-m", "core.cli", "metrics", run_dir], push, {})
        _exec(job_id, [sys.executable, "-m", "core.cli", "analyze", run_dir], push, {})


def _exec(job_id, cmd, push, extra) -> int:
    with _JOBS_LOCK:
        _JOBS[job_id].update(extra)
    push(f"$ {' '.join(cmd[:6])} ...")
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in proc.stdout:
            push(line)
            if "-> results" in line:
                with _JOBS_LOCK:
                    _JOBS[job_id]["run_dir"] = line.split("-> ", 1)[-1].strip().replace("\\", "/")
        proc.wait()
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done" if proc.returncode == 0 else "error"
        push(f"[exit {proc.returncode}]")
        return proc.returncode
    except Exception as exc:  # noqa: BLE001
        push(f"[FAILED] {exc}")
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
        return 1


def _start(kind, target, *args) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "running", "kind": kind, "log": [], "run_dir": None}
    threading.Thread(target=target, args=(job_id, *args), daemon=True).start()
    return job_id


# ── HTTP ──────────────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            return self._send(200, _PAGE, "text/html; charset=utf-8")
        if u.path == "/api/registry":
            return self._send(200, _registry())
        if u.path == "/api/catalog":
            return self._send(200, _catalog(q.get("product", "bravo"), q.get("env", "int"), q.get("feed", "fd")))
        if u.path == "/api/dashboard":
            return self._send(200, _dashboard(q.get("product", "bravo"), q.get("env", "int"), q.get("feed", "fd")))
        if u.path == "/api/testdata":
            return self._send(200, _testdata(q.get("feed", "fd"), q.get("product", "bravo"), q.get("env", "int")))
        if u.path == "/api/reports":
            return self._send(200, _report_runs(q.get("feed", "fd")))
        if u.path == "/api/runcases":
            return self._send(200, _run_cases(q.get("run", "")))
        if u.path == "/api/analytics":
            return self._send(200, _analytics(q.get("run", "")))
        if u.path == "/api/job":
            return self._send(200, _job(q.get("id", ""), None))
        if u.path.startswith("/r/"):
            import mimetypes
            f = (ROOT / u.path[3:]).resolve()
            ok = str(f).startswith(str(RESULTS_ROOT.resolve())) or str(f).startswith(str(SEED_ROOT.resolve()))
            if not ok or not f.is_file():
                return self._send(404, {"error": "not found"})
            ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            if ct.startswith("text/") or ct == "application/json":
                ct += "; charset=utf-8"
            return self._send(200, f.read_bytes(), ct)
        if u.path == "/download":
            return self._download(q)
        return self._send(404, {"error": "not found"})

    def _in_results(self, p: Path) -> bool:
        return str(p.resolve()).startswith(str(RESULTS_ROOT.resolve()))

    def _serve_bytes(self, data: bytes, fname: str, ctype="application/zip"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _download(self, q):
        """Every download option:
          ?file=<path>                         single report (evidence/quality/json) as a download
          ?run=<path>[&kind=all|evidence|quality]   one run's reports (optionally filtered)
          ?feed=<feed>&scope=all[&kind=...]    BULK — every run for a flow, filtered
        """
        kind = q.get("kind", "all")
        keep = _kind_filter(kind)

        # 1) single file
        if q.get("file"):
            f = (ROOT / q["file"]).resolve()
            if not self._in_results(f) or not f.is_file():
                return self._send(404, {"error": "not found"})
            return self._serve_bytes(f.read_bytes(), f.name, "text/html; charset=utf-8")

        # 2) bulk across all runs for a flow
        if q.get("scope") == "all" and q.get("feed"):
            feed = q["feed"]
            runs = [Path(ROOT / r["path"]) for r in _report_runs(feed)]
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for run in runs:
                    for fp in run.rglob("*"):
                        if fp.is_file() and keep(fp.name):
                            z.write(fp, Path(run.name) / fp.relative_to(run))
            return self._serve_bytes(buf.getvalue(), f"{feed}_ALL_{kind}.zip")

        # 3) one run (optionally filtered by kind)
        run = (ROOT / q.get("run", "")).resolve()
        if not self._in_results(run) or not run.is_dir():
            return self._send(404, {"error": "not found"})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fp in run.rglob("*"):
                if fp.is_file() and keep(fp.name):
                    z.write(fp, fp.relative_to(run.parent))
        return self._serve_bytes(buf.getvalue(), f"{run.name}_{kind}.zip")

    def do_POST(self):
        u = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if u.path == "/api/seed":
            ids = [x for x in (body.get("ids") or []) if x]
            if not ids:
                return self._send(400, {"error": "no test cases selected"})
            job = _start("seed", _seed_job, body.get("product", "bravo"), body.get("env", "int"),
                         body.get("feed", "fd"), ids)
            return self._send(200, {"job": job})
        if u.path == "/api/run":
            clone = body.get("clone", "")
            if not (ROOT / clone).resolve().is_dir() if clone else True:
                pass
            job = _start("run", _run_job, body.get("product", "bravo"), body.get("env", "int"),
                         body.get("feed", "fd"), clone, bool(body.get("pipeline")))
            return self._send(200, {"job": job})
        return self._send(404, {"error": "not found"})


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="cctqa ui-app")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--host", default="127.0.0.1")
    a = p.parse_args(argv)
    print(f"AC Test Management UI -> http://{a.host}:{a.port}/  (Ctrl-C to stop)")
    try:
        ThreadingHTTPServer((a.host, a.port), H).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


_PAGE = r"""<!doctype html><html><head><meta charset=utf-8><title>AC Test Management</title>
<style>
:root{--ac:#d0021b;--bg:#0f172a;--pnl:#1e293b;--bd:#334155;--tx:#e2e8f0;--mut:#94a3b8}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--tx)}
header{background:#111827;border-bottom:2px solid var(--ac);padding:12px 20px;display:flex;align-items:center;gap:16px}
header h1{font-size:17px;margin:0}header .sel{margin-left:auto;display:flex;gap:8px;align-items:center}
select,input{background:#0f172a;color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:6px 8px;font-size:13px}
nav{display:flex;gap:2px;background:#111827;padding:0 20px;border-bottom:1px solid var(--bd)}
nav button{background:none;border:0;color:var(--mut);padding:11px 16px;cursor:pointer;font-size:14px;border-bottom:2px solid transparent}
nav button.on{color:#fff;border-bottom-color:var(--ac)}
main{padding:20px;max-width:1400px;margin:0 auto}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.card{background:var(--pnl);border:1px solid var(--bd);border-radius:10px;padding:14px 18px;min-width:130px}
.card b{font-size:26px;display:block}.card span{color:var(--mut);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--pnl);border-radius:8px;overflow:hidden}
th,td{border-bottom:1px solid var(--bd);padding:7px 10px;text-align:left}th{background:#0f172a;position:sticky;top:0;font-size:12px}
button.act{background:var(--ac);color:#fff;border:0;border-radius:6px;padding:7px 13px;cursor:pointer;font-size:13px}
button.act:hover{filter:brightness(1.1)}button.gh{background:var(--bd)}button:disabled{opacity:.4;cursor:not-allowed}
.pass{color:#4ade80}.fail{color:#f87171}.mut{color:var(--mut)}
.pill{padding:1px 8px;border-radius:9px;font-size:11px}.pill.Seeded{background:#065f46}.pill.No{background:#7c2d12}
.pill.Passed{background:#065f46}.pill.Failed{background:#7f1d1d}.pill.Not{background:#334155}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
#log{background:#020617;border:1px solid var(--bd);border-radius:8px;padding:12px;font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap;max-height:260px;overflow:auto;margin-top:12px}
.filt{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
</style></head><body>
<header><h1>✈ Air Canada — Test Data Management &amp; Execution</h1>
<div class=sel>
 <select id=fProduct onchange=reload()></select>
 <select id=fEnv onchange=reload()></select>
 <select id=fType onchange=reload()></select>
 <select id=fFlow onchange=reload()></select>
</div></header>
<nav id=nav></nav>
<main id=main></main>
<script>
const S={product:'bravo',env:'int',type:'UAT',feed:'fd',cat:[],sel:new Set(),tab:'Dashboard',lastClone:null};
const TABS=['Dashboard','Test Cases','Test Data','Execution','Reports','Analytics'];
const $=s=>document.querySelector(s), el=(h)=>{const d=document.createElement('div');d.innerHTML=h;return d.firstElementChild};
async function jget(u){return (await fetch(u)).json()}
async function jpost(u,b){return (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json()}
function q(){return `product=${S.product}&env=${S.env}&feed=${S.feed}`}

async function boot(){
 const r=await jget('/api/registry');
 $('#fProduct').innerHTML=r.products.map(p=>`<option>${p}</option>`).join('');
 $('#fEnv').innerHTML=r.envs.map(e=>`<option>${e}</option>`).join('');
 $('#fType').innerHTML=r.types.map(t=>`<option>${t}</option>`).join('');
 $('#fFlow').innerHTML=r.flows.map(f=>`<option value=${f.id}>${f.label}</option>`).join('');
 $('#fProduct').value=S.product;$('#fEnv').value=S.env;$('#fFlow').value=S.feed;
 $('#nav').innerHTML=TABS.map(t=>`<button class="${t==S.tab?'on':''}" onclick="go('${t}')">${t}</button>`).join('');
 reload();
}
function go(t){S.tab=t;$('#nav').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.textContent==t));render()}
function reload(){S.product=$('#fProduct').value;S.env=$('#fEnv').value;S.type=$('#fType').value;S.feed=$('#fFlow').value;S.sel.clear();render()}

async function render(){
 const m=$('#main');m.innerHTML='<div class=mut>Loading…</div>';
 if(S.tab=='Dashboard')return renderDash(m);
 if(S.tab=='Test Cases')return renderCases(m);
 if(S.tab=='Test Data')return renderData(m);
 if(S.tab=='Execution')return renderExec(m);
 if(S.tab=='Reports')return renderReports(m);
 if(S.tab=='Analytics')return renderAnalytics(m);
}
async function renderAnalytics(m){
 const runs=await jget('/api/reports?feed='+S.feed);
 if(!runs.length){m.innerHTML='<div class=mut>No runs yet — execute a flow first.</div>';return}
 m.innerHTML=`<div class=bar>Analytics &amp; metrics for run
   <select id=anRun onchange=drawAnalytics()>${runs.map(r=>`<option value="${r.path}">${r.name} (${r.passed}✓/${r.failed}✗)</option>`).join('')}</select>
   <span id=anMetaBtn style=margin-left:auto></span></div>
   <div id=anBody class=mut>Loading…</div>`;
 drawAnalytics();
}
async function drawAnalytics(){
 const run=$('#anRun').value, a=await jget('/api/analytics?run='+run);
 $('#anMetaBtn').innerHTML=a.has_metrics?`<button class="act gh" onclick="window.open('/r/${run}/metrics/report.html')">Open full metrics report ↗</button>`:'<span class=mut>metrics/analysis not generated (run Full pipeline)</span>';
 const bar=(o,color)=>{const tot=Object.values(o||{}).reduce((s,v)=>s+v,0)||1;
   return Object.entries(o||{}).sort((x,y)=>y[1]-x[1]).map(([k,v])=>`<div style=margin:3px 0><span style=display:inline-block;width:190px>${k}</span>
   <span style="display:inline-block;height:14px;width:${Math.round(300*v/tot)}px;background:${color};vertical-align:middle;border-radius:3px"></span> <b>${v}</b></div>`).join('')};
 const funnel=Object.entries(a.stage_coverage||{}).map(([k,v])=>`<tr><td>${k}</td><td>${Math.round((v.rate||0)*100)}%</td>
   <td><span style="display:inline-block;height:10px;width:${Math.round(240*(v.rate||0))}px;background:#d0021b;border-radius:3px"></span></td></tr>`).join('');
 $('#anBody').innerHTML=`
  <div style=display:grid;grid-template-columns:1fr 1fr;gap:20px>
   <div><h3>Decision mix</h3>${bar(a.decisions,'#2563eb')}</div>
   <div><h3>Grade mix (P6)</h3>${bar(a.grades,'#7c3aed')}</div>
  </div>
  <h3 style=margin-top:20px>Business-flow trajectory ${a.stage_coverage?'':'<span class=mut>(run Full pipeline to populate)</span>'}</h3>
  ${funnel?`<table style=max-width:600px><tr><th>Stage</th><th>%</th><th></th></tr>${funnel}</table>`:'<div class=mut>No trajectory metrics for this run.</div>'}
  ${a.clusters&&a.clusters.length?`<h3 style=margin-top:20px>Failure clusters</h3><table><tr><th>Count</th><th>Reason</th></tr>${a.clusters.map(c=>`<tr><td>${c.count}</td><td>${c.reason}</td></tr>`).join('')}</table>`:''}`;
}
async function renderDash(m){
 const d=await jget('/api/dashboard?'+q());
 if(d.error){m.innerHTML=`<div class=fail>Error: ${d.error}</div>`;return}
 m.innerHTML=`<div class=cards>
  <div class=card><b>${d.total}</b><span>Total test cases</span></div>
  <div class=card><b>${d.seeded}</b><span>With test data</span></div>
  <div class=card><b>${d.no_data}</b><span>Without data</span></div>
  <div class=card><b>${d.seed_pct}%</b><span>Data-seeding complete</span></div>
  <div class=card><b class=pass>${d.passed}</b><span>Passed</span></div>
  <div class=card><b class=fail>${d.failed}</b><span>Failed</span></div>
  <div class=card><b>${d.not_run}</b><span>Not run</span></div>
  <div class=card><b>${d.pass_pct}%</b><span>Pass rate</span></div>
 </div>
 <h3>Expected outcome mix</h3><table><tr><th>Verdict</th><th>Count</th></tr>
 ${Object.entries(d.by_status).map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('')}</table>`;
}
async function renderCases(m){
 S.cat=await jget('/api/catalog?'+q());
 if(S.cat[0]&&S.cat[0].error){m.innerHTML=`<div class=fail>${S.cat[0].error}</div>`;return}
 m.innerHTML=`<div class=filt>
   <input id=fId placeholder="Test case ID…" oninput=drawCases()>
   <select id=fStatus onchange=drawCases()><option value="">All verdicts</option>
     ${[...new Set(S.cat.map(c=>c.status))].map(s=>`<option>${s}</option>`).join('')}</select>
   <select id=fData onchange=drawCases()><option value="">All data</option><option>Seeded</option><option>No Data</option></select>
   <span class=mut id=selInfo></span>
   <span style="margin-left:auto"></span>
   <button class="act gh" onclick=selAll()>Select all filtered</button>
   <button class=act onclick=seedSel()>Seed selected ▶</button>
 </div>
 <div id=confirm></div>
 <table id=ctab></table><div id=log style="display:none"></div>`;
 drawCases();
}
function filtered(){
 const id=($('#fId').value||'').toLowerCase(),st=$('#fStatus').value,dt=$('#fData').value;
 return S.cat.filter(c=>(!id||c.id.toLowerCase().includes(id))&&(!st||c.status==st)&&(!dt||c.data_status==dt));
}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function drawCases(){
 const rows=filtered();
 $('#selInfo').textContent=`${S.sel.size} selected · ${rows.length} shown · ${S.cat.length} total`;
 $('#ctab').innerHTML=`<tr><th></th><th>Test Case</th><th>Scenario (UAT)</th><th>Expected</th><th>systemCode</th><th>Amount</th><th>Data</th><th>Last Run</th><th></th></tr>`+
  rows.map((c,i)=>`<tr><td><input type=checkbox ${S.sel.has(c.id)?'checked':''} onchange=tog('${c.id}',this.checked)></td>
   <td><b>${c.id}</b>${c.third_party?' 👤':''}</td>
   <td style=max-width:320px>${esc(c.name)}</td>
   <td><b>${c.status}</b></td><td class=mut style=font-size:11px>${c.system_code}</td>
   <td>${c.amount||'—'}</td>
   <td><span class="pill ${c.data_status=='Seeded'?'Seeded':'No'}">${c.data_status}</span></td>
   <td><span class="pill ${c.exec_status.replace(' ','')}">${c.exec_status}</span></td>
   <td><button class="act gh" onclick=det('${c.id}',${i})>Details ▾</button></td></tr>
   <tr id=det_${i} style=display:none><td colspan=9 style=background:#0f172a></td></tr>`).join('');
}
function det(id,i){
 const row=$('#det_'+i);if(row.style.display!='none'){row.style.display='none';return}
 const c=S.cat.find(x=>x.id==id);row.style.display='table-row';
 const tr=(c.expected_transcript||[]).map(t=>`<div><b class=mut>${t.role}:</b> ${esc(t.text)}</div>`).join('');
 row.firstElementChild.innerHTML=`<div style=padding:6px 10px>
   <div style=display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;margin-bottom:8px>
     <div><span class=mut>Scenario:</span> <b>${esc(c.name)}</b></div>
     <div><span class=mut>Expected verdict:</span> <b>${c.status}</b></div>
     <div><span class=mut>systemCode:</span> ${c.system_code}</div>
     <div><span class=mut>Expected amount:</span> ${c.amount||'— (none)'}</div>
     <div><span class=mut>Regime:</span> ${c.regime||''} &nbsp; <span class=mut>Group:</span> ${c.group||''} &nbsp; <span class=mut>Scenario type:</span> ${c.scenario||''}</div>
     <div><span class=mut>Route:</span> ${c.route||''} &nbsp; <span class=mut>3rd-party:</span> ${c.third_party?'Yes':'No'}</div>
   </div>
   ${c.detail?`<div style=margin-bottom:8px><span class=mut>UAT gap-doc spec:</span><br>${esc(c.detail)}</div>`:''}
   ${c.intent?`<div style=margin-bottom:8px><span class=mut>Customer intent:</span> ${esc(c.intent)}</div>`:''}
   ${tr?`<div><span class=mut>Expected conversation:</span>${tr}</div>`:''}
 </div>`;
}
function tog(id,on){on?S.sel.add(id):S.sel.delete(id);drawCases()}
function selAll(){filtered().forEach(c=>S.sel.add(c.id));drawCases()}
async function seedSel(){
 if(!S.sel.size){alert('Select at least one test case');return}
 const ids=[...S.sel];
 $('#confirm').innerHTML=`<div class=card style=margin-bottom:12px>
   <b style=font-size:15px>Confirm seeding</b><br>
   <span class=mut>Cases: <b>${ids.length}</b> · Product <b>${S.product}</b> · Env <b>${S.env}</b> · Type <b>${S.type}</b> · Flow <b>${S.feed}</b> · Est. records: <b>${ids.length*4}</b> Kafka + ${ids.length} DDS</span><br><br>
   <button class=act onclick="doSeed(${JSON.stringify(ids).replace(/"/g,'&quot;')})">Confirm &amp; start seeding</button>
   <button class="act gh" onclick="$('#confirm').innerHTML=''">Cancel</button></div>`;
}
async function doSeed(ids){
 $('#confirm').innerHTML='';const lg=$('#log');lg.style.display='block';lg.textContent='Starting seed…';
 const r=await jpost('/api/seed',{product:S.product,env:S.env,feed:S.feed,ids});
 if(r.error){lg.textContent='ERROR: '+r.error;return}
 poll(r.job,lg,()=>{drawCases();renderCases($('#main'))});
}
async function renderData(m){
 const d=await jget('/api/testdata?'+q());
 m.innerHTML=`<div class=bar><b>${d.length}</b> test-data records — ${S.feed}/${S.product}/${S.env}</div>
  <table><tr><th>Data ID (PNR)</th><th>Test Case</th><th>Passenger</th><th>systemCode</th><th>Flight date</th><th>Created (UTC)</th><th>Status</th><th>Set</th></tr>
  ${d.map(r=>`<tr><td><b>${r.data_id||''}</b></td><td>${r.case_id||''}</td><td>${r.passenger}</td>
   <td class=mut style=font-size:11px>${r.system_code||''}</td><td>${r.date||''}</td><td>${r.created_utc}</td>
   <td><span class="pill Seeded">${r.status}</span></td><td class=mut style=font-size:11px>${r.set}</td></tr>`).join('')}</table>`;
}
async function renderExec(m){
 const d=await jget('/api/testdata?'+q());
 const sets=[...new Set(d.map(r=>r.set))];
 m.innerHTML=`<div class=bar>Run the bot against a seeded set — validates data belongs to ${S.env}/${S.feed}.
   <span style=margin-left:auto></span>
   <select id=exSet>${sets.map(s=>`<option>${s}</option>`).join('')||'<option>— seed data first —</option>'}</select>
   <label class=mut><input type=checkbox id=exPipe checked> + metrics/analysis</label>
   <button class=act onclick=doRun()>Run ▶</button></div>
   <div id=log style="display:none"></div>`;
}
async function doRun(){
 const set=$('#exSet').value;if(!set||set.startsWith('—')){alert('Seed data first');return}
 const lg=$('#log');lg.style.display='block';lg.textContent='Starting run…';
 const r=await jpost('/api/run',{product:S.product,env:S.env,feed:S.feed,clone:'runs/seed/'+set,pipeline:$('#exPipe').checked});
 if(r.error){lg.textContent='ERROR: '+r.error;return}
 poll(r.job,lg,null);
}
async function renderReports(m){
 const runs=await jget('/api/reports?feed='+S.feed);
 const dl=`/download?feed=${S.feed}&scope=all`;
 m.innerHTML=`<div class=bar><b>${runs.length}</b> execution runs — ${S.feed}
   <span style=margin-left:auto></span>
   <span class=mut>Bulk (all runs):</span>
   <button class=act onclick="location.href='${dl}&kind=all'">Everything ⬇</button>
   <button class="act gh" onclick="location.href='${dl}&kind=evidence'">All evidence ⬇</button>
   <button class="act gh" onclick="location.href='${dl}&kind=reports'">All HTML reports ⬇</button></div>
  <table><tr><th>Run</th><th>When (UTC)</th><th>Cases</th><th>Passed</th><th>Failed</th><th>View</th><th>Download</th></tr>
  ${runs.map((r,i)=>`<tr><td><b>${r.name}</b></td><td>${r.utc}</td><td>${r.cases}</td>
   <td class=pass>${r.passed}</td><td class=fail>${r.failed}</td>
   <td>${r.has_index?`<button class="act gh" onclick="window.open('/r/${r.path}/index.html')">Index</button>`:''}
   ${r.has_metrics?`<button class="act gh" onclick="window.open('/r/${r.path}/metrics/report.html')">Metrics</button>`:''}
   <button class="act gh" onclick="cases('${r.path}',${i})">Cases ▾</button></td>
   <td><button class=act onclick="location.href='/download?run=${r.path}&kind=all'">All ⬇</button>
   <button class="act gh" onclick="location.href='/download?run=${r.path}&kind=evidence'">Evidence ⬇</button>
   <button class="act gh" onclick="location.href='/download?run=${r.path}&kind=quality'">Quality ⬇</button></td></tr>
   <tr id=rc_${i} style=display:none><td colspan=7></td></tr>`).join('')}</table>`;
}
async function cases(path,i){
 const row=$('#rc_'+i);if(row.style.display!='none'){row.style.display='none';return}
 row.style.display='table-row';row.firstElementChild.innerHTML='<span class=mut>loading…</span>';
 const cs=await jget('/api/runcases?run='+path);
 row.firstElementChild.innerHTML=`<table style=margin:4px 0>
  <tr><th>Case</th><th>Result</th><th>Expected</th><th>Actual</th><th>Evidence</th><th>Download</th></tr>
  ${cs.map(c=>`<tr><td>${c.id}</td><td class="${c.result=='Passed'?'pass':'fail'}">${c.result}</td>
   <td>${c.expected}</td><td>${c.actual}</td>
   <td>${c.evidence?`<button class="act gh" onclick="window.open('/r/${c.evidence}')">View evidence</button>`:''}
   ${c.quality?`<button class="act gh" onclick="window.open('/r/${c.quality}')">View quality</button>`:''}</td>
   <td>${c.evidence?`<button class=act onclick="location.href='/download?file=${c.evidence}'">Evidence ⬇</button>`:''}
   ${c.quality?`<button class="act gh" onclick="location.href='/download?file=${c.quality}'">Quality ⬇</button>`:''}</td></tr>`).join('')}</table>`;
}
function poll(job,lg,done){
 const t=setInterval(async()=>{
  const j=await jget('/api/job?id='+job);
  lg.textContent=(j.log||[]).join('\n');lg.scrollTop=lg.scrollHeight;
  if(j.status=='done'||j.status=='error'){clearInterval(t);lg.textContent+='\n=== '+j.status.toUpperCase()+' ===';if(done)done()}
 },1500);
}
boot();
</script></body></html>"""


if __name__ == "__main__":
    main()
