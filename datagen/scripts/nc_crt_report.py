#!/usr/bin/env python3
"""Generate the Name Correction CRT test-data report (HTML + CSV) — TC -> PNR map,
attributes, expected eligibility outcome (live-endpoint verified), and chatbot routing notes."""
import json, csv, html, datetime
import nc_crt_build as B

rows=B.load_index()
try: ver={v["pnr"]:v for v in json.load(open(f"{B.WORK}/nc_verify{B._sfx}.json"))}
except Exception: ver={}
import os as _os
OUTDIR=_os.environ.get("NC_OUTDIR","/Users/chathuranga/Downloads")
_os.makedirs(OUTDIR, exist_ok=True)
OUT_HTML=f"{OUTDIR}/NameCorrection_CRT_TestData{B._sfx}.html"
OUT_CSV =f"{OUTDIR}/NameCorrection_CRT_TestData{B._sfx}.csv"
CONTACT=rows[0]["email"]; PHONE=rows[0]["phone"]

def paxstr(paxs):
    out=[]
    for p in paxs:
        t=p[2]; tag={"YTH":" [YP]","INF":" [INF]","CHD":" [CHD]"}.get(t,"")
        o=p[3] if len(p)>3 else {}
        if o.get("ssr"): tag+=" SSR:"+"/".join(o["ssr"])
        if o.get("loyalty"): tag+=" [Aeroplan]"
        if o.get("corrected"): tag+=" [prior-corr]"
        out.append(f"{p[0]} {p[1]}{tag}")
    return ", ".join(out)
def chan(r):
    return r["src"] if r["src"]!="AC_ONLINE" else "AC_ONLINE (web)"
def carr(r):
    return " + ".join(f"{op}/{mkt}" for op,mkt in r["carriers"])

# CSV
with open(OUT_CSV,"w",newline="") as f:
    w=csv.writer(f); w.writerow(["TC","Priority","Feature","PNR","Passengers","Window","Channel(source)","Office","Carriers op/mkt","ExpEligible","ProcessingWindow","ReasonCode","EndpointVerified","ChatbotRouting/Note","Tickets"])
    for r in rows:
        v=ver.get(r["pnr"],{})
        w.writerow([r["tc"],r["pri"],r["feat"],r["pnr"],paxstr(r["paxs"]),r["window"],chan(r),r["office"],carr(r),
                    r["exp_elig"],r["exp_win"],r["exp_reason"],("PASS" if v.get("ok") else "?"),r["chatbot"],r["ticket"]])

FEATCLR={"Happy":"#1a7f37","Ineligible":"#b35900","Failure":"#8250df","Edge":"#0969da"}
def rowhtml(r):
    v=ver.get(r["pnr"],{})
    vok = v.get("ok"); vtxt = "✅" if vok else ("—" if not v else "❌")
    elig="ELIGIBLE" if r["exp_elig"] else "ineligible"
    ec = "#1a7f37" if r["exp_elig"] else "#b35900"
    fc=FEATCLR.get(r["feat"],"#333")
    return f"""<tr>
<td class=tc>{html.escape(r['tc'])}</td><td><span class=pri>{r['pri']}</span></td>
<td><span class=feat style='background:{fc}'>{r['feat']}</span></td>
<td class=pnr>{r['pnr']}</td>
<td>{html.escape(paxstr(r['paxs']))}</td>
<td>{r['window']}</td>
<td>{html.escape(chan(r))}<br><span class=dim>{html.escape(r['office'])}</span></td>
<td>{html.escape(carr(r))}</td>
<td style='color:{ec};font-weight:600'>{elig}<br><span class=dim>{r['exp_win']} · {r['exp_reason']}</span></td>
<td style='text-align:center'>{vtxt}</td>
<td class=note>{html.escape(r['chatbot'])}</td>
</tr>"""

