#!/usr/bin/env python3
"""Generate HTML + CSV reports for the BAT FD test-data sets, merging the build
index with the live endpoint verification results."""
import json, csv, html, sys, datetime, os

FD=f"{KB}/scenarios/fd-sit"
WORK="/tmp/cctqa-datagen/bat_work"
OUT=os.environ.get("REPORT_OUT","/Users/chathuranga/Downloads"); os.makedirs(OUT, exist_ok=True)
NOW=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

SETS={
 "elig91": dict(idx=f"{FD}/_FD_ELIG91_bat_index.json", verify=f"{WORK}/elig91_verify.json",
                base="FD_TC_ELIG91_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT)",
                idcol=("tc","Test Case")),
 "sit44":  dict(idx=f"{FD}/_FD_SIT44_bat_index.json",  verify=f"{WORK}/sit44_verify.json",
                base="FD_SIT44_BAT", title="FD 'Ask AC' — 44 Eligible SIT Cases (CHAI-21271) (BAT)",
                idcol=("sit","SIT Case")),
 "batch69": dict(idx=f"{FD}/_FD_BATCH69_bat_index.json", verify=f"{WORK}/batch69_verify.json",
                base="FD_TC_BATCH69_BAT", title="FD 'Ask AC' — 69 UAT Cases from Miro Gap Analysis (BAT)",
                idcol=("tc","Test Case")),
 "elig91b": dict(idx=f"{FD}/_FD_ELIG91B_bat_index.json", verify=f"{WORK}/elig91b_verify.json",
                base="FD_TC_ELIG91B_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 2)",
                idcol=("tc","Test Case")),
 "elig91c": dict(idx=f"{FD}/_FD_ELIG91C_bat_index.json", verify=f"{WORK}/elig91c_verify.json",
                base="FD_TC_ELIG91C_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 3)",
                idcol=("tc","Test Case")),
 "tc19":    dict(idx=f"{FD}/_FD_TC19_bat_index.json", verify=f"{WORK}/tc19_verify.json",
                base="FD_TC_019_BAT", title="FD 'Ask AC' — FD_TC_019 (APPR 6–<9h AC Wallet, CAD700) (BAT)",
                idcol=("tc","Test Case")),
 "elig91d": dict(idx=f"{FD}/_FD_ELIG91D_bat_index.json", verify=f"{WORK}/elig91d_verify.json",
                base="FD_TC_ELIG91D_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 4)",
                idcol=("tc","Test Case")),
 "tc19b":   dict(idx=f"{FD}/_FD_TC19B_bat_index.json", verify=f"{WORK}/tc19b_verify.json",
                base="FD_TC_019_BAT_2", title="FD 'Ask AC' — FD_TC_019 #2 (APPR 6–<9h AC Wallet, CAD700) (BAT)",
                idcol=("tc","Test Case")),
 "elig91e": dict(idx=f"{FD}/_FD_ELIG91E_bat_index.json", verify=f"{WORK}/elig91e_verify.json",
                base="FD_TC_ELIG91E_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 5)",
                idcol=("tc","Test Case")),
 "tc119":   dict(idx=f"{FD}/_FD_TC119_bat_index.json", verify=f"{WORK}/tc119_verify.json",
                base="FD_TC_119_BAT", title="FD 'Ask AC' — FD_TC_119 (ASL No-Travel Return, ILS 3670) (BAT)",
                idcol=("tc","Test Case")),
 "tc119x5": dict(idx=f"{FD}/_FD_TC119X5_bat_index.json", verify=f"{WORK}/tc119x5_verify.json",
                base="FD_TC_119_BAT_x5", title="FD 'Ask AC' — FD_TC_119 ×5 (ASL No-Travel Return, ILS 3670) (BAT)",
                idcol=("tc","Test Case")),
 "elig91f": dict(idx=f"{FD}/_FD_ELIG91F_bat_index.json", verify=f"{WORK}/elig91f_verify.json",
                base="FD_TC_ELIG91F_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 6)",
                idcol=("tc","Test Case")),
 "elig91g": dict(idx=f"{FD}/_FD_ELIG91G_bat_index.json", verify=f"{WORK}/elig91g_verify.json",
                base="FD_TC_ELIG91G_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 7)",
                idcol=("tc","Test Case")),
 "elig91h": dict(idx=f"{FD}/_FD_ELIG91H_bat_index.json", verify=f"{WORK}/elig91h_verify.json",
                base="FD_TC_ELIG91H_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 8)",
                idcol=("tc","Test Case")),
 "elig91i": dict(idx=f"{FD}/_FD_ELIG91I_bat_index.json", verify=f"{WORK}/elig91i_verify.json",
                base="FD_TC_ELIG91I_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 9)",
                idcol=("tc","Test Case")),
 "elig91cp": dict(idx=f"{FD}/_FD_ELIG91CP_bat_index.json", verify=f"{WORK}/elig91cp_verify.json",
                base="FD_TC_ELIG91CP_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases + Aeroplan Loyalty / CP Profile (BAT — Diana)",
                idcol=("tc","Test Case")),
 "elig91j": dict(idx=f"{FD}/_FD_ELIG91J_bat_index.json", verify=f"{WORK}/elig91j_verify.json",
                base="FD_TC_ELIG91J_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 11)",
                idcol=("tc","Test Case")),
 "elig91k": dict(idx=f"{FD}/_FD_ELIG91K_bat_index.json", verify=f"{WORK}/elig91k_verify.json",
                base="FD_TC_ELIG91K_BAT", title="FD 'Ask AC' — 91 Eligible UAT Cases (BAT — Set 12)",
                idcol=("tc","Test Case")),
 "wallet2": dict(idx=f"{FD}/_FD_WALLET2_bat_index.json", verify=f"{WORK}/wallet2_verify.json",
                base="FD_TC_WALLET2_BAT", title="FD 'Ask AC' — AC Wallet cases FD_TC_002 + FD_TC_019 (+ Aeroplan loyalty) (BAT)",
                idcol=("tc","Test Case")),
}
def env_note(rows):  # contact derived from the set's own data
    c=rows[0] if rows else {}
    return ("BAT — account 209479273605 · trip-tracer proxy bat-cac1 · "
            "DDS rule-engine endpoint rule-engine-platform-service.ac-cct-bat.cloud.aircanada.com · "
            f"contact {c.get('email','')} / {c.get('phone','')} · DOB 1986-04-23")

