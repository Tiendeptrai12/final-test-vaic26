"""Ranking engine tests. Synthetic records only — no real BTC data, no LLM/API."""
from __future__ import annotations

import copy

from antigravity.aircon_ranking import (
    NeedProfile, filter_candidates, rank_top,
)


def rec(pid, price, amin, amax, noise, cspf, inverter=True, brand="Daikin",
        eligible=True, stars=None, features=("Wi-Fi",)):
    return {
        "product_id": pid, "brand": brand, "effective_price": price,
        "category": "air_conditioner", "stock_status": "unknown",
        "spec": {
            "area_min_m2": amin, "area_max_m2": amax, "indoor_noise_min_db": noise,
            "cspf": cspf, "energy_stars": stars, "inverter": inverter,
            "features": list(features),
        },
        "data_quality": {"eligible_for_demo": eligible, "missing_fields": [], "warnings": []},
        "source": {"type": "btc_excel", "sheet": "Máy lạnh", "source_row": 2, "sku": pid},
    }


def sample():
    return [
        rec("A", 10_000_000, 15, 20, 30, 6.2),   # cheap, quiet, fits 18
        rec("B", 18_000_000, 15, 20, 42, 4.5),   # pricier, loud
        rec("C", 25_000_000, 25, 35, 25, 7.0, brand="Panasonic"),  # big room, quietest
        rec("D", 12_000_000, 15, 20, 35, 5.5, inverter=False),     # non-inverter
        rec("E", 30_000_000, 30, 45, 28, 6.8),   # very big room
        rec("F", 9_000_000, 15, 20, 33, None, stars=5),  # cspf null, has stars
    ]


# --- hard filter ------------------------------------------------------------
def test_budget_filter_excludes_over_budget():
    kept, rej = filter_candidates(sample(), NeedProfile(budget_max=15_000_000))
    ids = {r["product_id"] for r in kept}
    assert "B" not in ids and "C" not in ids and "E" not in ids
    assert rej.get("over_budget", 0) >= 3


def test_area_filter_excludes_wrong_room():
    kept, _ = filter_candidates(sample(), NeedProfile(area_m2=18))
    ids = {r["product_id"] for r in kept}
    assert ids >= {"A", "B", "D", "F"}  # 15-20 range fits 18
    assert "C" not in ids and "E" not in ids  # 25-35 / 30-45 do not


def test_inverter_and_brand_filters():
    kept, _ = filter_candidates(sample(), NeedProfile(inverter_required=True))
    assert "D" not in {r["product_id"] for r in kept}
    kept2, _ = filter_candidates(sample(), NeedProfile(brands=["panasonic"]))
    assert {r["product_id"] for r in kept2} == {"C"}


def test_missing_price_excluded_when_budget_set():
    recs = sample()
    recs[0]["effective_price"] = None
    kept, rej = filter_candidates(recs, NeedProfile(budget_max=15_000_000))
    assert "A" not in {r["product_id"] for r in kept}
    assert rej.get("missing_price", 0) == 1


def test_sunny_requires_headroom():
    # area 18, sunny -> need amax >= 20.7; A/B/D/F have amax 20 -> rejected
    kept, rej = filter_candidates(sample(), NeedProfile(area_m2=18, sunny=True))
    assert {r["product_id"] for r in kept} == set()  # none has headroom in 15-20
    assert rej.get("insufficient_headroom_sunny", 0) >= 1


# --- scoring / ordering -----------------------------------------------------
def test_priority_changes_ordering():
    # stark trade-off, both fit an 18m² room:
    #   QUIET = very quiet (22 dB) but expensive (22tr) and average energy
    #   CHEAP = cheapest (9tr) but loud (46 dB)
    recs = [
        rec("QUIET", 22_000_000, 15, 20, 22, 5.0),
        rec("CHEAP", 9_000_000, 15, 20, 46, 5.0),
    ]
    quiet = rank_top(NeedProfile(area_m2=18, priority="quiet"), recs, n=2)
    price = rank_top(NeedProfile(area_m2=18, priority="price"), recs, n=2)
    assert quiet.items[0].product_id == "QUIET"
    assert price.items[0].product_id == "CHEAP"
    assert quiet.items[0].product_id != price.items[0].product_id


def test_null_cspf_uses_stars_not_dropped():
    res = rank_top(NeedProfile(area_m2=18, priority="energy_saving"), sample(), n=6)
    ids = {it.product_id for it in res.items}
    assert "F" in ids  # F has null cspf but stars=5 -> still scored, not dropped


