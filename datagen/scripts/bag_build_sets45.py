#!/usr/bin/env python3
"""Driver: build Baggage CRT sets 4 & 5 end-to-end, sequentially.

Sequential is REQUIRED: each set's passenger names must already be in the DB before the
next set's `index` runs, so crt_uniqnames.fresh_pool DB-filters them out -> disjoint names.

Per set: index -> publish -> wait cascade -> finalize -> EDS-gap repair -> checkpoints.
The EDS service occasionally drops a PNR's eds_pnr_output; re-publishing that single PNR
re-triggers it (lands in ~10s).

Usage: AWS_PROFILE=ac-cct-crt python3 bag_build_sets45.py
"""
import os, sys, json, time, subprocess, psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = "/tmp/cctqa-datagen"
WORK = f"{SCR}/bag_work"
TODAY = "2026-07-12"
os.makedirs(WORK, exist_ok=True)

SETS = [
    dict(name="set4", seed="747474", tprefix="014308", out=f"{WORK}/_BAG_crt_index_set4.json"),
    dict(name="set5", seed="858585", tprefix="014309", out=f"{WORK}/_BAG_crt_index_set5.json"),
]
TT = dict(host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
          db="trip-tracer", user="dbadmin", password=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""))

def log(m): print(m, flush=True)
def conn(): return psycopg2.connect(host=TT["host"], port=5432, dbname=TT["db"], user=TT["user"],
                                    password=TT["password"], sslmode="require", connect_timeout=25)

def env_for(s):
    e = dict(os.environ)
    e.update(CRT_UNIQ_NAMES="1", BAG_TODAY=TODAY, BAG_WORK=WORK,
             BAG_SEED=s["seed"], BAG_TPREFIX=s["tprefix"], BAG_OUT=s["out"],
             AWS_PROFILE=e.get("AWS_PROFILE", "ac-cct-crt"))
    return e

def run(s, phase, extra=None):
    cmd = ["python3", "-u", f"{HERE}/bag_crt_build.py", phase] + (extra or [])
    p = subprocess.run(cmd, env=env_for(s), capture_output=True, text=True, cwd=HERE)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out

def ids_of(s): return [r["pnr_id"] for r in json.load(open(s["out"]))]

def count(sql, ids):
    c = conn(); cur = c.cursor(); cur.execute(sql, (ids,)); n = cur.fetchone()[0]; c.close(); return n

def missing_eds(ids):
    c = conn(); cur = c.cursor()
    cur.execute("SELECT DISTINCT pnr_id FROM eds_pnr_output WHERE pnr_id=ANY(%s)", (ids,))
    have = {r[0] for r in cur.fetchall()}; c.close()
    return [p for p in ids if p not in have]

def build(s):
    log(f"\n{'='*70}\n### {s['name'].upper()}  seed={s['seed']} tickets={s['tprefix']} TODAY={TODAY}\n{'='*70}")
    rc, o = run(s, "index"); log(o.strip())
    if rc: log("INDEX FAILED"); return False
    ids = ids_of(s); n = len(ids)

    rc, o = run(s, "publish")
    log([l for l in o.splitlines() if l.startswith("[publish]")][-1:] or o[-300:])

    # wait cascade
    for i in range(90):
        c = count("select count(distinct pnr_id) from trip where pnr_id=any(%s)", ids)
        if c >= n: log(f"[cascade] {c}/{n}"); break
        time.sleep(10)
    else:
        log(f"[cascade] TIMEOUT at {c}/{n}"); return False

    rc, o = run(s, "finalize")
    log([l for l in o.splitlines() if l.startswith("[finalize]")][-1:] or o[-300:])

    # EDS-gap repair
    for rnd in range(4):
        miss = missing_eds(ids)
        if not miss: log("[eds] all present"); break
        log(f"[eds] round {rnd}: {len(miss)} missing -> re-publishing {miss}")
        idx = {p: i for i, p in enumerate(ids)}
        for p in miss:
            i = idx[p]
            run(s, "publish", ["--start", str(i), "--end", str(i + 1)])
        time.sleep(25)
    else:
        log(f"[eds] STILL MISSING: {missing_eds(ids)}")

    # checkpoints
    p = subprocess.run(["python3", "-u", f"{HERE}/bag_checkpoints.py", s["out"]],
                       env=env_for(s), capture_output=True, text=True, cwd=HERE)
    log(f"--- CHECKPOINTS {s['name']} ---")
    log((p.stdout or "") + (p.stderr or ""))
    return p.returncode == 0

if __name__ == "__main__":          # guard so importing this as a lib (e.g. bag_build_set6) doesn't re-run
    ok = True
    for s in SETS:
        if not build(s):
            ok = False
            log(f"!!! {s['name']} did not fully pass")
    log("\nALL_DONE ok=" + str(ok))
