"""Validate the generated schemas + registry against the real workbook headers.

Checks (fails loudly, naming sheet + column):
  1. every JSON schema file parses and is a valid draft-07 schema;
  2. registry covers exactly the 14 workbook sheets;
  3. every registry `source_column` (mappings + deep_fields) exists in that
     sheet's real header row;
  4. no dropped column is also mapped;
  5. base + per-category schemas load and compose (allOf $ref resolves).

Read-only: only the header row of each sheet is read. No product data touched.

Usage:
    python scripts/validate_schemas.py --input data/raw/Spec_cate_gia.xlsx --schemas schemas
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openpyxl
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7


def read_header(ws) -> set[str]:
    row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    return {str(c).strip() for c in row if c is not None and str(c).strip()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw/Spec_cate_gia.xlsx", type=Path)
    ap.add_argument("--schemas", default="schemas", type=Path)
    args = ap.parse_args(argv)

    errors: list[str] = []
    schemas_dir: Path = args.schemas

    registry = json.loads((schemas_dir / "registry.json").read_text(encoding="utf-8"))
    store: dict[str, dict] = {}
    for f in schemas_dir.glob("*.schema.json"):
        schema = json.loads(f.read_text(encoding="utf-8"))
        store[f.name] = schema
        try:
            Draft7Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - surface, do not swallow
            errors.append(f"schema '{f.name}' invalid: {exc}")

    # every per-category schema composes with the base ($ref "_base.schema.json")
    base_name = registry["base_schema"]
    ref_registry = Registry().with_resources(
        [(name, Resource.from_contents(s, default_specification=DRAFT7))
         for name, s in store.items()])
    for name, schema in store.items():
        if name == base_name:
            continue
        try:
            Draft7Validator(schema, registry=ref_registry)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schema '{name}' does not compose with base: {exc}")

    wb = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    sheet_headers = {ws.title: read_header(ws) for ws in wb.worksheets}

    reg_sheets = set(registry["sheets"])
    wb_sheets = set(sheet_headers)
    if reg_sheets != wb_sheets:
        errors.append(f"registry sheets != workbook sheets: "
                      f"missing={wb_sheets - reg_sheets} extra={reg_sheets - wb_sheets}")

    for sheet, info in registry["sheets"].items():
        header = sheet_headers.get(sheet, set())
        drop = set(info.get("drop_columns", []))
        cols = [m["source_column"] for m in info["mappings"]]
        cols += [d["source_column"] for d in info.get("deep_fields", [])]
        for col in cols:
            if col not in header:
                errors.append(f"[{sheet}] mapped column not in sheet header: '{col}'")
            if col in drop:
                errors.append(f"[{sheet}] column both dropped and mapped: '{col}'")
        schema_file = info["schema"]
        if schema_file not in store:
            errors.append(f"[{sheet}] schema file missing: '{schema_file}'")

    if errors:
        print("SCHEMA VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1

    print(f"OK: {len(registry['sheets'])} sheets, {len(store)} schema files, "
          f"all mapped columns exist in real headers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
