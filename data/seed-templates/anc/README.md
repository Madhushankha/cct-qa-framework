# ANC (Ancillaries — Seat / Bag Refund) seed template

**Mechanism: seedable like FD, with two differences — an EMD instead of a delay leg, and a different
DDS array.**

ANC is a **CREATE + DDS** feed, the closest of the three divergent feeds to FD. An ANC message
represents an **already-purchased ancillary** (a paid seat selection or an extra bag), so the seed
has to make that ancillary *exist and be purchased* before the chat can reason about refunding it.

## What this base template carries

`base/` is the pnr + ticket + **EMD** family (NOT the FD pnr + ticket + **FDM** trio — there is no
disruption, so no FDM XML and no CREATE-prelude):

| file | role |
|------|------|
| `01_pnr.json` | the booking (copied from `data/fd-templates/base_appr` — the PNR skeleton is feed-agnostic) |
| `02_ticket.json` | the fare ticket (copied from `base_appr`) |
| `03_emd_issue.json` | the **EMD issue** — the record that a paid ancillary was issued: EMD document number (`014`-prefixed AC doc), status, RFISC/subcode, and `inConnectionWith` the flight ticket coupon |
| `04_emd_correlation.json` | the **correlation** tying the EMD coupon → ticket coupon → segment → passenger, so the refund-eligibility detector can find it |
| `meta.json` | identity + EMD fields (`emd`, `emd_status`, `emd_rfisc`, `emd_service`, `flow`) |

### EMD status and flow

- **`emd_status`** — `I` issued / `R` refunded / `V` voided / `E` exchanged. The base ships `I`.
  Several cases pin an already-`R`/`V` EMD to test the "already handled" branch
  (`SEAT_TC001` = *EMD Already Refunded (Status R)*, `BAG_TC002` = *EMD Voided (Status V)*).
- **`flow`** — `seat` or `bag`. Toggling it changes the EMD's `reasonForIssuanceSubCode` (RFISC) and
  `serviceType` (seat = `0B5` PRE RESERVED SEAT ASSIGNMENT; bag = `0DF` CHECKED BAGGAGE) **and** the
  DDS array the refund verdict lands in (`seatFeeRefundEligibility` vs `baggageRefundEligibility`).
  The base ships the **seat** variant; a bag variant swaps those two fields.
- Some cases use a **non-`014` EMD document** on purpose to force an OAL/other-airline referral
  (`ANC-SEAT-TC-003`).

## Refund DDS

Refund-eligibility variants pin a DDS whose array depends on the flow. The canonicalizer for that
array is `seed/feeds/anc_refund.py` (`canonicalize_refund` / `build_refund_response`) — the ANC
analogue of `seed/dds_pin.canonicalize_verdict`. The refund **verdict** (ELIGIBLE / NOT_ELIGIBLE /
PENDING / ESCALATED) and **EMD status** are read from the **case title**, because the ANC gap doc
carries no tabular dataset and no `data-out` verdict (see `anc.yaml` header). Pure "already
refunded/voided" status checks need no DDS — the EMD status alone drives the answer.

## Status: scaffold

`seed/render.py` `render_case` only copies `01_pnr.json` / `02_ticket*.json` / `*.xml` today — it
does **not** yet emit/rekey the `03_emd_issue.json` / `04_emd_correlation.json` EMD family. Wiring
ANC through the generic engine needs that renderer extension (emit the EMD family; rekey the EMD
docnum, status, RFISC, and correlation segment/passenger ids). The refund-DDS canonicalizer in
`seed/feeds/anc_refund.py` is fully offline-testable and ready ahead of that wiring. See
`docs/superpowers/plans/2026-07-17-anc-seed.md`.
