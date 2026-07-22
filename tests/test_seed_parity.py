"""Parity tests for the data-creation capabilities ported from the reference pipeline
(cct-crt-kb): DB-absent unique names, real name-uniqueness auditing, the post-cascade write-back
(per-passenger tickets / DOB / GROUP context), the free ticket-prefix scan, phone + DOB injection,
OAL AC-ify, and the version-bump republish. All offline — no AWS, no DB."""
from __future__ import annotations

import datetime
import json

import pytest

from catalog.model import SeedSpec, UseCase
from seed import finalize, identity, render, verify
from seed.source import FakeSource


# ── fakes ─────────────────────────────────────────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []

    def execute(self, sql, params=()):
        self.db["sql"].append((" ".join(sql.split()), params))
        s = sql.lower()
        if "from ticket where primary_document_number between" in s:
            self._rows = [(self.db["used_prefixes"].get(params[0][:6], 0),)]
        elif "select passenger_id from passenger" in s:
            self._rows = [(p,) for p in self.db["passenger_ids"]]
        elif "select id, booking_context from eds_pnr_output" in s:
            self._rows = list(self.db["eds_rows"])
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, **kw):
        self.db = {"sql": [], "used_prefixes": {}, "passenger_ids": [], "eds_rows": [], **kw}
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        self.commits += 1

    def sql_like(self, needle):
        return [s for s, _ in self.db["sql"] if needle.lower() in s.lower()]


def _case(cid="FD_TC_001", passenger="PERCY MOSSERSHAW", title="APPR eligible", **seed_kw):
    return UseCase(
        id=cid, regime="APPR", verdict="Eligible", system_code="FD-APPR-EL-01", title=title,
        third_party=False, checkpoint_vector=[], customer_intent="", expected_transcript=[],
        seed=SeedSpec(pnr="ABC123", pnr_id="ABC123-2026-01-01", passenger=passenger,
                      ticket="014363000001", status="ELIGIBLE", system_code="FD-APPR-EL-01",
                      **seed_kw),
        seed_pending=False, content_hash="h",
    )


# ── gap 1: DB-absent unique names ─────────────────────────────────────────────────────────────
def test_generated_surname_space_is_far_larger_than_the_old_fixed_pool():
    assert len(identity.generated_surnames()) > 10_000  # was 48 hardcoded surnames


def test_fresh_pool_excludes_surnames_already_in_the_db():
    seen = {s.upper() for s in identity.generated_surnames()[:900]}
    pool = identity.fresh_pool(50, in_db=lambda batch: {b for b in batch if b in seen})
    assert len(pool) == 50
    assert not any(last in seen for _, last in pool)


def test_fresh_pool_surnames_are_all_distinct():
    pool = identity.fresh_pool(200)
    assert len({last for _, last in pool}) == 200


def test_fresh_pool_raises_rather_than_returning_colliding_names():
    with pytest.raises(RuntimeError, match="unique-name generator short"):
        identity.fresh_pool(10, in_db=lambda batch: set(batch), batch=10_000_000)


# ── gap 2: real name_uniqueness checkpoint ────────────────────────────────────────────────────
def test_name_uniqueness_fails_when_the_name_exists_on_another_pnr():
    src = FakeSource({"ABC123": {"passengers": ["PERCY MOSSERSHAW"],
                                 "names_elsewhere": [("PERCY", "MOSSERSHAW")]}})
    r = verify.verify_case(_case(), src, areas=["name_uniqueness"]).checks[0]
    assert r.ok is False and "reused" in r.detail


def test_name_uniqueness_fails_on_a_duplicate_within_the_booking():
    src = FakeSource({"ABC123": {"passengers": ["PERCY MOSSERSHAW", "PERCY MOSSERSHAW"],
                                 "names_elsewhere": []}})
    r = verify.verify_case(_case(), src, areas=["name_uniqueness"]).checks[0]
    assert r.ok is False


def test_name_uniqueness_passes_for_an_exclusive_name():
    src = FakeSource({"ABC123": {"passengers": ["PERCY MOSSERSHAW"], "names_elsewhere": []}})
    r = verify.verify_case(_case(), src, areas=["name_uniqueness"]).checks[0]
    assert r.ok is True


def test_name_uniqueness_is_not_just_a_last_name_match():
    """The old implementation passed whenever trip.last_name equalled the expected surname, which
    certified nothing. A matching surname that is reused elsewhere must now FAIL."""
    src = FakeSource({"ABC123": {"trip": {"last_name": "MOSSERSHAW", "status": "ACTIVE"},
                                 "passengers": ["PERCY MOSSERSHAW"],
                                 "names_elsewhere": [("PERCY", "MOSSERSHAW")]}})
    report = verify.verify_case(_case(), src, areas=["passenger", "name_uniqueness"])
    passenger, uniqueness = report.checks
    assert passenger.ok is True and uniqueness.ok is False


