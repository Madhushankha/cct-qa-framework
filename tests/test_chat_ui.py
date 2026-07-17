"""Chat-UI rendering: widgets -> chips/banner/flight card, **bold**, OTP masking, no raw codes."""
import json

from evidence.render import _chat_html, _fmt_msg, _md
from quality.build import build_quality
from tests.test_evidence_render import result_pass


def test_md_bold():
    assert _md("say **hi** now") == "say <b>hi</b> now"
    assert _md("<script>") == "&lt;script&gt;"  # escaped first


def test_fmt_options_to_chips():
    out = _fmt_msg("Pick one §W§OPTIONS§English • Français")
    assert '<div class="bubble">Pick one</div>' in out
    assert out.count('class="chip"') == 2
    assert "English" in out and "Français" in out
    assert "§W§" not in out


def test_fmt_banner_and_flight():
    b = _fmt_msg("§W§BANNER§automated decision")
    assert 'class="banner"' in b and "§W§" not in b
    f = _fmt_msg("§W§FLIGHT§YYZ → LHR · AC8002")
    assert 'class="flightcard"' in f and "AC8002" in f


def test_fmt_bold_in_bubble():
    out = _fmt_msg("are you the **passenger**?")
    assert "<b>passenger</b>" in out and "**" not in out


def test_chat_html_alignment_and_mask():
    tx = [{"role": "assistant", "text": "Enter the code", "ts": "t1"},
          {"role": "customer", "text": "182415", "ts": "t2", "note": "otp"}]
    h = _chat_html(tx)
    assert 'class="turn bot"' in h and 'class="turn customer"' in h
    assert "\U0001f916 Ask AC" in h and "\U0001f464 Customer" in h
    assert "182415" not in h and "••••••" in h  # OTP masked
    assert "· otp" in h


def test_build_quality_writes_quality_index_not_index(tmp_path):
    # index.html belongs exclusively to the evidence Expected-vs-Actual report;
    # the quality index must be quality-index.html so the two never overwrite each other.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    doc = result_pass()
    tc = doc["case"]["test_case"]
    (run_dir / f"{tc}.result.json").write_text(json.dumps(doc), encoding="utf-8")
    out_dir = tmp_path / "out"

    build_quality(run_dir, out_dir)

    assert (out_dir / "quality-index.html").exists()
    assert not (out_dir / "index.html").exists()
    assert (out_dir / f"{tc}.quality.html").exists()
