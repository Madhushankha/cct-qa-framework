"""HTML -> Catalog. Tolerant regex/html.parser-style scraping — stdlib only, no BeautifulSoup.

Two entry points (see design doc §3):
- parse_gap_doc(html_path, feed) -> Catalog: reads the Miro gap-analysis HTML (spine + cards).
- join_dataset(catalog, dataset_html, feed) -> Catalog: fills seed_pending cases from a separate
  tabular dataset HTML, joining on test-case id (tolerant of '-'/'_' variants), falling back to
  systemCode.
- load_catalog(feed) -> Catalog: convenience = parse_gap_doc then, if feed.dataset, join_dataset.

The parser is feed-agnostic: all domain differences live in feed.columns.
"""
from __future__ import annotations

import dataclasses
import html as html_lib
import re
from pathlib import Path

from core.descriptors import Feed, SEEDSPEC_REQUIRED

from catalog.diff import content_hash
from catalog.model import Catalog, Checkpoint, CheckpointRef, SeedSpec, UseCase

_WS_RE = re.compile(r"\s+")


def _text(raw: str) -> str:
    return _WS_RE.sub(" ", html_lib.unescape(raw or "")).strip()


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_cp_id(raw: str) -> str:
    """Checkpoint id from a stage span: real docs wrap the marker as `<b>✓</b> SOC-01`.
    Strip inner tags, then drop the leading ✓/✕/· marker, leaving just the code (e.g. 'SOC-01',
    or 'GLOB-19 · ADD-112' with the interior separator preserved)."""
    t = _text(_TAG_RE.sub("", raw or ""))
    return re.sub(r"^[✓✕·\s]+", "", t).strip()


def _norm_col(name: str) -> str:
    return (name or "").strip().casefold()


def _norm_id(case_id: str) -> str:
    return (case_id or "").strip().upper().replace("-", "_")


_ID_COLUMN_NAMES = {"case", "test case", "tcid", "tc id"}

# --- spine -------------------------------------------------------------------

_SPINE_BLOCK_RE = re.compile(r'<details class="spine"[^>]*>(.*?)</details>', re.S)
_SPX_RE = re.compile(r'<div class="spx">(.*?)</div>', re.S)
_UNCOV_BLOCK_RE = re.compile(r'<div class="uncov">(.*?)</div>', re.S)
_SPID_RE = re.compile(r'<span class="spid">(.*?)</span>', re.S)
_SPL_RE = re.compile(r'<span class="spl">(.*?)</span>', re.S)
_SPM_RE = re.compile(r'<span class="spm[^"]*">(.*?)</span>', re.S)
_SPN_RE = re.compile(r'<span class="spn">(.*?)</span>', re.S)


