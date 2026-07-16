"""content_hash() over a normalized UseCase projection, and diff(old, new) -> ChangeSet."""
from __future__ import annotations

import hashlib
import re

from catalog.model import Catalog, ChangeSet, UseCase

_WS_RE = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _normalized_transcript(transcript: list) -> tuple:
    return tuple((entry.get("role", ""), _norm_text(entry.get("text", ""))) for entry in transcript)


def _seed_tuple(seed) -> tuple:
    amount = seed.amount
    amount_tuple = None if amount is None else (amount.get("currency"), amount.get("value"))
    return (
        seed.pnr, seed.pnr_id, seed.passenger, seed.route, seed.ticket,
        seed.status, seed.system_code, amount_tuple, seed.currency, seed.flags,
        tuple(sorted(seed.extras.items())),
    )


def _checkpoint_vector_tuple(checkpoint_vector: list) -> tuple:
    return tuple(sorted((ref.id, ref.state) for ref in checkpoint_vector))


def content_hash(uc: UseCase) -> str:
    """SHA-256 over a normalized projection of the case: seed fields, sorted checkpoint vector,
    verdict, system_code, and whitespace-normalized expected transcript text.

    Deliberately excludes ``title`` and ``third_party`` (cosmetic / not part of the case's
    behavioral contract) and normalizes whitespace so cosmetic HTML edits don't change the hash.
    """
    payload = repr((
        _seed_tuple(uc.seed),
        _checkpoint_vector_tuple(uc.checkpoint_vector),
        uc.verdict,
        uc.system_code,
        _normalized_transcript(uc.expected_transcript),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_tuple(uc: UseCase) -> tuple:
    return (uc.verdict, uc.system_code, _normalized_transcript(uc.expected_transcript))


def diff(old: Catalog, new: Catalog) -> ChangeSet:
    old_by_id = {c.id: c for c in old.cases}
    new_by_id = {c.id: c for c in new.cases}
    old_ids = set(old_by_id)
    new_ids = set(new_by_id)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    common = old_ids & new_ids

    data_changed: list[str] = []
    checkpoint_changed: list[str] = []
    expected_changed: list[str] = []
    unchanged: list[str] = []

    for case_id in sorted(common):
        old_uc = old_by_id[case_id]
        new_uc = new_by_id[case_id]
        if old_uc.content_hash and new_uc.content_hash and old_uc.content_hash == new_uc.content_hash:
            unchanged.append(case_id)
            continue
        if content_hash(old_uc) == content_hash(new_uc):
            unchanged.append(case_id)
            continue

        seed_differs = _seed_tuple(old_uc.seed) != _seed_tuple(new_uc.seed)
        checkpoint_differs = (_checkpoint_vector_tuple(old_uc.checkpoint_vector)
                              != _checkpoint_vector_tuple(new_uc.checkpoint_vector))
        expected_differs = _expected_tuple(old_uc) != _expected_tuple(new_uc)

        # Priority: DATA_CHANGED > EXPECTED_CHANGED > CHECKPOINT_CHANGED — report the single
        # highest-impact label even when more than one sub-part differs.
        if seed_differs:
            data_changed.append(case_id)
        elif expected_differs:
            expected_changed.append(case_id)
        elif checkpoint_differs:
            checkpoint_changed.append(case_id)
        else:
            # Hash differed but none of our tracked sub-parts did (shouldn't normally happen
            # since the hash is derived solely from them) — treat conservatively as unchanged.
            unchanged.append(case_id)

    # Spine-level change: a checkpoint added/removed at the domain level flags every case
    # (in both catalogs) whose checkpoint_vector references it, in addition to any bucket
    # already assigned above.
    old_cp_ids = {cp.id for cp in old.checkpoints}
    new_cp_ids = {cp.id for cp in new.checkpoints}
    spine_changed_ids = old_cp_ids ^ new_cp_ids
    if spine_changed_ids:
        already_flagged = set(checkpoint_changed)
        for case_id in sorted(common):
            new_uc = new_by_id[case_id]
            referenced = {ref.id for ref in new_uc.checkpoint_vector}
            if referenced & spine_changed_ids and case_id not in already_flagged:
                checkpoint_changed.append(case_id)
                already_flagged.add(case_id)
                if case_id in unchanged:
                    unchanged.remove(case_id)

    return ChangeSet(
        added=added, removed=removed, data_changed=data_changed,
        checkpoint_changed=checkpoint_changed, expected_changed=expected_changed,
        unchanged=unchanged,
    )
