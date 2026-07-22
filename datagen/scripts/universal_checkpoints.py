#!/usr/bin/env python3
"""UNIVERSAL post-creation checkpoints — ONE command that runs the FULL canonical
suite (scripts/CHECKPOINTS.md) against any standard index, any environment.

    python3 universal_checkpoints.py <index.json> --env int|crt|bat [--no-dds] [--no-scenario]

Index rows need: pnr_id. Optional per-row fields unlock more areas:
  email       -> eds contact email match          group      -> GROUP booking_context
  pin+syscode -> DDS endpoint code match           amount     -> DDS ELIGIBLE amount match
  npax        -> passenger-count assertions        uniq_names -> ENFORCE name uniqueness
  status/-PE- -> PENDING flight-freshness window

All logic lives in pnr_common_checks.py (shared with the 7 domain *_checkpoints.py).
Exit 0 = PASS, 1 = FAIL.
"""
import json, sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pnr_common_checks as C

ap = argparse.ArgumentParser()
ap.add_argument("index")
ap.add_argument("--env", default="int", choices=list(C.ENVS))
ap.add_argument("--no-dds", action="store_true", help="skip endpoint-side areas")
ap.add_argument("--no-scenario", action="store_true", help="skip segments==scenario")
ap.add_argument("--scenario-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       "..", "scenarios", "fd-sit"))
a = ap.parse_args()

rows = json.load(open(a.index))
print(f"UNIVERSAL CHECKPOINTS for {a.index} — {len(rows)} PNRs ({a.env})")
conn = C.connect(a.env); cur = conn.cursor()
booking = C.collect_full(cur, rows)
seg = None if a.no_scenario else C.segments_vs_scenario(cur, rows, a.scenario_dir)
cur.close(); conn.close()
dds = None if a.no_dds else C.dds_checks(rows, a.env, pax=booking.get("_pax"))
fail = C.print_full(rows, booking, dds, seg)
print("PASS ✅ all areas present" if not fail else "FAIL ❌ — see MISS/BAD above")
sys.exit(1 if fail else 0)
