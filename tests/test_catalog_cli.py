import catalog.cli as catalog_cli
import core.cli as core_cli

from tests.conftest import GAP_MIN, GAP_MIN_V2, make_feed


def test_run_catalog_prints_counts(capsys, feed):
    rc = catalog_cli.run_catalog(feed, None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "cases: 4" in out
    assert "checkpoints: 4" in out
    assert "uncovered: 1" in out


def test_run_catalog_prints_verdict_breakdown(capsys, feed):
    catalog_cli.run_catalog(feed, None)
    out = capsys.readouterr().out
    assert "Not Eligible" in out
    assert "Eligible" in out


def test_run_catalog_with_diff_prints_summary(capsys, feed):
    rc = catalog_cli.run_catalog(feed, str(GAP_MIN))
    out = capsys.readouterr().out
    assert rc == 0
    # diffing the feed's own gap doc (gap_min.html) against itself -> all unchanged, nothing else
    assert "4 unchanged" in out
    assert "added: (none)" in out
    assert "data-changed: (none)" in out


def test_run_catalog_with_diff_reports_added_case(capsys, feed):
    old_feed = make_feed(gap_doc=GAP_MIN, dataset=None)
    new_feed = make_feed(gap_doc=GAP_MIN_V2, dataset=None)
    rc = catalog_cli.run_catalog(new_feed, str(old_feed.gap_doc))
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 added" in out
    assert "SOC_UAT-005" in out


def test_catalog_cli_main_parses_feed_and_diff(monkeypatch, capsys, feed):
    monkeypatch.setattr(catalog_cli, "load_feed", lambda feed_id: feed)
    rc = catalog_cli.main(["anything"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cases: 4" in out


def test_catalog_cli_main_with_diff_flag(monkeypatch, capsys, feed):
    monkeypatch.setattr(catalog_cli, "load_feed", lambda feed_id: feed)
    rc = catalog_cli.main(["anything", "--diff", str(GAP_MIN)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unchanged" in out


def test_core_cli_forwards_catalog_subcommand(monkeypatch, capsys, feed):
    monkeypatch.setattr(catalog_cli, "load_feed", lambda feed_id: feed)
    rc = core_cli.main(["catalog", "anything"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cases: 4" in out


def test_core_cli_forwards_catalog_diff_flag(monkeypatch, capsys, feed):
    monkeypatch.setattr(catalog_cli, "load_feed", lambda feed_id: feed)
    rc = core_cli.main(["catalog", "anything", "--diff", str(GAP_MIN)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unchanged" in out


def test_core_cli_list_and_validate_still_work(capsys):
    # regression: adding the catalog subcommand must not disturb existing subcommands
    rc = core_cli.main(["list"])
    assert rc == 0
    rc = core_cli.main(["validate"])
    assert rc == 0


def test_core_cli_unknown_command_still_nonzero():
    assert core_cli.main(["frobnicate"]) != 0
