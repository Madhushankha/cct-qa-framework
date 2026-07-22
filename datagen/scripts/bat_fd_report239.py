#!/usr/bin/env python3
"""Detailed FD 239 report. Per case: Family, PNR Type (pax+legs), Status, Regime, SystemCode,
Reason(DDS), Amount, Flight Date, Route(booking segments), Delay/Code(DDS), Payment, Loyalty/CP,
Flow, Passenger, Ticket, Group. Header carries the checkpoint result + summary + edge/high-value
notes. Usage: bat_fd_report239.py <set_index.json> <base_name> <label> [<checkpoint_log>] [<out_dir>]"""
import json,html,csv,re,os,sys,datetime
FD=f"{KB}/scenarios/fd-sit"
idxf,base,label=sys.argv[1],sys.argv[2],sys.argv[3]
chklog=sys.argv[4] if len(sys.argv)>4 else ""
OUT=sys.argv[5] if len(sys.argv)>5 else "/Users/chathuranga/Downloads/BAT Data Sets"
os.makedirs(OUT,exist_ok=True)
NOW=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
idx=json.load(open(idxf))
doc=open("/Users/chathuranga/Downloads/FD_UAT_Miro_Gap_Analysis.html",encoding="utf-8").read()
gap={}
for m in re.finditer(r'<section class="card" id="((?:FD_TC|FD_PAY_TC|FD_ED_TC)_[0-9]+)"[^>]*>',doc):
    b=doc[m.end():m.end()+3500]; d={}
    for dk,dv in re.findall(r'<div class="dk">(.*?)</div><div class="dv[^"]*">(.*?)</div>',b):
        d[html.unescape(dk).strip()]=html.unescape(re.sub('<[^>]+>','',dv)).strip()
    nm=re.search(r'<span class="tcname">([^<]*)</span>',b)
    gap[m.group(1)]=dict(payment=d.get("Payment",""),name=html.unescape(nm.group(1)) if nm else "")
_c={}
def scen(src):
    if src not in _c:
        try:_c[src]=json.load(open(f"{FD}/{src}.json"))
        except:_c[src]={"passengers":[{}],"segments":[{}]}
    return _c[src]
_r={}
def dds_primary(src):
    if src not in _r:
        try:
            pe=json.load(open(f"{FD}/_dds-templates/{src}.dds.json"))["compensationEligibility"][0]["passengerEligibility"][0]
            _r[src]=pe.get("reason") or ""
        except:_r[src]=""
    return _r[src]
_dl={}
def dds_delay(src):
    if src not in _dl:
        out=""
        try:
            dd=json.load(open(f"{FD}/_dds-templates/{src}.dds.json"))
            ce=(dd.get("compensationEligibility") or [{}])[0]; dmin=ce.get("delayMinutes"); dcode=ce.get("delayCode")
            if not dcode or (dmin in (None,0)):
                for soc in dd.get("socFlightEligibility",[]):
                    if soc.get("delayMinutes"): dmin=dmin or soc.get("delayMinutes")
                    if soc.get("delayCode"): dcode=dcode or soc.get("delayCode")
            parts=[]
            if dmin is not None: parts.append(f"{dmin}m")
            if dcode: parts.append(f"code {dcode}")
            out=" / ".join(parts)
        except:out=""
        _dl[src]=out
    return _dl[src]
def route_of(src):
    s=scen(src); segs=s.get("segments",[])
    return "-".join([segs[0].get("origin","")]+[sg.get("destination","") for sg in segs]) if segs else ""
reg=lambda sc:("APPR" if "-APPR-" in sc else "EU" if "-EU-" in sc else "ASL" if "-ASL-" in sc else "MIXED" if "-MIXED-" in sc else "—")
fam=lambda t:"Main" if t.startswith("FD_TC") else "Payment" if t.startswith("FD_PAY") else "Edge"
scls={"NOT_ELIGIBLE":"ne","NO_DETERMINATION":"nd","PENDING":"pe","ELIGIBLE":"el","PRE-TRAVEL":"pt"}
from collections import Counter
rows=[]
for r in idx:
    s=scen(r["src_scn"]); npax=r.get("npax") or len(s["passengers"]); nseg=len(s.get("segments",[{}]))
    pt=(f"Group ({npax} pax)" if r.get("group") else f"Multi-pax ({npax})" if npax>1 else "Single pax")+(f" · {nseg}-leg" if nseg>1 else " · 1-leg")
    g=gap.get(r["tc"],{}); reason=dds_primary(r["src_dds"]); st=r["status"] or "PRE-TRAVEL"
    if r["tc"]=="FD_TC_063": reason="Customer submitted before flight — no DDS (rejected)"
    rows.append(dict(tc=r["tc"],pnr_id=r["pnr_id"],loc=r.get("loc",""),fam=fam(r["tc"]),ptype=pt,status=st,regime=reg(r["syscode"]) if r["syscode"] else "—",
        syscode=r["syscode"] or "—",reason=reason,amount=r["amount"],currency=r["currency"],date=r["date"],
        route=route_of(r["src_scn"]) or r.get("route",""),delaycode=dds_delay(r["src_dds"]),
        payment=g.get("payment","") or ("Cash/Interac (default)" if st=="ELIGIBLE" and r["tc"].startswith("FD_TC") else ""),
        loyalty=r.get("loyalty_id") or "",cp=r.get("cp_account") or "",flow=g.get("name",""),
        pax=r.get("pax_set") or r["pax"],ticket=r["ticket"],group="GROUP" if r.get("group") else "",
        edge=r["date"]!="2026-06-15",hv=(r["tc"]=="FD_PAY_TC_010")))
