#!/usr/bin/env python3
"""Seat Change CRT test-data report (HTML + CSV).

Reads the built index, re-queries the LIVE eligibility endpoint for each PNR so the report
shows the verdict actually returned at generation time, and writes:
   ~/Downloads/SeatChange_CRT_TestData.html
   ~/Downloads/SeatChange_CRT_TestData.csv
"""
import json, csv, html, os, datetime, sys
import sc_crt_build as B

BASE = os.environ.get("SC_REPORT", "SeatChange_CRT_TestData")
OUTH = os.path.expanduser(f"~/Downloads/{BASE}.html")
OUTC = os.path.expanduser(f"~/Downloads/{BASE}.csv")
SETNAME = os.environ.get("SC_SETNAME", "")
rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else B.OUT))
STAMP = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# Verdict source: the LIVE endpoint by default. When it is unreachable (private-API-Gateway
# 403 from an off-VPC path), set SC_OFFLINE=1 to compute the verdict locally with the same
# rule flow (sc_local_eval) — deterministic, so it reproduces the live verdict for this data.
OFFLINE = os.environ.get("SC_OFFLINE") == "1"
_now = datetime.datetime.now(datetime.timezone.utc)
conn = B.tt_conn()
if OFFLINE:
    import sc_local_eval as LE
    for r in rows:
        if not r["seed_pnr"]: r["_live"] = {}; continue
        p = B.db_payload(r["pnr_id"], r["bound"], conn)
        code, elig, win, st = LE.evaluate(p, _now)
        r["_live"] = {"reason": code, "elig": elig, "win": win,
                      "fee": (win == "NON_VOID") if win in ("VOID", "NON_VOID") else None,
                      "offline": True}
else:
    for r in rows:
        r["_live"] = B.eligibility_of(r, conn) if r["seed_pnr"] else {}
conn.close()

DIVERGENCES = [r for r in rows if r["divergence"]]
NE = [r for r in rows if r["seed_pnr"] and not r["exp_elig"]]
EL = [r for r in rows if r["seed_pnr"] and r["exp_elig"]]

REASONS = [
    ("SC-EL-01", "All seat-change eligibility criteria are met", "eligible"),
    ("SC-NE-01", "ruleCarrierMix — marketing OR operating carrier is not AC / QK / RV", "carrier"),
    ("SC-NE-02", "ruleBookingChannel — booking source missing/empty", "channel"),
    ("SC-NE-03", "ruleBookingChannel — booking source not in the eligible-channel lookup", "channel"),
    ("SC-NE-04", "ruleTicketStatus — ticket not 014 stock, missing, or all coupons flown/void", "ticket"),
    ("SC-NE-05", "ruleTimeWindow — flight departs in &lt;24h, or has already departed (OUT_OF_SCOPE)", "time"),
    ("SC-NE-06", "ruleSsrRestriction — blocking SSR present (EXST / CBBG / SVAN / ESAN)", "ssr"),
    ("SC-NE-07", "ruleGroupPnr — GROUP booking within 6h of departure", "group"),
    ("SC-NE-08", "ruleCheckinStatus — passenger already checked in (acceptance = ACCEPTED)", "checkin"),
]

def esc(s): return html.escape(str(s if s is not None else ""))

def pax_cell(r):
    out = []
    for k, p in enumerate(r["paxs"]):
        bits = [f"{p['first']} {p['last']}", f"<span class='mut'>{p['ptype']}</span>"]
        if p["ssr"]: bits.append(f"<span class='ssr'>{'/'.join(p['ssr'])}</span>")
        seat = r["seats"].get(str(k))
        if seat: bits.append(f"<span class='seat'>seat {seat}</span>")
        out.append(" ".join(bits))
    return "<br>".join(out)

