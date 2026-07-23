#!/usr/bin/env python3
"""Generate HTML + CSV reports for the CRT FD test-data sets, merging the build
index with the live endpoint verification results."""
import json, csv, html, sys, datetime

FD=f"{KB}/scenarios/fd-sit"
WORK="/tmp/cctqa-datagen/crt_work"
OUT="/Users/chathuranga/Downloads"
NOW=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

SETS={
 "elig91": dict(idx=f"{FD}/_FD_ELIG91_crt_index.json", verify=f"{WORK}/elig91_verify.json",
                base="FD_TC_ELIG91_CRT", title="FD 'Ask AC' — 91 Eligible UAT Cases (CRT)",
                idcol=("tc","Test Case")),
 "sit44":  dict(idx=f"{FD}/_FD_SIT44_crt_index.json",  verify=f"{WORK}/sit44_verify.json",
                base="FD_SIT44_CRT", title="FD 'Ask AC' — 44 Eligible SIT Cases (CHAI-21271) (CRT)",
                idcol=("sit","SIT Case")),
 "elig91m": dict(idx=f"{FD}/_FD_ELIG91_crt_marizza_index.json", verify=f"{WORK}/elig91m_verify.json",
                base="FD_TC_ELIG91_CRT_marizza", title="FD 'Ask AC' — 91 Eligible UAT Cases (CRT, set 2)",
                idcol=("tc","Test Case")),
 "elig91c": dict(idx=f"{FD}/_FD_ELIG91_crt_set3_index.json", verify=f"{WORK}/elig91c_verify.json",
                base="FD_TC_ELIG91_CRT_set3", title="FD 'Ask AC' — 91 Eligible UAT Cases (CRT, set 3)",
                idcol=("tc","Test Case")),
 "elig91d": dict(idx=f"{FD}/_FD_ELIG91_crt_set4_index.json", verify=f"{WORK}/elig91d_verify.json",
                base="FD_TC_ELIG91_CRT_set4", title="FD 'Ask AC' — 91 Eligible UAT Cases (CRT, set 4)",
                idcol=("tc","Test Case")),
}
def env_note(rows):
    contact=f"{rows[0].get('email')} / {rows[0].get('phone')}" if rows else "—"
    return ("CRT — account 050752605169 (profile ac-cct-crt) · trip-tracer cluster crt-cac1 · "
            "DDS rule-engine endpoint rule-engine-platform-service-be.ac-cct-crt.cloud.aircanada.com · "
            f"contact {contact} · DOB 1986-04-23")

def load(setname):
    cfg=SETS[setname]
    recs=json.load(open(cfg["idx"]))
    try: ver={v["pnr_id"]:v for v in json.load(open(cfg["verify"]))}
    except FileNotFoundError: ver={}
    rows=[]
    for r in recs:
        v=ver.get(r["pnr_id"],{})
        ep = ("ELIGIBLE %s %s (%s)"%(v.get("amount"),v.get("currency"),v.get("syscode"))) if v.get("ok") \
             else ("FAIL: %s"%(v.get("detail") or ("HTTP %s"%v.get("http")))) if v else "—"
        note=[]
        if r.get("forced"): note.append("TC063 forced-eligible (pre-travel case)")
        if r.get("group"): note.append("GROUP booking")
        rows.append(dict(r, endpoint=ep, eligible=bool(v.get("ok")), note="; ".join(note)))
    return cfg,rows

def write_csv(cfg,setname,rows):
    p=f"{OUT}/{cfg['base']}.csv"
    cols=[cfg["idcol"][0]] + ["sit","src_tc","pnr_id","loc","pax","route","ticket","status","syscode",
          "amount","currency","email","phone","group","endpoint","note"]
    seen=set(); cols=[c for c in cols if not (c in seen or seen.add(c))]
    with open(p,"w",newline="") as f:
        w=csv.writer(f); w.writerow(cols)
        for r in rows:
            r2=dict(r); r2["src_tc"]=r.get("tc")
            w.writerow([r2.get(c,"") for c in cols])
    return p

def write_html(cfg,setname,rows):
    idk,idlbl=cfg["idcol"]
    elig=sum(1 for r in rows if r["eligible"]); n=len(rows)
    head=[idlbl] + (["Src TC"] if setname=="sit44" else []) + \
         ["PNR ID","Locator","Passenger","Route","Ticket","Status","SysCode","Amount","Cur",
          "Endpoint result","Notes"]
    def td(x,cls=""): return f'<td class="{cls}">{html.escape(str(x))}</td>'
    trs=[]
    for r in rows:
        cls="ok" if r["eligible"] else "bad"
        cells=[td(r.get(idk,""))]
        if setname=="sit44": cells.append(td(r.get("tc","")))
        cells+= [td(r["pnr_id"]),td(r["loc"]),td(r["pax"]),td(r.get("route","")),td(r["ticket"]),
                 td(r["status"]),td(r["syscode"]),td(r["amount"]),td(r["currency"]),
                 td(r["endpoint"],cls),td(r.get("note",""))]
        trs.append("<tr>"+"".join(cells)+"</tr>")
    p=f"{OUT}/{cfg['base']}.html"
    doc=f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(cfg['title'])}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:24px;color:#1a1a1a}}
h1{{font-size:20px;margin-bottom:2px}} .sub{{color:#555;font-size:13px;margin-bottom:10px}}
.summary{{background:#f2f7f2;border:1px solid #cfe3cf;border-radius:6px;padding:10px 14px;margin:12px 0;font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid #ddd;padding:5px 7px;text-align:left;vertical-align:top}}
th{{background:#2a3b4d;color:#fff;position:sticky;top:0}}
tr:nth-child(even){{background:#fafafa}}
td.ok{{background:#e6f5e6;color:#176117;font-weight:600}} td.bad{{background:#fdecec;color:#a11;font-weight:600}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>{html.escape(cfg['title'])}</h1>
<div class="sub">Generated {NOW} · {env_note(rows)}</div>
<div class="summary"><b>{elig}/{n} ELIGIBLE</b> at the live CRT DDS endpoint
(<code>/rule-engine/dds/output/&lt;pnrId&gt;</code>). All bookings cascaded to trip-tracer with ticket + DOB;
DDS verdicts pinned via execution_traces (S3 <code>cct-ask-ac-crt-logs</code>). Ticket series
<code>{rows[0]['ticket'][:6]}xxxxxx</code>.</div>
<table><thead><tr>{''.join(f'<th>{html.escape(h)}</th>' for h in head)}</tr></thead>
<tbody>{''.join(trs)}</tbody></table></body></html>"""
    open(p,"w").write(doc)
    return p,elig,n

def main():
    for setname in (sys.argv[1:] or ["elig91","sit44"]):
        cfg,rows=load(setname)
        c=write_csv(cfg,setname,rows); h,elig,n=write_html(cfg,setname,rows)
        print(f"{setname}: {elig}/{n} ELIGIBLE -> {h} | {c}")

if __name__=="__main__": main()
