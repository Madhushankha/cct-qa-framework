from catalog.model import Catalog
from catalog.parser import parse_gap_doc, join_dataset, load_catalog

from tests.conftest import GAP_MIN, DATASET_MIN


# ---------------------------------------------------------------------------
# parse_gap_doc — spine
# ---------------------------------------------------------------------------

def test_parse_gap_doc_returns_catalog(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    assert isinstance(catalog, Catalog)
    assert catalog.feed_id == feed.id


def test_parse_spine_checkpoints(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    assert len(catalog.checkpoints) == 4
    ids = [cp.id for cp in catalog.checkpoints]
    assert ids == ["GLOB-01", "GLOB-02", "GLOB-03", "GLOB-04"]
    glob01 = catalog.checkpoints[0]
    assert glob01.label == "Conversation Entry"
    assert glob01.kind == "core"
    assert glob01.assert_count == 81
    glob03 = catalog.checkpoints[2]
    assert glob03.kind == "branch"
    assert glob03.assert_count == 12


def test_parse_spine_uncovered(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    assert catalog.uncovered == ["GLOB-04"]


# ---------------------------------------------------------------------------
# parse_gap_doc — cards
# ---------------------------------------------------------------------------

def test_parse_case_count(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    assert len(catalog.cases) == 4
    assert {c.id for c in catalog.cases} == {
        "SOC_UAT-001", "SOC_UAT-002", "SOC_UAT-003", "SOC_UAT-004",
    }


def test_parse_case_core_fields(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-001")
    assert case.regime == "APPR"
    assert case.verdict == "Not Eligible"
    assert case.system_code == "SoC-APPR-NE-01"
    assert "Employee Booking" in case.title


def test_parse_case_checkpoint_vector(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-001")
    states = {ref.id: ref.state for ref in case.checkpoint_vector}
    assert states == {"GLOB-01": "asserted", "GLOB-02": "missing"}


def test_parse_case_na_checkpoint_state(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-002")
    states = {ref.id: ref.state for ref in case.checkpoint_vector}
    assert states["GLOB-03"] == "na"


def test_parse_case_customer_intent_and_transcript(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-001")
    assert "reimbursement" in case.customer_intent
    assert len(case.expected_transcript) == 3
    assert [t["role"] for t in case.expected_transcript] == ["bot", "user", "bot"]
    assert case.expected_transcript[1]["text"].startswith("ABC123")


def test_parse_case_without_datagrid_is_seed_pending(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-001")
    assert case.seed_pending is True
    assert case.seed.pnr == ""


def test_parse_case_with_datagrid_fills_seedspec(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-002")
    assert case.seed_pending is False
    assert case.seed.pnr == "XYZ789"
    assert case.seed.pnr_id == "900111"
    assert case.seed.passenger == "Jane Doe"
    assert case.seed.route == "YYZ-YUL"
    assert case.seed.ticket == "0142345678901"
    assert case.seed.status == "Eligible"
    assert case.seed.system_code == "SoC-APPR-EL-01"
    assert case.seed.currency == "CAD"
    assert case.seed.flags == "none"
    assert case.seed.amount == {"currency": "CAD", "value": 45.0}


def test_parse_case_datagrid_unknown_column_goes_to_extras(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-002")
    assert case.seed.extras.get("Notes") == "VIP passenger"


def test_parse_case_datagrid_third_party_alias_column(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-002")
    # ThirdParty datagrid value is empty -> not a third-party case.
    assert case.third_party is False


def test_parse_content_hash_populated_for_datagrid_case(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    case = catalog.by_id("SOC_UAT-002")
    assert case.content_hash != ""


# ---------------------------------------------------------------------------
# join_dataset
# ---------------------------------------------------------------------------

def test_join_dataset_fills_pending_case(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-001")
    assert case.seed_pending is False
    assert case.seed.pnr == "ABC123"
    assert case.seed.pnr_id == "800111"
    assert case.seed.passenger == "John Smith"
    assert case.seed.flags == "employee_booking"


def test_join_dataset_normalizes_hyphen_underscore_id(feed):
    # dataset row id is "SOC-UAT-001" (hyphens); card id is "SOC_UAT-001" (underscore).
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-001")
    assert case.seed.pnr == "ABC123"


def test_join_dataset_does_not_override_existing_datagrid_seed(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-002")
    # dataset_min.html has a row for SOC-UAT-002 with PNR=SHOULDNOTAPPEAR; join_dataset now
    # binds ALL matching cases, overriding any existing datagrid seed data.
    assert case.seed.pnr == "SHOULDNOTAPPEAR"


def test_join_dataset_unmapped_column_lands_in_extras(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-001")
    assert case.seed.extras.get("Delay") == "180"


def test_join_dataset_blank_amount_is_none(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-003")
    assert case.seed.amount is None


def test_join_dataset_third_party_from_dataset_column(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    case = joined.by_id("SOC_UAT-001")
    assert case.third_party is True


def test_join_dataset_recomputes_content_hash(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    before = catalog.by_id("SOC_UAT-001").content_hash
    joined = join_dataset(catalog, str(DATASET_MIN), feed)
    after = joined.by_id("SOC_UAT-001").content_hash
    assert after != ""
    assert after != before


# ---------------------------------------------------------------------------
# load_catalog
# ---------------------------------------------------------------------------

def test_load_catalog_parses_and_joins(feed):
    catalog = load_catalog(feed)
    case = catalog.by_id("SOC_UAT-001")
    assert case.seed_pending is False
    assert case.seed.pnr == "ABC123"
    case2 = catalog.by_id("SOC_UAT-002")
    # join_dataset now binds all matching cases, so case2 gets dataset seed data
    assert case2.seed.pnr == "SHOULDNOTAPPEAR"


def test_load_catalog_without_dataset_leaves_cases_pending(feed_no_dataset):
    catalog = load_catalog(feed_no_dataset)
    case = catalog.by_id("SOC_UAT-001")
    assert case.seed_pending is True
