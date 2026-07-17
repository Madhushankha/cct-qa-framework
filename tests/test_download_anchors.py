"""Per-case pages carry a self-referencing download anchor so a tester can
save/share the report straight from the browser (relative self-link + the
``download`` attribute = save-as, no JS, page stays self-contained).
"""
from __future__ import annotations

import re

from evidence.render import render_case
from quality.render import render_quality
from tests.test_evidence_render import result_pass

# any <a ...> tag carrying a download attribute
_DL_ANCHOR_RE = re.compile(r"<a\b[^>]*\bdownload\b[^>]*>", re.I)


def _download_anchors(html_out: str) -> list[str]:
    return _DL_ANCHOR_RE.findall(html_out)


def _quality_report():
    return {
        "scenario_id": "bravo.crt.fd.FD_TC_001",
        "test_case": "FD_TC_001",
        "deterministic": [],
        "llm": None,
        "score": 92,
        "summary": "clean run",
    }


def test_evidence_case_page_has_exactly_one_download_anchor():
    html_out = render_case(result_pass())
    anchors = _download_anchors(html_out)
    assert len(anchors) == 1


def test_evidence_download_anchor_points_at_own_filename():
    html_out = render_case(result_pass())
    (anchor,) = _download_anchors(html_out)
    assert 'href="FD_TC_001.evidence.html"' in anchor


def test_quality_case_page_has_exactly_one_download_anchor():
    html_out = render_quality(_quality_report())
    anchors = _download_anchors(html_out)
    assert len(anchors) == 1


def test_quality_download_anchor_points_at_own_filename():
    """Filename must match how quality/build.py names the file:
    ``<test_case>.quality.html``."""
    html_out = render_quality(_quality_report())
    (anchor,) = _download_anchors(html_out)
    assert 'href="FD_TC_001.quality.html"' in anchor
