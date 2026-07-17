"""Kafka (MSK) seeder — publish FD preseed fixtures to an env's ingress topics so they cascade
into trip-tracer Aurora, with the OTP contact email rewritten to the env's mailinator inbox.

Env-independent by construction: every coordinate (bootstrap, MSK secret, topics, cascade settle
windows, fixtures dir) is read from the Env descriptor's `seed_targets` block — this module has no
per-env branches. Swapping env=crt/int/bat changes only the descriptor, not this code.

Cascade order (matches the live Flink pipeline): PNR -> settle -> TKT -> settle -> FDM-SKD ->
settle -> FDM-DELAY -> settle (-> AACC). The settle windows let each stage's derived events land
in Aurora before the next stage references them.

Live deps (boto3, kafka-python) are imported lazily so the module loads offline; unit tests inject
a fake producer via `producer_factory` and a no-op `sleep`.
"""
from __future__ import annotations

import glob
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SeedMessage:
    """One Kafka record to produce: a resolved topic, a value (dict for JSON feeds, bytes for FDM
    XML), and an optional partition key."""
    topic: str
    value: object
    key: str | None


@dataclass
class SeedPlan:
    """The full set of records to produce for a batch of fixtures, grouped by cascade stage."""
    pnr: list[SeedMessage] = field(default_factory=list)
    tkt: list[SeedMessage] = field(default_factory=list)
    fdm_skd: list[SeedMessage] = field(default_factory=list)
    fdm_delay: list[SeedMessage] = field(default_factory=list)
    aacc: list[SeedMessage] = field(default_factory=list)
    locators: list[str] = field(default_factory=list)

    def total(self) -> int:
        return len(self.pnr) + len(self.tkt) + len(self.fdm_skd) + len(self.fdm_delay) + len(self.aacc)


def mailinator_contact(env) -> str:
    """The env's uniform OTP address, `<inbox>@<domain>` — the same address the runner's OTP
    provider polls, so a seeded PNR's verification email lands where the runner reads it."""
    otp = env.otp or {}
    return f"{otp['inbox']}@{otp['domain']}"


def inject_contact(pnr: dict, email: str) -> int:
    """Rewrite every `processedPnr.contacts[].email.address` to `email`. Returns the number of
    contact emails changed (0 means the fixture had no email contact to gate OTP on)."""
    changed = 0
    for c in (pnr.get("processedPnr", {}).get("contacts") or []):
        em = c.get("email")
        if isinstance(em, dict):
            em["address"] = email
            changed += 1
    return changed


def build_plan(env, locators, *, contact_email: str | None = None,
               pnr_version: str | None = None, fixtures_dir: str | None = None) -> SeedPlan:
    """Read each fixture locator dir and assemble the produce plan. Rewrites the PNR contact email
    to `contact_email` (default: the env's mailinator address) and, if `pnr_version` is given,
    overrides `processedPnr.version` to force an update instead of a replay-dedup."""
    st = env.seed_targets
    topics = st["topics"]
    contact_email = contact_email or mailinator_contact(env)
    root = Path(fixtures_dir or st["fixtures_dir"])
    plan = SeedPlan()
    for loc in locators:
        d = root / loc
        pnr = json.loads((d / "01_pnr.json").read_text(encoding="utf-8"))
        if pnr_version:
            pnr["processedPnr"]["version"] = str(pnr_version)
        inject_contact(pnr, contact_email)
        plan.pnr.append(SeedMessage(topics["pnr"], pnr, pnr["processedPnr"]["bookingIdentifier"]))
        plan.locators.append(loc)
        for tf in sorted(glob.glob(str(d / "02_ticket*.json"))):
            t = json.loads(Path(tf).read_text(encoding="utf-8"))
            plan.tkt.append(SeedMessage(topics["tkt"], t, t["processedTicket"]["primaryDocumentNumber"]))
        for f in sorted(glob.glob(str(d / "*.xml"))):
            msg = SeedMessage(topics["fdm"], Path(f).read_bytes(), None)
            (plan.fdm_skd if "skd" in Path(f).name.lower() else plan.fdm_delay).append(msg)
        for af in sorted(glob.glob(str(d / "05_aacc*.json"))):
            a_ = json.loads(Path(af).read_text(encoding="utf-8"))
            rec = a_["PassengerNotification"]["recordLocator"][0]["recordNumber"]
            plan.aacc.append(SeedMessage(topics["aacc"], a_, rec))
    return plan


def make_producer(env):
    """Live SCRAM-SHA-512 KafkaProducer built entirely from the env descriptor: the MSK secret
    (via boto3 Secrets Manager under env.aws.profile) yields the SCRAM creds and, if present, the
    authoritative `sourceBootstrapServers`; otherwise the descriptor's `bootstrap` is used."""
    import boto3  # lazy — live only
    from kafka import KafkaProducer  # lazy — live only

    st = env.seed_targets
    region = (env.chatbot or {}).get("region") or (env.aws or {}).get("region") or "ca-central-1"
    profile = (env.aws or {}).get("profile")
    sm = boto3.Session(profile_name=profile).client("secretsmanager", region_name=region)
    sec = json.loads(sm.get_secret_value(SecretId=st["msk_secret"])["SecretString"])
    boot = sec.get("sourceBootstrapServers") or st.get("bootstrap")
    return KafkaProducer(
        bootstrap_servers=boot.split(","),
        security_protocol="SASL_SSL", sasl_mechanism="SCRAM-SHA-512",
        sasl_plain_username=sec["username"], sasl_plain_password=sec["password"],
        value_serializer=lambda v: v if isinstance(v, (bytes, bytearray)) else json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: None if k is None else str(k).encode("utf-8"),
        acks="all", retries=3, linger_ms=20,
    )


def seed(env, locators, *, contact_email: str | None = None, pnr_version: str | None = None,
         fixtures_dir: str | None = None, stages=None, producer_factory=None,
         sleep=time.sleep, log=print) -> SeedPlan:
    """Build the plan and produce it in cascade order with the descriptor's settle windows.

    `stages` optionally restricts to a subset of {PNR, TKT, FDM, AACC}. `producer_factory` and
    `sleep` are injection points for offline tests (a fake producer + a no-op sleep). Returns the
    SeedPlan so the caller can log/verify what was produced."""
    plan = build_plan(env, locators, contact_email=contact_email,
                      pnr_version=pnr_version, fixtures_dir=fixtures_dir)
    settle = (env.seed_targets.get("settle") or {})
    wanted = None if not stages else {s.strip().upper() for s in stages}
    want = (lambda s: True) if wanted is None else (lambda s: s in wanted)
    producer = (producer_factory or make_producer)(env)

    def _stage(name: str, msgs: list[SeedMessage], secs: float) -> None:
        if not msgs:
            return
        log(f"-- stage {name}: {len(msgs)} msg(s) --")
        for m in msgs:
            producer.send(m.topic, key=m.key, value=m.value)
        producer.flush()
        log(f"   sent to {msgs[0].topic}; settle {secs}s")
        sleep(secs)

    try:
        if want("PNR"):
            _stage("PNR", plan.pnr, settle.get("pnr", 45))
        if want("TKT"):
            _stage("TKT", plan.tkt, settle.get("tkt", 30))
        if want("FDM"):
            _stage("FDM-SKD", plan.fdm_skd, settle.get("fdm_skd", 45))
            _stage("FDM-DELAY", plan.fdm_delay, settle.get("fdm_delay", 60))
        if want("AACC"):
            _stage("AACC", plan.aacc, settle.get("aacc", 40))
    finally:
        try:
            producer.flush()
            producer.close()
        except Exception:
            pass
    return plan
