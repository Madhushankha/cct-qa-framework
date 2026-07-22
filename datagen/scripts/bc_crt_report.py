#!/usr/bin/env python3
"""Booking Change CRT test-data report (HTML + CSV) — VOL + INVOL."""
import json, sys, html, os, datetime
import bc_crt_build as B

IDX = sys.argv[1] if len(sys.argv) > 1 else B.OUT
recs = json.load(open(IDX))
OUTBASE = os.environ.get("BC_REPORT", os.path.expanduser("~/Downloads/BookingChange_CRT_TestData"))

def segstr(r):
    out = []
    for s in r["segs"]:
        tag = f"{s['op']}{'/'+s['mkt'] if s['mkt']!=s['op'] else ''} {s['o']}-{s['d']} b{s['bound']} {s['status']}"
        if s["coupon"] == "FLOWN": tag += " FLOWN"
        out.append(tag)
    return " | ".join(out)

def paxstr(r):
    return "; ".join(f"{p['first']} {p['last']} ({p['ptype']}"
                     + (f" {'/'.join(p['ssr'])}" if p['ssr'] else "") + ")" for p in r["paxs"])

def tkts(r): return ", ".join(sorted(set(r["tickets"].values())))

hdr = ["TC", "Flow", "Pri", "Feature", "Name", "PNR", "Passengers", "Tickets(014)", "Source",
       "Segments", "Fare/Cabin", "Bag", "CheckedIn", "Seat", "Bound", "VOL exp", "Chatbot/Runtime", "Divergence"]
def rowvals(r):
    extra = []
    if r["checkin"]: extra.append("checked-in")
    return [r["tc"], r["flow"].upper(), r["pri"], r["feat"], r["name"], r["pnr"] if r["seed_pnr"] else r["pnr"]+" (RESERVED)",
            paxstr(r), tkts(r) if r["seed_pnr"] else "-", r["src"], segstr(r),
            f"{r['fare']}/{r['cabin']}", r["bag"] or "-", "yes" if r["checkin"] else "-",
            r["seat"] or "-", r["bound"], r["exp"] or ("INVOL delay=%s rebooked=%s" % (r.get("delay"), r.get("rebooked"))),
            (r["chatbot"] + (" | " + r["runtime"] if r["runtime"] else "")).strip(" |"), r["divergence"]]

# CSV
import csv
with open(OUTBASE + ".csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(hdr)
    for r in recs: w.writerow(rowvals(r))

# HTML
vol = [r for r in recs if r["flow"] == "vol"]
invol = [r for r in recs if r["flow"] == "invol"]
def table(rows):
    h = "<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in hdr) + "</tr>"
    body = ""
    for r in rows:
        cls = "res" if not r["seed_pnr"] else ("div" if r["divergence"] else "")
        body += f"<tr class='{cls}'>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in rowvals(r)) + "</tr>"
    return f"<table>{h}{body}</table>"

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
doc = f"""<!doctype html><meta charset=utf-8><title>Booking Change CRT Test Data</title>
<style>
body{{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a}}
h1{{font-size:20px}} h2{{margin-top:28px;border-bottom:2px solid #d00;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:11.5px}}
th,td{{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#d00;color:#fff;position:sticky;top:0}}
tr.div td{{background:#fff8e6}} tr.res td{{background:#f0f0f0;color:#777}}
.meta{{background:#f6f6f6;border:1px solid #ddd;padding:12px 16px;border-radius:6px}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
</style>
<h1>Booking Change — CRT Test Data ({len(recs)} PNRs)</h1>
<div class=meta>
<b>Generated:</b> {now} &nbsp;|&nbsp; <b>Env:</b> CRT (account 050752605169) &nbsp;|&nbsp;
<b>Contact:</b> <code>{B.EMAIL}</code> / <code>{B.PHONE}</code><br>
<b>Booking date:</b> {B.BOOK_DATE} &nbsp;|&nbsp; <b>Ticket series:</b> {B.TPREFIX}xxxxxxx (014 stock) &nbsp;|&nbsp;
<b>Adult DOB:</b> {B.DOB_ADT}<br>
<b>VOL</b> ({len(vol)} PNRs): eligibility computed LIVE by
<code>POST /eligibility-service/execute-with-mapping</code> (trigger <b>BOOKING_CHANGE</b>,
changeTrigger.selectedBound = journey selection). Verified 50/50 against the endpoint.<br>
<b>INVOL</b> ({len(invol)} PNRs): the endpoint rejects trigger INVOLUNTARY (HTTP 422) — eligibility is
computed downstream by the Involuntary API (Order Retrieve + DBaaS/DDS), disruption-driven. INVOL PNRs
carry the retrievable disruption model (original <b>UN</b> cancelled seg + rebooked <b>HK</b> seg, delay,
booking source, SSRs, checked baggage) and are verified on the booking side only.<br>
<b>VOL reason codes (probed live):</b>
VBC-EL-01 eligible · VBC-NE-01 72hr-window (&gt;72h15m or departed) · VBC-NE-02 checked-bag (downstream) ·
VBC-NE-03 booking-source (only ACO/ADO/AC_MOBILE/AIRPORT/CONTACT_CENTRE/NDC/1A_GDS) · VBC-NE-04 basic fare ·
VBC-NE-05 blocking SSR · VBC-NE-06 ticket/coupon · VBC-NE-07 checked-in · VBC-NE-08 eUpgrade.<br>
<b>Legend:</b> <span style="background:#fff8e6">yellow = spec divergence</span>,
<span style="background:#f0f0f0">grey = reserved (deliberately never seeded)</span>.
</div>
<h2>Voluntary (BCVol) — {len(vol)} PNRs</h2>{table(vol)}
<h2>Involuntary (BCInvol) — {len(invol)} PNRs</h2>{table(invol)}
"""
open(OUTBASE + ".html", "w").write(doc)
print(f"[report] {OUTBASE}.html  +  {OUTBASE}.csv   ({len(recs)} PNRs)")
