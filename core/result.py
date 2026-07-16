"""Canonical Result: load schema, validate, and write."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

RESULT_SCHEMA_VERSION = "1.0"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "result.schema.json"


class ResultError(Exception):
    pass


def load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_result(doc: dict) -> None:
    try:
        jsonschema.validate(instance=doc, schema=load_schema())
    except jsonschema.ValidationError as ex:
        path = "/".join(str(p) for p in ex.absolute_path) or "<root>"
        raise ResultError(f"Result invalid at '{path}': {ex.message}") from ex


def write_result(doc: dict, path: str | Path) -> None:
    validate_result(doc)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
