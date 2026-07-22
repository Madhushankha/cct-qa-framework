"""Post-cascade write-back to trip-tracer — the step between "the PNR cascaded" and "the case is
usable". Ported from the reference pipeline's `finalize_one`.

Publishing to Kafka lands the booking (trip / trip_details / passenger / flight_segment /
eds_pnr_output), but three things the bot reads are NOT carried by that cascade and have to be
written directly:

  1. TICKETS   — one row per passenger. The ticket feed only reliably lands the primary traveller,
                 so multi-pax and GROUP bookings otherwise cascade with ticketless passengers and
                 the bot refuses the claim for them.
  2. DOB       — `passenger.date_of_birth` is nulled by ANY republish (including the version-bump
                 republish used to fix an eds straggler), so it must be re-set after every publish.
  3. GROUP     — `eds_pnr_output.booking_context.bookingSubtype = "GROUP"`, which is what switches
                 the bot into group handling.

Every write is idempotent, so re-finalizing a set is safe. All functions take a DB-API connection
(psycopg2 in production, a fake in the tests) and never open one themselves.
"""
from __future__ import annotations

import json

# Ticket numbers are `<6-digit-prefix><6-digit-serial>`. Serials 000001..000300 are the "base band"
# one per case; a case's 2nd..nth passenger gets `<prefix><case:04d><pax:02d>`, which lands above
# the base band and so cannot collide with another case's primary ticket.
_BASE_BAND = 300


def ticket_for(prefix: str, case_index: int, pax_index: int = 1) -> str:
    """Ticket number for passenger `pax_index` (1-based) of case `case_index` (1-based)."""
    if pax_index <= 1:
        return f"{prefix}{case_index:06d}"
    return f"{prefix}{case_index:04d}{pax_index:02d}"


def free_ticket_prefix(conn, start: int = 14363, end: int = 14420, band: int = _BASE_BAND) -> str:
    """Scan for a 6-digit ticket prefix whose low serial band is completely unused.

    A colliding ticket does NOT error — the insert is `on conflict do nothing`, so the ticket is
    silently dropped and only the `ticket` checkpoint catches it, long after the seed. Picking a
    free prefix up front avoids the whole class of failure.

    Prefixes are probed as `0<n>` for n in [start, end). Raises RuntimeError if none is free.
    """
    cur = conn.cursor()
    for n in range(start, end):
        prefix = f"0{n}"
        cur.execute(
            "select count(*) from ticket where primary_document_number between %s and %s",
            (f"{prefix}000001", f"{prefix}{band:06d}"))
        row = cur.fetchone()
        if row and int(row[0]) == 0:
            return prefix
    raise RuntimeError(f"no free ticket prefix in 0{start}..0{end - 1} — widen the scan range")


def passenger_ids(conn, pnr_id: str) -> list[int]:
    """The 1-based PT indexes actually present for this booking, ascending."""
    cur = conn.cursor()
    cur.execute("select passenger_id from passenger where pnr_id=%s and not is_removed", (pnr_id,))
    out = []
    for (pid,) in cur.fetchall():
        try:
            out.append(int(str(pid).rsplit("-PT-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(out)


def insert_tickets(conn, pnr_id: str, prefix: str, case_index: int, *,
                   issuance_date: str = "2026-06-01") -> list[str]:
    """One ticket row per passenger on the booking. Returns the ticket numbers written.

    PT-1 keeps the case's base-band number; PT-2..PT-n get the banded form (see `ticket_for`).
    `on conflict do nothing` makes a re-finalize a no-op rather than an error."""
    written = []
    cur = conn.cursor()
    for k in passenger_ids(conn, pnr_id) or [1]:
        tkt = ticket_for(prefix, case_index, k)
        cur.execute(
            "insert into ticket (primary_document_number, pnr_id, passenger_id, ticket_id, "
            "document_numbers, issuance_local_date, document_type) "
            "values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing",
            (tkt, pnr_id, f"{pnr_id}-PT-{k}", f"{tkt}-{issuance_date}", tkt, issuance_date))
        written.append(tkt)
    return written


def set_dob(conn, pnr_id: str, dob: str) -> None:
    """Restore `passenger.date_of_birth` for the booking (nulled by every republish)."""
    conn.cursor().execute(
        "update passenger set date_of_birth=%s where pnr_id=%s", (dob, pnr_id))


def set_group_context(conn, pnr_id: str) -> int:
    """Mark the booking as a GROUP in `eds_pnr_output.booking_context`. Returns rows updated."""
    cur = conn.cursor()
    cur.execute("select id, booking_context from eds_pnr_output where pnr_id=%s", (pnr_id,))
    rows = cur.fetchall()
    n = 0
    for row_id, bc in rows:
        ctx = json.loads(bc) if isinstance(bc, str) else (bc or {})
        ctx["bookingSubtype"] = "GROUP"
        cur.execute("update eds_pnr_output set booking_context=%s where id=%s",
                    (json.dumps(ctx), row_id))
        n += 1
    return n


def finalize_case(conn, *, pnr_id: str, prefix: str, case_index: int, dob: str,
                  group: bool = False, issuance_date: str = "2026-06-01") -> dict:
    """Run every post-cascade write for one case and commit. Returns what was written."""
    tickets = insert_tickets(conn, pnr_id, prefix, case_index, issuance_date=issuance_date)
    set_dob(conn, pnr_id, dob)
    groups = set_group_context(conn, pnr_id) if group else 0
    if hasattr(conn, "commit"):
        conn.commit()
    return {"pnr_id": pnr_id, "tickets": tickets, "dob": dob, "group_rows": groups}


def connect_writable(env):
    """A READ-WRITE psycopg2 connection to the env's trip-tracer Aurora.

    `source.connect()` deliberately hands back a read-only auditing wrapper; finalize needs to
    write, so it opens its own connection from the same secret."""
    from seed.source import db_connect, read_secret

    st = env.seed_targets
    return db_connect(st["aurora_host"], "trip-tracer", read_secret(env, st["aurora_secret"]))
