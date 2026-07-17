"""Per-feed seed helpers for the divergent (non-FD) feeds.

Each module here canonicalizes / builds the seed payload for one feed whose mechanism differs from
FD's pnr+ticket+FDM+DDS(compensationEligibility) path:

- prelude        — CREATE-prelude for UPDATE feeds (nc, seatchange): this framework's port of
                   contrail's proven pnr_lifecycle.py. `needs_create_prelude`/`build_create_payload`
                   synthesize the CREATE that must precede a bare UPDATE on a fresh locator (a name-
                   change or seating UPDATE alone produces no Aurora write — no parent row to FK to);
                   `wait_for` polls seed/source.py's AuroraSource/TripTracerSource for that parent
                   row. Offline-testable; see data/seed-templates/nc/README.md and
                   data/seed-templates/seatchange/README.md for the two-Kafka-burst seed path this
                   feeds into.
- nc_outcome     — NC (Name Correction): reads each case's REAL flow outcome (CORRECTED/
                   DOCS_REQUIRED/NOT_ELIGIBLE/LIVE_AGENT/NO_DETERMINATION/UNKNOWN) directly off the
                   gap-doc card body (title + Gherkin "Then" checklist) — NC carries no systemCode/
                   data-out for catalog/parser.py to derive a verdict from. Heuristic, not ground
                   truth; see the module docstring.
- seatchange_outcome — SeatChange: the same card-body outcome read as nc_outcome, for SeatChange's
                   verdict_enum (SEAT_CHANGED/PAYMENT_REQUIRED/DECLINED/LIVE_AGENT/NO_DETERMINATION/
                   UNKNOWN).
- anc_refund     — ANC (seat/bag ancillary refund): builds the refund-DDS arrays
                   (seatFeeRefundEligibility / baggageRefundEligibility). CREATE + DDS, like FD but a
                   different DDS array and an EMD instead of a delay leg. Offline-testable rewrite.
- baggage_events — BAGGAGE: a SEPARATE LANE. STUB that builds SmartSuite bag-event payloads
                   (BagReadyForLoading/Loaded/Seen/Mishandled) with today-relative timestamps. NOT a
                   Kafka/DDS seed and NOT wired to a live SmartSuite/baggage-rules path.
- nonmvp_routing — NON-MVP: NO per-case seed. Reads the expected routing target (Claims Dashboard /
                   Live Agent / FAQ / Manual Handling) out of the gap-doc case title; every case
                   reuses one pool PNR.
- soc_verdict     — SoC (Standards of Care): canonicalizes the `socFlightEligibility[]` DDS array
                   (different array/field shape than FD's compensationEligibility — expenseCategories
                   instead of a cash amount, delayCategory instead of a delayBand tier). CREATE + DDS,
                   same pnr+ticket+FDM cascade as FD (see data/seed-templates/soc/base/).
- bookingchange_verdict — Booking Change: canonicalizes `compensationEligibility[]` (same array FD
                   uses) but with VOL/INVOL-flavored disruptionReason/reason text instead of FD's
                   amount-tier logic, since bookingchange's gap docs carry no real systemCode or
                   data-out verdict per case (see data/seed-templates/bookingchange/base/).

All functions are pure (no boto3/kafka/live deps) so they unit-test offline.
"""
