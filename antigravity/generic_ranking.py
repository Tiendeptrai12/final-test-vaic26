"""Generic category ranker (pure code, deterministic, grounded) — the fallback engine
for DMX categories that have no dedicated spec ranker yet (everything except máy lạnh /
điện thoại).

WHY: aircon + phone each have a hand-built spec engine; the other ~117 DMX categories
had no ranker, so `advise()` returned empty items for them (honest, but useless — a fridge
query got "chưa có sản phẩm"). This engine ranks any category on the signals that ARE
present + trustworthy in every DMX record: price (budget fit), rating, and units sold
(popularity). No category-specific spec parsing, so it never invents a spec — numbers come
straight from the record, same anti-hallucination guarantee as the aircon/phone engines.

Operates on raw DMX product dicts (same shape phone_ranking reads). Public:
`rank_generic(need, records, n=3) -> list[GenericItem]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from antigravity.phone_ranking import load_default_records  # raw-json loader, reused


@dataclass
class GenericNeed:
    budget_max: int | None = None
    budget_min: int | None = None
    priority: str | None = None          # only "price" is meaningful here
    brands: list[str] = field(default_factory=list)


@dataclass
class GenericItem:
    product_id: str
    name: str | None
    brand: str | None
    price: int | None
    url: str | None
    rating: float | None
    total_score: float
    breakdown: dict[str, float]
    reasons: list[str]
    spec: dict[str, Any]


# --------------------------------------------------------------------------- #
# grounded field parsers (raw DMX value formats)
# --------------------------------------------------------------------------- #
def _price(rec: dict[str, Any]) -> int | None:
    for k in ("Giá khuyến mãi", "Giá gốc"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v)
    return None


def _rating(rec: dict[str, Any]) -> float | None:
    try:
        r = float(str(rec.get("rating_vote") or "").replace(",", "."))
        return r if 0 < r <= 5 else None
    except ValueError:
        return None


def _sold(rec: dict[str, Any]) -> int | None:
    """'14,5k' -> 14500, '1.234' -> 1234, '' -> None."""
    s = str(rec.get("quantity_sold") or "").strip().lower().replace(" ", "")
    if not s:
        return None
    m = re.match(r"^([\d.,]+)k$", s)
    if m:
        return int(float(m.group(1).replace(".", "").replace(",", ".")) * 1000)
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


# --------------------------------------------------------------------------- #
# filter + score
# --------------------------------------------------------------------------- #
def _passes(rec: dict[str, Any], need: GenericNeed) -> bool:
    price = _price(rec)
    if need.budget_max and (price is None or price > need.budget_max):
        return False
    if need.budget_min and (price is None or price < need.budget_min):
        return False
    if need.brands:
        brand = (rec.get("brand") or "").strip().lower()
        if brand not in {b.strip().lower() for b in need.brands}:
            return False
    return True


# base weights: rating (trust) + popularity (proven demand) lead; price is a tie-shaper
# unless the user explicitly prioritises giá rẻ, then it dominates.
_BASE_W = {"rating": 0.45, "popularity": 0.35, "price": 0.20}
_PRICE_BOOST = {"rating": 0.25, "popularity": 0.20, "price": 0.55}


def _weights(need: GenericNeed) -> dict[str, float]:
    return dict(_PRICE_BOOST) if need.priority == "price" else dict(_BASE_W)


def _norm(v, vals, higher_better):
    xs = [x for x in vals if x is not None]
    if v is None or not xs:
        return 0.5
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return 0.5
    f = (v - lo) / (hi - lo)
    return f if higher_better else 1 - f


def _reasons(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    p = _price(rec)
    if p:
        out.append(f"giá {p/1_000_000:.1f}tr")
    r = _rating(rec)
    if r and r >= 4.0:
        out.append(f"đánh giá {r:g}/5")
    sold = _sold(rec)
    if sold:
        out.append(f"đã bán {sold:g}")
    w = (rec.get("chính sách bảo hành") or "").strip()
    if w:
        out.append(f"bảo hành {w}")
    return out


def rank_generic(need: GenericNeed, records: list[dict[str, Any]], n: int = 3) -> list[GenericItem]:
    """Filter by budget/brand, then rank on rating + popularity + price. Grounded only —
    every number comes from the record; returns [] (never fabricates) when nothing fits."""
    kept = [r for r in records if _passes(r, need)]
    if not kept:
        return []
    ratings = [_rating(r) for r in kept]
    solds = [_sold(r) for r in kept]
    prices = [_price(r) for r in kept]
    weights = _weights(need)

    scored = []
    for r in kept:
        bd = {
            "rating": _norm(_rating(r), ratings, higher_better=True),
            "popularity": _norm(_sold(r), solds, higher_better=True),
            "price": _norm(_price(r), prices, higher_better=False),
        }
        total = sum(weights[k] * bd[k] for k in weights)
        scored.append((r, total, bd))

    # deterministic tie-break: score, then better-rated, more-sold, cheaper, product_id
    scored.sort(key=lambda t: (
        -t[1], -(_rating(t[0]) or 0), -(_sold(t[0]) or 0),
        _price(t[0]) or 1 << 62, str(t[0].get("product_id", "")),
    ))

    out = []
    for r, total, bd in scored[:n]:
        out.append(GenericItem(
            product_id=str(r.get("product_id", "")), name=r.get("tên sản phẩm"),
            brand=r.get("brand"), price=_price(r), url=r.get("url"), rating=_rating(r),
            total_score=round(total, 4), breakdown={k: round(v, 4) for k, v in bd.items()},
            reasons=_reasons(r), spec={},
        ))
    return out


def load_category_records(category_name: str) -> list[dict[str, Any]]:
    """Raw DMX records for any category (by canonical category_name). [] if data absent."""
    return load_default_records(category_name)