def pnr_type(r):
    """Booking composition, read from the case's source scenario (pax + leg count)."""
    try:
        s=json.load(open(f"{FD}/{r.get('src_scn') or r['pnr_id']}.json"))
        npax=len(s["passengers"]); nseg=len(s["segments"])
    except Exception:
        npax,nseg=1,1
    if r.get("group"): base=f"Group PNR ({npax} pax)"
    elif npax>1:       base=f"Multi-pax ({npax} pax)"
    else:              base="Single pax"
    return base + (f" · {nseg}-leg" if nseg>1 else " · 1-leg")

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
        rows.append(dict(r, pnr_type=pnr_type(r), endpoint=ep, eligible=bool(v.get("ok")), note="; ".join(note)))
    return cfg,rows

def write_csv(cfg,setname,rows):
    p=f"{OUT}/{cfg['base']}.csv"
    cols=[cfg["idcol"][0]] + ["sit","src_tc","pnr_id","loc","pax","pnr_type","loyalty_id","cp_account",
          "route","ticket","status","syscode",
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
    has_loy=any(r.get("loyalty_id") for r in rows)
    head=[idlbl] + (["Src TC"] if setname=="sit44" else []) + \
         ["PNR ID","Locator","Passenger","PNR Type"] + \
         (["LoyaltyMembershipId","CP AccountNumber"] if has_loy else []) + \
         ["Route","Ticket","Status","SysCode","Amount","Cur","Endpoint result","Notes"]
    def td(x,cls=""): return f'<td class="{cls}">{html.escape(str(x))}</td>'
    trs=[]
    for r in rows:
        cls="ok" if r["eligible"] else "bad"
        cells=[td(r.get(idk,""))]
        if setname=="sit44": cells.append(td(r.get("tc","")))
        cells+= [td(r["pnr_id"]),td(r["loc"]),td(r["pax"]),td(r.get("pnr_type",""))]
        if has_loy: cells+= [td(r.get("loyalty_id") or "—"),td(r.get("cp_account") or "—")]
        cells+= [td(r.get("route","")),td(r["ticket"]),
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
<div class="summary"><b>{elig}/{n} ELIGIBLE</b> at the live BAT DDS endpoint
(<code>/rule-engine/dds/output/&lt;pnrId&gt;</code>). All bookings cascaded to trip-tracer with ticket + DOB;
DDS verdicts pinned via execution_traces (S3 <code>cct-ask-ac-bat-logs</code>). Ticket series
<code>{rows[0]['ticket'][:6]}xxxxxx</code>.{(" Each PNR carries an Aeroplan FQTV membership (<code>PNRBooking.LoyaltyMembershipId</code> in <code>loyaltyRequests.membership.number</code>); the same 9-digit value is assigned as the <b>CP standard-profile AccountNumber</b> (one member identity). NOTE: the numbers are stamped on the PNR + reported here; provisioning the matching profile records in the customer-profile / Gigya store is a separate step." if any(r.get('loyalty_id') for r in rows) else "")}</div>
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
