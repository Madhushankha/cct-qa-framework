"""Result types for seed verification (P2)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CheckpointResult:
    area: str            # e.g. "eds_contact_email", "trip_active"
    ok: bool | None      # True=pass, False=fail, None=not verifiable in this env
    detail: str = ""     # human-readable evidence / reason


@dataclass(frozen=True)
class VerifyReport:
    case_id: str
    pnr: str
    checks: list[CheckpointResult] = field(default_factory=list)

    @property
    def verifiable(self) -> list[CheckpointResult]:
        return [c for c in self.checks if c.ok is not None]

    @property
    def all_ok(self) -> bool:
        """True only if every verifiable checkpoint passed (None = skipped, not a failure)."""
        v = self.verifiable
        return bool(v) and all(c.ok for c in v)

    @property
    def failed(self) -> list[CheckpointResult]:
        return [c for c in self.checks if c.ok is False]

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.ok is True)
        failed = sum(1 for c in self.checks if c.ok is False)
        skipped = sum(1 for c in self.checks if c.ok is None)
        return f"{self.case_id} ({self.pnr}): {passed} pass, {failed} fail, {skipped} skipped"
