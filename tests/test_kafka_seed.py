"""Offline tests for seed/kafka_seed.py — build_plan contact injection + seed() cascade ordering,
using a tmp fixtures dir, a fake producer, and a no-op sleep (no boto3 / no live MSK)."""
import json
from dataclasses import dataclass, field

from seed.kafka_seed import SeedMessage, build_plan, inject_contact, mailinator_contact, seed


@dataclass
class FakeEnv:
    otp: dict
    seed_targets: dict
    aws: dict = field(default_factory=dict)
    chatbot: dict = field(default_factory=dict)


def _env(fixtures_dir):
    return FakeEnv(
        otp={"inbox": "lahiru", "domain": "ae-qa1-aircanada.mailinator.com"},
        seed_targets={
            "topics": {"pnr": "T.PNR", "tkt": "T.TKT", "fdm": "T.FDM", "aacc": "T.AACC"},
            "settle": {"pnr": 1, "tkt": 1, "fdm_skd": 1, "fdm_delay": 1, "aacc": 1},
            "fixtures_dir": str(fixtures_dir),
        },
    )


def _write_fixture(root, loc, *, email="old@gmail.com"):
    d = root / loc
    d.mkdir(parents=True)
    (d / "01_pnr.json").write_text(json.dumps({
        "processedPnr": {"bookingIdentifier": loc, "version": "1",
                         "contacts": [{"type": "contact", "email": {"address": email}}]}
    }), encoding="utf-8")
    (d / "02_ticket.json").write_text(json.dumps({
        "processedTicket": {"primaryDocumentNumber": "0142000800200"}
    }), encoding="utf-8")
    (d / "03_fdm_skd_leg1.xml").write_text("<skd/>", encoding="utf-8")
    (d / "04_fdm_delay_leg1.xml").write_text("<delay/>", encoding="utf-8")


def test_mailinator_contact():
    env = _env("/x")
    assert mailinator_contact(env) == "lahiru@ae-qa1-aircanada.mailinator.com"


def test_inject_contact_rewrites_all():
    pnr = {"processedPnr": {"contacts": [
        {"email": {"address": "a@a.com"}}, {"email": {"address": "b@b.com"}}, {"phone": {"number": "1"}}]}}
    assert inject_contact(pnr, "x@m.com") == 2
    addrs = [c["email"]["address"] for c in pnr["processedPnr"]["contacts"] if "email" in c]
    assert addrs == ["x@m.com", "x@m.com"]


def test_build_plan_injects_mailinator_and_groups(tmp_path):
    _write_fixture(tmp_path, "FDAP36")
    env = _env(tmp_path)
    plan = build_plan(env, ["FDAP36"])
    assert plan.locators == ["FDAP36"]
    assert plan.pnr[0].value["processedPnr"]["contacts"][0]["email"]["address"] == \
        "lahiru@ae-qa1-aircanada.mailinator.com"
    assert plan.pnr[0].topic == "T.PNR" and plan.pnr[0].key == "FDAP36"
    assert plan.tkt[0].topic == "T.TKT" and plan.tkt[0].key == "0142000800200"
    assert len(plan.fdm_skd) == 1 and len(plan.fdm_delay) == 1
    assert plan.total() == 4


def test_build_plan_pnr_version_override(tmp_path):
    _write_fixture(tmp_path, "FDAP36")
    plan = build_plan(_env(tmp_path), ["FDAP36"], pnr_version="2")
    assert plan.pnr[0].value["processedPnr"]["version"] == "2"


class _FakeProducer:
    def __init__(self):
        self.sent = []
        self.flushed = 0
        self.closed = False

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key))

    def flush(self, *a, **k):
        self.flushed += 1

    def close(self, *a, **k):
        self.closed = True


def test_seed_produces_in_cascade_order(tmp_path):
    _write_fixture(tmp_path, "FDAP36")
    fake = _FakeProducer()
    slept = []
    plan = seed(_env(tmp_path), ["FDAP36"], producer_factory=lambda e: fake,
                sleep=lambda s: slept.append(s), log=lambda *a: None)
    topics = [t for t, _ in fake.sent]
    # PNR before TKT before both FDM
    assert topics.index("T.PNR") < topics.index("T.TKT") < topics.index("T.FDM")
    assert plan.total() == 4
    assert fake.closed and slept  # settle windows honoured, producer closed


def test_seed_stage_filter(tmp_path):
    _write_fixture(tmp_path, "FDAP36")
    fake = _FakeProducer()
    seed(_env(tmp_path), ["FDAP36"], stages=["PNR"], producer_factory=lambda e: fake,
         sleep=lambda s: None, log=lambda *a: None)
    assert {t for t, _ in fake.sent} == {"T.PNR"}
