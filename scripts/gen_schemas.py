"""Generate canonical JSON schemas + registry for every sheet of the BTC workbook.

Stage 1 of the schema-first pipeline. Reads ONLY the header row of each sheet
(openpyxl read_only) and emits, deterministically:

    schemas/_base.schema.json          shared base record
    schemas/registry.json              sheet -> {category, mappings, ...}
    schemas/<category>.schema.json     one per sheet (14)

No product data is read or written here. Re-running with the same workbook
produces byte-identical output (sorted keys, stable ordering).

Usage:
    python scripts/gen_schemas.py --input data/raw/Spec_cate_gia.xlsx --outdir schemas
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import openpyxl

# --- sheet name -> category slug ------------------------------------------------
SHEET_TO_CATEGORY: dict[str, str] = {
    "Tủ Lạnh": "refrigerator",
    "Máy lạnh": "air_conditioner",
    "Máy giặt": "washing_machine",
    "Máy sấy quần áo": "dryer",
    "Máy rửa chén": "dishwasher",
    "Tủ mát, tủ đông": "freezer",
    "Máy nước nóng": "water_heater",
    "Micro karaoke": "karaoke_mic",
    "Micro thu âm điện thoại": "phone_mic",
    "Đồng hồ thông minh": "smartwatch",
    "Máy tính để bàn": "desktop_pc",
    "Màn hình máy tính": "monitor",
    "Máy in": "printer",
    "Máy tính bảng": "tablet",
}

# Columns handled by the shared base record (not repeated in per-category spec).
SPINE_COLUMNS = {
    "model_code", "sku", "productidweb", "category_code", "brand_id", "brand",
    "giá gốc", "giá khuyến mãi", "khuyến mãi quà",
}

# Header -> canonical key override (nice English keys where it matters).
KEY_OVERRIDE: dict[str, str] = {
    "Dòng sản phẩm": "product_year",
    "Phạm vi sử dụng": "usage_area",
    "Công suất đầu ra": "output_capacity",
    "Nhãn năng lượng": "energy_label",
    "Độ ồn": "noise",
    "Loại Inverter": "inverter_type",
    "Chuẩn chống nước, bụi": "air_filter_features",
    "Loại máy": "machine_type",
    "Công nghệ làm lạnh": "cooling_technology",
    "Công nghệ tiết kiệm điện": "energy_saving_technology",
    "Tiện ích": "features",
    "Chế độ gió": "wind_modes",
    "Bảo hành bộ phận": "warranty",
    "Bảo hành động cơ": "compressor_warranty",
    "Loại Gas": "gas_type",
}

# Headers whose cells are "|"-separated multi-value lists.
LIST_COLUMNS = {
    "Tiện ích", "Tiện ích khác", "Tính năng khác", "Tính năng đặc biệt",
    "Tính năng an toàn", "Tính năng cơ bản", "Công nghệ", "Công nghệ làm lạnh",
    "Công nghệ tiết kiệm điện", "Công nghệ bảo quản thực phẩm", "Công nghệ sấy",
    "Công nghệ âm thanh", "Kết nối", "Kết nối Internet", "Cổng kết nối",
    "Cổng giao tiếp", "Cổng I/O mặt sau", "Phụ kiện đi kèm", "Chế độ gió",
    "Chế độ tự động", "Cảm biến", "Môn thể thao", "Theo dõi sức khoẻ",
    "Hiển thị thông báo", "Chương trình", "Ứng dụng", "Tương thích",
    "Băng tần", "Ngôn ngữ", "Định vị", "Quay phim",
    "Tính năng camera sau", "Tính năng camera trước", "Chất liệu ruột",
    "khuyến mãi quà",  # promotions -> promotions[] in base
}

# Per-sheet dropped columns (known-bad data).
DROP_COLUMNS: dict[str, set[str]] = {
    "Máy lạnh": {"Số lượng", "Điện năng tiêu thụ"},
}

# Aircon deep-parse: source column -> canonical spec fields it produces + types.
AIRCON_DEEP: dict[str, list[tuple[str, str]]] = {
    "Dòng sản phẩm": [("product_year", "integer")],
    "Phạm vi sử dụng": [("area_min_m2", "number"), ("area_max_m2", "number")],
    "Công suất đầu ra": [("cooling_capacity_btu", "integer")],
    "Nhãn năng lượng": [("energy_stars", "integer"), ("cspf", "number")],
    "Độ ồn": [("indoor_noise_min_db", "number"), ("indoor_noise_max_db", "number"),
              ("outdoor_noise_db", "number")],
    "Loại Inverter": [("inverter", "boolean")],
}

JSON_TYPE = {"string": "string", "integer": "integer", "number": "number",
             "boolean": "boolean", "list": "array"}


def slugify(text: str) -> str:
    """Vietnamese header -> deterministic ascii snake_case key."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def canonical_key(header: str) -> str:
    return KEY_OVERRIDE.get(header, slugify(header))