order={"ELIGIBLE":0,"PENDING":1,"NO_DETERMINATION":2,"NOT_ELIGIBLE":3,"PRE-TRAVEL":4}
rows.sort(key=lambda r:(order.get(r["status"],9),r["fam"],r["tc"]))
cols=["tc","pnr_id","loc","fam","ptype","status","regime","syscode","reason","amount","currency","date","route","delaycode","payment","loyalty","cp","flow","pax","ticket","group"]
with open(f"{OUT}/{base}.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(cols); [w.writerow([r[c] for c in cols]) for r in rows]
chk=""
if chklog and os.path.exists(chklog):
    chk="<pre style='background:#0f1c2e;color:#d7e3f4;padding:10px 14px;border-radius:6px;font-size:12px;overflow:auto'>"+html.escape(open(chklog).read().replace("CDONE","").strip())+"</pre>"
def td(x,c=""):return f'<td class="{c}">{html.escape(str(x))}</td>'
trs=[]
for r in rows:
    rc=' style="background:#fff7e6"' if (r["edge"] or r["hv"]) else ''
    trs.append(f"<tr{rc}>"+td(r["tc"])+td(r["pnr_id"])+td(r["fam"])+td(r["ptype"])+td(r["status"],scls.get(r["status"],""))+td(r["regime"])+td(r["syscode"])+td(r["reason"])+td(f'{r["amount"]} {r["currency"]}' if r["amount"] else "—")+td(r["date"],"edge" if r["edge"] else "")+td(r["route"])+td(r["delaycode"])+td(r["payment"])+td(r["loyalty"] or "—")+td(r["cp"] or "—")+td(r["flow"])+td(r["pax"])+td(r["ticket"])+td(r["group"])+"</tr>")
sd=Counter(r["status"] for r in rows); fd=Counter(r["fam"] for r in rows); rd=Counter(r["regime"] for r in rows); pdc=Counter(r["ptype"].split(" · ")[0] for r in rows)
hdr="".join(f"<th>{h}</th>" for h in ["Case","PNR ID","Family","PNR Type","Status","Regime","SystemCode","Reason (DDS)","Amount","Flight Date","Route","Delay/Code","Payment","Loyalty (FQTV)","CP Account","Flow","Passenger","Ticket","Group"])
docx=f"""<!doctype html><meta charset=utf-8><title>{base}</title>
<style>body{{font-family:-apple-system,Arial,sans-serif;margin:22px;color:#182430}}h1{{font-size:20px;margin-bottom:2px}}.sub{{color:#555;font-size:12.5px;margin-bottom:8px}}
.s{{background:#eef7ee;border:1px solid #cfe3cf;border-radius:6px;padding:10px 14px;margin:10px 0;font-size:13px}}
.grid{{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}}.chip{{background:#f0f3f7;border:1px solid #d6dee8;border-radius:14px;padding:3px 10px;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:11px}}th,td{{border:1px solid #dce0e6;padding:4px 6px;vertical-align:top}}th{{background:#22344a;color:#fff;position:sticky;top:0;text-align:left}}
td.el{{background:#e6f5e6;color:#176117;font-weight:600}}td.ne{{background:#fdecec;color:#a11;font-weight:600}}td.nd{{background:#fff3d6;color:#8a5a00;font-weight:600}}td.pe{{background:#e7eefc;color:#2350a8;font-weight:600}}td.pt{{background:#efe7fb;color:#5b3aa8;font-weight:600}}td.edge{{background:#ffe8bf;color:#8a5a00;font-weight:700}}</style>
<h1>FD 'Ask AC' — {len(rows)}-PNR BAT Set — {' · '.join(f'{v} {k}' for k,v in fd.items())}</h1>
<div class=sub>Generated {NOW} · {html.escape(label)} · account 209479273605 · DOB 1986-04-23</div>
<div class=s><b>Coverage &amp; verification:</b>
<div class=grid>
<span class=chip><b>Status</b>: {' · '.join(f'{k} {v}' for k,v in sd.items())}</span>
<span class=chip><b>Family</b>: {' · '.join(f'{k} {v}' for k,v in fd.items())}</span>
<span class=chip><b>Regime</b>: {' · '.join(f'{k} {v}' for k,v in rd.items() if k!='—')}</span>
<span class=chip><b>PNR type</b>: {' · '.join(f'{k} {v}' for k,v in pdc.items())}</span></div>
<b>Date-corrected edge cases</b> (highlighted): FD_TC_063 pre-travel (future→404) · FD_TC_060/116/145 PENDING (≤72h) · FD_TC_039 NOT_ELIGIBLE (&gt;366d). <b>High-value payment</b>: FD_PAY_TC_010 = CAD 9,500. <b>Multi-pax DDS</b>: FD_TC_011=3, FD_TC_012=12 passengerEligibility. Route from booking segments; Delay/Code from DDS; Loyalty only on AC-Wallet cases; NE/ND carry lookup reason + no compensationDetails.</div>
{chk}
<table><thead><tr>{hdr}</tr></thead><tbody>{''.join(trs)}</tbody></table>"""
open(f"{OUT}/{base}.html","w").write(docx)
print(f"{base}: {len(rows)} rows -> {OUT}/{base}.{{html,csv}}")
