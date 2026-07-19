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
    # choose-factors: weight_keys the user prioritized. This engine only has
    # rating/popularity/price, so only those keys boost here; spec-based factor keys
    # (capacity/battery/…) are ignored by the ranker but still drive decision.py.
    factor_priorities: list[str] = field(default_factory=list)


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
    # canonical demo_catalog shape first (effective_price int), then raw DMX columns.
    v = rec.get("effective_price")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return int(v)
    for k in ("Giá khuyến mãi", "Giá gốc"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v)
    return None


def _rating(rec: dict[str, Any]) -> float | None:
    # canonical `rating` (float) first, then raw `rating_vote` (string).
    v = rec.get("rating")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 5:
        return float(v)
    try:
        r = float(str(rec.get("rating_vote") or "").replace(",", "."))
        return r if 0 < r <= 5 else None
    except ValueError:
        return None


def _sold(rec: dict[str, Any]) -> int | None:
    """canonical `quantity_sold` (int) first, then raw string '14,5k' -> 14500."""
    v = rec.get("quantity_sold")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
        return int(v)
    s = str(v or "").strip().lower().replace(" ", "")
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
    # demo_catalog records carry an explicit eligibility gate (same as aircon). Raw DMX
    # records have no such flag -> treated as eligible.
    dq = rec.get("data_quality")
    if isinstance(dq, dict) and dq.get("eligible_for_demo") is False:
        return False
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


_FACTOR_DELTA = 0.35


def _weights(need: GenericNeed) -> dict[str, float]:
    w = dict(_PRICE_BOOST) if need.priority == "price" else dict(_BASE_W)
    for wk in getattr(need, "factor_priorities", []) or []:
        if wk in w:
            w[wk] += _FACTOR_DELTA
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}  # renormalize to sum 1


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
    w = str(rec.get("warranty") or rec.get("chính sách bảo hành") or "").strip()
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
            product_id=str(r.get("product_id", "")),
            name=r.get("name") or r.get("tên sản phẩm"),
            brand=r.get("brand"), price=_price(r), url=r.get("url"), rating=_rating(r),
            total_score=round(total, 4), breakdown={k: round(v, 4) for k, v in bd.items()},
            reasons=_reasons(r),
            # surface the raw DMX spec so decision.py can best-effort parse numbers for
            # factor scoring (canonical keys may not match raw column names — neutral 0.5
            # fallback covers that; never invents data).
            spec=(r.get("spec_product") or r.get("spec") or {}),
        ))
    return out


# category_name (DMX) -> demo_catalog file slug (dmx_<slug>.all.jsonl). Cùng quy ước
# đặt tên với dmx_air_conditioner.all.jsonl. Ngành nào có file bundled thì chạy được
# trên Vercel (NDA-safe demo data); ngành không có -> fallback raw json (chỉ local).
CATEGORY_SLUG: dict[str, str] = {
    "Tủ lạnh": "tu_lanh",
    "Máy giặt": "may_giat",
    "Máy sấy quần áo": "may_say_quan_ao",
    "Máy rửa chén": "may_rua_chen",
    "Máy nước nóng": "may_nuoc_nong",
    "Tủ đông, tủ mát": "tu_dong_tu_mat",
    "Máy tính bảng": "may_tinh_bang",
    "Đồng hồ thông minh": "dong_ho_thong_minh",
    "Micro": "micro",
    "Máy tính để bàn": "may_tinh_de_ban",
    "Màn hình máy tính": "man_hinh_may_tinh",
    "Máy in": "may_in",
}


def load_category_records(category_name: str) -> list[dict[str, Any]]:
    """Records cho 1 ngành (theo category_name DMX). Ưu tiên demo_catalog canonical
    (bundled, chạy được trên Vercel); nếu ngành không có file demo thì fallback raw
    NDA json (chỉ có ở local). [] nếu cả hai đều vắng — KHÔNG bịa sản phẩm."""
    slug = CATEGORY_SLUG.get(category_name)
    if slug:
        try:
            from antigravity import btc_catalog
            records = btc_catalog.load_category(slug)
            if records:
                return records
        except Exception:  # noqa: BLE001 — file thiếu/không đọc được -> thử raw json
            pass
    return load_default_records(category_name)