def raw_type(header: str) -> str:
    return "list" if header in LIST_COLUMNS else "string"


def read_header(ws) -> list[str]:
    row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    return [str(c).strip() if c is not None else "" for c in row]


def spec_property(t: str) -> dict[str, Any]:
    if t == "list":
        return {"type": "array", "items": {"type": "string"}}
    if t in ("integer", "number", "boolean"):
        return {"type": [t, "null"]}
    return {"type": ["string", "null"]}


def build(input_path: Path, outdir: Path) -> None:
    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # --- base schema ---
    base = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "btc:_base",
        "title": "BTC canonical product (base)",
        "type": "object",
        "required": ["product_id", "category", "source", "data_quality"],
        "properties": {
            "product_id": {"type": "string", "minLength": 1},
            "product_web_id": {"type": ["string", "null"]},
            "model_code": {"type": ["string", "null"]},
            "category": {"type": "string",
                         "enum": sorted(set(SHEET_TO_CATEGORY.values()))},
            "brand": {"type": ["string", "null"]},
            "brand_id": {"type": ["string", "null"]},
            "category_code": {"type": ["string", "null"]},
            "original_price": {"type": ["integer", "null"]},
            "promotion_price": {"type": ["integer", "null"]},
            "effective_price": {"type": ["integer", "null"]},
            "promotions": {"type": "array", "items": {"type": "string"}},
            "stock_status": {"type": "string", "enum": ["unknown"]},
            "stock_by_location": {"type": "object"},
            "spec": {"type": "object"},
            "raw": {"type": "object"},
            "source": {
                "type": "object",
                "required": ["type", "sheet", "source_row", "sku"],
                "properties": {
                    "type": {"const": "btc_excel"},
                    "sheet": {"type": "string"},
                    "source_row": {"type": "integer"},
                    "sku": {"type": "string"},
                },
            },
            "data_quality": {
                "type": "object",
                "required": ["eligible_for_demo", "missing_fields", "warnings"],
                "properties": {
                    "eligible_for_demo": {"type": "boolean"},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }
    (outdir / "_base.schema.json").write_text(
        json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    registry: dict[str, Any] = {"version": 1, "base_schema": "_base.schema.json",
                                "sheets": {}}

    for ws in wb.worksheets:
        sheet = ws.title
        if sheet not in SHEET_TO_CATEGORY:
            raise ValueError(f"Sheet '{sheet}' not in SHEET_TO_CATEGORY map")
        category = SHEET_TO_CATEGORY[sheet]
        deep = sheet == "Máy lạnh"
        drop = DROP_COLUMNS.get(sheet, set())
        header = read_header(ws)

        mappings: list[dict[str, Any]] = []
        spec_props: dict[str, Any] = {}
        seen_keys: set[str] = set()
        for col in header:
            if not col or col in SPINE_COLUMNS or col in drop:
                continue
            key = canonical_key(col)
            if key in seen_keys:  # dedupe collisions deterministically
                key = f"{key}_{slugify(col)}"[:60]
            seen_keys.add(key)
            t = raw_type(col)
            mappings.append({"source_column": col, "key": key, "type": t})
            spec_props[key] = spec_property(t)

        # aircon deep-parse spec fields (parsed, typed)
        deep_fields: list[dict[str, Any]] = []
        if deep:
            for src, fields in AIRCON_DEEP.items():
                for fkey, ftype in fields:
                    spec_props[fkey] = spec_property(ftype)
                    deep_fields.append({"source_column": src, "key": fkey, "type": ftype})

        schema_file = f"{category}.schema.json"
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": f"btc:{category}",
            "title": f"BTC canonical product - {category}",
            "allOf": [{"$ref": "_base.schema.json"}],
            "properties": {
                "category": {"const": category},
                "spec": {"type": "object", "properties": dict(sorted(spec_props.items()))},
            },
        }
        (outdir / schema_file).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

        registry["sheets"][sheet] = {
            "category": category,
            "schema": schema_file,
            "deep_parse": deep,
            "drop_columns": sorted(drop),
            "list_columns": sorted(c for c in header if c in LIST_COLUMNS
                                   and c not in SPINE_COLUMNS and c not in drop),
            "mappings": mappings,
            "deep_fields": deep_fields,
        }

    (outdir / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"generated base + {len(registry['sheets'])} category schemas + registry "
          f"into {outdir}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw/Spec_cate_gia.xlsx", type=Path)
    ap.add_argument("--outdir", default="schemas", type=Path)
    args = ap.parse_args(argv)
    if not args.input.exists():
        print(f"ERROR: input workbook not found: {args.input}", file=sys.stderr)
        return 2
    build(args.input, args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