def _first(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return m.group(1) if m else ""


def _parse_spine(html_text: str) -> tuple[list, list]:
    block_m = _SPINE_BLOCK_RE.search(html_text)
    if not block_m:
        return [], []
    block = block_m.group(1)

    checkpoints = []
    for spx in _SPX_RE.findall(block):
        spid = _text(_first(_SPID_RE, spx))
        if not spid:
            continue
        spl = _text(_first(_SPL_RE, spx))
        spm = _text(_first(_SPM_RE, spx))
        spn_raw = _text(_first(_SPN_RE, spx))
        try:
            assert_count = int(spn_raw)
        except ValueError:
            assert_count = 0
        checkpoints.append(Checkpoint(id=spid, label=spl, kind=spm, assert_count=assert_count))

    uncovered = []
    uncov_m = _UNCOV_BLOCK_RE.search(block)
    if uncov_m:
        uncovered = [_text(x) for x in _SPID_RE.findall(uncov_m.group(1))]

    return checkpoints, uncovered


# --- cards ---------------------------------------------------------------------

_CARD_RE = re.compile(r'<section class="card"([^>]*)>(.*?)</section>', re.S)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_SYSCODE_RE = re.compile(r'<span class="badge req">(.*?)</span>', re.S)
_TCNAME_RE = re.compile(r'<span class="tcname">(.*?)</span>', re.S)
_STAGEROW_RE = re.compile(r'<div class="stagerow">(.*?)</div>', re.S)
_STAGE_SPAN_RE = re.compile(r'<span class="stage (sc-cov|sc-miss|sc-na)"[^>]*>(.*?)</span>', re.S)
_INTBUB_RE = re.compile(r'<div class="intbub">(.*?)</div>', re.S)
_ROW_RE = re.compile(r'<div class="row (bot|user)">(.*?)</div>', re.S)
_DATAGRID_RE = re.compile(r'<div class="datagrid">(.*?)</div>', re.S)
_DGPAIR_RE = re.compile(r'<span class="dk">(.*?)</span>\s*<span class="dv">(.*?)</span>', re.S)

_STATE_BY_CLASS = {"sc-cov": "asserted", "sc-miss": "missing", "sc-na": "na"}


def _third_party_columns(feed: Feed) -> set:
    tp = feed.columns.get("third_party")
    if isinstance(tp, list):
        return {_norm_col(c) for c in tp}
    return set()


def _seedspec_column_map(feed: Feed) -> dict:
    """source-column-name (casefolded) -> SeedSpec field name, for the required fields only."""
    return {_norm_col(col): field for field, col in feed.columns.items()
            if field in SEEDSPEC_REQUIRED and isinstance(col, str)}


def _build_seed(pairs: dict, feed: Feed) -> tuple:
    """pairs: raw-column-name -> raw-value (already text-normalized). Returns (SeedSpec, third_party)."""
    col_to_field = _seedspec_column_map(feed)
    third_party_cols = _third_party_columns(feed)

    values: dict = {}
    extras: dict = {}
    third_party = False

    for raw_col, raw_val in pairs.items():
        key = _norm_col(raw_col)
        if key in _ID_COLUMN_NAMES:
            continue
        if key in third_party_cols:
            if raw_val.strip():
                third_party = True
            continue
        field_name = col_to_field.get(key)
        if field_name:
            values[field_name] = raw_val
        else:
            extras[raw_col] = raw_val

    amount_val = values.get("amount", "")
    currency_val = values.get("currency", "")
    amount = None
    if amount_val.strip():
        try:
            amount_num = float(amount_val)
        except ValueError:
            amount_num = amount_val
        amount = {"currency": currency_val, "value": amount_num}

    seed = SeedSpec(
        pnr=values.get("pnr", ""),
        pnr_id=values.get("pnr_id", ""),
        passenger=values.get("passenger", ""),
        route=values.get("route", ""),
        ticket=values.get("ticket", ""),
        status=values.get("status", ""),
        system_code=values.get("system_code", ""),
        amount=amount,
        currency=currency_val,
        flags=values.get("flags", ""),
        extras=extras,
    )
    return seed, third_party


def _parse_card(attrs_raw: str, body: str, feed: Feed) -> UseCase:
    attrs = dict(_ATTR_RE.findall(attrs_raw))
    case_id = attrs.get("id", "")
    regime = attrs.get("data-feat", "")
    verdict = attrs.get("data-out", "")

    system_code = _text(_first(_SYSCODE_RE, body))
    title = _text(_first(_TCNAME_RE, body))

    checkpoint_vector = []
    stagerow_m = _STAGEROW_RE.search(body)
    if stagerow_m:
        for cls, cp_id in _STAGE_SPAN_RE.findall(stagerow_m.group(1)):
            checkpoint_vector.append(CheckpointRef(id=_clean_cp_id(cp_id), state=_STATE_BY_CLASS[cls]))

    customer_intent = _text(_first(_INTBUB_RE, body))

    expected_transcript = [
        {"role": role, "text": _text(text)} for role, text in _ROW_RE.findall(body)
    ]

    dg_m = _DATAGRID_RE.search(body)
    if dg_m:
        pairs = {_text(k): _text(v) for k, v in _DGPAIR_RE.findall(dg_m.group(1))}
        seed, third_party = _build_seed(pairs, feed)
        seed_pending = False
    else:
        seed = SeedSpec()
        third_party = False
        seed_pending = True

    return UseCase(
        id=case_id, regime=regime, verdict=verdict, system_code=system_code, title=title,
        third_party=third_party, checkpoint_vector=checkpoint_vector,
        customer_intent=customer_intent, expected_transcript=expected_transcript,
        seed=seed, seed_pending=seed_pending, content_hash="",
    )


def _finalize(catalog: Catalog) -> Catalog:
    """Recompute content_hash for every case (safe to call repeatedly / after a join)."""
    cases = [dataclasses.replace(c, content_hash=content_hash(c)) for c in catalog.cases]
    return dataclasses.replace(catalog, cases=cases)


def parse_gap_doc(html_path: str, feed: Feed) -> Catalog:
    text = Path(html_path).read_text(encoding="utf-8")
    checkpoints, uncovered = _parse_spine(text)
    cases = [_parse_card(attrs, body, feed) for attrs, body in _CARD_RE.findall(text)]
    catalog = Catalog(feed_id=feed.id, checkpoints=checkpoints, cases=cases, uncovered=uncovered)
    return _finalize(catalog)


# --- dataset table ---------------------------------------------------------------

_TABLE_RE = re.compile(r'<table[^>]*>(.*?)</table>', re.S)
_TR_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_TH_RE = re.compile(r'<th[^>]*>(.*?)</th>', re.S)
_TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S)


