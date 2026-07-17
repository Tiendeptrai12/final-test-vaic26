"""Canonical BTC catalog loader (prepared for a later phase; OFF by default).

Loads the JSONL/JSON produced by scripts/build_btc_catalog.py and validates each
record against the Stage 1 schemas. Does NOT touch ProductAdvisor or the existing
mock_catalog in core.py. Enable in a later phase via env var CATALOG_SOURCE=btc.

Guarantees:
  - a record without a non-empty `product_id` is rejected (ValueError);
  - `stock_status` "unknown" is preserved verbatim - never treated as in-stock.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = BASE_DIR / "schemas"
PROCESSED_DIR = BASE_DIR / "data" / "processed"


def catalog_source() -> str:
    """'btc' or 'mock' (default). Nothing here flips the app automatically."""
    return os.environ.get("CATALOG_SOURCE", "mock").strip().lower()


def is_btc_enabled() -> bool:
    return catalog_source() == "btc"


@lru_cache(maxsize=None)
def _load_validator(category: str):
    """Return a jsonschema validator for a category, or None if unavailable.

    Cached: building the referencing Registry + parsing every schema file is
    expensive, and load paths validate one record at a time (~1039 aircon rows).
    Without the cache a full catalog load rebuilt the validator per record.
    """
    try:
        from jsonschema import Draft7Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT7
    except ImportError:
        return None
    store = []
    for f in SCHEMAS_DIR.glob("*.schema.json"):
        store.append((f.name, Resource.from_contents(
            json.loads(f.read_text(encoding="utf-8")), default_specification=DRAFT7)))
    schema_path = SCHEMAS_DIR / f"{category}.schema.json"
    if not schema_path.exists():
        return None
    reg = Registry().with_resources(store)
    return Draft7Validator(json.loads(schema_path.read_text(encoding="utf-8")), registry=reg)


def validate_record(record: dict[str, Any], validate_schema: bool = True) -> dict[str, Any]:
    """Reject bad records; keep unknown stock unknown. Returns the record."""
    pid = record.get("product_id")
    if not isinstance(pid, str) or not pid.strip():
        raise ValueError("record rejected: missing/empty product_id")
    if record.get("stock_status", "unknown") != "unknown":
        # loader never invents availability; anything else is a data error
        raise ValueError(f"record {pid}: unexpected stock_status "
                         f"{record.get('stock_status')!r} (expected 'unknown')")
    if validate_schema:
        validator = _load_validator(record.get("category", ""))
        if validator is not None:
            errs = sorted(validator.iter_errors(record), key=lambda e: e.path)
            if errs:
                raise ValueError(f"record {pid} failed schema: {errs[0].message}")
    return record


def load_jsonl(path: str | Path, validate_schema: bool = True) -> Iterator[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"catalog file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
            yield validate_record(record, validate_schema)


def load_category(category: str, validate_schema: bool = True) -> list[dict[str, Any]]:
    return list(load_jsonl(PROCESSED_DIR / f"btc_{category}.all.jsonl", validate_schema))
