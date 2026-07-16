"""P1 — catalog: gap-doc HTML -> normalized Catalog of use-cases, + diff into a ChangeSet.

Consumes P0's Feed descriptor; does not touch AWS/the chatbot; pure and offline.
"""
from __future__ import annotations

from catalog.model import Catalog, CheckpointRef, Checkpoint, ChangeSet, SeedSpec, UseCase
from catalog.parser import join_dataset, load_catalog, parse_gap_doc
from catalog.diff import content_hash, diff

__all__ = [
    "Catalog", "CheckpointRef", "Checkpoint", "ChangeSet", "SeedSpec", "UseCase",
    "join_dataset", "load_catalog", "parse_gap_doc",
    "content_hash", "diff",
]
