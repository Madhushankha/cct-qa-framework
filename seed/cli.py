"""`cctqa seed <product> <env> <feed> --from SRC:NEW [SRC:NEW ...]` — the full 3-part INT/CRT seed:

  1. clone each source fixture to a FRESH locator (in-window flight date + the env's mailinator
     contact + version left at "1" — a fresh locator needs no version bump, and a bumped version
     overflows the trip version column and the CREATE fails silently);
  2. Kafka-inject PNR -> TKT -> FDM so it cascades to trip/ticket/flight_leg/EDS in Aurora;
  3. verify the trip landed, then pin the DDS determination (S3 + execution_traces) and confirm the
     bot's by-pnr endpoint serves it.

Everything is descriptor-driven (env.seed_targets). The cloned corpus is written under a run-scoped
output dir so the runner can pick it up with `--fixtures <clone_dir> --only <locators>`.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path


def _family_for(uc, default: str) -> str:
    """Pick the DDS template family from the case's expected amount/regime (APPR CAD 400/700/1000),
    falling back to `default` when it can't be inferred."""
    if uc is None:
        return default
    amt = (uc.seed.amount or {})
    if (uc.regime or "").upper() == "APPR" and (amt.get("currency") == "CAD"):
        fam = {400: "APPR_CAD_400", 700: "APPR_CAD_700", 1000: "APPR_CAD_1000"}.get(int(amt.get("value", 0)))
        if fam:
            return fam
    return default