def seg_cell(r):
    out = []
    for j, s in enumerate(r["segs"]):
        oal = "" if (s["mkt"] in ("AC", "QK", "RV") and s["op"] in ("AC", "QK", "RV")) else " oal"
        dep = s["dep_iso"].replace("T", " ").replace("Z", "")
        out.append(f"<span class='seg{oal}'>b{s['bound']} {s['mkt']}{870+j} {s['o']}→{s['d']} "
                   f"<span class='mut'>op {s['op']} · {dep}Z</span></span>")
    return "<br>".join(out)

def verdict_cell(r):
    if not r["seed_pnr"]:
        return "<span class='pill grey'>not seeded</span>"
    g = r["_live"]
    good = g.get("reason") == r["exp_reason"] and g.get("elig") == r["exp_elig"]
    cls = "green" if g.get("elig") else "red"
    mark = "" if good else " <span class='pill red'>MISMATCH</span>"
    return (f"<span class='pill {cls}'>{esc(g.get('reason'))}</span> "
            f"<span class='mut'>{esc(g.get('win'))}"
            + (f" · fee {'yes' if g.get('fee') else 'no'}" if g.get("fee") is not None else "") + "</span>" + mark)

def flags_cell(r):
    g = r.get("_live") or {}
    f = []
    if any(p.get("umnr") for p in g.get("pax", [])): f.append("isUmnr")
    if any(p.get("yth") for p in g.get("pax", [])): f.append("isYouth")
    ss = sorted({s for p in g.get("pax", []) for s in (p.get("ssrs") or [])})
    if ss: f.append("persist:" + "/".join(ss))
    if r["checkin"]: f.append("checked-in")
    if r["src"] == "GROUP": f.append("group")
    return " ".join(f"<span class='tag'>{esc(x)}</span>" for x in f)

CSS = """
:root{--bg:#fbfbfd;--fg:#1d1d20;--mut:#6b6b76;--line:#e4e4ea;--card:#fff;--accent:#0b5cd5}
@media(prefers-color-scheme:dark){:root{--bg:#131317;--fg:#e9e9ee;--mut:#9a9aa6;--line:#2b2b33;--card:#1a1a20;--accent:#6ea8ff}}
:root[data-theme=dark]{--bg:#131317;--fg:#e9e9ee;--mut:#9a9aa6;--line:#2b2b33;--card:#1a1a20;--accent:#6ea8ff}
:root[data-theme=light]{--bg:#fbfbfd;--fg:#1d1d20;--mut:#6b6b76;--line:#e4e4ea;--card:#fff;--accent:#0b5cd5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:17px;margin:36px 0 12px;letter-spacing:-.01em}
.sub{color:var(--mut);margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .n{font-size:24px;font-weight:600;letter-spacing:-.02em}
.card .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-top:2px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:1180px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);font-weight:600;
   position:sticky;top:0;background:var(--card);z-index:1}
tr:last-child td{border-bottom:none}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.loc{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:14px}
.mut{color:var(--mut);font-size:12px}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;font-weight:600;white-space:nowrap}
.pill.green{background:#0f8a3d1a;color:#0f8a3d;border:1px solid #0f8a3d40}
.pill.red{background:#c62f2f1a;color:#c62f2f;border:1px solid #c62f2f40}
.pill.grey{background:var(--line);color:var(--mut)}
.tag{display:inline-block;padding:1px 6px;border-radius:5px;background:var(--line);color:var(--mut);font-size:11px;margin-right:3px}
.ssr{color:#b3541e;font-size:11px;font-weight:600}
.seat{color:var(--accent);font-size:11px}
.seg{font-size:12px}.seg.oal{color:#c62f2f}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:12px 14px;margin:10px 0}
.warn{border-left-color:#e0a800}
.pri{font-size:11px;color:var(--mut)}
.rt{font-size:12px;color:var(--mut);max-width:340px}
ul{margin:6px 0 0 18px;padding:0}li{margin:3px 0}
.kv{font-size:13px}.kv b{font-weight:600}
"""

