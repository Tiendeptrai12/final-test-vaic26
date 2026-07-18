"""Phone ranking (pure code, deterministic, grounded) — the phone analog of aircon_ranking.

Operates on raw DMX product dicts (category_name == "Điện thoại"): reads spec_product +
"Giá gốc"/"Giá khuyến mãi". Prices/specs come only from the record, so numbers can't be
hallucinated. Public: rank_phones(need, records, n=3) -> list[PhoneItem].
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PHONE_PRIORITIES = ("price", "battery", "storage", "performance", "screen", "camera")


@dataclass
class PhoneNeed:
    budget_max: int | None = None
    budget_min: int | None = None
    priority: str | None = None          # one of PHONE_PRIORITIES
    brands: list[str] = field(default_factory=list)
    min_storage_gb: float | None = None
    min_ram_gb: float | None = None


@dataclass
class PhoneItem:
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
# parsers (grounded on real DMX value formats)
# --------------------------------------------------------------------------- #
def _price(rec: dict[str, Any]) -> int | None:
    for k in ("Giá khuyến mãi", "Giá gốc"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return None


def _gb(v: Any) -> float | None:
    """'256 GB' -> 256; '128 MB' -> 0.125."""
    if not v:
        return None
    m = re.search(r"([\d.,]+)\s*(gb|mb|tb)", str(v), re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return num * (1 / 1024 if unit == "mb" else 1024 if unit == "tb" else 1)


def _mah(v: Any) -> float | None:
    m = re.search(r"([\d.,]+)\s*mah", str(v or ""), re.IGNORECASE)
    return float(m.group(1).replace(",", "").replace(".", "")) if m else None


def _inch(v: Any) -> float | None:
    m = re.search(r'([\d.,]+)\s*["” inch]', str(v or ""), re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def _hz(v: Any) -> float | None:
    m = re.search(r"(\d+)\s*hz", str(v or ""), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _ram_gb(rec: dict[str, Any]) -> float | None:
    spec = rec.get("spec_product") or {}
    g = _gb(spec.get("RAM"))
    if g is not None:
        return g
    # fallback: name "12GB/512GB" -> first = RAM
    m = re.search(r"(\d+)\s*gb\s*/\s*\d+\s*gb", str(rec.get("tên sản phẩm") or ""), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _phone_specs(rec: dict[str, Any]) -> dict[str, Any]:
    spec = rec.get("spec_product") or {}
    return {
        "storage_gb": _gb(spec.get("Dung lượng lưu trữ")),
        "ram_gb": _ram_gb(rec),
        "battery_mah": _mah(spec.get("Dung lượng pin")),
        "screen_inch": _inch(spec.get("Màn hình rộng")),
        "refresh_hz": _hz(spec.get("Màn hình rộng")),
        "resolution": spec.get("Độ phân giải màn hình"),
    }


def _rating(rec: dict[str, Any]) -> float | None:
    try:
        r = float(str(rec.get("rating_vote") or "").replace(",", "."))
        return r if 0 < r <= 5 else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# filter + score
# --------------------------------------------------------------------------- #
def _passes(rec: dict[str, Any], need: PhoneNeed) -> bool:
    price = _price(rec)
    if need.budget_max and (price is None or price > need.budget_max):
        return False
    if need.budget_min and (price is None or price < need.budget_min):
        return False
    if need.brands:
        brand = (rec.get("brand") or "").strip().lower()
        if brand not in {b.strip().lower() for b in need.brands}:
            return False
    s = _phone_specs(rec)
    if need.min_storage_gb and (s["storage_gb"] or 0) < need.min_storage_gb:
        return False
    if need.min_ram_gb and (s["ram_gb"] or 0) < need.min_ram_gb:
        return False
    return True


_BASE_W = {"price": 0.25, "battery": 0.2, "storage": 0.2, "ram": 0.2, "screen": 0.15}
_BOOST = {
    "price": {"price": 0.35}, "battery": {"battery": 0.35}, "storage": {"storage": 0.35},
    "performance": {"ram": 0.3, "storage": 0.15}, "screen": {"screen": 0.35},
    "camera": {"screen": 0.15},  # no camera spec parsed -> lean on screen/quality proxy
}


def _weights(need: PhoneNeed) -> dict[str, float]:
    w = dict(_BASE_W)
    for k, extra in _BOOST.get(need.priority or "", {}).items():
        w[k] += extra
    t = sum(w.values())
    return {k: v / t for k, v in w.items()}


def _norm(v, vals, higher_better):
    xs = [x for x in vals if x is not None]
    if not xs or v is None:
        return 0.5 if v is None else 0.5
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return 0.5
    f = (v - lo) / (hi - lo)
    return f if higher_better else 1 - f


def rank_phones(need: PhoneNeed, records: list[dict[str, Any]], n: int = 3) -> list[PhoneItem]:
    kept = [r for r in records if _passes(r, need)]
    if not kept:
        return []
    weights = _weights(need)
    prices = [_price(r) for r in kept]
    specs = [_phone_specs(r) for r in kept]
    batt = [s["battery_mah"] for s in specs]
    stor = [s["storage_gb"] for s in specs]
    ram = [s["ram_gb"] for s in specs]
    scr = [s["screen_inch"] for s in specs]

    scored = []
    for r, s in zip(kept, specs):
        p = _price(r)
        bd = {
            "price": _norm(p, prices, higher_better=False),
            "battery": _norm(s["battery_mah"], batt, higher_better=True),
            "storage": _norm(s["storage_gb"], stor, higher_better=True),
            "ram": _norm(s["ram_gb"], ram, higher_better=True),
            "screen": _norm(s["screen_inch"], scr, higher_better=True),
        }
        total = sum(weights[k] * bd[k] for k in weights)
        scored.append((r, s, total, bd))

    scored.sort(key=lambda t: (
        -t[2], -(_rating(t[0]) or 0), t[0].get("Giá khuyến mãi") or t[0].get("Giá gốc") or 1 << 62,
        t[0].get("product_id", ""),
    ))

    out = []
    for r, s, total, bd in scored[:n]:
        out.append(PhoneItem(
            product_id=r.get("product_id", ""), name=r.get("tên sản phẩm"),
            brand=r.get("brand"), price=_price(r), url=r.get("url"), rating=_rating(r),
            total_score=round(total, 4), breakdown={k: round(v, 4) for k, v in bd.items()},
            reasons=_reasons(r, s), spec=s,
        ))
    return out


def _reasons(rec: dict[str, Any], s: dict[str, Any]) -> list[str]:
    out: list[str] = []
    p = _price(rec)
    if p:
        out.append(f"giá {p/1_000_000:.1f}tr")
    if s["storage_gb"]:
        out.append(f"bộ nhớ {s['storage_gb']:g}GB")
    if s["ram_gb"]:
        out.append(f"RAM {s['ram_gb']:g}GB")
    if s["battery_mah"]:
        out.append(f"pin {s['battery_mah']:g} mAh")
    if s["screen_inch"]:
        hz = f" {s['refresh_hz']:g}Hz" if s["refresh_hz"] else ""
        out.append(f"màn {s['screen_inch']:g}\"{hz}")
    r = _rating(rec)
    if r and r >= 4.0:
        out.append(f"đánh giá {r:g}/5")
    return out