def in_window_date(now: datetime.datetime | None = None, days_ago: int = 7) -> str:
    """A flight date inside the FD data window: >72h past AND <14 days ago. Default 7 days ago."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now.date() - datetime.timedelta(days=days_ago)).isoformat()


def run_seed(product: str, env: str, feed: str, mapping: list[tuple[str, str]], *,
             clone_dir: str, family: str = "APPR_CAD_400", days_ago: int = 7,
             verify: bool = True) -> int:
    from core.registry import resolve
    from seed import clone as cloner
    from seed import dds_pin, kafka_seed

    ctx = resolve(product, env, feed)
    e = ctx.env
    contact = kafka_seed.mailinator_contact(e)
    fixtures_root = e.seed_targets["fixtures_dir"]
    now = datetime.datetime.now(datetime.timezone.utc)
    flight_date = in_window_date(now, days_ago)
    today = now.date().isoformat()
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Ticket document numbers must be UNIQUE per run — the finalize insert is ON CONFLICT DO NOTHING,
    # so a reused docnum silently drops the ticket (HOWTO gotcha). Base the index on the run time
    # (seconds-of-day * 100 + case idx) so repeat single-case seeds never collide.
    docnum_base = int(now.strftime("%H%M%S")) * 100
    print(f"[seed] {product}.{env}.{feed} contact={contact} flight_date={flight_date} -> {clone_dir}",
          flush=True)
    metas, locs = {}, []
    for i, (src, new) in enumerate(mapping):
        d = cloner.clone_fixture(f"{fixtures_root}/{src}", clone_dir, new, contact_email=contact,
                                 index=docnum_base + i, new_date=flight_date)
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        metas[new] = m
        locs.append(new)
        print(f"  [clone] {src} -> {new} pnr_id={m['pnr_id']} {m['carrier']}{m['flight']} {m['route']}")

    print(f"[seed] Kafka-injecting {locs} ...", flush=True)
    kafka_seed.seed(e, locs, fixtures_dir=clone_dir)

    ok = 0
    from catalog.fixtures import load_fixture_catalog
    cat = load_fixture_catalog(clone_dir, only=locs)
    by_id = {c.id: c for c in cat.cases}
    for new in locs:
        m = metas[new]
        landed = _trip_landed(e, new) if verify else True
        if not landed:
            print(f"  [trip] {new}: NOT FOUND — skipping DDS pin")
            continue
        o, dst = (m["route"].split("-") + ["", ""])[:2]
        fam = _family_for(by_id.get(new), family)
        res = dds_pin.pin_case(e, pnr_id=m["pnr_id"], locator=new, carrier=m["carrier"],
                               flight_number=m["flight"], origin=o, destination=dst, date=today,
                               passenger_id=f"{m['pnr_id']}-PT-1", family=fam, timestamp=ts)
        line = f"  [ok] {new} trip=ACTIVE dds={res['pin']}"
        if verify:
            v = dds_pin.verify_by_pnr(e, m["pnr_id"])
            line += f" by-pnr={v['status_code']} {'ELIGIBLE' if v['eligible'] else '-'} {v['amount']}"
            print(line, flush=True)
            vec = _audit_checkpoints(e, by_id.get(new), contact, v)
            _write_checkpoints(clone_dir, new, vec)
        else:
            print(line, flush=True)
        ok += 1

    print(f"\n=== seeded {ok}/{len(locs)} cases to {env} · clone_dir={clone_dir} ===")
    print(f"    run them: cctqa run {product} {env} {feed} --fixtures {clone_dir} --only {' '.join(locs)}")
    return 0 if ok else 1


def _dds_family(uc) -> str | None:
    """Derive the DDS template family from the case's systemCode (regime is blank on gap-doc cases,
    so the systemCode `FD-<REGIME>-<CLASS>-<n>` is the reliable signal). Today only APPR-eligible
    CAD tiers have a template: FD-APPR-EL-* + CAD amount -> APPR_CAD_400/700/1000."""
    sc = (uc.seed.system_code or uc.system_code or "").upper()
    amt = (uc.seed.amount or {})
    if sc.startswith("FD-APPR-EL") and amt.get("currency") == "CAD":
        try:
            return {400: "APPR_CAD_400", 700: "APPR_CAD_700",
                    1000: "APPR_CAD_1000"}.get(int(amt.get("value", 0)))
        except (TypeError, ValueError):
            return None
    return None


def _templated_family(uc, templates: set) -> str | None:
    """The DDS template family this case can pin with today, or None if unavailable/unregistered."""
    fam = _dds_family(uc)
    return fam if fam and fam in templates else None


def _pin_and_verify_one(e, c, *, flight_date: str, today: str, ts: str, contact: str,
                        clone_dir: str, verify: bool, flight_number: int = 8002) -> dict:
    """Pin DDS + (optionally) verify one already-published case. Independent per pnr_id, so the
    whole set can run concurrently. Catches its own errors and returns a gate=error record so one
    transient failure (e.g. an expired SSO token on a single worker) never aborts the whole batch
    or loses the mapping for the cases that did succeed."""
    from seed import dds_pin
    loc = c.seed.pnr
    pnr_id = f"{loc}-{flight_date}"
    try:
        if verify and not _trip_landed(e, loc):
            print(f"  [trip] {c.id} {loc}: NOT FOUND — skipping DDS pin", flush=True)
            return {"case_id": c.id, "locator": loc, "gate": "trip_missing"}
        o, dst = (c.seed.route.split("-") + ["", ""])[:2]
        fam = _dds_family(c) or "APPR_CAD_400"
        res = dds_pin.pin_case(e, pnr_id=pnr_id, locator=loc, carrier="AC",
                               flight_number=flight_number, origin=o, destination=dst, date=today,
                               passenger_id=f"{pnr_id}-PT-1", family=fam, timestamp=ts)
        line = f"  [ok] {c.id} {loc} dds={res['pin']}"
        gate = "seeded"
        if verify:
            v = dds_pin.verify_by_pnr(e, pnr_id)
            line += f" by-pnr={v['status_code']} {'ELIGIBLE' if v['eligible'] else '-'} {v['amount']}"
            vec = _audit_checkpoints(e, c, contact, v)
            _write_checkpoints(clone_dir, loc, vec)
            gate = "all-pass" if all(x.get("pass") is not False for x in vec) else "checkpoint_fail"
        print(line, flush=True)
        return {"case_id": c.id, "locator": loc, "pnr_id": pnr_id, "gate": gate}
    except Exception as exc:  # noqa: BLE001 — isolate a single case's failure from the batch
        print(f"  [ERR] {c.id} {loc}: {type(exc).__name__}: {exc}", flush=True)
        return {"case_id": c.id, "locator": loc, "pnr_id": pnr_id, "gate": "error",
                "error": f"{type(exc).__name__}: {exc}"}


def run_seed_all(product: str, env: str, feed: str, *, clone_dir: str, days_ago: int = 7,
                 verify: bool = True, limit: int | None = None, workers: int = 8) -> int:
    """Seed the WHOLE gap-doc catalog: render each case from the framework base template with its
    own dataset 6-char locator + independent name (seed/render.py), then publish -> pin -> verify.
    Staged: only cases whose DDS family has a registered template are seeded; the rest are reported
    as skipped (need a harvested template). The pin/verify pass runs concurrently (`workers`
    threads) since each pnr_id is independent; the Kafka publish + settle is already one shared
    batch. Prints a case_id -> locator mapping."""
    from concurrent.futures import ThreadPoolExecutor
    from core.registry import resolve
    from catalog.parser import load_catalog
    from core.descriptors import Feed  # noqa: F401 (documents the resolve dependency)
    from seed import kafka_seed, render

    ctx = resolve(product, env, feed)
    e = ctx.env
    contact = kafka_seed.mailinator_contact(e)
    templates = set((e.seed_targets.get("dds", {}).get("templates") or {}).keys())
    now = datetime.datetime.now(datetime.timezone.utc)
    flight_date = in_window_date(now, days_ago)
    today = now.date().isoformat()
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    docnum_base = int(now.strftime("%H%M%S")) * 100
    base_dir = "data/fd-templates/base_appr"

    cat = load_catalog(ctx.feed)
    seedable, skipped = [], []
    for c in cat.cases:
        if c.seed_pending or not c.seed.pnr:
            skipped.append((c.id, "no_data"))
        elif _templated_family(c, templates) is None:
            skipped.append((c.id, "no_template"))
        else:
            seedable.append(c)
    if limit:
        seedable = seedable[:limit]

    print(f"[seed-all] {product}.{env}.{feed} contact={contact} flight_date={flight_date}")
    print(f"[seed-all] seedable={len(seedable)} skipped={len(skipped)} -> {clone_dir}", flush=True)

    by_loc, flight_of, locs = {}, {}, []
    for i, c in enumerate(seedable):
        flt = 8000 + (i + 1)  # unique per case so each FDM leg_id is distinct
        d = render.render_case(base_dir, clone_dir, c, contact_email=contact,
                               flight_date=flight_date, index=docnum_base + i, flight_number=flt)
        by_loc[c.seed.pnr] = c
        flight_of[c.seed.pnr] = flt
        locs.append(c.seed.pnr)
        print(f"  [render] {c.id} -> {c.seed.pnr} {c.seed.passenger} {c.seed.route} AC{flt}")

    print(f"[seed-all] Kafka-injecting {len(locs)} PNR(s) ...", flush=True)
    kafka_seed.seed(e, locs, fixtures_dir=clone_dir)

    print(f"[seed-all] pin+verify {len(locs)} case(s) with {workers} workers ...", flush=True)
    cases = [by_loc[loc] for loc in locs]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        mapping = list(pool.map(
            lambda c: _pin_and_verify_one(e, c, flight_date=flight_date, today=today, ts=ts,
                                          contact=contact, clone_dir=clone_dir, verify=verify,
                                          flight_number=flight_of[c.seed.pnr]),
            cases))

    ok = sum(1 for m in mapping if m.get("gate") in ("seeded", "all-pass"))
    _write_mapping(clone_dir, feed, mapping, skipped)
    print(f"\n=== seed-all: {ok}/{len(locs)} ok · {len(skipped)} skipped · clone_dir={clone_dir} ===")
    return 0 if ok else 1


def _write_mapping(clone_dir: str, feed: str, mapping: list[dict], skipped: list[tuple]) -> None:
    """Write the case_id -> locator ledger for this campaign run (JSON, next to the fixtures)."""
    doc = {"feed": feed, "seeded": mapping,
           "skipped": [{"case_id": cid, "reason": r} for cid, r in skipped]}
    (Path(clone_dir) / "seed-mapping.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")


def _audit_checkpoints(env, uc, contact_email, dds_verdict) -> list[dict]:
    """Run the feed's checkpoint audit for one seeded case, print a compact per-area vector, and
    return it as canonical-Result checkpoint dicts ({area, pass, detail})."""
    if uc is None:
        return []
    import yaml

    from seed import source as _src
    from seed import verify as _verify

    areas = (yaml.safe_load(Path("core/registry/feeds/fd.yaml").read_text(encoding="utf-8"))
             .get("checkpoints") or {}).get("areas")
    src = _src.connect(env)
    rep = _verify.verify_case(uc, src, expected_email=contact_email, areas=areas, dds=dds_verdict)
    sym = {True: "PASS", False: "FAIL", None: "skip"}
    n_pass = sum(1 for c in rep.checks if c.ok is True)
    n_fail = sum(1 for c in rep.checks if c.ok is False)
    for c in rep.checks:
        flag = "  " if c.ok is None else ("✓ " if c.ok else "✗ ")
        print(f"      {flag}{c.area:30} {sym[c.ok]:5} {c.detail}")
    print(f"      checkpoints: {n_pass} PASS / {n_fail} FAIL "
          f"({sum(1 for c in rep.checks if c.ok is None)} skip)", flush=True)
    return [{"area": c.area, "pass": c.ok, "detail": c.detail} for c in rep.checks]


def _write_checkpoints(clone_dir: str, locator: str, vector: list[dict]) -> None:
    """Persist the checkpoint vector next to the cloned fixture so the runner attaches it to the
    Result (report shows the full vector instead of 0/0)."""
    if not vector:
        return
    (Path(clone_dir) / f"{locator}.checkpoints.json").write_text(
        json.dumps(vector, indent=1), encoding="utf-8")


def _trip_landed(env, locator: str) -> bool:
    """True if a trip row exists for this locator in the env's trip-tracer Aurora."""
    import boto3  # lazy
    import psycopg2  # lazy

    st = env.seed_targets
    profile = (env.aws or {}).get("profile")
    sm = boto3.Session(profile_name=profile).client("secretsmanager", region_name="ca-central-1")
    sec = json.loads(sm.get_secret_value(SecretId=st["aurora_secret"])["SecretString"])
    conn = psycopg2.connect(host=st["aurora_host"], port=5432, dbname="trip-tracer",
                            user=sec["username"], password=sec["password"], sslmode="require",
                            connect_timeout=15)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    cur.execute("select 1 from trip where pnr=%s limit 1", (locator,))
    found = cur.fetchone() is not None
    conn.close()
    return found


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cctqa seed")
    p.add_argument("product")
    p.add_argument("env")
    p.add_argument("feed")
    p.add_argument("--from", dest="mapping", nargs="+",
                   help="SRC:NEW pairs, e.g. FDAP36:ZZFDAE FDAP69:ZZFDBF")
    p.add_argument("--all", action="store_true",
                   help="seed the WHOLE gap-doc catalog (render each case from data/fd-templates)")
    p.add_argument("--limit", type=int, default=None, help="with --all: cap the number of cases")
    p.add_argument("--workers", type=int, default=8,
                   help="with --all: concurrent pin/verify workers (default 8)")
    p.add_argument("--clone-dir", default=None, help="output dir for cloned fixtures (default: runs/seed/<ts>)")
    p.add_argument("--family", default="APPR_CAD_400", help="DDS template family")
    p.add_argument("--days-ago", type=int, default=7, help="flight date = N days ago (FD window 3..14)")
    p.add_argument("--no-verify", action="store_true", help="skip trip-landed + by-pnr verification")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    clone_dir = args.clone_dir or str(Path("runs") / "seed" /
                                      datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    if args.all:
        return run_seed_all(args.product, args.env, args.feed, clone_dir=clone_dir,
                            days_ago=args.days_ago, verify=not args.no_verify, limit=args.limit,
                            workers=args.workers)
    if not args.mapping:
        print("provide --from SRC:NEW pairs, or --all to seed the whole catalog")
        return 2

    pairs = []
    for item in args.mapping:
        if ":" not in item:
            print(f"bad --from item '{item}', expected SRC:NEW")
            return 2
        src, new = item.split(":", 1)
        pairs.append((src, new))
    return run_seed(args.product, args.env, args.feed, pairs, clone_dir=clone_dir,
                    family=args.family, days_ago=args.days_ago, verify=not args.no_verify)


if __name__ == "__main__":
    import sys
    sys.exit(main())
