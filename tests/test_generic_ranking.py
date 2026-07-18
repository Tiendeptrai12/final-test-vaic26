"""Tests for the generic category ranker (antigravity/generic_ranking.py).

The fallback engine for DMX categories without a dedicated spec ranker. Confirms
budget/brand filtering, grounded scoring on price/rating/popularity, deterministic
order, and that it never fabricates (empty in -> empty out).
"""
from antigravity.generic_ranking import GenericNeed, rank_generic


def _rec(pid, price, rating, sold, brand="Sharp"):
    return {
        "product_id": pid, "tên sản phẩm": f"SP {pid}", "brand": brand, "url": None,
        "Giá khuyến mãi": price, "rating_vote": str(rating), "quantity_sold": str(sold),
    }


RECORDS = [
    _rec("A", 3_000_000, 4.9, 5000),
    _rec("B", 8_000_000, 4.2, 200),
    _rec("C", 20_000_000, 5.0, 10, brand="LG"),
]


def test_budget_max_filters_out():
    items = rank_generic(GenericNeed(budget_max=10_000_000), RECORDS, n=5)
    assert {i.product_id for i in items} == {"A", "B"}


def test_brand_filter():
    items = rank_generic(GenericNeed(brands=["LG"]), RECORDS, n=5)
    assert [i.product_id for i in items] == ["C"]


def test_empty_when_nothing_fits():
    assert rank_generic(GenericNeed(budget_max=1_000_000), RECORDS, n=3) == []


def test_price_priority_prefers_cheaper():
    # with priority=price, the cheap high-rating popular item leads
    items = rank_generic(GenericNeed(priority="price"), RECORDS, n=3)
    assert items[0].product_id == "A"


def test_grounded_numbers_only():
    items = rank_generic(GenericNeed(), RECORDS, n=1)
    it = items[0]
    assert it.price in {3_000_000, 8_000_000, 20_000_000}
    assert it.spec == {}  # no invented specs
    assert any("giá" in r for r in it.reasons)


def test_deterministic_order_stable():
    a = [i.product_id for i in rank_generic(GenericNeed(), RECORDS, n=3)]
    b = [i.product_id for i in rank_generic(GenericNeed(), RECORDS, n=3)]
    assert a == b