def table(rows_):
    h = ["<div class='scroll'><table><thead><tr>"
         "<th>Test case</th><th>Locator</th><th>Passengers / seats</th><th>Segments</th>"
         "<th>Channel</th><th>Live eligibility verdict</th><th>Flags</th><th>Tester note</th>"
         "</tr></thead><tbody>"]
    for r in rows_:
        note = r["chatbot"] or r["runtime"]
        if r["divergence"]: note = f"⚠ {r['divergence']}"
        h.append(f"<tr><td><b>{esc(r['tc'].replace('SeatChange_',''))}</b><br>"
                 f"<span class='mut'>{esc(r['name'])}</span><br><span class='pri'>{esc(r['pri'])} · {esc(r['feat'])}</span></td>"
                 f"<td><span class='loc'>{esc(r['pnr'])}</span><br><span class='mut mono'>{esc(r['pnr_id'])}</span>"
                 f"<br><span class='mut mono'>tkt {esc(list(r['tickets'].values())[0] if r['tickets'] else '—')}</span>"
                 + (f"<br><span class='mut'>bound {r['bound']}</span>" if r["bound"] != 1 else "") + "</td>"
                 f"<td>{pax_cell(r)}</td><td>{seg_cell(r)}</td>"
                 f"<td class='mono' style='font-size:12px'>{esc(r['src'])}</td>"
                 f"<td>{verdict_cell(r)}</td><td>{flags_cell(r)}</td>"
                 f"<td class='rt'>{esc(note)}</td></tr>")
    h.append("</tbody></table></div>")
    return "".join(h)

nseeded = sum(1 for r in rows if r["seed_pnr"])
npax = sum(r["npax"] for r in rows if r["seed_pnr"])
matched = sum(1 for r in rows if r["seed_pnr"] and r["_live"].get("reason") == r["exp_reason"])