# ── gap 5/9/10/12: the previously-skipped checkpoint areas ────────────────────────────────────
def test_group_context_requires_booking_subtype_group():
    uc = _case(title="GROUP booking of 9")
    bad = FakeSource({"ABC123": {"booking_context": {"bookingSubtype": "INDIVIDUAL"}}})
    good = FakeSource({"ABC123": {"booking_context": {"bookingSubtype": "GROUP"}}})
    assert verify.verify_case(uc, bad, areas=["group_context"]).checks[0].ok is False
    assert verify.verify_case(uc, good, areas=["group_context"]).checks[0].ok is True


def test_group_context_is_not_applicable_to_a_normal_booking():
    r = verify.verify_case(_case(), FakeSource({}), areas=["group_context"]).checks[0]
    assert r.ok is None


def test_ac_wallet_loyalty_requires_a_membership_when_the_case_declares_one():
    uc = _case(extras={"loyalty_id": "123456789"})
    assert verify.verify_case(uc, FakeSource({"ABC123": {"loyalty": []}}),
                              areas=["ac_wallet_loyalty"]).checks[0].ok is False
    assert verify.verify_case(uc, FakeSource({"ABC123": {"loyalty": ["123456789"]}}),
                              areas=["ac_wallet_loyalty"]).checks[0].ok is True


def test_ac_wallet_loyalty_is_skipped_when_the_title_merely_mentions_the_wallet():
    """"AC Wallet" in a title usually names the payout OPTION, not a seeded membership. Enforcing on
    the wording failed 8 correctly-seeded SIT cases; the reference gates on a declared loyalty id."""
    uc = _case(title="APPR eligible - 3 to <6 hour delay - AC Wallet +20% (CAD 480)")
    assert verify.verify_case(uc, FakeSource({"ABC123": {"loyalty": []}}),
                              areas=["ac_wallet_loyalty"]).checks[0].ok is None


def test_pending_flight_must_be_inside_the_72h_window():
    uc = _case(title="PENDING - 72 hours not elapsed")
    near = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    far = (datetime.date.today() - datetime.timedelta(days=9)).isoformat()
    assert verify.verify_case(uc, FakeSource({"ABC123": {"flight_dates": [near]}}),
                              areas=["pending_flight_le_72h"]).checks[0].ok is True
    assert verify.verify_case(uc, FakeSource({"ABC123": {"flight_dates": [far]}}),
                              areas=["pending_flight_le_72h"]).checks[0].ok is False


def test_passenger_count_reconciles_against_the_declared_party_size():
    uc = _case(title="APPR eligible - 3 passengers on one booking")
    one = FakeSource({"ABC123": {"passengers": ["A B"]}})
    three = FakeSource({"ABC123": {"passengers": ["A B", "C D", "E F"]}})
    assert verify.verify_case(uc, one, areas=["passenger_count"]).checks[0].ok is False
    assert verify.verify_case(uc, three, areas=["passenger_count"]).checks[0].ok is True


def test_every_declared_fd_checkpoint_area_is_now_implemented():
    """No area in the fd feed's checkpoints.areas may report 'not verifiable by this auditor' —
    a silently-skipped area makes an all-pass gate weaker than it looks."""
    from core.registry import load_feed
    areas = load_feed("fd").checkpoints["areas"]
    src = FakeSource({"ABC123": {}})
    report = verify.verify_case(_case(), src, areas=areas, dds={})
    unhandled = [c.area for c in report.checks if c.detail == "not verifiable by this auditor"]
    assert unhandled == []


# ── gap 3/5/8: post-cascade write-back ────────────────────────────────────────────────────────
def test_finalize_writes_one_ticket_per_passenger():
    conn = FakeConn(passenger_ids=["P-2026-01-01-PT-1", "P-2026-01-01-PT-2", "P-2026-01-01-PT-3"])
    written = finalize.insert_tickets(conn, "ABC123-2026-01-01", "014363", 7)
    assert written == ["014363000007", "014363000702", "014363000703"]
    assert len(conn.sql_like("insert into ticket")) == 3


def test_finalize_ticket_insert_is_idempotent():
    conn = FakeConn(passenger_ids=["X-PT-1"])
    finalize.insert_tickets(conn, "ABC123-2026-01-01", "014363", 1)
    assert all("on conflict do nothing" in s for s in conn.sql_like("insert into ticket"))


def test_secondary_passenger_tickets_land_above_the_base_band():
    """PT-2..PT-n numbers must not fall inside the 000001..000300 band another case's primary
    ticket occupies."""
    assert int(finalize.ticket_for("014363", 7, 2)[6:]) > 300


def test_finalize_sets_dob_and_group_context():
    conn = FakeConn(passenger_ids=["X-PT-1"], eds_rows=[(1, {"bookingSubtype": "INDIVIDUAL"})])
    out = finalize.finalize_case(conn, pnr_id="ABC123-2026-01-01", prefix="014363",
                                 case_index=1, dob="1986-04-23", group=True)
    assert out["group_rows"] == 1 and conn.commits == 1
    assert conn.sql_like("update passenger set date_of_birth")
    updated = [p for s, p in conn.db["sql"] if "update eds_pnr_output" in s][0]
    assert json.loads(updated[0])["bookingSubtype"] == "GROUP"


