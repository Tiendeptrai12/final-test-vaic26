"""Stage 2 tests. Pure-function parsers + loader on synthetic data. No real BTC data."""
from __future__ import annotations

import json

import pytest

from scripts.build_btc_catalog import (
    build_record, clean_str, parse_area, parse_btu, parse_energy, parse_inverter,
    parse_noise, parse_price, parse_year, split_list,
)
from antigravity import btc_catalog


# --- scalar normalizers -----------------------------------------------------
def test_parse_price_variants():
    assert parse_price("29.490.000") == 29490000
    assert parse_price("29,490,000đ") == 29490000
    assert parse_price("0") is None
    assert parse_price("-5") == 5 or parse_price("-5") is None  # digits-only -> 5
    assert parse_price("") is None
    assert parse_price("Đang cập nhật") is None


def test_missing_tokens_to_none():
    for tok in ["", "-", "null", "Đang cập nhật", "Hãng không công bố"]:
        assert clean_str(tok) is None
    assert clean_str("  Panasonic ") == "Panasonic"


def test_split_list_trim_dedupe_order():
    assert split_list("a | b |  | a | c") == ["a", "b", "c"]
    assert split_list("") == []
    assert split_list("x |  - | y") == ["x", "y"]


def test_parse_area_three_forms():
    assert parse_area("Từ 30 - 40m² (từ 80 đến 120m³)")[:2] == (30.0, 40.0)
    assert parse_area("Từ 15 - 20m²")[:2] == (15.0, 20.0)
    assert parse_area("Dưới 15m²")[:2] == (0.0, 15.0)
    amin, amax, warn = parse_area("khong biet")
    assert amin is None and amax is None and warn is not None


def test_parse_energy_and_cspf():
    assert parse_energy("5 sao (Hiệu suất năng lượng 6.23)")[:2] == (5, 6.23)
    assert parse_energy("3 sao (Hiệu suất năng lượng 4.55)")[:2] == (3, 4.55)
    assert parse_energy("Không")[:2] == (None, None)


def test_parse_noise_three_and_single():
    assert parse_noise("Dàn lạnh: 45/34/29 dB - Dàn nóng: 51 dB")[:3] == (29.0, 45.0, 51.0)
    imin, imax, outdoor, _ = parse_noise("Dàn lạnh: 38 dB - Dàn nóng: 49 dB")
    assert (imin, imax, outdoor) == (38.0, 38.0, 49.0)
    assert parse_noise("Không")[:3] == (None, None, None)


def test_parse_btu_only_with_btu_unit():
    assert parse_btu("9000 BTU")[0] == 9000
    assert parse_btu("Không")[0] is None
    assert parse_btu("40 m2")[0] is None  # no BTU -> never inferred


def test_parse_year_and_inverter():
    assert parse_year("2026") == 2026
    assert parse_year("Dòng 2025") == 2025
    assert parse_inverter("Máy lạnh Inverter") is True
    assert parse_inverter("Đang cập nhật") is None


def test_parse_inverter_non_inverter():
    """Regression: non-inverter must return False, not True."""
    assert parse_inverter("Non-Inverter") is False
    assert parse_inverter("non-inverter") is False
    assert parse_inverter("Không Inverter") is False
    assert parse_inverter("Máy lạnh Non-Inverter 1HP") is False
    assert parse_inverter("Inverter") is True
    assert parse_inverter("random text") is None


# --- record building (registry-shaped info dict, synthetic) ------------------
AIRCON_INFO = {
    "category": "air_conditioner",
    "deep_parse": True,
    "mappings": [
        {"source_column": "Tiện ích", "key": "features", "type": "list"},
        {"source_column": "Chuẩn chống nước, bụi", "key": "air_filter_features", "type": "string"},
    ],
}


def _row(**over):
    base = {
        "sku": "SKU1", "productidweb": "362465", "model_code": "180706",
        "brand": "Panasonic", "brand_id": "7", "category_code": "36",
        "giá gốc": "29490000", "giá khuyến mãi": "", "khuyến mãi quà": "Quà A | Quà B",
        "Tiện ích": "Wi-Fi | Sleep Mode", "Chuẩn chống nước, bụi": "Nanoe-G PM2.5",
        "Dòng sản phẩm": "2026", "Phạm vi sử dụng": "Từ 30 - 40m²",
        "Nhãn năng lượng": "5 sao (Hiệu suất năng lượng 6.23)",
        "Độ ồn": "Dàn lạnh: 45/34/29 dB - Dàn nóng: 51 dB",
        "Công suất đầu ra": "12000 BTU", "Loại Inverter": "Máy lạnh Inverter",
        "Công nghệ tiết kiệm điện": "Inverter",
    }
    base.update(over)
    return base


