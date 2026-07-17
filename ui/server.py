"""Local operator control panel — a small stdlib HTTP server behind the dashboard so the buttons can
actually DO things (a static HTML file can't run a test). Three actions:

  * Load existing data  — list already-seeded fixture sets under runs/seed/ (no re-seed needed)
  * Run test            — drive the bot against a chosen seeded set (background subprocess, live log)
  * Download reports    — zip a completed run folder's HTML/JSON reports

No external deps (http.server + zipfile + subprocess). Run it with:  python -m ui.server
then open http://127.0.0.1:8765/ . The run subprocess inherits THIS process's environment, so start
the server from a shell that already has AWS_PROFILE / DDS_API_KEY / MAILINATOR_TOKEN exported.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SEED_ROOT = ROOT / "runs" / "seed"
RESULTS_ROOT = ROOT / "results"

# in-memory job registry: job_id -> {status, log[], run_dir, returncode}
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


# ── data discovery ────────────────────────────────────────────────────────────
def _seed_sets() -> list:
    """Every seeded fixture set under runs/seed/, newest first, with its case count."""
    out = []
    if SEED_ROOT.is_dir():
        for d in sorted(SEED_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            metas = list(d.glob("*/meta.json"))
            if not metas:
                continue
            out.append({"name": d.name, "path": str(d.relative_to(ROOT)).replace("\\", "/"),
                        "cases": len(metas), "mtime": int(d.stat().st_mtime)})
    return out


def _runs() -> list:
    """Every completed run folder under results/<date>/<cell>/, newest first, with PASS/FAIL tallies."""
    out = []
    if RESULTS_ROOT.is_dir():
        for datedir in sorted(RESULTS_ROOT.iterdir(), reverse=True):
            if not datedir.is_dir():
                continue
            for run in sorted(datedir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if not run.is_dir():
                    continue
                results = list(run.glob("*.result.json"))
                if not results and not (run / "index.html").exists():
                    continue
                p = f = 0
                for r in results:
                    try:
                        d = json.loads(r.read_text(encoding="utf-8"))
                        ok = d.get("verdict", {}).get("matches_expected")
                        p, f = (p + 1, f) if ok else (p, f + 1)
                    except Exception:
                        pass
                out.append({"name": run.name, "path": str(run.relative_to(ROOT)).replace("\\", "/"),
                            "cases": len(results), "passed": p, "failed": f,
                            "has_index": (run / "index.html").exists(),
                            "has_metrics": (run / "metrics" / "report.html").exists(),
                            "mtime": int(run.stat().st_mtime)})
    return out


def _cases(run_rel: str) -> list:
    """Per-case report links for a run folder: test-case id + whether evidence/quality HTML exist."""
    run = (ROOT / run_rel).resolve()
    out = []
    if str(run).startswith(str(RESULTS_ROOT.resolve())) and run.is_dir():
        for res in sorted(run.glob("*.result.json")):
            cid = res.name[: -len(".result.json")]
            ev = run / f"{cid}.evidence.html"
            ql = run / f"{cid}.quality.html"
            verdict = ""
            try:
                d = json.loads(res.read_text(encoding="utf-8"))
                verdict = "PASS" if d.get("verdict", {}).get("matches_expected") else "FAIL"
            except Exception:
                pass
            out.append({"id": cid, "verdict": verdict,
                        "evidence": f"{run_rel}/{ev.name}" if ev.exists() else None,
                        "quality": f"{run_rel}/{ql.name}" if ql.exists() else None})
    return out


def _cell_axes(seed_name: str) -> tuple:
    """Best-effort (product, env, feed) from a seed dir name like 'fd_bravo_int_...'; default bravo/int/fd."""
    toks = seed_name.split("_")
    feeds = {"fd", "soc", "nc", "anc", "baggage", "seatchange", "bookingchange", "nonmvp"}
    envs = {"int", "crt", "bat"}
    prods = {"bravo"}
    feed = next((t for t in toks if t in feeds), "fd")
    env = next((t for t in toks if t in envs), "int")
    prod = next((t for t in toks if t in prods), "bravo")
    return prod, env, feed


# ── run job ───────────────────────────────────────────────────────────────────
def _exec(job_id: str, cmd: list, push) -> int:
    """Run one CLI subprocess, streaming its output into the job log. Returns the exit code."""
    push(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    for line in proc.stdout:
        push(line)
        if "-> results" in line:  # capture the run folder the run CLI announces
            frag = line.split("-> ", 1)[-1].strip().replace("\\", "/")
            with _JOBS_LOCK:
                _JOBS[job_id]["run_dir"] = frag
    proc.wait()
    push(f"[exit {proc.returncode}]")
    return proc.returncode


def _run_job(job_id: str, fixtures: str, product: str, env: str, feed: str, only: list, conc: int,
             pipeline: bool):
    def push(line: str):
        with _JOBS_LOCK:
            _JOBS[job_id]["log"].append(line.rstrip("\n"))

    try:
        run_cmd = [sys.executable, "-m", "core.cli", "run", product, env, feed, "--fixtures", fixtures,
                   "--conc", str(conc), "--otp-conc", str(max(1, conc // 2))]
        if only:
            run_cmd += ["--only", *only]
        rc = _exec(job_id, run_cmd, push)
        with _JOBS_LOCK:
            run_dir = _JOBS[job_id]["run_dir"]
        # full pipeline: chain metrics + analysis over the run folder the bot just produced
        if pipeline and rc == 0 and run_dir:
            push("\n--- metrics ---")
            _exec(job_id, [sys.executable, "-m", "core.cli", "metrics", run_dir], push)
            push("\n--- analysis ---")
            _exec(job_id, [sys.executable, "-m", "core.cli", "analyze", run_dir], push)
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done" if rc == 0 else "error"
            _JOBS[job_id]["returncode"] = rc
    except Exception as exc:  # noqa: BLE001
        push(f"[FAILED] {type(exc).__name__}: {exc}")
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"


def _start_run(fixtures: str, only: list, conc: int, pipeline: bool) -> str:
    seed_name = Path(fixtures).name
    product, env, feed = _cell_axes(seed_name)
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "running", "log": [], "run_dir": None, "returncode": None,
                         "fixtures": fixtures}
    threading.Thread(target=_run_job,
                     args=(job_id, fixtures, product, env, feed, only, conc, pipeline),
                     daemon=True).start()
    return job_id


# ── report zip ────────────────────────────────────────────────────────────────
def _zip_run(run_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in run_dir.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(run_dir.parent))
    return buf.getvalue()


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, _PAGE, "text/html; charset=utf-8")
        if u.path == "/api/seeds":
            return self._send(200, _seed_sets())
        if u.path == "/api/runs":
            return self._send(200, _runs())
        if u.path == "/api/cases":
            return self._send(200, _cases(q.get("run", [""])[0]))
        if u.path == "/api/job":
            with _JOBS_LOCK:
                j = _JOBS.get(q.get("id", [""])[0])
                return self._send(200, dict(j) if j else {"status": "unknown"})
        if u.path == "/download":
            rel = q.get("run", [""])[0]
            run_dir = (ROOT / rel).resolve()
            if not str(run_dir).startswith(str(RESULTS_ROOT.resolve())) or not run_dir.is_dir():
                return self._send(404, {"error": "run not found"})
            data = _zip_run(run_dir)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{run_dir.name}_reports.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if u.path.startswith("/r/"):
            # serve any file under results/ or runs/seed/ at its real relative path, so relative links
            # INSIDE a report (index.html -> FD_..evidence.html, metrics/report.html) resolve correctly.
            import mimetypes
            rel = u.path[len("/r/"):]
            f = (ROOT / rel).resolve()
            allowed = str(f).startswith(str(RESULTS_ROOT.resolve())) or str(f).startswith(str(SEED_ROOT.resolve()))
            if not allowed or not f.is_file():
                return self._send(404, {"error": "not found: " + rel})
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype == "application/json":
                ctype += "; charset=utf-8"
            return self._send(200, f.read_bytes(), ctype)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if u.path == "/api/run":
            fixtures = body.get("fixtures", "")
            fdir = (ROOT / fixtures).resolve()
            if not str(fdir).startswith(str(SEED_ROOT.resolve())) or not fdir.is_dir():
                return self._send(400, {"error": "invalid fixtures dir"})
            only = [x for x in (body.get("only") or []) if x]
            conc = int(body.get("conc") or 4)
            pipeline = bool(body.get("pipeline"))
            return self._send(200, {"job": _start_run(fixtures, only, conc, pipeline)})
        return self._send(404, {"error": "not found"})


_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>CCT QA — Control Panel</title>
<style>
 body{font-family:system-ui,Segoe UI,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
 header{background:#1e293b;padding:14px 22px;border-bottom:1px solid #334155}
 header h1{margin:0;font-size:18px}
 .wrap{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:22px;max-width:1200px;margin:0 auto}
 .card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px}
 .card h2{margin:0 0 12px;font-size:15px;color:#93c5fd}
 .row{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border:1px solid #334155;border-radius:8px;margin-bottom:8px}
 .row .meta{font-size:12px;color:#94a3b8}
 button{background:#2563eb;color:#fff;border:0;border-radius:7px;padding:7px 12px;cursor:pointer;font-size:13px}
 button:hover{background:#1d4ed8}
 button.ghost{background:#334155}
 button.ghost:hover{background:#475569}
 .pass{color:#4ade80}.fail{color:#f87171}
 #log{grid-column:1/3;background:#020617;border:1px solid #334155;border-radius:12px;padding:14px;font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap;max-height:340px;overflow:auto;min-height:80px}
 .muted{color:#64748b;font-size:12px}
 select,input{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:5px}
</style></head><body>
<header><h1>CCT QA — Control Panel <span class=muted>bravo · int · fd</span></h1></header>
<div class=wrap>
 <div class=card>
   <h2>1 · Load existing seeded data</h2>
   <div class=muted style=margin-bottom:8px>Pick an already-seeded fixture set (no re-seed). Optional case filter (locators, comma-sep).</div>
   <div id=seeds></div>
 </div>
 <div class=card>
   <h2>2 · Completed runs — view / download reports</h2>
   <div id=runs></div>
 </div>
 <div id=log>Ready. Load a seeded set on the left and press <b>Run test ▶</b>.</div>
</div>
<script>
const $=s=>document.querySelector(s), log=$('#log');
function line(t){log.textContent+='\\n'+t; log.scrollTop=log.scrollHeight;}
async function loadSeeds(){
  const s=await (await fetch('/api/seeds')).json();
  $('#seeds').innerHTML = s.map(x=>`<div class=row><div><b>${x.name}</b><div class=meta>${x.cases} case(s)</div></div>
    <div><input id="only_${x.name}" placeholder="all cases" size=10>
    <button onclick="runIt('${x.path}','${x.name}',false)">Run test ▶</button>
    <button onclick="runIt('${x.path}','${x.name}',true)" title="run → metrics → analysis">Full pipeline ▶▶</button></div></div>`).join('') || '<div class=muted>No seeded sets under runs/seed/</div>';
}
async function loadRuns(){
  const r=await (await fetch('/api/runs')).json();
  $('#runs').innerHTML = r.map((x,i)=>`<div class=row><div><b>${x.name}</b>
    <div class=meta><span class=pass>${x.passed} PASS</span> · <span class=fail>${x.failed} FAIL</span> · ${x.cases} case(s)</div></div>
    <div>${x.has_index?`<button class=ghost onclick="window.open('/r/${x.path}/index.html')">View</button>`:''}
    ${x.has_metrics?`<button class=ghost onclick="window.open('/r/${x.path}/metrics/report.html')">Metrics</button>`:''}
    <button class=ghost onclick="toggleCases('${x.path}',${i})">Cases ▾</button>
    <button onclick="location.href='/download?run=${x.path}'">Download all ⬇</button></div></div>
    <div id="cases_${i}" style="display:none;margin:-4px 0 10px 12px"></div>`).join('') || '<div class=muted>No runs yet</div>';
}
async function toggleCases(path,i){
  const box=$('#cases_'+i);
  if(box.style.display!=='none'){box.style.display='none';return;}
  box.style.display='block'; box.innerHTML='<span class=muted>loading…</span>';
  const cs=await (await fetch('/api/cases?run='+path)).json();
  box.innerHTML = cs.map(c=>`<div class=row style=padding:4px 8px><div><b>${c.id}</b>
    <span class="${c.verdict==='PASS'?'pass':'fail'}" style=font-size:11px>${c.verdict}</span></div>
    <div>${c.evidence?`<button class=ghost onclick="window.open('/r/${c.evidence}')">Evidence</button>`:''}
    ${c.quality?`<button class=ghost onclick="window.open('/r/${c.quality}')">Quality</button>`:''}</div></div>`).join('')
    || '<span class=muted>no cases</span>';
}
async function runIt(path,name,pipeline){
  const only=($('#only_'+name).value||'').split(',').map(s=>s.trim()).filter(Boolean);
  log.textContent=(pipeline?'Starting FULL PIPELINE (run → metrics → analysis) over ':'Starting run over ')+path+' ...';
  const r=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({fixtures:path,only,pipeline})})).json();
  if(r.error){line('ERROR: '+r.error);return;}
  poll(r.job);
}
async function poll(job){
  let n=0;
  const t=setInterval(async()=>{
    const j=await (await fetch('/api/job?id='+job)).json();
    log.textContent=j.log.join('\\n'); log.scrollTop=log.scrollHeight;
    if(j.status==='done'||j.status==='error'){clearInterval(t);
      line('\\n=== '+j.status.toUpperCase()+(j.run_dir?' · '+j.run_dir:'')+' ===');
      loadRuns();}
  },1500);
}
loadSeeds();loadRuns();
</script></body></html>"""


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="cctqa serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CCT QA control panel -> http://{args.host}:{args.port}/  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
