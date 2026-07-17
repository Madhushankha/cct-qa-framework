"""Fresh-locator fixture cloning — produce a new, never-seeded fixture from a source preseed
fixture so it can be pushed to a live env without colliding with an already-consumed PNR.

Why this exists: on INT a PNR-CREATE dedups on `pnr_id`, and a claimed PNR is single-use (re-running
it makes the bot escalate). To run a case cleanly we need a FRESH locator. Every derived id in the
fixtures is prefixed by the locator (`<LOC>-<date>-ST-1`, `-PT-1`, `-TKT`, ...), so replacing the
locator string rewrites them all consistently. The ticket document number is replaced with a
run-unique value (the ticket dedup key has no date suffix), and the contact email is set to the
env's mailinator inbox so the OTP lands where the runner reads it.

The clone is written to a scratch output root — never back into the source corpus.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def ac_docnum(index: int) -> str:
    """A synthetic, run-unique 13-digit Air Canada (014) e-ticket number for clone `index`."""
    return f"014{9000000000 + index:010d}"


def clone_fixture(src_dir, out_root, new_locator: str, *, contact_email: str,
                  new_docnum: str | None = None, index: int = 1,
                  pnr_version: str | None = None, new_date: str | None = None) -> Path:
    """Clone the fixture at `src_dir` into `out_root/<new_locator>/`, rewriting:
      - the source locator string -> `new_locator` (across 01_pnr.json + 02_ticket*.json), which
        carries every `<LOC>-<date>-*` derived id with it;
      - the source ticket document number -> `new_docnum` (default: ac_docnum(index));
      - the source flight date -> `new_date` (across JSON *and* the FDM XML timestamps) when given —
        required so the flight lands inside the FD data window (>72h past, <14 days ago); a stale date
        is dropped by trip ingestion;
      - the PNR contact email -> `contact_email`;
      - `processedPnr.version` -> `pnr_version` if given.
    Returns the new fixture dir.
    """
    src = Path(src_dir)
    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    src_loc = meta["locator"]
    src_docnum = str(meta.get("ticket") or "")
    src_date = str(meta.get("date") or "")
    new_docnum = new_docnum or ac_docnum(index)

    dst = Path(out_root) / new_locator
    dst.mkdir(parents=True, exist_ok=True)

    def _retext(text: str) -> str:
        text = text.replace(src_loc, new_locator)
        if src_docnum:
            text = text.replace(src_docnum, new_docnum)
        if new_date and src_date:
            text = text.replace(src_date, new_date)
        return text

    def _rewrite_json(name: str) -> None:
        obj = json.loads(_retext((src / name).read_text(encoding="utf-8")))
        if name == "01_pnr.json":
            _set_contact(obj, contact_email)
            if pnr_version:
                obj["processedPnr"]["version"] = str(pnr_version)
        (dst / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    _rewrite_json("01_pnr.json")
    for tf in sorted(src.glob("02_ticket*.json")):
        _rewrite_json(tf.name)
    for xf in sorted(src.glob("*.xml")):
        # date-shift the FDM XML timestamps too (the leg schedule/delay times are date-baked)
        (dst / xf.name).write_text(_retext(xf.read_text(encoding="utf-8")), encoding="utf-8")

    date = new_date or src_date
    new_meta = dict(meta)
    new_meta["locator"] = new_locator
    new_meta["pnr_id"] = f"{new_locator}-{date}" if date else new_locator
    new_meta["date"] = date
    if meta.get("leg_id") and src_date and new_date:
        new_meta["leg_id"] = meta["leg_id"].replace(src_date, new_date)
    new_meta["ticket"] = new_docnum
    new_meta["tickets"] = [new_docnum]
    new_meta["email"] = contact_email
    new_meta["cloned_from"] = src_loc
    (dst / "meta.json").write_text(json.dumps(new_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def _set_contact(pnr: dict, email: str) -> int:
    changed = 0
    for c in (pnr.get("processedPnr", {}).get("contacts") or []):
        em = c.get("email")
        if isinstance(em, dict):
            em["address"] = email
            changed += 1
    return changed


def clone_batch(src_root, out_root, mapping, *, contact_email: str,
                pnr_version: str | None = None, start_index: int = 1) -> list[Path]:
    """Clone many fixtures. `mapping` is an ordered list of (src_locator, new_locator) pairs.
    Ticket doc numbers are assigned sequentially from `start_index`. Returns the new fixture dirs."""
    src_root = Path(src_root)
    dirs = []
    for i, (src_loc, new_loc) in enumerate(mapping):
        dirs.append(clone_fixture(
            src_root / src_loc, out_root, new_loc,
            contact_email=contact_email, index=start_index + i, pnr_version=pnr_version))
    return dirs
