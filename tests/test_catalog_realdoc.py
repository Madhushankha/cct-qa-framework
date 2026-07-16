"""Smoke test: the parser must handle a REAL gap doc, not just synthetic fixtures.
Skips gracefully if the (large) real doc isn't checked out."""
from pathlib import Path
import collections
import pytest

from core.registry import load_feed
from catalog.parser import parse_gap_doc

REAL = Path(__file__).resolve().parents[1] / "data" / "gap-docs" / "soc" / "SOC_Miro_Gap_Analysis.html"


@pytest.mark.skipif(not REAL.exists(), reason="real SOC gap doc not present")
def test_parses_real_soc_gap_doc():
    cat = parse_gap_doc(REAL, load_feed("soc"))
    assert len(cat.checkpoints) == 31
    assert len(cat.cases) == 81
    by_verdict = collections.Counter(c.verdict for c in cat.cases)
    assert by_verdict["Not Eligible"] == 43
    assert by_verdict["Eligible"] == 23

    uc = cat.by_id("SOC_UAT-001")
    assert uc is not None
    assert uc.regime == "APPR"
    assert uc.system_code == "SoC-APPR-NE-01"
    # exactly one required-but-missing Miro step for this case (SOC-01)
    missing = [cr.id for cr in uc.checkpoint_vector if cr.state == "missing"]
    assert missing == ["SOC-01"], f"expected SOC-01 missing, got {missing}"
    assert uc.content_hash  # a hash was computed