def test_missing_data_flagged_neutral():
    recs = sample()
    recs[0]["spec"]["indoor_noise_min_db"] = None
    res = rank_top(NeedProfile(area_m2=18), recs, n=6)
    item_a = next(it for it in res.items if it.product_id == "A")
    assert "indoor_noise_min_db" in item_a.missing_data
    assert item_a.breakdown["noise"] == 0.0


# --- relaxation -------------------------------------------------------------
def test_relaxation_triggers_and_records_notes():
    # budget too low for anything -> relax budget upward
    res = rank_top(NeedProfile(budget_max=8_000_000, area_m2=18), sample(), n=3)
    assert res.relaxations  # something was relaxed
    assert any("ngân sách" in note for note in res.relaxations)
    assert len(res.items) >= 1


def test_brand_relaxed_first():
    res = rank_top(NeedProfile(area_m2=25, brands=["Toshiba"]), sample(), n=1)
    # no Toshiba -> must relax brand to return anything
    assert any("thương hiệu" in n for n in res.relaxations)
    assert len(res.items) >= 1


# --- determinism + grounding ------------------------------------------------
def test_deterministic_same_input_same_output():
    p = NeedProfile(area_m2=18, budget_max=20_000_000, priority="quiet")
    r1 = rank_top(p, sample(), n=3)
    r2 = rank_top(copy.deepcopy(p), sample(), n=3)
    assert [i.product_id for i in r1.items] == [i.product_id for i in r2.items]
    assert [i.total_score for i in r1.items] == [i.total_score for i in r2.items]


def test_reasons_are_grounded_in_record():
    res = rank_top(NeedProfile(area_m2=18, budget_max=20_000_000), sample(), n=3)
    for it in res.items:
        spec = it.spec
        for reason in it.reasons:
            if "dB" in reason:
                assert str(int(spec["indoor_noise_min_db"])) in reason
            if "CSPF" in reason:
                assert spec["cspf"] is not None
            if "Inverter" in reason:
                assert spec["inverter"] is True


def test_no_fabricated_stock():
    res = rank_top(NeedProfile(area_m2=18), sample(), n=3)
    for it in res.items:
        # engine never asserts availability
        assert "stock" not in it.reasons


# --- P4: DMX-rich signals (power_kwh energy, rating/sold tie-break, card fields) ---
def _dmx_rec(pid, price, power_kwh, rating=None, sold=None, name=None):
    return {
        "product_id": pid, "brand": "LG", "effective_price": price,
        "name": name, "image": "http://img/" + pid, "url": "http://dmx/" + pid,
        "rating": rating, "quantity_sold": sold,
        "category": "air_conditioner", "stock_status": "unknown",
        "spec": {"area_min_m2": 15, "area_max_m2": 20, "indoor_noise_min_db": 30,
                 "power_kwh": power_kwh, "inverter": True},
        "data_quality": {"eligible_for_demo": True, "missing_fields": [], "warnings": []},
        "source": {"type": "dmx_json", "sku": pid},
    }


def test_energy_from_power_kwh_lower_is_better():
    recs = [_dmx_rec("LOW", 10_000_000, 0.7), _dmx_rec("HIGH", 10_000_000, 2.5)]
    res = rank_top(NeedProfile(area_m2=18, priority="energy_saving"), recs, n=2)
    assert res.items[0].product_id == "LOW"  # less power draw ranks first
    assert res.items[0].breakdown["energy"] > res.items[1].breakdown["energy"]


def test_tiebreak_prefers_higher_rating_then_sold():
    # identical spec/price -> tie broken by rating, then quantity_sold
    a = _dmx_rec("A", 10_000_000, 1.0, rating=4.2, sold=50)
    b = _dmx_rec("B", 10_000_000, 1.0, rating=4.9, sold=10)
    c = _dmx_rec("C", 10_000_000, 1.0, rating=4.9, sold=900)
    res = rank_top(NeedProfile(area_m2=18), [a, b, c], n=3)
    assert [it.product_id for it in res.items] == ["C", "B", "A"]


def test_item_exposes_dmx_fields_and_grounded_reasons():
    res = rank_top(NeedProfile(area_m2=18), [_dmx_rec("X", 9_000_000, 1.0, rating=4.8,
                   sold=1500, name="Máy lạnh LG demo")], n=1)
    it = res.items[0]
    assert it.name == "Máy lạnh LG demo" and it.url == "http://dmx/X" and it.rating == 4.8
    assert any("đánh giá 4.8/5" in r for r in it.reasons)
    assert any("đã bán" in r for r in it.reasons)
