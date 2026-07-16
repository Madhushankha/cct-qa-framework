"""Render a per-case ALTEA fixture from the framework-owned base template + a gap-doc UseCase.

This is the framework's port of the scenario engine (HOWTO §4 `scenario_engine.py`, contrail
`PnrSynthesizer`): load the committed base template under `data/fd-templates/<family>/`, then
text-rewrite the base's identity fields to the case's OWN gap-doc data — its dataset 6-char locator,
independent passenger name, route, flight date, delay, and a run-unique ticket. No reference-corpus
cloning: every value comes from the base template (structure) + the parsed catalog (identity).

The base template carries its source values in `meta.json` (locator/date/ticket/surname/first/
route/flight/fdm_spec); those are the strings replaced across 01_pnr.json, 02_ticket*.json and the
FDM XML legs — the same whole-string replacement the cloner uses, so every `<locator>-<date>-*`
derived id stays internally consistent.
"""
from __future__ import annotations

import json
from pathlib import Path

from seed.clone import ac_docnum

# systemCode amount -> FDM delay minutes (APPR tiers): 400=3-6h, 700=6-9h, 1000=9h+.
_TIER_DELAY = {400: 240, 700: 420, 1000: 600}


def _split_passenger(full: str) -> tuple[str, str]:
    """'YANNICK THORNENLOW' -> ('YANNICK', 'THORNENLOW'); single token -> ('', token)."""
    toks = (full or "").strip().upper().split()
    return (" ".join(toks[:-1]), toks[-1]) if len(toks) >= 2 else ("", (full or "").strip().upper())


def _delay_for(case) -> int:
    amt = (case.seed.amount or {})
    try:
        return _TIER_DELAY.get(int(amt.get("value", 0)), 240)
    except (TypeError, ValueError):
        return 240


def render_case(base_dir, out_root, case, *, contact_email: str, flight_date: str,
                index: int = 1) -> Path:
    """Render `case` into `out_root/<locator>/` from the base template at `base_dir`.

    Rewrites (source value read from the base `meta.json`):
      - locator      -> case.seed.pnr           (dataset 6-char PNR; carries every derived id)
      - flight date  -> flight_date             (must be in the FD window; >72h past, <14d)
      - ticket docnum-> ac_docnum(index)        (run-unique; ticket dedup has no date suffix)
      - passenger    -> case.seed.passenger     (first + surname, independent per case)
      - route        -> case.seed.route         (departure/arrival airport codes)
      - delay        -> tier(case amount)       (FDM delayTime minutes)
      - contact email-> contact_email           (the OTP-gating eds contact)
    Returns the rendered fixture dir.
    """
    base = Path(base_dir)
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))

    src_loc = meta["locator"]
    src_date = str(meta.get("date") or "")
    src_docnum = str(meta.get("ticket") or "")
    src_first = str(meta.get("first") or "").upper()
    src_sur = str(meta.get("surname") or "").upper()
    src_route = str(meta.get("route") or "")
    src_delay = str(_TIER_DELAY.get(400, 240))

    new_loc = case.seed.pnr
    new_first, new_sur = _split_passenger(case.seed.passenger)
    new_docnum = ac_docnum(index)
    new_delay = str(_delay_for(case))

    # route: "YYZ-LHR" -> ("YYZ", "LHR"); rewrite each airport code independently.
    src_o, src_d = (src_route.split("-") + ["", ""])[:2]
    new_o, new_d = ((case.seed.route or src_route).split("-") + ["", ""])[:2]

    def _retext(text: str) -> str:
        text = text.replace(src_loc, new_loc)
        if src_docnum:
            text = text.replace(src_docnum, new_docnum)
        if src_date and flight_date:
            text = text.replace(src_date, flight_date)
        if src_sur and new_sur and len(src_sur) >= 3:
            text = text.replace(src_sur, new_sur)
        if src_first and new_first and len(src_first) >= 3:
            text = text.replace(src_first, new_first)
        if src_o and new_o and src_o != new_o:
            text = text.replace(f">{src_o}<", f">{new_o}<")
        if src_d and new_d and src_d != new_d:
            text = text.replace(f">{src_d}<", f">{new_d}<")
        if src_delay != new_delay:
            text = text.replace(f"<delayTime>{src_delay}</delayTime>",
                                f"<delayTime>{new_delay}</delayTime>")
        return text

    dst = Path(out_root) / new_loc
    dst.mkdir(parents=True, exist_ok=True)

    pnr = json.loads(_retext((base / "01_pnr.json").read_text(encoding="utf-8")))
    _set_contact(pnr, contact_email)
    (dst / "01_pnr.json").write_text(json.dumps(pnr, ensure_ascii=False), encoding="utf-8")

    for tf in sorted(base.glob("02_ticket*.json")):
        obj = json.loads(_retext(tf.read_text(encoding="utf-8")))
        (dst / tf.name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    for xf in sorted(base.glob("*.xml")):
        (dst / xf.name).write_text(_retext(xf.read_text(encoding="utf-8")), encoding="utf-8")

    new_meta = dict(meta)
    new_meta.update({
        "locator": new_loc,
        "pnr_id": f"{new_loc}-{flight_date}",
        "date": flight_date,
        "ticket": new_docnum,
        "tickets": [new_docnum],
        "first": new_first or meta.get("first"),
        "surname": new_sur or meta.get("surname"),
        "route": case.seed.route or src_route,
        "email": contact_email,
        "system_code": case.system_code or case.seed.system_code,
        "rendered_from": src_loc,
        "case_id": case.id,
    })
    if meta.get("leg_id") and src_date and flight_date:
        new_meta["leg_id"] = meta["leg_id"].replace(src_date, flight_date)
    (dst / "meta.json").write_text(json.dumps(new_meta, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return dst


def _set_contact(pnr: dict, email: str) -> int:
    changed = 0
    for c in (pnr.get("processedPnr", {}).get("contacts") or []):
        em = c.get("email")
        if isinstance(em, dict):
            em["address"] = email
            changed += 1
    return changed