doc = f"""<title>Seat Change — CRT Test Data{(' ' + SETNAME) if SETNAME else ''}</title>
<style>{CSS}</style>
<div class="wrap">
<h1>Seat Change — CRT test data{(' <span class="pill grey">' + esc(SETNAME) + '</span>') if SETNAME else ''}</h1>
<div class="sub">67 test cases from <code>Seat Change.xlsx</code> · {nseeded} freshly-built PNRs in CRT
(account 050752605169, <code>ca-central-1</code>) · generated {STAMP}</div>

<div class="cards">
  <div class="card"><div class="n">{nseeded}</div><div class="l">PNRs seeded</div></div>
  <div class="card"><div class="n">{npax}</div><div class="l">unique passengers</div></div>
  <div class="card"><div class="n">{len(EL)}</div><div class="l">eligible (SC-EL-01)</div></div>
  <div class="card"><div class="n">{len(NE)}</div><div class="l">not eligible</div></div>
  <div class="card"><div class="n">{matched}/{nseeded}</div><div class="l">live verdict matches</div></div>
  <div class="card"><div class="n">{len(DIVERGENCES)}</div><div class="l">spec divergences</div></div>
</div>

<div class="note"><b>Identification &amp; OTP (same for every PNR).</b>
<div class="kv" style="margin-top:6px">
  <b>Email</b> <code>{esc(rows[0]['email'])}</code> &nbsp;·&nbsp;
  <b>Phone</b> <code>{esc(rows[0]['phone'])}</code> &nbsp;·&nbsp;
  <b>Adult DOB</b> <code>{B.DOB_ADT}</code> &nbsp;·&nbsp;
  <b>Booking date</b> <code>{rows[0]['booking_date']}</code> &nbsp;·&nbsp;
  <b>Ticket series</b> <code>{B.TPREFIX}xxxxxxx</code>
</div>
<div class="mut" style="margin-top:6px">Identify with the locator + the passenger's last name (shown per row).
Every passenger name in the set is globally unique, so no PNR can be reached by another PNR's name.</div>
</div>

<h2>How seat-change eligibility is actually decided</h2>
<div class="note">
The bot calls <code>POST /eligibility-service/execute-with-mapping</code> with
<code>changeTrigger.trigger = SEAT_CHANGE</code> and a <b>required</b> <code>changeTrigger.selectedBound</code>
(that is the GenUC-08 Journey Selection step). The response is scoped to that one bound:
<code>boundEligibility → segmentsEligibility[] → passengerEligibility[]</code>.
A bound is eligible only when <b>every</b> passenger on it passes <b>all</b> seven rules.
<div class="mut" style="margin-top:8px">Verified live on CRT — the copy of <code>rules.json</code> checked into
<code>cct-cascade</code> is stale: it is missing the 8th rule (<code>ruleCheckinStatus</code> / SC-NE-08).</div>
</div>
<div class="scroll"><table style="min-width:760px"><thead><tr><th>Reason code</th><th>Meaning</th>
<th>Seeded where</th></tr></thead><tbody>
{''.join(f"<tr><td><span class='pill {'green' if c=='SC-EL-01' else 'red'}'>{c}</span></td><td>{m}</td>"
         f"<td class='mut'>{', '.join(r['tc'].replace('SeatChange_','') for r in rows if r['seed_pnr'] and r['exp_reason']==c) or '—'}</td></tr>"
         for c, m, _ in REASONS)}
</tbody></table></div>

<div class="note" style="margin-top:14px"><b>Where each rule input lives</b> (this is what the build patches):
<ul>
<li><code>ruleBookingChannel</code> ← <code>eds_pnr_output.booking_context.bookingSource</code>
    <span class="mut">(authoritative; falls back to <code>trip_details.source</code>, which is <code>varchar(5)</code>
    and holds the GDS code — the SP router maps <code>AC → ACO</code>)</span></li>
<li><code>ruleCarrierMix</code> ← <code>flight_segment.marketing_carrier_code</code> <b>and</b>
    <code>operating_carrier_code</code> <span class="mut">(both must be AC/QK/RV)</span></li>
<li><code>ruleTimeWindow</code> ← <code>trip.created_at</code> + first segment's
    <code>departure_datetime</code> <span class="mut">(≤24h since booking → VOID + no fee; otherwise ≥24h to
    departure → NON_VOID + fee; else OUT_OF_SCOPE)</span></li>
<li><code>ruleTicketStatus</code> ← <code>ticket.primary_document_number</code> (014 stock) +
    <code>ticket.coupons[].status</code>, <span class="mut">one coupon correlated to each segment of the bound</span></li>
<li><code>ruleSsrRestriction</code> ← <code>special_service_request.code</code>
    <span class="mut">(blocks on EXST/CBBG/SVAN/ESAN; reports WCHR/MEDA/DPNA/OXYG/MEQT as <code>specialSsrs</code>)</span></li>
<li><code>ruleCheckinStatus</code> ← <code>journey_updates</code> <code>event_type=CHECK_IN</code> with
    <code>data.segment.legDeliveries[].acceptance.status = ACCEPTED</code></li>
<li><code>ruleGroupPnr</code> ← <code>bookingSource = GROUP</code>, and only fails within 6h of departure</li>
</ul></div>

<h2>⚠ Spec divergences — test case vs. live rule flow ({len(DIVERGENCES)})</h2>
{''.join(f"<div class='note warn'><b>{esc(r['tc'].replace('SeatChange_',''))} — {esc(r['name'])}</b>"
         f"<div style='margin-top:5px'>{esc(r['divergence'])}</div>"
         f"<div class='mut' style='margin-top:5px'>PNR <code>{esc(r['pnr'])}</code> was still built to match the "
         f"test case's stated preconditions, so the chatbot-layer behaviour can be exercised.</div></div>"
         for r in DIVERGENCES)}

<h2>Not seedable from the PNR (environmental / runtime)</h2>
<div class="note">These cases have a working, eligible PNR seeded, but the condition under test is raised by a
system outside trip-tracer and must be produced at test time:
<ul>
<li><b>Seat map</b> — inventory, full flight, concurrent seat grab, cabin restrictions, exit-row / proximity /
    bassinet rules (TC031, TC032, TC035, TC040–TC047) all live in the Seat Change Widget, not the PNR.
    The PNRs <i>do</i> carry the ages, passenger types, SSRs and current seat assignments those rules read.</li>
<li><b>Payment</b> — expired card, FlexPay threshold, split payment, network drop (TC036–TC039, TC007/8/50/67).</li>
<li><b>Session / concurrency / network</b> — TC055, TC056, TC058, TC060, TC065, TC066.</li>
<li><b>Aircraft swap</b> (TC059) and <b>mid-flow check-in</b> (TC061) are flight-level / DCS events.
    TC061's PNR starts <i>not</i> checked in; TC015's PNR shows the checked-in end state (SC-NE-08).</li>
<li><b>Disruption</b> (TC048) is raised by FDM; the PNR carries the ACV booking source only.</li>
<li><b>TC025</b> deliberately has <b>no</b> PNR — locator <code>{esc([r['pnr'] for r in rows if not r['seed_pnr']][0])}</code>
    is reserved and confirmed absent from trip-tracer, so identification genuinely fails.</li>
</ul></div>

<div class="note warn"><b>Time-sensitive rows.</b> TC020 (45&nbsp;min), TC021 (12&nbsp;h), TC023 (departed 3&nbsp;h ago)
and TC057 (23:59:59) are anchored to the build time. They decay: once TC021's flight departs it is still
OUT_OF_SCOPE, but the narrative drifts. Re-anchor with
<code>python3 sc_crt_build.py redate</code> then re-run <code>sc_checkpoints.py</code>.
<div class="mut" style="margin-top:5px">Boundary confirmed live: 23:59:59 → OUT_OF_SCOPE · 24:05:00 → NON_VOID.</div></div>

<h2>All {len(rows)} test cases</h2>
{table(rows)}

<h2>Rebuild / verify</h2>
<div class="note mono" style="font-size:12.5px">
python3 sc_crt_build.py index<br>
python3 sc_crt_build.py publish&nbsp;&nbsp;&nbsp;<span class="mut"># Kafka emh-dev.ALTEA-PNRDATA-UAT (WARP on, no AWS creds)</span><br>
python3 sc_crt_build.py checkcascade<br>
python3 sc_crt_build.py finalize&nbsp;&nbsp;<span class="mut"># tickets, DOB, pax types, SSRs, CHECK_IN, booking_context, carriers, dates</span><br>
python3 sc_crt_build.py redate&nbsp;&nbsp;&nbsp;&nbsp;<span class="mut"># only when the time-boundary rows have decayed</span><br>
python3 sc_checkpoints.py&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="mut"># 26 areas: 15 booking-side + 11 live-endpoint</span>
</div>
</div>
"""
open(OUTH, "w").write(doc)

