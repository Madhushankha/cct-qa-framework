"""Pure checkpoint-verification logic. Runs against a TripTracerSource (fake or live Aurora), so it
is fully unit-testable offline. Verifies the trip-tracer-backed checkpoints by matching the use-case's
seeded data; areas it can't check in this env are reported as skipped (ok=None), never as failures."""
from __future__ import annotations

from catalog.model import UseCase
from seed.model import CheckpointResult, VerifyReport

# checkpoint areas this verifier can confirm against trip-tracer Aurora (read-only).
# Everything else in a feed's checkpoints.areas is reported skipped (ok=None).
_SUPPORTED = {"eds_pnr_output", "eds_contact_email", "trip_active", "trip_details", "passenger",
              "passenger_count", "name_uniqueness", "ticket", "dob"}
# DDS areas — confirmed against the live by-pnr verdict when one is passed in, else skipped.
_DDS_AREAS = {"dds_endpoint_systemcode_match", "dds_amount_match", "ne_nd_reason_text"}


def _last_name(uc: UseCase) -> str:
    p = (uc.seed.passenger or "").strip()
    return p.split()[-1].upper() if p else ""


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
    if area in ("passenger", "name_uniqueness"):
        trip = src.trip(pnr)
        want = _last_name(uc)
        if trip is None:
            return CheckpointResult(area, False, "no trip row")
        got = str(trip.get("last_name", "")).upper()
        ok = bool(want) and got == want
        return CheckpointResult(area, ok, f"trip.last_name={got} expected={want}")
    if area == "passenger_count":
        got = len(src.passengers(pnr))
        if got == 0:
            return CheckpointResult(area, False, "no passenger rows")
        return CheckpointResult(area, True, f"{got} passenger(s)")
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
    # ne_nd_reason_text — only applies to NE/ND cases
    if (uc.verdict or "").upper() in ("NOT_ELIGIBLE", "NO_DETERMINATION"):
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
