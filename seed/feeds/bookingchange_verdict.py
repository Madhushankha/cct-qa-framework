"""Pure canonicalization for the bookingchange feed's DDS verdict -- reuses `compensationEligibility`
(the same array `seed.dds_pin.canonicalize_verdict` targets for FD) but a DIFFERENT input shape:
bookingchange's gap docs carry NO `data-out` verdict and NO real systemCode per case (see
`docs/superpowers/plans/2026-07-17-soc-bookingchange-seed.md` §1 caveats 1-2) -- every parsed
`UseCase.verdict` is `""` and `UseCase.system_code` is a test-case priority token (`"P1"`/`"P2"`),
not a determination code. The expected-outcome signal for this feed is `UseCase.regime`
(`Eligible`/`Ineligible`/`System-Edge`/`Other`, parsed from the gap doc's `data-feat`).

Because of that, this canonicalizer does NOT try to derive `eligibilityStatus`/`systemCode` from a
UseCase field the way `canonicalize_verdict` derives them from FD's `system_code` -- the caller must
supply `status` (map a case's regime bucket through `outcome_status()`) and `system_code` explicitly.
No `BC-...` systemCode family has been observed anywhere in this repo or either gap doc; passing a
real one is the caller's responsibility once a live rule-engine sample confirms the shape (plan §1
caveat 2, §5) -- this module will not fabricate one.

Not wired into `seed/dds_pin.py` or `seed/cli.py` (out of scope, see plan §6). Pure / offline
testable -- see `tests/test_bookingchange_verdict.py`.
"""
from __future__ import annotations

VOL = "VOL"
INVOL = "INVOL"

# UseCase.regime bucket (from data-feat) -> the bot's eligibilityStatus enum (bookingchange.yaml's
# judge.verdict_enum). "System-Edge"/"Other" have no confirmed 1:1 mapping to a single DDS status --
# NO_DETERMINATION is the closest analog (an edge case the rule engine couldn't cleanly resolve), a
# documented approximation, not a guess at a more specific enum value.
_OUTCOME_STATUS = {
    "eligible": "ELIGIBLE",
    "ineligible": "NOT_ELIGIBLE",
    "system-edge": "NO_DETERMINATION",
    "other": "NO_DETERMINATION",
}

_DISRUPTION_REASON = {VOL: "VOLUNTARY_CHANGE", INVOL: "COMMERCIAL"}
_DISRUPTION_TYPE = {VOL: "VOLUNTARY", INVOL: "INVOLUNTARY"}
_FRIENDLY = {
    VOL: "You've requested a voluntary change to your booking.",
    INVOL: "Your flight was changed by Air Canada and you may be eligible to rebook.",
}
_ELIGIBLE_REASON = "You're eligible to rebook your itinerary."
_INELIGIBLE_REASON = "Not eligible for this booking change."


def kind_for(case_id: str) -> str:
    """Case id prefix -> VOL/INVOL (`'VOL_TC019'` -> VOL, `'InVOL_TC004'` -> INVOL). Mirrors the
    doc-merge id convention documented in `bookingchange.yaml`/the plan §1 (both docs' ids already
    avoid collision this way). Defaults to INVOL for any id that matches neither prefix -- documented,
    not silently arbitrary: INVOL is the shape `data/dds-templates/appr_cad_400.json`'s existing
    compensationEligibility template already carries, so it's the closer default when the id is
    unrecognized."""
    idl = (case_id or "").lower()
    if idl.startswith("invol_") or idl.startswith("bcinvol_"):
        return INVOL
    if idl.startswith("vol_") or idl.startswith("bcvol_"):
        return VOL
    return INVOL


def outcome_status(regime_bucket: str) -> str:
    """`'Eligible'`/`'Ineligible'`/`'System-Edge'`/`'Other'` (`UseCase.regime`, case-insensitive) ->
    the bot's eligibilityStatus enum. Unknown buckets map to NO_DETERMINATION (a documented fallback,
    not a KeyError -- the parser is feed-agnostic and could in principle see other data-feat text)."""
    return _OUTCOME_STATUS.get((regime_bucket or "").strip().lower(), "NO_DETERMINATION")


def canonicalize_bookingchange_verdict(response: dict, *, kind: str, status: str, system_code: str,
                                       expiry_date: str = "", reason: str | None = None) -> dict:
    """Rewrite `response["compensationEligibility"]`'s APPR regime entry in place to a bookingchange
    determination. `kind` (VOL/INVOL, see `kind_for`) drives `disruptionReason`/`disruptionType`/the
    customer-friendly text; `status` (see `outcome_status`) and `system_code` (caller-supplied -- see
    module docstring) drive the passenger's verdict. Every other regime is marked NOT_ELIGIBLE /
    not-applicable with a `BC-<regime>-NA-01` placeholder code, the same not-applicable convention
    `canonicalize_verdict` uses for FD (`FD-<regime>-NA-01`) -- unconfirmed for bookingchange, but a
    structurally consistent placeholder rather than leaving the field unset.

    Returns `response` (mutated in place)."""
    if kind not in (VOL, INVOL):
        raise ValueError(f"canonicalize_bookingchange_verdict: kind must be 'VOL' or 'INVOL', got {kind!r}")
    eligible = status == "ELIGIBLE"

    for c in response.get("compensationEligibility", []):
        reg = (c.get("regime") or "").upper()
        is_target = reg == "APPR"
        if is_target:
            c["delayType"] = "CONTROLLABLE" if eligible else ""
            c["disruptionReason"] = _DISRUPTION_REASON[kind]
            c["customerFriendlyDisruptionReason"] = _FRIENDLY[kind]
        else:
            c["delayMinutes"] = 0
            c["delayType"] = ""
            c["delayCode"] = ""
        for pe in c.get("passengerEligibility", []):
            pe["passengerType"] = pe.get("passengerType") or "ADT"
            pe.pop("failureReasons", None)
            if is_target:
                pe["disruptionType"] = _DISRUPTION_TYPE[kind]
                pe["eligibilityStatus"] = status
                pe["systemCode"] = system_code
                pe["reason"] = reason or (_ELIGIBLE_REASON if eligible else _INELIGIBLE_REASON)
                pe["compensationDetails"] = {
                    "amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE",
                    "expiryDate": expiry_date if eligible else "",
                }
            else:
                pe["eligibilityStatus"] = "NOT_ELIGIBLE"
                pe["systemCode"] = f"BC-{reg}-NA-01"
                pe["reason"] = "Regime not applicable to this itinerary"
                pe["compensationDetails"] = {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}
    return response
