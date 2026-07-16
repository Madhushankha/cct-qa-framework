"""Live INT smoke for the seed verifier. Skipped unless CCTQA_LIVE=1 (needs AWS int-sso + network),
so normal offline runs never touch AWS. Validates: env descriptor -> secret -> Aurora -> verify_case."""
import os
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CCTQA_LIVE") != "1",
                                reason="live INT smoke (set CCTQA_LIVE=1 + AWS_PROFILE=int-sso)")


def test_verify_case_against_live_int():
    from core.registry import load_env
    from seed.source import connect
    from seed.verify import verify_case
    from catalog.model import UseCase, SeedSpec

    src = connect(load_env("int"))
    cur = src._conn.cursor()
    cur.execute("select substring(pnr_id from 1 for 6) from eds_pnr_output "
                "where bounds like '%@%' and pnr_id not like 'ZZ%' order by received_at desc limit 1")
    pnr = cur.fetchone()[0]
    cur.close()

    trip = src.trip(pnr)
    email = src.eds(pnr)["emails"][0]
    uc = UseCase(id="LIVE", regime="", verdict="", system_code="", title="", third_party=False,
                 checkpoint_vector=[], customer_intent="", expected_transcript=[],
                 seed=SeedSpec(pnr=pnr, passenger=f"X {trip['last_name']}"),
                 seed_pending=False, content_hash="h")
    rep = verify_case(uc, src, expected_email=email,
                      areas=["eds_pnr_output", "eds_contact_email", "trip_active", "passenger"])
    # a real, correctly-seeded booking should pass all four trip-tracer checkpoints
    assert rep.all_ok, rep.summary()
