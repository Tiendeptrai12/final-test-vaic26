"""Phone ranking tests — synthetic raw-DMX dicts, pure code, no API."""
from __future__ import annotations

from antigravity.phone_ranking import rank_phones, PhoneNeed, _gb, _mah, _ram_gb


def _p(pid, price, storage, ram, batt, name=None):
    return {
        "product_id": pid, "category_name": "Điện thoại",
        "tên sản phẩm": name or f"Phone {pid}", "brand": "X", "Giá gốc": price,
        "rating_vote": "4.5", "url": f"u/{pid}",
        "spec_product": {"Dung lượng lưu trữ": storage, "RAM": ram, "Dung lượng pin": batt,
                         "Màn hình rộng": '6.7" - Tần số quét 120 Hz'},
    }


def test_parsers():
    assert _gb("256 GB") == 256 and _gb("128 MB") == 0.125 and _gb("1 TB") == 1024
    assert _mah("5000 mAh") == 5000
    assert _ram_gb({"spec_product": {"RAM": "8 GB"}}) == 8
    assert _ram_gb({"tên sản phẩm": "Phone 12GB/512GB", "spec_product": {}}) == 12


def test_budget_filter():
    recs = [_p("A", 5_000_000, "128 GB", "8 GB", "5000 mAh"),
            _p("B", 20_000_000, "256 GB", "12 GB", "5000 mAh")]
    out = rank_phones(PhoneNeed(budget_max=10_000_000), recs)
    assert [it.product_id for it in out] == ["A"]


def test_battery_priority_ranks_bigger_battery():
    recs = [_p("SMALL", 8_000_000, "128 GB", "8 GB", "4000 mAh"),
            _p("BIG", 8_000_000, "128 GB", "8 GB", "8000 mAh")]
    out = rank_phones(PhoneNeed(priority="battery"), recs)
    assert out[0].product_id == "BIG"


def test_min_ram_filter():
    recs = [_p("LO", 10_000_000, "128 GB", "6 GB", "5000 mAh"),
            _p("HI", 10_000_000, "128 GB", "12 GB", "5000 mAh")]
    out = rank_phones(PhoneNeed(min_ram_gb=8), recs)
    assert [it.product_id for it in out] == ["HI"]


def test_grounded_fields_and_reasons():
    out = rank_phones(PhoneNeed(), [_p("A", 9_000_000, "256 GB", "12 GB", "7000 mAh")])
    it = out[0]
    assert it.name and it.url == "u/A" and it.price == 9_000_000
    assert any("256GB" in r for r in it.reasons) and any("7000 mAh" in r for r in it.reasons)
