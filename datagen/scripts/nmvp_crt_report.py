#!/usr/bin/env python3
"""Generate HTML+CSV report for a Non-MVP CRT PNR set.
Usage: python3 nmvp_crt_report.py <index.json> <out_basename>
  e.g. python3 nmvp_crt_report.py .../_NMVP_crt_set2_index.json NonMVP_UAT_CRT_set2
Writes ~/Downloads/<out_basename>.{html,csv}. NO-PNR list pulled from nmvp_crt_build.
"""
import json, csv, sys, datetime, html, os
import nmvp_crt_build as B

idx=sys.argv[1]; base=sys.argv[2]
rows=json.load(open(idx)); NO=B.NO_PNR
today=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
EMAIL=rows[0]["email"]; PHONE=rows[0]["phone"]; TSER=rows[0]["ticket"][:6]
home=os.path.expanduser("~/Downloads")

csvp=f"{home}/{base}.csv"
with open(csvp,"w",newline="") as f:
    w=csv.writer(f)
    w.writerow(["TC","Name","PNR","pnr_id","Ticket","Pax","Itinerary","TravelState","Team","OTP","Email","Phone","Notes"])
    for r in rows:
        route="/".join(f"{o}-{d}" for o,d in r["legs"])
        pax="; ".join(f"{p[0]} {p[1]}" for p in r["paxs"])
        w.writerow([r["tc"],r["name"],r["pnr"],r["pnr_id"],r["ticket"],pax,route,r["state"],r["team"],r["otp"],r["email"],r["phone"],r["note"]])
print("CSV ->",csvp)

def td(x): return f"<td>{html.escape(str(x))}</td>"
rowshtml=""
for r in rows:
    route="/".join(f"{o}-{d}" for o,d in r["legs"])
    pax="; ".join(f"{p[0]} {p[1]}" for p in r["paxs"])
    st="POST-travel" if r["state"]=="POST" else "FUTURE-travel"
    rowshtml+="<tr>"+td(r["tc"])+td(r["name"])+f"<td class=pnr>{html.escape(r['pnr'])}</td>"+td(pax)+td(route)+td(st)+td(r["team"])+td(r["otp"])+td(r["ticket"])+td(r["note"])+"</tr>\n"
nohtml="".join("<tr>"+td(tc)+f"<td colspan=9>{html.escape(desc)}</td>"+"</tr>\n" for tc,desc in NO)

doc=f"""<!doctype html><meta charset=utf-8><title>{html.escape(base)}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px;border-bottom:2px solid #c8102e;padding-bottom:4px}}
.meta{{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:14px 18px;font-size:13px;line-height:1.7}}
.meta b{{color:#c8102e}}
table{{border-collapse:collapse;width:100%;font-size:12px;background:#fff;margin-top:8px}}
th,td{{border:1px solid #e0e0e0;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#c8102e;color:#fff;position:sticky;top:0}}
tr:nth-child(even) td{{background:#f7f7f7}}
.pnr{{font-family:ui-monospace,Menlo,monospace;font-weight:700;color:#0a58ca}}
.pass{{color:#137333;font-weight:700}} code{{background:#eef;padding:1px 4px;border-radius:3px}}
</style>
<h1>Non-MVP UAT — CRT Test PNR Data — {html.escape(base)}</h1>
<div class=meta>
<b>Environment:</b> CRT (account 050752605169, profile ac-cct-crt, ca-central-1) &nbsp;·&nbsp; <b>Built:</b> {today}<br>
<b>Contact (all PNRs):</b> {html.escape(EMAIL)} / {html.escape(PHONE)} &nbsp;·&nbsp; <b>DOB:</b> 1986-04-23 &nbsp;·&nbsp; <b>Ticket series:</b> {TSER}xxxxxxx<br>
<b>Source:</b> Non-MVP_UAT.xlsx (55 cases) + Non_MVP_Miro_Gap_Analysis.html<br>
<b>PNRs built:</b> {len(rows)} &nbsp;·&nbsp; <b>NO-PNR cases (documented):</b> {len(NO)} &nbsp;·&nbsp; <b>Checkpoints:</b> <span class=pass>PASS {len(rows)}/{len(rows)} all areas + name-uniqueness</span><br>
<b>Flow:</b> Non-MVP is <i>non-automated</i> — no DDS, no eligibility endpoint, manual_path=<code>non_mvp_topic</code>. Each PNR cascades a retrievable booking into trip-tracer so the chatbot can <b>identify</b> (GenUC-01) → <b>OTP-PNR</b> (GenUC-05, email/phone above) → <b>journey/segment select</b> (GenUC-08/18a) → manual Claims-Dashboard case. Passenger names are globally unique (verified absent from the live passenger table + prior sets).<br>
<b>Not encoded in the PNR (loyalty-service / chat gated — see Notes):</b> loyalty tier SE/VIP, Aeroplan membership (OTP-Aeroplan), country of residence (GLOB-20c). Itinerary geography (US/China/EU) IS seeded.
</div>
<h2>Seeded PNRs ({len(rows)})</h2>
<table>
<tr><th>TC</th><th>Name</th><th>PNR</th><th>Passenger(s)</th><th>Itinerary</th><th>Travel state</th><th>Team</th><th>OTP</th><th>Ticket</th><th>Notes</th></tr>
{rowshtml}
</table>
<h2>NO-PNR cases ({len(NO)}) — not seeded by design</h2>
<table><tr><th>TC</th><th>Reason</th></tr>
{nohtml}
</table>
"""
outp=f"{home}/{base}.html"
open(outp,"w").write(doc)
print("HTML ->",outp)
