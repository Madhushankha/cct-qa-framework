#!/usr/bin/env python3
"""Payout-scenario report for the 24 payout-routing PNRs. Joins the built index (pnr_id/loc/
ticket/date) with the payout metadata in the SOURCE index (payout_case/name/method, country_res,
language, chat_trigger) by tc. All PNRs are ELIGIBLE; country of residence is captured IN-FLOW
(paymentContact.countryOfResidenceCode) NOT in PNR/DDS data — the report documents which
country/language/in-chat trigger the tester supplies per case.
Usage: bat_fd_payout_report.py <built_index.json> <src_index.json> <base_name> <label> [chklog] [outdir]"""
import json,html,csv,os,sys,datetime
built=json.load(open(sys.argv[1])); src=json.load(open(sys.argv[2]))
base,label=sys.argv[3],sys.argv[4]
chklog=sys.argv[5] if len(sys.argv)>5 else ""
OUT=sys.argv[6] if len(sys.argv)>6 else "/Users/chathuranga/Downloads/BAT Data Sets"
os.makedirs(OUT,exist_ok=True)
NOW=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
meta={r["tc"]:r for r in src}
rows=[]
for r in built:
    m=meta.get(r["tc"],{})
    rows.append(dict(tc=r["tc"], pnr_id=r["pnr_id"], loc=r.get("loc",""),
        case=m.get("payout_case",""), scenario=m.get("payout_name",""), method=m.get("payout_method",""),
        country=f'{m.get("country_res","")} ({m.get("country_code","")})', language=m.get("language",""),
        trigger=m.get("chat_trigger",""), status=r["status"], syscode=r["syscode"],
        amount=r["amount"], currency=r["currency"], date=r["date"], pax=r.get("pax_set") or r["pax"], ticket=r["ticket"]))
rows.sort(key=lambda r:(r["case"], r["tc"]))
cols=["tc","pnr_id","loc","case","scenario","country","language","method","trigger","status","syscode","amount","currency","date","pax","ticket"]
with open(f"{OUT}/{base}.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(cols); [w.writerow([r[c] for c in cols]) for r in rows]
chk=""
if chklog and os.path.exists(chklog):
    chk="<pre style='background:#0f1c2e;color:#d7e3f4;padding:10px 14px;border-radius:6px;font-size:12px;overflow:auto'>"+html.escape(open(chklog).read().strip())+"</pre>"
def td(x,c=""):return f'<td class="{c}">{html.escape(str(x))}</td>'
casecolor={1:"#e6f5e6",2:"#eaf6ea",3:"#e7eefc",4:"#eef1fb",5:"#fff3d6",6:"#ffe8cc",7:"#f0e7fb",8:"#fde9ef"}
trs=[]
for r in rows:
    bg=casecolor.get(r["case"],"#fff")
    trs.append(f'<tr style="background:{bg}">'+td(r["tc"])+td(r["pnr_id"])+td(f'Case {r["case"]}: {r["scenario"]}')+td(r["country"])+td(r["language"])+td(r["method"])+td(r["trigger"])+td(r["status"],"el")+td(r["syscode"])+td(f'{r["amount"]} {r["currency"]}')+td(r["date"])+td(r["pax"])+td(r["ticket"])+"</tr>")
hdr="".join(f"<th>{h}</th>" for h in ["Case","PNR ID","Payout Scenario","Country of Residence","Language","Payout Method / Rail","In-flow Trigger","Verdict","SystemCode","Amount","Flight Date","Passenger","Ticket"])
from collections import Counter
cc=Counter(r["currency"] for r in rows)
docx=f"""<!doctype html><meta charset=utf-8><title>{base}</title>
<style>body{{font-family:-apple-system,Arial,sans-serif;margin:22px;color:#182430}}h1{{font-size:20px;margin-bottom:2px}}.sub{{color:#555;font-size:12.5px;margin-bottom:8px}}
.s{{background:#eef7ee;border:1px solid #cfe3cf;border-radius:6px;padding:10px 14px;margin:10px 0;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:11.5px}}th,td{{border:1px solid #dce0e6;padding:5px 7px;vertical-align:top}}th{{background:#22344a;color:#fff;position:sticky;top:0;text-align:left}}
td.el{{color:#176117;font-weight:600}}</style>
<h1>FD 'Ask AC' — 24 Payout-Routing Test PNRs (8 scenarios × 3) — BAT</h1>
<div class=sub>Generated {NOW} · {html.escape(label)} · account 209479273605 · DOB 1986-04-23</div>
<div class=s><b>How to test:</b> every PNR is <b>ELIGIBLE</b> (compensation approved). The payout <b>rail</b> is
NOT in the PNR/DDS — it is derived downstream from <b>country of residence</b>, captured in-flow via
<code>paymentContact.countryOfResidenceCode</code> (or supplied on pre-auth) → <code>claim_ref.country_payment_capability</code>.
For each PNR, run the claim and supply the <b>Country of Residence</b> + <b>Language</b> (+ the <b>In-flow Trigger</b> for the
cheque/no-banking fallbacks) shown below; confirm the offered rail matches <b>Payout Method / Rail</b>.
<br><b>Currency-matched eligibility</b>: Case 5 = EU EUR (FD-EU-EL-09 €400), Case 6 = GBP (FD-EU-EL-03 £260),
all others = APPR CAD 400 (no matching DDS currency for US/AU/JP/CH/BR/AR/NG — payout rail converts). Amounts by currency: {dict(cc)}.</div>
{chk}
<table><thead><tr>{hdr}</tr></thead><tbody>{''.join(trs)}</tbody></table>"""
open(f"{OUT}/{base}.html","w").write(docx)
print(f"{base}: {len(rows)} rows -> {OUT}/{base}.{{html,csv}}")
