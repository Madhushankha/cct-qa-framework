"""Verify seeded DDS determinations against the UAT gap doc — from the DDS endpoint, NOT the bot.

For every fixture in a clone dir, GET the live DDS determination (`by_pnr_url/{pnrId}`) and compare its
verdict / systemCode / amount against the gap-doc expected for that test case. This proves the SEED is
correct independently of the chatbot (the bot can escalate a perfectly-good determination for its own
reasons; this checks the data we injected). Usage:

    python -m seed.verify_uat <clone_dir> [--product bravo --env int --feed fd]
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from catalog.parser import load_catalog
from core.registry import resolve
from seed.dds_pin import parse_system_code

_CLASS_STATUS = {"EL": "ELIGIBLE", "DB": "ELIGIBLE", "NE": "NOT_ELIGIBLE",
                 "ND": "NO_DETERMINATION", "PE": "PENDING"}


def _dds_get(env, pnr_id: str) -> dict | None:
    dds = env.seed_targets["dds"]
    url = dds["by_pnr_url"].rstrip("/") + "/" + pnr_id
    req = urllib.request.Request(url, headers={"x-api-key": dds.get("api_key") or ""})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _winning_pe(dds: dict) -> dict:
    """The real determination entry — the passengerEligibility whose systemCode is NOT a -NA- filler
    (that's the regime the verdict actually landed on). Falls back to the first entry."""
    first = {}
    for c in dds.get("compensationEligibility", []):
        for pe in c.get("passengerEligibility", []):
            first = first or pe
            sc = str(pe.get("systemCode") or "")
            if "-NA-" not in sc:
                return {**pe, "_regime_delayMinutes": c.get("delayMinutes")}
    return first


def _dds_amount(pe: dict):
    cd = pe.get("compensationDetails") or {}
    v = cd.get("amount")
    return float(v) if isinstance(v, (int, float)) and v else None


def verify_clone(clone_dir: str, product: str, env: str, feed: str) -> dict:
    ctx = resolve(product, env, feed)
    cat = load_catalog(ctx.feed)
    by_id = {c.id: c for c in cat.cases}

    rows, npass, nfail = [], 0, 0
    for mp in sorted(Path(clone_dir).glob("*/meta.json")):
        meta = json.loads(mp.read_text(encoding="utf-8"))
        cid = meta.get("case_id")
        uc = by_id.get(cid)
        if not uc:
            continue
        # expected systemCode = the code we INTEND to pin (real FD code), not the gap-doc EDGE-*/FD-PAY-*
        # label — matches seed.cli._pin_system_code, so edge/pay cases aren't false mismatches.
        from seed.cli import _pin_system_code
        exp_sc = _pin_system_code(uc)
        _, cls = parse_system_code(uc.system_code or uc.seed.system_code or "")
        exp_status = (uc.verdict or uc.seed.status or _CLASS_STATUS.get(cls, "")).upper()
        exp_amt = (uc.seed.amount or {}).get("value") if exp_status == "ELIGIBLE" else None

        from seed.dds_pin import verify_by_pnr
        try:
            v = verify_by_pnr(ctx.env, meta.get("pnr_id"), timeout=25)
        except Exception as exc:  # noqa: BLE001
            rows.append({"id": cid, "ok": False, "note": f"no DDS determination ({type(exc).__name__})"})
            nfail += 1
            continue
        got_sc = str(v.get("system_code") or "")
        _, gcls = parse_system_code(got_sc)
        got_status = "ELIGIBLE" if v.get("eligible") else _CLASS_STATUS.get(gcls, "NOT_ELIGIBLE")
        got_amt = float(v["amount"]) if v.get("amount") else None

        status_ok = got_status == exp_status
        sc_ok = got_sc == exp_sc
        amt_ok = (exp_amt is None and not got_amt) or (exp_amt is not None and got_amt == float(exp_amt))
        ok = status_ok and sc_ok and amt_ok
        npass += ok
        nfail += not ok
        rows.append({"id": cid, "ok": ok, "exp": f"{exp_status}/{exp_sc}/{exp_amt}",
                     "got": f"{got_status}/{got_sc}/{got_amt}",
                     "flags": "".join(["" if status_ok else "S", "" if sc_ok else "C", "" if amt_ok else "A"])})
    return {"pass": npass, "fail": nfail, "total": npass + nfail, "rows": rows}


def main(argv=None):
    p = argparse.ArgumentParser(prog="cctqa verify-uat")
    p.add_argument("clone_dir")
    p.add_argument("--product", default="bravo")
    p.add_argument("--env", default="int")
    p.add_argument("--feed", default="fd")
    a = p.parse_args(argv)
    res = verify_clone(a.clone_dir, a.product, a.env, a.feed)
    print(f"=== DDS-vs-UAT: {res['pass']}/{res['total']} match · {res['fail']} mismatch ===")
    for r in res["rows"]:
        if not r["ok"]:
            print(f"  MISMATCH [{r.get('flags','')}] {r['id']}: exp {r.get('exp')}  got {r.get('got')}  {r.get('note','')}")
    return 0 if res["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