def test_build_record_promo_priority_and_effective():
    rec = build_record("Máy lạnh", AIRCON_INFO, _row(**{"giá khuyến mãi": "25000000"}), 2)
    assert rec["promotion_price"] == 25000000
    assert rec["effective_price"] == 25000000  # promo preferred
    rec2 = build_record("Máy lạnh", AIRCON_INFO, _row(), 3)
    assert rec2["effective_price"] == 29490000  # falls back to original


def test_build_record_deep_fields_and_eligible():
    rec = build_record("Máy lạnh", AIRCON_INFO, _row(), 2)
    s = rec["spec"]
    assert s["product_year"] == 2026
    assert (s["area_min_m2"], s["area_max_m2"]) == (30.0, 40.0)
    assert (s["energy_stars"], s["cspf"]) == (5, 6.23)
    assert s["indoor_noise_min_db"] == 29.0 and s["outdoor_noise_db"] == 51.0
    assert s["cooling_capacity_btu"] == 12000
    assert s["inverter"] is True
    assert s["features"] == ["Wi-Fi", "Sleep Mode"]
    assert s["air_filter_features"] == "Nanoe-G PM2.5"
    assert rec["promotions"] == ["Quà A", "Quà B"]
    assert rec["data_quality"]["eligible_for_demo"] is True


def test_placeholder_web_id_to_null_with_warning():
    rec = build_record("Máy lạnh", AIRCON_INFO, _row(**{"productidweb": "9999"}), 2)
    assert rec["product_web_id"] is None
    assert "placeholder_productidweb" in rec["data_quality"]["warnings"]


def test_promo_gt_original_warns_not_silently_fixed():
    rec = build_record("Máy lạnh", AIRCON_INFO,
                       _row(**{"giá gốc": "10000000", "giá khuyến mãi": "20000000"}), 2)
    assert rec["original_price"] == 10000000 and rec["promotion_price"] == 20000000
    assert "promotion_gt_original" in rec["data_quality"]["warnings"]


def test_no_sku_record_skipped():
    assert build_record("Máy lạnh", AIRCON_INFO, _row(**{"sku": ""}), 2) is None


def test_ineligible_kept_when_old_year():
    rec = build_record("Máy lạnh", AIRCON_INFO, _row(**{"Dòng sản phẩm": "2020"}), 2)
    assert rec is not None
    assert rec["data_quality"]["eligible_for_demo"] is False


# --- loader -----------------------------------------------------------------
def _valid_record():
    return {
        "product_id": "SKU1", "category": "air_conditioner", "stock_status": "unknown",
        "source": {"type": "btc_excel", "sheet": "Máy lạnh", "source_row": 2, "sku": "SKU1"},
        "data_quality": {"eligible_for_demo": True, "missing_fields": [], "warnings": []},
    }


def test_loader_rejects_missing_product_id():
    bad = _valid_record()
    bad["product_id"] = ""
    with pytest.raises(ValueError):
        btc_catalog.validate_record(bad, validate_schema=False)


def test_loader_keeps_unknown_stock():
    rec = btc_catalog.validate_record(_valid_record(), validate_schema=False)
    assert rec["stock_status"] == "unknown"


def test_loader_rejects_non_unknown_stock():
    bad = _valid_record()
    bad["stock_status"] = "in_stock"
    with pytest.raises(ValueError):
        btc_catalog.validate_record(bad, validate_schema=False)


def test_loader_reads_jsonl(tmp_path):
    p = tmp_path / "btc_air_conditioner.all.jsonl"
    p.write_text(json.dumps(_valid_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    recs = list(btc_catalog.load_jsonl(p, validate_schema=False))
    assert len(recs) == 1 and recs[0]["product_id"] == "SKU1"


def test_default_source_is_mock():
    assert btc_catalog.catalog_source() in ("mock", "btc")
    assert btc_catalog.is_btc_enabled() == (btc_catalog.catalog_source() == "btc")
