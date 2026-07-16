"""Frozen dataclasses for Feed/Product/Env descriptors and the resolved RunContext."""
from __future__ import annotations

from dataclasses import dataclass

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

    def scenario_id(self, case_id: str) -> str:
        return f"{self.scenario_prefix}.{case_id}"
