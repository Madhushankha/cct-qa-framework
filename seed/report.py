"""Preseed HTML report — the human-readable deliverable a tester uses to run a seeded set.

Reads a seed run's clone dir (one `<locator>/meta.json` per rendered case, plus the run's
`seed-mapping.json` gates and optional `<locator>.checkpoints.json` audit vectors) and renders one
`preseed.html` table: per case the Test Case ID, PNR, full passenger name, the last name + PNR +
OTP email a tester enters into the chatbot, the ticket, flight date, route, systemCode, and the
seed gate result. Pure over the filesystem — no AWS."""
from __future__ import annotations

import json
from pathlib import Path

from evidence.render import CSS, _esc

_COLS = ("Test Case", "PNR", "Passenger", "Last name", "Ticket", "Flight date", "Route",
         "SystemCode", "OTP email", "Gate")


def _gate_of(mapping: dict, locator: str) -> str:
    for e in mapping.get("seeded", []):
        if e.get("locator") == locator:
            return e.get("gate", "")
    return ""


def collect_preseed(clone_dir) -> list[dict]:
    """One row dict per rendered case in the clone dir, sorted by case id."""
    root = Path(clone_dir)
    mp = {}
    mpf = root / "seed-mapping.json"
    if mpf.exists():
        mp = json.loads(mpf.read_text(encoding="utf-8"))
    rows = []
    for meta_f in sorted(root.glob("*/meta.json")):
        m = json.loads(meta_f.read_text(encoding="utf-8"))
        loc = m.get("locator", meta_f.parent.name)
        rows.append({
            "case_id": m.get("case_id", ""), "pnr": loc,
            "passenger": f"{m.get('first', '')} {m.get('surname', '')}".strip(),
            "last_name": m.get("surname", ""), "ticket": m.get("ticket", ""),
            "date": m.get("date", ""), "route": m.get("route", ""),
            "system_code": m.get("system_code", ""), "email": m.get("email", ""),
            "gate": _gate_of(mp, loc),
        })
    return sorted(rows, key=lambda r: r["case_id"])


def _gate_class(gate: str) -> str:
    return "pass" if gate in ("all-pass", "seeded") else ("fail" if gate else "")


def render_preseed(rows: list[dict], *, product: str = "", env: str = "", feed: str = "",
                   date: str = "") -> str:
    head = " · ".join(x for x in (product, env, feed, date) if x)
    n_ok = sum(1 for r in rows if r["gate"] in ("all-pass", "seeded"))
    th = "".join(f"<th>{_esc(c)}</th>" for c in _COLS)
    trs = []
    for r in rows:
        cells = [r["case_id"], r["pnr"], r["passenger"], r["last_name"], r["ticket"], r["date"],
                 r["route"], r["system_code"], r["email"], r["gate"]]
        tds = "".join(f'<td>{_esc(str(v))}</td>' for v in cells[:-1])
        tds += f'<td class="{_gate_class(r["gate"])}">{_esc(r["gate"])}</td>'
        trs.append(f"<tr>{tds}</tr>")
    return (f"{CSS}"
            f"<h1>Preseed — {_esc(head)}</h1>"
            f'<div class="stat">{len(rows)} cases · {n_ok} seeded</div>'
            f"<p>To run a case in the chatbot: enter its <b>PNR</b> + <b>Last name</b>; the OTP goes "
            f"to the <b>OTP email</b>.</p>"
            f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>")


def preseed_filename(product: str, env: str, feed: str, date: str, time: str = "") -> str:
    """Identifiable filename carrying the full run key incl. time, e.g.
    `fd_bravo_int_2026-07-17_143022_preseed.html` — time is included because one day can hold
    several seed runs, so the report stays self-describing and unique even out of its folder."""
    stem = "_".join(x for x in (feed, product, env, date, time) if x)
    return f"{stem}_preseed.html" if stem else "preseed.html"


def build_preseed_report(clone_dir, *, product: str = "", env: str = "", feed: str = "",
                         date: str = "", time: str = "") -> Path:
    rows = collect_preseed(clone_dir)
    html = render_preseed(rows, product=product, env=env, feed=feed, date=date)
    out = Path(clone_dir) / preseed_filename(product, env, feed, date, time)
    out.write_text(html, encoding="utf-8")
    return out