npass=sum(1 for r in rows if ver.get(r["pnr"],{}).get("ok"))
nelig=sum(1 for r in rows if r["exp_elig"]); ninel=len(rows)-nelig
body=f"""<!-- generated {datetime.date.today()} -->
<h1>Name Correction — CRT Test Data</h1>
<p class=sub>{len(rows)} PNRs cascaded into CRT trip-tracer · eligibility verified live against
<code>POST /eligibility-service/execute-with-mapping</code> (trigger NAME_CORRECTION) ·
{npass}/{len(rows)} endpoint-verified · {nelig} eligible / {ninel} ineligible.</p>
<div class=meta>
<b>Contact (OTP):</b> {html.escape(CONTACT)} &nbsp;·&nbsp; {html.escape(PHONE)} &nbsp;·&nbsp;
<b>DOB:</b> {B.DOB} &nbsp;·&nbsp; <b>Ticket series:</b> {B.TPREFIX}xxxxxx &nbsp;·&nbsp;
<b>Env:</b> CRT (acct 050752605169, profile ac-cct-crt)
</div>
<div class=notes>
<b>How eligibility is verified.</b> Name Correction has no pinned DDS — the rule engine computes eligibility
live and statelessly from the posted EDS PNR. Each PNR's designed <code>pnrData</code> is POSTed to the CRT
endpoint and the response (<code>isPnrEligible</code> / <code>processingWindow</code> / <code>reasonCode</code>)
is asserted. The booking is also cascaded into trip-tracer so the chatbot can retrieve it and send the OTP.
<br><b>Service rules vs chatbot gates.</b> The eligibility service enforces 6 rules (carrier-mix on MARKETING
carrier == AC, booking-channel source whitelist {{AC_ONLINE, AC_MOBILE}}, time-to-departure = departed/no-upcoming,
passenger-type YTH/UMNR/YPTU, coupon-status, correction-limits). Group Desk, Aeroplan-<i>linked</i>, checked-in,
EXST/CBBG, prior-correction, name-transfer and the &lt;24h-before-departure Window-3 gate are <b>chatbot-level</b> —
the endpoint returns ELIGIBLE and routing happens in the agentic layer (see the Routing/Note column).
<br><b>Known divergence (TC050 codeshare).</b> The BRD says an AC-<i>operated</i> codeshare (partner marketing carrier)
is eligible, but the live service fails carrier-mix because it checks the <i>marketing</i> carrier — so NCCDS1
returns ineligible NC-NE-01. Flagged for the product team.
<br><b>Not seeded:</b> TC012 (Invalid PNR) intentionally has no booking — it tests retrieval of a non-existent PNR.
</div>
<table>
<thead><tr><th>Test Case</th><th>Pri</th><th>Feature</th><th>PNR</th><th>Passengers</th><th>Win</th>
<th>Channel / Office</th><th>Carriers op/mkt</th><th>Expected eligibility</th><th>Verified</th><th>Chatbot routing / note</th></tr></thead>
<tbody>
{''.join(rowhtml(r) for r in rows)}
</tbody></table>
"""
css="""
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2328;background:#fff}
h1{margin:0 0 4px} .sub{color:#57606a;margin:0 0 12px}
.meta{background:#f6f8fa;border:1px solid #d0d7de;border-radius:8px;padding:10px 14px;margin:8px 0;font-size:13px}
.notes{background:#fff8e6;border:1px solid #eac54f;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:12.5px;line-height:1.5}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}
th,td{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa;position:sticky;top:0}
.tc{font-family:ui-monospace,Menlo,monospace;font-size:11px;white-space:nowrap}
.pnr{font-family:ui-monospace,Menlo,monospace;font-weight:700;color:#0969da}
.pri{font-size:11px;color:#57606a} .dim{color:#8b949e;font-size:11px}
.note{font-size:11px;color:#57606a;max-width:260px}
.feat{color:#fff;padding:1px 7px;border-radius:10px;font-size:11px;white-space:nowrap}
tr:hover{background:#f6f8fa}
"""
open(OUT_HTML,"w").write(f"<!doctype html><html><head><meta charset=utf-8><title>Name Correction CRT Test Data</title><style>{css}</style></head><body>{body}</body></html>")
print(f"[report] {OUT_HTML}\n[report] {OUT_CSV}  ({len(rows)} PNRs, {npass} verified)")