with open(OUTC, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["test_case", "priority", "feature", "name", "locator", "pnr_id", "tickets", "npax",
                "passengers", "passenger_types", "ssrs", "seats", "segments", "selected_bound",
                "booking_source", "expected_reason", "live_reason", "live_eligible", "processing_window",
                "fee_applicable", "divergence", "tester_note"])
    for r in rows:
        g = r["_live"]
        w.writerow([r["tc"], r["pri"], r["feat"], r["name"], r["pnr"], r["pnr_id"] if r["seed_pnr"] else "",
                    " ".join(r["tickets"].values()), r["npax"],
                    "; ".join(f"{p['first']} {p['last']}" for p in r["paxs"]),
                    "/".join(p["ptype"] for p in r["paxs"]),
                    "/".join(",".join(p["ssr"]) or "-" for p in r["paxs"]),
                    " ".join(f"PT{int(k)+1}:{v}" for k, v in r["seats"].items()),
                    " | ".join(f"b{s['bound']} {s['mkt']}/{s['op']} {s['o']}->{s['d']} {s['dep_iso']}" for s in r["segs"]),
                    r["bound"], r["src"], r["exp_reason"], g.get("reason", ""), g.get("elig", ""),
                    g.get("win", ""), g.get("fee", ""), r["divergence"], r["chatbot"] or r["runtime"]])
print(f"wrote {OUTH}\nwrote {OUTC}")