def test_group_context_is_left_alone_for_a_normal_booking():
    conn = FakeConn(passenger_ids=["X-PT-1"], eds_rows=[(1, {})])
    finalize.finalize_case(conn, pnr_id="P", prefix="014363", case_index=1,
                           dob="1986-04-23", group=False)
    assert conn.sql_like("update eds_pnr_output") == []


# ── gap 7: free ticket-prefix scan ────────────────────────────────────────────────────────────
def test_free_ticket_prefix_skips_consumed_bands():
    conn = FakeConn(used_prefixes={"014363": 239, "014364": 12})
    assert finalize.free_ticket_prefix(conn, start=14363, end=14370) == "014365"


def test_free_ticket_prefix_raises_when_every_band_is_consumed():
    conn = FakeConn(used_prefixes={f"01436{n}": 1 for n in range(3, 6)})
    with pytest.raises(RuntimeError, match="no free ticket prefix"):
        finalize.free_ticket_prefix(conn, start=14363, end=14366)


# ── gap 4/6: phone, DOB, OAL AC-ify at render time ────────────────────────────────────────────
def test_contact_phone_is_written_alongside_the_email():
    pnr = {"processedPnr": {"contacts": [{"email": {"address": "old@x.com"}}]}}
    render._set_contact(pnr, "new@x.com", "+94712534323")
    c = pnr["processedPnr"]["contacts"][0]
    assert c["email"]["address"] == "new@x.com" and c["phone"]["number"] == "+94712534323"


def test_contact_phone_is_optional():
    pnr = {"processedPnr": {"contacts": [{"email": {"address": "old@x.com"}}]}}
    render._set_contact(pnr, "new@x.com")
    assert "phone" not in pnr["processedPnr"]["contacts"][0]


def test_dob_is_set_on_every_traveler():
    pnr = {"processedPnr": {"travelers": [{"birthDate": "1970-01-01"}, {"name": "x"}]}}
    render._set_dob(pnr, "1986-04-23")
    assert [t.get("birthDate") for t in pnr["processedPnr"]["travelers"]] == \
        ["1986-04-23", "1986-04-23"]


def test_oal_legs_are_ac_ified():
    """A non-AC operating carrier blocks the trip-tracer cascade, so the trip row is never created
    and the bot cannot find the booking."""
    pnr = {"processedPnr": {"segments": [
        {"operatingCarrier": {"code": "PAL"}, "marketingCarrier": {"code": "AC"},
         "flightNumber": "8001", "operatingFlightNumber": "215"}]}}
    changed = render._acify_segments(pnr)
    seg = pnr["processedPnr"]["segments"][0]
    assert changed == 1
    assert seg["operatingCarrier"]["code"] == "AC"
    assert seg["operatingFlightNumber"] == "8001"


def test_ac_only_legs_are_untouched():
    pnr = {"processedPnr": {"segments": [{"operatingCarrier": {"code": "AC"}}]}}
    assert render._acify_segments(pnr) == 0


# ── gap 11: version-bump republish ────────────────────────────────────────────────────────────
def test_republish_bumps_the_feed_timestamps():
    pnr = {"processedPnr": {"lastModification": {"dateTime": "2020-01-01T00:00:00.000Z"},
                            "originFeedTimeStamp": "2020-01-01T00:00:00.000Z"}}
    from seed.kafka_seed import bump_feed_timestamps
    assert bump_feed_timestamps(pnr, "2026-07-21T10:00:00.000Z") == 2
    assert pnr["processedPnr"]["lastModification"]["dateTime"] == "2026-07-21T10:00:00.000Z"
    assert pnr["processedPnr"]["originFeedTimeStamp"] == "2026-07-21T10:00:00.000Z"


def test_ne_nd_reason_text_applies_to_spaced_and_underscored_verdicts():
    """Catalogs spell the verdict "Not Eligible" (gap doc) or "NOT_ELIGIBLE" (donor index); both
    must reach the reason check rather than reporting "n/a for eligible case"."""
    import dataclasses
    base = _case()
    for spelling in ("Not Eligible", "NOT_ELIGIBLE", "No Determination", "NO_DETERMINATION"):
        uc = dataclasses.replace(base, verdict=spelling)
        r = verify.verify_case(uc, FakeSource({}), areas=["ne_nd_reason_text"],
                               dds={"reason": "delay below threshold"}).checks[0]
        assert r.ok is True, f"{spelling} -> {r.detail}"


def test_flight_dates_query_uses_a_real_column():
    """Guards the column name against the live schema shape (departure_datetime_local, not
    departure_local_date, which did not exist and errored the PENDING case in the CRT pilot)."""
    import inspect
    from seed.source import AuroraSource
    sql = inspect.getsource(AuroraSource.flight_dates)
    assert "departure_datetime_local" in sql and "departure_local_date" not in sql
