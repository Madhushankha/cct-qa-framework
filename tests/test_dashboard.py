"""Tests for the P7 dashboard over a synthetic results tree."""
import json

from ui.dashboard import _parse_cell, build_dashboard, collect_runs


def _run(root, date, cell, verdicts, docs=()):
    d = root / date / cell
    d.mkdir(parents=True)
    for i, me in enumerate(verdicts):
        (d / f"C{i}.result.json").write_text(json.dumps({
            "verdict": {"matches_expected": me, "reached_determination": True},
            "harness": {"error": None}}), encoding="utf-8")
    for fname in docs:
        (d / fname).write_text("<html></html>", encoding="utf-8")


def test_parse_cell():
    assert _parse_cell("int_bravo_fd_204833") == {"env": "int", "product": "bravo", "feed": "fd", "time": "204833"}


def test_collect_and_build(tmp_path):
    _run(tmp_path, "2026-07-16", "int_bravo_fd_100000", [True, True, False], docs=["index.html"])
    _run(tmp_path, "2026-07-16", "int_bravo_fd_090000", [True])
    _run(tmp_path, "2026-07-15", "crt_bravo_soc_120000", [False])
    runs = collect_runs(tmp_path)
    assert len(runs) == 3
    newest = runs[0]  # newest date + newest time first
    assert newest["date"] == "2026-07-16" and newest["time"] == "100000"
    assert newest["cases"] == 3 and newest["pass"] == 2 and newest["fail"] == 1
    out = build_dashboard(tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "CCT-QA-FRAMEWORK" in html
    assert "int · bravo · fd" in html
    assert '2026-07-16/int_bravo_fd_100000/index.html' in html  # links to per-run report
    assert "2026-07-15" in html and "2026-07-16" in html


def test_chips_link_only_when_files_exist(tmp_path):
    _run(tmp_path, "2026-07-16", "int_bravo_fd_100000", [True],
         docs=["index.html", "quality-index.html"])
    html = build_dashboard(tmp_path).read_text(encoding="utf-8")
    # existing files -> linked pipeline chips (Run == index.html, Quality == quality-index.html)
    assert '<a class="chip" href="2026-07-16/int_bravo_fd_100000/index.html">Run</a>' in html
    assert '<a class="chip" href="2026-07-16/int_bravo_fd_100000/quality-index.html">Quality</a>' in html
    # missing stages -> greyed, unlinked spans
    assert '<span class="chip off">Evidence</span>' in html
    assert '<span class="chip off">Metrics</span>' in html
    assert 'bot-issues.html"' not in html and 'report.html"' not in html


def test_dead_run_dir_is_not_linked(tmp_path):
    # a run with results but NO index.html must not produce a Report link (old dead-link bug)
    _run(tmp_path, "2026-07-16", "int_bravo_fd_090000", [True])
    html = build_dashboard(tmp_path).read_text(encoding="utf-8")
    assert 'href="2026-07-16/int_bravo_fd_090000/index.html"' not in html
    assert '<span class="chip off">Run</span>' in html


def test_rows_carry_data_attributes(tmp_path):
    _run(tmp_path, "2026-07-16", "int_bravo_fd_100000", [True, True, False])
    html = build_dashboard(tmp_path).read_text(encoding="utf-8")
    assert 'data-env="int"' in html
    assert 'data-product="bravo"' in html
    assert 'data-feed="fd"' in html
    assert 'data-date="2026-07-16"' in html
    # per-run tallies embedded so the filter JS can recompute tiles without parsing text
    assert 'data-cases="3"' in html and 'data-pass="2"' in html
    assert 'data-fail="1"' in html and 'data-error="0"' in html


def test_filter_bar_and_recompute_js(tmp_path):
    _run(tmp_path, "2026-07-16", "int_bravo_fd_100000", [True])
    _run(tmp_path, "2026-07-15", "crt_bravo_soc_120000", [False])
    html = build_dashboard(tmp_path).read_text(encoding="utf-8")
    # dropdowns for env/product/feed with distinct values plus 'all'
    for fid in ("f-env", "f-product", "f-feed"):
        assert f'id="{fid}"' in html
    assert '<option value="all">all</option>' in html
    assert '<option value="int">int</option>' in html
    assert '<option value="crt">crt</option>' in html
    assert '<option value="fd">fd</option>' in html and '<option value="soc">soc</option>' in html
    # from/to date inputs
    assert 'type="date"' in html and 'id="f-from"' in html and 'id="f-to"' in html
    # inline vanilla JS that hides rows and recomputes the stat tiles from visible rows
    assert "<script>" in html and "applyFilters" in html
    for tid in ("t-runs", "t-cases", "t-pass", "t-notpass", "t-pct"):
        assert f'id="{tid}"' in html


def test_download_anchors(tmp_path):
    _run(tmp_path, "2026-07-16", "int_bravo_fd_100000", [True], docs=["index.html"])
    html = build_dashboard(tmp_path).read_text(encoding="utf-8")
    assert 'download href="2026-07-16/int_bravo_fd_100000/index.html"' in html
    # only existing files get a download anchor (one doc file -> exactly one)
    assert html.count("download href=") == 1
