"""Pure checkpoint-verification logic. Runs against a TripTracerSource (fake or live Aurora), so it
is fully unit-testable offline. Verifies the trip-tracer-backed checkpoints by matching the use-case's
seeded data; areas it can't check in this env are reported as skipped (ok=None), never as failures."""
from __future__ import annotations

import datetime
import re

from catalog.model import UseCase
from seed.model import CheckpointResult, VerifyReport

# checkpoint areas this verifier can confirm against trip-tracer Aurora (read-only).
# Everything else in a feed's checkpoints.areas is reported skipped (ok=None).
_SUPPORTED = {"eds_pnr_output", "eds_contact_email", "trip_active", "trip_details", "passenger",
              "passenger_count", "name_uniqueness", "ticket", "dob",
              "group_context", "ac_wallet_loyalty", "pending_flight_le_72h"}
# PENDING only holds while the flight is inside ±3 days of today (see the reference auditor's
# "PENDING flight≤72h" area): re-audit a PENDING case later and it needs a fresh flight date.
_PENDING_WINDOW_DAYS = 3
# DDS areas — confirmed against the live by-pnr verdict when one is passed in, else skipped.
_DDS_AREAS = {"dds_endpoint_systemcode_match", "dds_amount_match", "ne_nd_reason_text"}


def _last_name(uc: UseCase) -> str:
    p = (uc.seed.passenger or "").strip()
    return p.split()[-1].upper() if p else ""


_PAX_RE = re.compile(r"(\d+)\s*(?:pax|passengers?|travellers?|adults?)", re.IGNORECASE)


def _expected_pax(uc: UseCase) -> int | None:
    """Declared party size for the case, or None when it says nothing. Read from the seed extras
    (`npax`, set by the seeder) first, else from a "3 pax"/"2 passengers" phrase in the title."""
    npax = (uc.seed.extras or {}).get("npax")
    if npax:
        try:
            return int(npax)
        except (TypeError, ValueError):
            pass
    m = _PAX_RE.search(uc.title or "")
    return int(m.group(1)) if m else None


def _is_group(uc: UseCase) -> bool:
    """Group booking — the eds booking_context must carry bookingSubtype=GROUP for the bot to apply
    group handling. Flagged by the seeder in extras, else by the gap-doc title/flags."""
    extras = uc.seed.extras or {}
    if extras.get("group"):
        return True
    blob = f"{uc.title or ''} {' '.join(uc.seed.flags or [])}".lower()
    return "group" in blob


def _wants_loyalty(uc: UseCase) -> bool:
    """AC-Wallet / Aeroplan case whose booking must carry an FQTV membership.

    Gated on the case DECLARING a loyalty id — never on wallet/Aeroplan wording in the title. Many
    eligible cases mention "AC Wallet" only to describe the payout OPTION offered at the end of the
    claim; no membership is seeded for them and none is required. Enforcing on the wording failed 8
    correctly-seeded SIT cases. This mirrors the reference auditor, which computes
    `LOY_SET = any(row loyalty_id)` and skips the area entirely for sets without one."""
    extras = uc.seed.extras or {}
    return bool(extras.get("loyalty_id") or extras.get("cp_account"))


