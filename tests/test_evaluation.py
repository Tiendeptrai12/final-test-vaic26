"""C6 evaluation tests — fit / compatibility / upgrade, grounded + honest-on-missing."""
from __future__ import annotations

from antigravity import evaluation as E


AC = {"product_id": "A", "name": "Daikin", "price": 14_000_000,
      "spec": {"area_min_m2": 15, "area_max_m2": 20}}


def test_fit_pass_and_fail():
    assert E.evaluate_fit(AC, budget_max=15_000_000, area_m2=18)["verdict"] == "phù hợp"
    assert E.evaluate_fit(AC, budget_max=10_000_000, area_m2=18)["verdict"] == "không phù hợp"
    assert E.evaluate_fit(AC, budget_max=15_000_000, area_m2=40)["verdict"] == "không phù hợp"


def test_fit_missing_data_is_honest():
    p = {"product_id": "X", "name": "X", "spec": {}}
    assert E.evaluate_fit(p, area_m2=18)["verdict"] == "chưa đủ dữ liệu"


def test_compatibility_shared_port_vs_no_data():
    mon = {"name": "M", "spec_product": {"Cổng kết nối": "HDMI, USB-C"}}
    pc = {"name": "P", "spec_product": {"Cổng xuất hình": "HDMI, DisplayPort"}}
    assert E.evaluate_compatibility(mon, pc)["verdict"] == "tương thích"
    blank = {"name": "B", "spec_product": {}}
    assert E.evaluate_compatibility(blank, blank)["verdict"] == "chưa đủ dữ liệu"


def test_upgrade_worth_and_not():
    cur = {"name": "cũ", "price": 8_000_000, "spec": {"screen_inch": 43}}
    new = {"name": "mới", "price": 12_000_000, "spec": {"screen_inch": 55}}
    r = E.evaluate_upgrade(cur, new)
    assert r["verdict"] == "nên nâng cấp nếu cần" and r["gains"]
    same = {"name": "s", "price": 12_000_000, "spec": {"screen_inch": 43}}
    assert E.evaluate_upgrade(cur, same)["verdict"] == "chưa nên nâng cấp"


def test_upgrade_missing_specs_no_evidence():
    assert E.evaluate_upgrade({"spec": {}}, {"spec": {}})["verdict"] == "chưa đủ bằng chứng"
