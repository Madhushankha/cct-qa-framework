"""Pure canonicalization for the soc feed's DDS verdict array (`socFlightEligibility[]`) — the
soc-specific sibling to `seed.dds_pin.canonicalize_verdict` (which only knows
`compensationEligibility`).

`socFlightEligibility` is a DIFFERENT array on the same determination document, with different field
names from FD's `compensationEligibility`: no `compensationDetails.amount`, an `expenseCategories[]`
list instead, `delayCategory` (a threshold enum) instead of a `delayBand` tier. See
`data/seed-templates/soc/base/dds_soc_appr.json` for the base shape this rewrites, and
`docs/superpowers/plans/2026-07-17-soc-bookingchange-seed.md` §5 for the array-shape rationale.

NOT wired into `seed/dds_pin.py` or `seed/cli.py`'s `run_seed_all` (both out of scope for this pass
— the plan's §6 lists the concrete follow-up work, e.g. generalizing `run_seed_all`'s FD-hardcoded
`_seedable_verdict`/systemCode-prefix checks). Pure functions only; no S3/DB side effects, no live
deps — offline-testable like `dds_pin`'s rewrite functions (see `tests/test_soc_verdict.py`).

Open question NOT resolved here (plan §3): the exact `delayCategory` enum string for soc's eligible
"at or above 2h" band. The one concrete data point in this repo
(`data/dds-templates/appr_cad_400.json`'s `socFlightEligibility[*].delayCategory`) only shows
`"DELAY_LT_2_HOURS"`, a NOT_ELIGIBLE/NO_DETERMINATION sample. This module takes `delay_category` as
an explicit caller-supplied argument rather than guessing the eligible-band string into committed
code.
"""
from __future__ import annotations

# CLASS token (from systemCode SoC-<REGIME>-<CLASS>-<n>) -> the bot's eligibilityStatus enum.
# Confirmed classes from the 81 parsed soc cases (see the plan doc §5): NE/ND/EL/PE.
_CLASS_STATUS = {"EL": "ELIGIBLE", "NE": "NOT_ELIGIBLE", "ND": "NO_DETERMINATION", "PE": "PENDING"}
_REGIME_TARGET = {"APPR": "APPR", "EU": "EU", "UK": "EU", "ASL": "ASL"}
_CLASS_REASON = {
    "NE": "Not eligible for expense reimbursement for this disruption.",
    "ND": "A determination could not be made for this disruption.",
    "PE": "Your claim is pending -- the disruption is within the assessment window.",
}
_NA_SYS = {"EU": "SoC-EU-NA-01", "ASL": "SoC-ASL-NA-01", "APPR": "SoC-APPR-NA-01"}
_ELIGIBLE_REASON = "You're eligible to submit expenses for reimbursement."
_FRIENDLY = ("Your flight was delayed and you may be eligible to submit eligible expenses for "
             "reimbursement.")


def parse_soc_system_code(system_code: str) -> tuple[str, str]:
    """`SoC-APPR-NE-01` -> `('APPR', 'NE')`. Tolerant of the override family observed in the 81-case
    catalog (`SoC-Override-Pending`/`SoC-Override-Pay`, no regime token at all) -- returns
    `('OVERRIDE', <token>)` for those so callers can special-case them rather than silently
    defaulting to APPR/EL, which would fabricate a determination shape nobody has confirmed (plan
    doc §5 flags these as "worth a special case if/when a canonicalizer is built" -- not resolved
    here). Defaults to `('APPR', 'EL')` for anything else unparseable (e.g. empty string)."""
    parts = (system_code or "").upper().split("-")
    if len(parts) >= 2 and parts[1] == "OVERRIDE":
        return "OVERRIDE", parts[2] if len(parts) > 2 else ""
    regime = parts[1] if len(parts) > 1 else "APPR"
    cls = parts[2] if len(parts) > 2 else "EL"
    return regime, cls


def canonicalize_soc_verdict(response: dict, *, system_code: str, delay_category: str,
                             delay_minutes: int = 0, expense_categories: list[str] | None = None,
                             expiry_date: str = "") -> dict:
    """Rewrite `response["socFlightEligibility"]` in place to the target regime's verdict, marking
    every other regime NOT_ELIGIBLE / not-applicable. Mirrors `seed.dds_pin.canonicalize_verdict`'s
    shape/behavior (one base template, the case's own systemCode picks the target regime + status)
    but targets `socFlightEligibility` instead of `compensationEligibility`.

    For an ELIGIBLE (EL) target, the passenger's `expenseCategories` is set from
    `expense_categories` (soc-specific -- fd has nothing analogous) and `expiryDate` from
    `expiry_date`; NE/ND/PE read an empty `expenseCategories` and a class-appropriate `reason`.

    Raises `ValueError` for the OVERRIDE family (`SoC-Override-Pending`/`-Pay`) -- those carry no
    regime token to target, so silently defaulting to APPR would fabricate an unconfirmed
    determination shape; the plan (§5) flags this as unresolved, not something to guess here.
    Returns `response` (mutated in place, same convention as `canonicalize_verdict`)."""
    regime_tok, cls = parse_soc_system_code(system_code)
    if regime_tok == "OVERRIDE":
        raise ValueError(
            f"canonicalize_soc_verdict: {system_code!r} is an override code with no regime to "
            "target -- not supported yet (see "
            "docs/superpowers/plans/2026-07-17-soc-bookingchange-seed.md §5)")
    target = _REGIME_TARGET.get(regime_tok, "APPR")
    status = _CLASS_STATUS.get(cls, "NOT_ELIGIBLE")
    eligible = status == "ELIGIBLE"
    expenses = list(expense_categories or []) if eligible else []

    for entry in response.get("socFlightEligibility", []):
        reg = (entry.get("regime") or "").upper()
        is_target = reg == target
        if is_target:
            entry["delayMinutes"] = delay_minutes
            entry["delayCategory"] = delay_category
            if eligible:
                entry["customerFriendlyDisruptionReason"] = _FRIENDLY
        for pe in entry.get("passengerEligibility", []):
            pe["passengerType"] = pe.get("passengerType") or "ADT"
            if is_target:
                pe["eligibilityStatus"] = status
                pe["systemCode"] = system_code
                pe["expenseCategories"] = expenses
                pe["expiryDate"] = expiry_date if eligible else ""
                pe["reason"] = _ELIGIBLE_REASON if eligible else _CLASS_REASON.get(cls, "Not eligible.")
            else:
                pe["eligibilityStatus"] = "NOT_ELIGIBLE"
                pe["systemCode"] = _NA_SYS.get(reg, f"SoC-{reg}-NA-01")
                pe["reason"] = "Regime not applicable to this itinerary"
                pe["expenseCategories"] = []
                pe["expiryDate"] = ""
    return response
