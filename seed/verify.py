"""Pure checkpoint-verification logic. Runs against a TripTracerSource (fake or live Aurora), so it
is fully unit-testable offline. Verifies the trip-tracer-backed checkpoints by matching the use-case's
seeded data; areas it can't check in this env are reported as skipped (ok=None), never as failures."""
from __future__ import annotations

from catalog.model import UseCase
from seed.model import CheckpointResult, VerifyReport

# checkpoint areas this verifier can confirm against trip-tracer Aurora (read-only).
# Everything else in a feed's checkpoints.areas is reported skipped (ok=None).
_SUPPORTED = {"eds_pnr_output", "eds_contact_email", "trip_active", "passenger",
              "name_uniqueness", "ticket"}
# DDS areas are known but need a DDS source (S3/execution_traces), not wired here -> skipped.
_DDS_AREAS = {"dds_endpoint_systemcode_match", "dds_amount_match", "ne_nd_reason_text"}


def _last_name(uc: UseCase) -> str:
    p = (uc.seed.passenger or "").strip()
    return p.split()[-1].upper() if p else ""


def _check(area: str, uc: UseCase, src, expected_email: str | None) -> CheckpointResult:
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
    if area in ("passenger", "name_uniqueness"):
        trip = src.trip(pnr)
        want = _last_name(uc)
        if trip is None:
            return CheckpointResult(area, False, "no trip row")
        got = str(trip.get("last_name", "")).upper()
        ok = bool(want) and got == want
        return CheckpointResult(area, ok, f"trip.last_name={got} expected={want}")
    if area == "ticket":
        ok = len(src.tickets(pnr)) > 0
        return CheckpointResult(area, ok, "ticket row present" if ok else "no ticket")
    if area in _DDS_AREAS:
        return CheckpointResult(area, None, "DDS source not wired in this env")
    return CheckpointResult(area, None, "not verifiable by this auditor")


def verify_case(uc: UseCase, src, expected_email: str | None = None,
                areas: list[str] | None = None) -> VerifyReport:
    """Verify one use-case's seeded data against `areas` (the feed's `checkpoints.areas`, the auditor
    vocabulary). Defaults to the areas this auditor supports when none are given."""
    if areas is None:
        areas = sorted(_SUPPORTED)
    checks = [_check(a, uc, src, expected_email) for a in areas]
    return VerifyReport(case_id=uc.id, pnr=uc.seed.pnr, checks=checks)
