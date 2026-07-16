"""Frozen dataclasses for the P1 catalog model: Checkpoint, SeedSpec, CheckpointRef, UseCase,
Catalog, ChangeSet. Pure data — no parsing/hashing logic lives here (see parser.py / diff.py)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Checkpoint:
    """One spine step (a Miro checkpoint), e.g. GLOB-01 / GenUC-05."""
    id: str
    label: str
    kind: str  # "core" | "branch"
    assert_count: int


@dataclass(frozen=True)
class SeedSpec:
    """The bound data for a case: the SEEDSPEC_REQUIRED fields plus domain-specific extras."""
    pnr: str = ""
    pnr_id: str = ""
    passenger: str = ""
    route: str = ""
    ticket: str = ""
    status: str = ""
    system_code: str = ""
    amount: dict | None = None  # {"currency": str, "value": float|str} | None
    currency: str = ""
    flags: str = ""
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckpointRef:
    """Per-case checkpoint state: a projection of the spine onto one use-case."""
    id: str
    state: str  # "asserted" | "missing" | "na"


@dataclass(frozen=True)
class UseCase:
    id: str
    regime: str
    verdict: str
    system_code: str
    title: str
    third_party: bool
    checkpoint_vector: list  # list[CheckpointRef]
    customer_intent: str
    expected_transcript: list  # list[dict] {"role": "bot"|"user", "text": str}
    seed: SeedSpec
    seed_pending: bool
    content_hash: str = ""


@dataclass(frozen=True)
class Catalog:
    feed_id: str
    checkpoints: list  # list[Checkpoint] — the spine
    cases: list  # list[UseCase]
    uncovered: list  # list[str] — spine ids with zero coverage

    def by_id(self, case_id: str) -> UseCase | None:
        for case in self.cases:
            if case.id == case_id:
                return case
        return None


_BUCKET_LABELS = (
    ("added", "added"),
    ("removed", "removed"),
    ("data_changed", "data-changed"),
    ("checkpoint_changed", "checkpoint-changed"),
    ("expected_changed", "expected-changed"),
    ("unchanged", "unchanged"),
)


@dataclass(frozen=True)
class ChangeSet:
    """The diff between two Catalog versions: per-bucket lists of case ids."""
    added: list
    removed: list
    data_changed: list
    checkpoint_changed: list
    expected_changed: list
    unchanged: list

    def summary(self) -> str:
        parts = []
        for attr, label in _BUCKET_LABELS:
            n = len(getattr(self, attr))
            if n:
                parts.append(f"{n} {label}")
        return ", ".join(parts) if parts else "no changes"

    def to_seed(self) -> list:
        """Cases that need (re-)seeding: added ∪ data_changed, order-preserving, deduped."""
        seen = set()
        out = []
        for case_id in [*self.added, *self.data_changed]:
            if case_id not in seen:
                seen.add(case_id)
                out.append(case_id)
        return out

    def to_run(self) -> list:
        """Cases that need (re-)running: added ∪ data_changed ∪ expected_changed."""
        seen = set()
        out = []
        for case_id in [*self.added, *self.data_changed, *self.expected_changed]:
            if case_id not in seen:
                seen.add(case_id)
                out.append(case_id)
        return out
