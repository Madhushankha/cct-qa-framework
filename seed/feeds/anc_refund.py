"""ANC (Ancillaries — Seat / Bag Refund) refund-DDS canonicalizer — the ANC analogue of
seed/dds_pin.py's `canonicalize_verdict`.

Where FD pins a `compensationEligibility[]` determination, ANC pins a REFUND-eligibility
determination whose array name depends on the flow:

  - seat flow -> `seatFeeRefundEligibility[]`
  - bag  flow -> `baggageRefundEligibility[]`

Each entry carries the per-EMD refund verdict (eligible / not-eligible / pending / escalated), the
underlying EMD status (I issued / R refunded / V voided / E exchanged), the refunded amount, and a
customer-friendly reason. The two axes are independent — the deterministic judge matches on
`[status, system_code]` where `status` = the refund verdict and `system_code` = the EMD status (see
core/registry/feeds/anc.yaml).

The ANC gap doc carries no tabular dataset and no `data-out` verdict — the refund outcome and EMD
status live in the CASE TITLE (e.g. "EMD Already Refunded (Status R)", "ELIGIBLE (Refund to be
Processed)", "USED EMD -> 72-Hour Wait NOT Satisfied -> Pending"). So this module reads both off the
title, exactly the way seed/scenario.py reads temporal intent / delay off the FD title.

Pure functions only (no boto3 / no live rule-engine) — offline-testable. A live pin would wrap
`build_refund_response` the same way seed/dds_pin.pin_case wraps canonicalize_verdict.
"""
from __future__ import annotations

import re

# flow -> the DDS array the refund verdict lands in.
FLOW_ARRAY = {"seat": "seatFeeRefundEligibility", "bag": "baggageRefundEligibility"}
# flow -> (EMD reasonForIssuanceSubCode / RFISC, serviceType) — seat vs checked-bag ancillary.
FLOW_RFISC = {"seat": ("0B5", "SEAT"), "bag": ("0DF", "BAG")}

# EMD status enum (the ANC `system_code` axis): I issued / R refunded / V voided / E exchanged.
EMD_STATUSES = ("I", "R", "V", "E")
# Refund verdict enum (the ANC `status` axis) — mirrors anc.yaml judge.verdict_enum.
VERDICTS = ("ELIGIBLE", "NOT_ELIGIBLE", "PENDING", "ESCALATED", "NO_DETERMINATION", "UNKNOWN")


def flow_of(uc, feed: str | None = None) -> str:
    """seat|bag for a case. Prefer the parsed `regime` (the card's data-flow, "seat"|"bag"), then the
    id prefix (SEAT_/ANC-SEAT- vs BAG_/ANC-BAG-), then the title. Defaults to 'seat'."""
    reg = (getattr(uc, "regime", "") or "").strip().lower()
    if reg in ("seat", "bag"):
        return reg
    idu = (getattr(uc, "id", "") or "").upper()
    if "BAG" in idu:
        return "bag"
    if "SEAT" in idu:
        return "seat"
    t = (getattr(uc, "title", "") or "").lower()
    if "bag refund" in t or "baggage" in t or "checked bag" in t:
        return "bag"
    return "seat"


def emd_status_of(uc) -> str:
    """EMD document status (I/R/V/E) read from the case title. Defaults to 'I' (issued) — most cases
    pin a live issued EMD; only the "already handled" branch pins R/V, and exchange pins E."""
    t = (getattr(uc, "title", "") or "").lower()
    if "status r" in t or "already refunded" in t or "already been refunded" in t:
        return "R"
    if "status v" in t or "voided" in t:
        return "V"
    if "exchanged emd" in t or "exchanged" in t:
        return "E"
    return "I"


def refund_verdict_of(uc) -> str:
    """Refund verdict (ELIGIBLE/NOT_ELIGIBLE/PENDING/ESCALATED/UNKNOWN) read from the case title.

    Order matters: an escalation/redirect signal (manual handling, live-agent handoff, OAL/STAR
    referral, dispute flow) wins over a bare eligible/not-eligible mention, because those cases end
    OUTSIDE the automated refund verdict regardless of the underlying EMD state. PENDING (the
    72-hour-wait-not-satisfied branch) is checked before ELIGIBLE for the same reason.
    """
    t = (getattr(uc, "title", "") or "").lower()
    # escalation / redirect / manual branches — the refund is not auto-decided here.
    if any(k in t for k in ("manual handling", "live agent", "dispute flow", "redirected",
                            "redirect to", "oal referral", "referred to oal", "referred to star",
                            "star partner", "redirected to acv", "acv", "customer disputes",
                            "customer insists", "passenger selection required")):
        return "ESCALATED"
    # pending (used-EMD 72-hour wait not yet satisfied)
    if "pending" in t or "wait not satisfied" in t or "not satisfied" in t:
        return "PENDING"
    # not eligible (must be checked before 'eligible' since "not eligible" contains "eligible")
    if "not eligible" in t or "no refund" in t or "no seat fee paid" in t or "no paid emd" in t:
        return "NOT_ELIGIBLE"
    if "eligible" in t or "refund to be processed" in t or "refund with" in t:
        return "ELIGIBLE"
    # already-refunded / voided EMD with no explicit verdict -> the EMD state is the answer.
    if emd_status_of(uc) in ("R", "V"):
        return "NOT_ELIGIBLE"
    return "UNKNOWN"


