"""Stage 1 schema tests. No BTC product data is read here beyond header rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
WORKBOOK = ROOT / "data" / "raw" / "Spec_cate_gia.xlsx"

EXPECTED_CATEGORIES = {
    "refrigerator", "air_conditioner", "washing_machine", "dryer", "dishwasher",
    "freezer", "water_heater", "karaoke_mic", "phone_mic", "smartwatch",
    "desktop_pc", "monitor", "printer", "tablet",
}
AIRCON_DEEP_FIELDS = {
    "product_year", "area_min_m2", "area_max_m2", "cooling_capacity_btu",
    "energy_stars", "cspf", "indoor_noise_min_db", "indoor_noise_max_db",
    "outdoor_noise_db", "inverter",
}


def load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_registry_covers_14_categories():
    reg = load("registry.json")
    cats = {info["category"] for info in reg["sheets"].values()}
    assert cats == EXPECTED_CATEGORIES
    assert len(reg["sheets"]) == 14


def test_every_schema_file_exists_and_parses():
    reg = load("registry.json")
    for info in reg["sheets"].values():
        schema = load(info["schema"])
        assert schema["properties"]["category"]["const"] == info["category"]


def test_base_schema_requires_core_fields():
    base = load("_base.schema.json")
    assert set(base["required"]) >= {"product_id", "category", "source", "data_quality"}
    assert base["properties"]["stock_status"]["enum"] == ["unknown"]


def test_aircon_has_deep_parsed_spec_fields():
    schema = load("air_conditioner.schema.json")
    props = set(schema["properties"]["spec"]["properties"])
    assert AIRCON_DEEP_FIELDS <= props
    assert "air_filter_features" in props  # from "Chuẩn chống nước, bụi"


def test_aircon_drops_known_bad_columns():
    reg = load("registry.json")
    ac = reg["sheets"]["Máy lạnh"]
    assert set(ac["drop_columns"]) == {"Số lượng", "Điện năng tiêu thụ"}
    mapped = {m["source_column"] for m in ac["mappings"]}
    assert "Số lượng" not in mapped and "Điện năng tiêu thụ" not in mapped


@pytest.mark.skipif(not WORKBOOK.exists(), reason="BTC workbook not present locally")
def test_full_validation_passes_against_real_headers():
    import scripts.validate_schemas as v
    assert v.main(["--input", str(WORKBOOK), "--schemas", str(SCHEMAS)]) == 0