def _check(area: str, uc: UseCase, src, expected_email: str | None, dds: dict | None) -> CheckpointResult:
    pnr = uc.seed.pnr
    if area == "eds_pnr_output":
        ok = src.eds(pnr) is not None
        return CheckpointResult(area, ok, "booking present in eds_pnr_output" if ok else "no eds row")
    if area == "eds_contact_email":
        eds = src.eds(pnr)
        if eds is None:
            return CheckpointResult(area, False, "no eds row")
        if not expected_email:
            return CheckpointResult(area, None, "no expected email supplied")
        emails = [e.lower() for e in eds.get("emails", [])]
        ok = expected_email.lower() in emails
        return CheckpointResult(area, ok, f"contact={emails or 'none'} expected={expected_email}")
    if area == "trip_active":
        trip = src.trip(pnr)
        if trip is None:
            return CheckpointResult(area, False, "no trip row")
        ok = str(trip.get("status", "")).upper() == "ACTIVE"
        return CheckpointResult(area, ok, f"trip.status={trip.get('status')}")
    if area == "trip_details":
        ok = src.trip(pnr) is not None
        return CheckpointResult(area, ok, "trip row present" if ok else "no trip row")
    if area == "passenger":
        trip = src.trip(pnr)
        want = _last_name(uc)
        if trip is None:
            return CheckpointResult(area, False, "no trip row")
        got = str(trip.get("last_name", "")).upper()
        ok = bool(want) and got == want
        return CheckpointResult(area, ok, f"trip.last_name={got} expected={want}")
    if area == "name_uniqueness":
        # A real uniqueness check: every (first, last) on this booking must be exclusive to it —
        # not repeated within the PNR, and not already carried by a passenger on another PNR.
        # (This area used to re-test trip.last_name equality, which duplicated `passenger` and
        # certified nothing, so unique-name sets passed vacuously.)
        names = [n.upper() for n in src.passengers(pnr) if n.strip()]
        if not names:
            return CheckpointResult(area, False, "no passenger rows")
        dupes = {n for n in names if names.count(n) > 1}
        if not hasattr(src, "names_elsewhere"):
            return CheckpointResult(area, None, "source cannot check cross-PNR name collisions")
        elsewhere = {" ".join(p) for p in src.names_elsewhere(pnr)}
        clashes = sorted(dupes | (set(names) & elsewhere))
        ok = not clashes
        return CheckpointResult(area, ok, "names exclusive to this PNR" if ok
                                else f"reused: {', '.join(clashes[:4])}")
    if area == "passenger_count":
        rows = src.passengers(pnr)
        got = len(rows)
        if got == 0:
            return CheckpointResult(area, False, "no passenger rows")
        # When the case declares a party size, the cascade must have landed exactly that many
        # passenger rows — a multi-pax/GROUP booking that silently cascades one row is the failure
        # this area exists to catch.
        want = _expected_pax(uc)
        if want:
            ok = got == want
            return CheckpointResult(area, ok, f"{got} passenger(s) expected={want}")
        return CheckpointResult(area, True, f"{got} passenger(s)")
    if area == "group_context":
        if not _is_group(uc):
            return CheckpointResult(area, None, "not a group booking")
        bc = src.booking_context(pnr) if hasattr(src, "booking_context") else None
        if bc is None:
            return CheckpointResult(area, False, "no booking_context on eds_pnr_output")
        got = str(bc.get("bookingSubtype") or "")
        ok = got.upper() == "GROUP"
        return CheckpointResult(area, ok, f"bookingSubtype={got or 'none'} expected=GROUP")
    if area == "ac_wallet_loyalty":
        if not _wants_loyalty(uc):
            return CheckpointResult(area, None, "not an AC-Wallet/loyalty case")
        ids = src.loyalty(pnr) if hasattr(src, "loyalty") else []
        ok = bool(ids)
        return CheckpointResult(area, ok, f"loyalty={ids[:2]}" if ok else "no FQTV/Aeroplan membership")
    if area == "pending_flight_le_72h":
        from seed.scenario import temporal_intent
        if temporal_intent(uc) != "pending":
            return CheckpointResult(area, None, "not a PENDING case")
        dates = src.flight_dates(pnr) if hasattr(src, "flight_dates") else []
        if not dates:
            return CheckpointResult(area, False, "no flight_segment dates")
        today = datetime.date.today()
        deltas = []
        for d in dates:
            try:
                deltas.append(abs((datetime.date.fromisoformat(str(d)[:10]) - today).days))
            except ValueError:
                continue
        if not deltas:
            return CheckpointResult(area, False, f"unparseable flight dates {dates[:2]}")
        worst = min(deltas)
        ok = worst <= _PENDING_WINDOW_DAYS
        return CheckpointResult(area, ok, f"flight {dates[0]} is {worst}d from today "
                                          f"(window ±{_PENDING_WINDOW_DAYS}d)")
    if area == "ticket":
        ok = len(src.tickets(pnr)) > 0
        return CheckpointResult(area, ok, "ticket row present" if ok else "no ticket")
    if area == "dob":
        d = src.dob(pnr) if hasattr(src, "dob") else None
        ok = bool(d)
        return CheckpointResult(area, ok, f"date_of_birth={d}" if ok else "no DOB")
    if area in _DDS_AREAS:
        return _dds_check(area, uc, dds)
    return CheckpointResult(area, None, "not verifiable by this auditor")