_MONEY_RE = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)")


def refund_amount_of(uc, default: float = 45.0) -> float:
    """Refunded amount for an eligible verdict. The ANC titles rarely carry a figure, so this falls
    back to a nominal seat/bag-fee default; a real dataset join would supply the exact EMD price."""
    amt = getattr(getattr(uc, "seed", None), "amount", None) or {}
    val = amt.get("value") if isinstance(amt, dict) else None
    if isinstance(val, (int, float)) and val:
        return float(val)
    m = _MONEY_RE.search(getattr(uc, "title", "") or "")
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return float(default)


_REASON = {
    "ELIGIBLE": "The ancillary was not delivered as purchased — the fee is eligible for refund.",
    "NOT_ELIGIBLE": "The purchased ancillary was delivered — the fee is not eligible for refund.",
    "PENDING": "The refund is pending — the 72-hour post-travel wait has not yet elapsed.",
    "ESCALATED": "This refund requires manual handling / referral and cannot be auto-decided.",
    "NO_DETERMINATION": "No refund determination could be made for this ancillary.",
    "UNKNOWN": "Refund outcome undetermined.",
}


def build_eligibility_entry(*, flow: str, verdict: str, emd_status: str, emd_number: str,
                            amount: float, currency: str, segment_id: str, passenger_id: str,
                            reason: str | None = None, expiry_date: str | None = None) -> dict:
    """One refund-eligibility entry (the ANC analogue of a passengerEligibility record)."""
    rfisc, service_type = FLOW_RFISC.get(flow, FLOW_RFISC["seat"])
    eligible = verdict == "ELIGIBLE"
    entry = {
        "emdDocumentNumber": emd_number,
        "emdStatus": emd_status,
        "reasonForIssuanceSubCode": rfisc,
        "serviceType": service_type,
        "segmentId": segment_id,
        "passengerId": passenger_id,
        "refundStatus": verdict,
        "refundEligible": eligible,
        "reason": reason or _REASON.get(verdict, _REASON["UNKNOWN"]),
        "refundDetails": {
            "amount": round(float(amount), 2) if eligible else 0,
            "currency": currency,
        },
    }
    if eligible and expiry_date:
        entry["refundDetails"]["expiryDate"] = expiry_date
    return entry


def canonicalize_refund(response: dict, *, flow: str, verdict: str, emd_status: str,
                        emd_number: str, amount: float, currency: str = "CAD",
                        segment_id: str, passenger_id: str, reason: str | None = None,
                        expiry_date: str | None = None) -> dict:
    """Rewrite `response` in place to the bot's canonical refund shape: set the flow's refund array
    (`seatFeeRefundEligibility` or `baggageRefundEligibility`) to a single-entry list carrying the
    verdict, and clear the OTHER flow's array so no stale determination leaks. Returns `response`."""
    array = FLOW_ARRAY.get(flow)
    if array is None:
        return response  # unknown flow -> leave untouched
    entry = build_eligibility_entry(
        flow=flow, verdict=verdict, emd_status=emd_status, emd_number=emd_number, amount=amount,
        currency=currency, segment_id=segment_id, passenger_id=passenger_id, reason=reason,
        expiry_date=expiry_date)
    response[array] = [entry]
    other = FLOW_ARRAY["bag" if flow == "seat" else "seat"]
    response.setdefault(other, [])
    return response


def build_refund_response(uc, *, pnr_id: str, locator: str, flow: str | None = None,
                          currency: str = "CAD", expiry_date: str | None = None,
                          feed: str | None = None) -> dict:
    """Build a full ANC refund determination for `uc` (verdict + EMD status read from the title).

    Returns a determination dict shaped like the FD DDS response but carrying the refund arrays
    instead of compensationEligibility — ready for a live S3 PutObject + execution_traces pin (the
    same mechanism seed/dds_pin.pin_case uses for FD)."""
    fl = flow or flow_of(uc, feed)
    verdict = refund_verdict_of(uc)
    emd_status = emd_status_of(uc)
    amount = refund_amount_of(uc)
    emd_number = getattr(getattr(uc, "seed", None), "ticket", "") or "0142900800201"
    seg_id = f"{pnr_id}-ST-1"
    pax_id = f"{pnr_id}-PT-1"
    response: dict = {
        "pnrIdentifier": {"pnrId": pnr_id, "pnr": locator},
        "determinationType": "ANCILLARY_REFUND",
        "flow": fl,
    }
    canonicalize_refund(response, flow=fl, verdict=verdict, emd_status=emd_status,
                        emd_number=emd_number, amount=amount, currency=currency,
                        segment_id=seg_id, passenger_id=pax_id, expiry_date=expiry_date)
    return response
