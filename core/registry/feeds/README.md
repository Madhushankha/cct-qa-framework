# feeds/ — one descriptor per business domain

One file per feed. `fd.yaml` is a filled illustrative stub; the rest are placeholders to be filled
from each domain's gap doc during P1/P0.

| Feed | File | Domain |
|---|---|---|
| fd | `fd.yaml` ✍ (stub) | Flight Disruption (APPR/EU/ASL compensation) |
| soc | `soc.yaml` | Standards of Care (expense reimbursement) |
| nc | `nc.yaml` | Name Correction |
| anc | `anc.yaml` | Ancillary Seat/Bag refund |
| baggage | `baggage.yaml` | Baggage claim |
| seatchange | `seatchange.yaml` | Seat Change |
| bookingchange | `bookingchange.yaml` | Booking Change (VOL + INVOL) |
| nonmvp | `nonmvp.yaml` | Non-MVP routing |

Each declares: `gap_doc`, `columns` (datagrid → SeedSpec map), `persona` (+ branches), `judge`
(verdict enum + match rule), and `checkpoints` (auditor + areas). See `fd.yaml` for the shape and
[`../README.md`](../README.md).