_DISRUPTION_REGIMES = {"APPR", "EU", "UK", "ASL", "MIXED", "DUP"}
_DISRUPTION_CLASSES = {"EL", "NE", "ND", "PE", "DB"}


def _expected_system_code(uc: UseCase) -> str:
    """The systemCode the seeder actually PINS for this case — the gap-doc code for real FD verdicts,
    else the real FD code in seed.system_code for EDGE-*/FD-PAY-* label cases (mirrors
    seed.cli._pin_system_code, so the auditor's expectation matches what was pinned)."""
    from seed.dds_pin import parse_system_code
    gap = uc.system_code or ""
    regime, cls = parse_system_code(gap)
    if gap and regime in _DISRUPTION_REGIMES and cls in _DISRUPTION_CLASSES:
        return gap
    return uc.seed.system_code or gap


def _dds_check(area: str, uc: UseCase, dds: dict | None) -> CheckpointResult:
    """DDS-endpoint checks against a by-pnr verdict dict ({eligible, amount, system_code, ...})."""
    if dds is None:
        return CheckpointResult(area, None, "no DDS verdict supplied")
    if area == "dds_endpoint_systemcode_match":
        sc = str(dds.get("system_code") or "")
        want = _expected_system_code(uc)  # the code actually pinned (real FD code, not an EDGE/PAY label)
        if want:
            ok = sc == want
        else:
            ok = bool(dds.get("eligible")) and sc.startswith("FD-") and "-EL-" in sc
        return CheckpointResult(area, ok, f"systemCode={sc or 'none'}" + (f" expected={want}" if want else ""))
    if area == "dds_amount_match":
        want = (uc.seed.amount or {}).get("value")
        got = dds.get("amount")
        if want is None:
            return CheckpointResult(area, None, "no expected amount")
        ok = got is not None and float(got) == float(want)
        return CheckpointResult(area, ok, f"amount={got} expected={want}")
    # ne_nd_reason_text — only applies to NE/ND cases. Normalise the verdict first: catalogs spell
    # it "Not Eligible" (gap doc) or "NOT_ELIGIBLE" (donor index), and comparing the raw upper-cased
    # string matched only the underscored form, so gap-doc NE/ND cases silently reported "n/a".
    verdict = (uc.verdict or "").upper().replace(" ", "_").replace("-", "_")
    if verdict in ("NOT_ELIGIBLE", "NO_DETERMINATION"):
        ok = bool(dds.get("reason") or dds.get("system_code"))
        return CheckpointResult(area, ok, "reason present" if ok else "no reason")
    return CheckpointResult(area, None, "n/a for eligible case")


def verify_case(uc: UseCase, src, expected_email: str | None = None,
                areas: list[str] | None = None, dds: dict | None = None) -> VerifyReport:
    """Verify one use-case's seeded data against `areas` (the feed's `checkpoints.areas`, the auditor
    vocabulary). Pass `dds` (a by-pnr verdict) to confirm the DDS-endpoint checkpoints. Defaults to
    the areas this auditor supports when none are given."""
    if areas is None:
        areas = sorted(_SUPPORTED)
    checks = [_check(a, uc, src, expected_email, dds) for a in areas]
    return VerifyReport(case_id=uc.id, pnr=uc.seed.pnr, checks=checks)
