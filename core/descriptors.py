"""Frozen dataclasses for Feed/Product/Env descriptors and the resolved RunContext."""
from __future__ import annotations

from dataclasses import dataclass, field

# P0 pins the SeedSpec field names; P1 (catalog) fills their values from the gap doc.
SEEDSPEC_REQUIRED: tuple[str, ...] = (
    "pnr", "pnr_id", "passenger", "route", "ticket",
    "status", "system_code", "amount", "currency", "flags",
)


@dataclass(frozen=True)
class Feed:
    id: str
    label: str
    gap_doc: str
    columns: dict
    persona: dict
    judge: dict
    checkpoints: dict
    dataset: str = ""  # optional tabular PNR-data HTML joined to gap-doc cases (P1); "" = data embedded in gap doc


@dataclass(frozen=True)
class Product:
    id: str
    label: str
    transcript_dialect: str
    overrides: dict
    defaults: dict


@dataclass(frozen=True)
class Env:
    id: str
    label: str
    chatbot: dict
    aws: dict
    otp: dict
    seed_targets: dict


@dataclass(frozen=True)
class RunContext:
    product: Product
    env: Env
    feed: Feed
    scenario_prefix: str
    # feed persona/judge with the product's overrides layered on top (see registry.resolve)
    persona: dict = field(default_factory=dict)
    judge: dict = field(default_factory=dict)

    def scenario_id(self, case_id: str) -> str:
        return f"{self.scenario_prefix}.{case_id}"

    def secret(self, name: str) -> str:
        """Resolve a named secret via the env's resolver (env-var based in P0). Called lazily so
        resolution stays offline until a secret is actually needed."""
        from core.secrets import resolve_secret
        return resolve_secret(name)
