#!/usr/bin/env python3
"""Re-pin ONLY the FD compensationEligibility DDS (UAT031/032) for a baggage index.

Needed when the AWS SSO session expires mid-build: every other layer of the build uses
direct psycopg2 creds and succeeds, but the FD DDS pin does an S3 put via boto3, so it
fails with UnauthorizedSSOTokenError and the rule-engine endpoint then 404s.

Fix: `aws sso login --profile ac-cct-crt`, then run this. It re-does S3 put +
execution_traces pin for just the 2 FD PNRs (no touching of booking/baggage rows).

Usage: AWS_PROFILE=ac-cct-crt python3 bag_fd_repin.py <index.json> [<index2.json> ...]
"""
import os, sys, json

# builder env must be set BEFORE importing (module-level reads BAG_OUT/BAG_WORK)
os.environ.setdefault("CRT_UNIQ_NAMES", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bag_crt_build as B

def repin(idx_path):
    recs = json.load(open(idx_path))
    fd = [r for r in recs if r["ahl"] == "fd"]
    print(f"\n=== {os.path.basename(idx_path)} — {len(fd)} FD case(s) ===")
    n = B.finalize_fd(recs)
    print(f"  pinned {n} FD DDS rows")
    for r in fd:
        res = B.verify_one(r, None) if False else None
    # verify via endpoint
    import ssl, urllib.request
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    ok = 0
    for r in fd:
        pid = r["pnr_id"]
        try:
            req = urllib.request.Request(B.CRT["endpoint"] + pid, headers={"x-api-key": B.CRT["api_key"]})
            d = json.load(urllib.request.urlopen(req, context=ctx, timeout=25))
            ce = d.get("compensationEligibility", []) or []
            good = len(ce) > 0 and ce[0]["passengerEligibility"][0]["eligibilityStatus"] == "ELIGIBLE"
            print(f"  {r['tc']} {pid}: {'ELIGIBLE ✅' if good else 'comp=' + str(len(ce))}")
            ok += bool(good)
        except Exception as e:
            print(f"  {r['tc']} {pid}: ERR {str(e)[:60]}")
    print(f"  FD verified {ok}/{len(fd)}")
    return ok == len(fd)

allok = True
for p in sys.argv[1:]:
    allok &= repin(p)
print("\nFD REPIN " + ("PASS ✅" if allok else "FAIL ❌"))
sys.exit(0 if allok else 1)