def _parse_table_rows(html_text: str) -> tuple[list, list]:
    table_m = _TABLE_RE.search(html_text)
    if not table_m:
        return [], []
    body = table_m.group(1)
    header: list = []
    data_rows: list = []
    for row in _TR_RE.findall(body):
        ths = _TH_RE.findall(row)
        if ths:
            header = [_text(h) for h in ths]
            continue
        tds = _TD_RE.findall(row)
        if tds:
            data_rows.append([_text(t) for t in tds])
    return header, data_rows


def join_dataset(catalog: Catalog, dataset_html: str, feed: Feed) -> Catalog:
    text = Path(dataset_html).read_text(encoding="utf-8")
    header, rows = _parse_table_rows(text)

    id_idx = None
    for i, h in enumerate(header):
        if _norm_col(h) in _ID_COLUMN_NAMES:
            id_idx = i
            break

    syscode_col = feed.columns.get("system_code", "")
    by_norm_id: dict = {}
    by_syscode: dict = {}
    for row in rows:
        pairs = dict(zip(header, row))
        if id_idx is not None and id_idx < len(row):
            by_norm_id[_norm_id(row[id_idx])] = pairs
        for col_name, val in pairs.items():
            if _norm_col(col_name) == _norm_col(syscode_col) and val:
                by_syscode[val] = pairs

    new_cases = []
    for uc in catalog.cases:
        pairs = by_norm_id.get(_norm_id(uc.id))
        if pairs is None:
            pairs = by_syscode.get(uc.system_code) if uc.system_code else None
        if pairs is None:
            new_cases.append(uc)  # no dataset row: keep as-is (incl. seed_pending)
            continue
        seed, third_party = _build_seed(pairs, feed)
        new_cases.append(dataclasses.replace(uc, seed=seed, third_party=third_party,
                                             seed_pending=False))

    joined = dataclasses.replace(catalog, cases=new_cases)
    return _finalize(joined)


def load_catalog(feed: Feed) -> Catalog:
    catalog = parse_gap_doc(feed.gap_doc, feed)
    if feed.dataset:
        catalog = join_dataset(catalog, feed.dataset, feed)
    return catalog
