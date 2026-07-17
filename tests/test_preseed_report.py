"""Preseed HTML report: per-case tester-facing table (case id, PNR, full name, ticket, OTP email)."""
import json

from seed.report import build_preseed_report, collect_preseed


def _case_dir(root, loc, case_id, first, surname, ticket, sc):
    d = root / loc
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "locator": loc, "pnr_id": f"{loc}-2026-07-09", "case_id": case_id, "first": first,
        "surname": surname, "ticket": ticket, "route": "YUL-YYZ", "flight": 8001,
        "date": "2026-07-09", "system_code": sc,
        "email": "lahiru@ae-qa1-aircanada.mailinator.com"}), encoding="utf-8")


def test_collect_and_render(tmp_path):
    _case_dir(tmp_path, "MHGQHS", "FD_TC_001", "YANNICK", "THORNENLOW", "0142000000011", "FD-APPR-EL-01")
    _case_dir(tmp_path, "MPGPAW", "FD_TC_002", "PRIYA", "FAIRINGWYN", "0142000000022", "FD-APPR-EL-02")
    (tmp_path / "seed-mapping.json").write_text(json.dumps({"feed": "fd", "seeded": [
        {"case_id": "FD_TC_001", "locator": "MHGQHS", "gate": "all-pass"},
        {"case_id": "FD_TC_002", "locator": "MPGPAW", "gate": "checkpoint_fail"}]}), encoding="utf-8")

    rows = collect_preseed(tmp_path)
    assert [r["case_id"] for r in rows] == ["FD_TC_001", "FD_TC_002"]
    assert rows[0]["pnr"] == "MHGQHS" and rows[0]["passenger"] == "YANNICK THORNENLOW"
    assert rows[0]["last_name"] == "THORNENLOW" and rows[0]["gate"] == "all-pass"

    out = build_preseed_report(tmp_path, product="bravo", env="int", feed="fd", date="2026-07-17")
    html = out.read_text(encoding="utf-8")
    assert "MHGQHS" in html and "THORNENLOW" in html and "0142000000011" in html
    assert "lahiru@ae-qa1-aircanada.mailinator.com" in html
    assert "FD_TC_002" in html and "2 cases" in html
