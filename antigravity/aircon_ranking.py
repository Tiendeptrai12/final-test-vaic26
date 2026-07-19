"""Air-conditioner ranking + filter engine (pure code, deterministic, no LLM/API).

The two `code` steps of the advisor workflow:
    LLM extract needs -> code check slots -> [FILTER hard constraints -> RANK] -> LLM explain

Prices and specs come straight from the canonical catalog records (built in Phase 1) and are
NEVER produced by an LLM, so numbers cannot be hallucinated. Ranking runs in-memory over the
~152 eligible aircon records in well under a millisecond, so the <5s SLA is never at risk.

Public entry point: `rank_top(profile, records=None, n=3) -> RankResult`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# need profile (slots an LLM will later fill)
# --------------------------------------------------------------------------- #
PRIORITIES = ("quiet", "fast_cooling", "energy_saving", "price")
ROOM_TYPES = ("bedroom", "living_room")


@dataclass
class NeedProfile:
    category: str | None = None            # DMX category_name, e.g. "Máy lạnh" | "Điện thoại"
    budget_max: int | None = None          # VND, hard
    budget_min: int | None = None          # VND, hard
    area_m2: float | None = None           # room size, hard (capacity fit) — aircon-specific
    usage: str | None = None               # free-text hoàn cảnh dùng (mọi ngành)
    room_type: str | None = None           # "bedroom" | "living_room"
    sunny: bool | None = None              # direct sun -> capacity headroom
    priority: str | None = None            # one of PRIORITIES
    inverter_required: bool | None = None  # hard
    brands: list[str] = field(default_factory=list)  # allow-list, empty = any
    # Multi-ngành slots (additive; None cho ngành không dùng — aircon rank bỏ qua).
    household_size: int | None = None      # số người dùng (tủ lạnh/máy giặt/sấy/rửa chén/nước nóng)
    capacity_liters: float | None = None   # dung tích lít (tủ đông, tủ mát)
    battery_priority: bool | None = None   # ưu tiên pin lâu (đồng hồ TM / máy tính bảng)
    portability_priority: bool | None = None  # ưu tiên nhỏ gọn (micro / máy tính bảng)
    # choose-factors flow: weight_keys the user chose to prioritize (factors.py). Each
    # boosts its matching ranking dimension; empty = plain base weights. Additive to the
    # legacy single `priority` slot (both are honored).
    factor_priorities: list[str] = field(default_factory=list)


@dataclass
class RankedItem:
    product_id: str
    brand: str | None
    effective_price: int | None
    total_score: float
    breakdown: dict[str, float]
    reasons: list[str]
    missing_data: list[str]
    spec: dict[str, Any]
    source: dict[str, Any]
    # DMX-rich fields (None on older BTC records) — display + grounding, straight from record
    name: str | None = None
    image: str | None = None
    url: str | None = None
    rating: float | None = None
    quantity_sold: int | None = None
    promotion: str | None = None
    original_price: int | None = None
    promotion_price: int | None = None
    promotions: list[str] | None = None


@dataclass
class RankResult:
    items: list[RankedItem]
    relaxations: list[str]
    rejected_summary: dict[str, int]
    total_candidates: int


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
AREA_TOLERANCE = 1.0
SUNNY_HEADROOM = 1.15


def _spec(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("spec") or {}


def _is_eligible(rec: dict[str, Any]) -> bool:
    return bool((rec.get("data_quality") or {}).get("eligible_for_demo"))


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


# --------------------------------------------------------------------------- #
# hard-constraint filter
# --------------------------------------------------------------------------- #
def filter_candidates(
    records: list[dict[str, Any]], profile: NeedProfile, *, area_tol: float = AREA_TOLERANCE,
    use_brands: bool = True, use_sunny: bool = True, budget_scale: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return (kept, rejected_summary). rejected_summary maps first-failing constraint -> count.

    `budget_scale` multiplies budget_max (relaxation lever). `use_brands`/`use_sunny` toggle
    those constraints off during relaxation.
    """
    kept: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    budget_max = int(profile.budget_max * budget_scale) if profile.budget_max else None

    for rec in records:
        if not _is_eligible(rec):
            reject("not_eligible")
            continue
        spec = _spec(rec)
        price = rec.get("effective_price")

        if (budget_max or profile.budget_min) and not isinstance(price, int):
            reject("missing_price")
            continue
        if budget_max is not None and price > budget_max:
            reject("over_budget")
            continue
        if profile.budget_min is not None and price < profile.budget_min:
            reject("under_budget_min")
            continue

        if profile.area_m2 is not None:
            amin, amax = _num(spec.get("area_min_m2")), _num(spec.get("area_max_m2"))
            if amin is None or amax is None:
                reject("missing_area")
                continue
            if not (amin - area_tol <= profile.area_m2 <= amax + area_tol):
                reject("area_mismatch")
                continue
            if use_sunny and profile.sunny and amax < profile.area_m2 * SUNNY_HEADROOM:
                reject("insufficient_headroom_sunny")
                continue

        if profile.inverter_required and spec.get("inverter") is not True:
            reject("not_inverter")
            continue

        if use_brands and profile.brands:
            brand = (rec.get("brand") or "").strip().lower()
            if brand not in {b.strip().lower() for b in profile.brands}:
                reject("brand_excluded")
                continue

        kept.append(rec)

    return kept, rejected


# fixed relaxation ladder (deterministic). each entry -> (kwargs override, note)
def _relaxation_steps(profile: NeedProfile) -> list[tuple[dict[str, Any], str]]:
    steps: list[tuple[dict[str, Any], str]] = []
    if profile.brands:
        steps.append(({"use_brands": False}, "bỏ giới hạn thương hiệu"))
    if profile.sunny:
        steps.append(({"use_brands": False, "use_sunny": False},
                      "bỏ yêu cầu dự phòng công suất cho phòng nắng"))
    if profile.budget_max:
        steps.append(({"use_brands": False, "use_sunny": False, "budget_scale": 1.10},
                      "nới ngân sách +10%"))
        steps.append(({"use_brands": False, "use_sunny": False, "budget_scale": 1.25},
                      "nới ngân sách +25%"))
    if profile.area_m2 is not None:
        steps.append(({"use_brands": False, "use_sunny": False, "budget_scale": 1.25,
                       "area_tol": 3.0}, "nới dung sai diện tích ±3m²"))
    return steps


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
# base weights per metric; priority/room adjust them. keys: price, noise, energy, capacity
_BASE_WEIGHTS = {"price": 0.25, "noise": 0.25, "energy": 0.25, "capacity": 0.25}
_PRIORITY_BOOST = {
    "quiet": {"noise": 0.35},
    "fast_cooling": {"capacity": 0.35},
    "energy_saving": {"energy": 0.35},
    "price": {"price": 0.35},
}


# choose-factors flow: each chosen weight_key bumps its dimension by this delta
# (same magnitude as a legacy priority boost) before renormalizing.
_FACTOR_DELTA = 0.35


def _weights(profile: NeedProfile) -> dict[str, float]:
    w = dict(_BASE_WEIGHTS)
    boost = _PRIORITY_BOOST.get(profile.priority or "", {})
    for k, extra in boost.items():
        w[k] += extra
    # choose-factors: boost every chosen weight_key that this engine actually has
    # (price/noise/energy/capacity). Unknown keys — e.g. generic "popularity" — are
    # ignored here; they only matter to the generic engine.
    for wk in getattr(profile, "factor_priorities", []) or []:
        if wk in w:
            w[wk] += _FACTOR_DELTA
    if profile.room_type == "bedroom":
        w["noise"] += 0.10  # quiet matters more in a bedroom
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}  # normalise to sum 1


def _minmax(values: list[float]) -> tuple[float, float]:
    return (min(values), max(values)) if values else (0.0, 0.0)


def _norm(v: float, lo: float, hi: float, *, higher_better: bool) -> float:
    if hi <= lo:
        return 0.5
    frac = (v - lo) / (hi - lo)
    return frac if higher_better else 1.0 - frac


def _capacity_fit(area: float, amin: float, amax: float) -> float:
    """1.0 when area sits mid-range, decays toward the edges, clamps to 0."""
    if amax <= amin:
        return 0.5
    mid = (amin + amax) / 2
    half = (amax - amin) / 2
    return max(0.0, 1.0 - abs(area - mid) / half)


def score_all(
    records: list[dict[str, Any]], profile: NeedProfile
) -> list[tuple[dict[str, Any], float, dict[str, float], list[str]]]:
    """Score every kept record. Returns (rec, total, breakdown, missing_data)."""
    weights = _weights(profile)
    prices = [r["effective_price"] for r in records if isinstance(r.get("effective_price"), int)]
    noises = [n for r in records if (n := _num(_spec(r).get("indoor_noise_min_db"))) is not None]
    energies = [e for r in records if (e := _energy_value(r)) is not None]
    p_lo, p_hi = _minmax(prices)
    n_lo, n_hi = _minmax(noises)
    e_lo, e_hi = _minmax(energies)

    out = []
    for rec in records:
        spec = _spec(rec)
        breakdown: dict[str, float] = {}
        missing: list[str] = []

        price = rec.get("effective_price")
        if isinstance(price, int):
            breakdown["price"] = _norm(price, p_lo, p_hi, higher_better=False)
        else:
            breakdown["price"] = 0.0
            missing.append("price")

        noise = _num(spec.get("indoor_noise_min_db"))
        if noise is not None:
            breakdown["noise"] = _norm(noise, n_lo, n_hi, higher_better=False)
        else:
            breakdown["noise"] = 0.0
            missing.append("indoor_noise_min_db")

        energy = _energy_value(rec)
        if energy is not None:
            breakdown["energy"] = _norm(energy, e_lo, e_hi, higher_better=True)
        else:
            breakdown["energy"] = 0.0
            missing.append("energy")

        amin, amax = _num(spec.get("area_min_m2")), _num(spec.get("area_max_m2"))
        if profile.area_m2 is not None and amin is not None and amax is not None:
            breakdown["capacity"] = _capacity_fit(profile.area_m2, amin, amax)
        elif amin is not None and amax is not None:
            breakdown["capacity"] = 0.5  # no target area given -> neutral
        else:
            breakdown["capacity"] = 0.0
            missing.append("area")

        total = sum(weights[k] * breakdown[k] for k in weights)
        out.append((rec, total, breakdown, missing))
    return out


CSPF_MIN, CSPF_MAX = 3.0, 8.0  # typical Vietnamese aircon CSPF span
POWER_KWH_MIN, POWER_KWH_MAX = 0.5, 3.0  # typical DMX aircon "Tiêu thụ điện" span


def _energy_value(rec: dict[str, Any]) -> float | None:
    """Unified 0..1 energy rating so CSPF and star labels are comparable.

    CSPF (~3-8) and energy_stars (1-5) live on different scales; map each onto a
    fixed 0..1 domain before they enter the same min-max, else a star fallback
    would be unfairly crushed against real CSPF numbers.
    """
    spec = _spec(rec)
    cspf = _num(spec.get("cspf"))
    if cspf is not None:
        return max(0.0, min(1.0, (cspf - CSPF_MIN) / (CSPF_MAX - CSPF_MIN)))
    stars = _num(spec.get("energy_stars"))
    if stars is not None:
        return max(0.0, min(1.0, (stars - 1.0) / 4.0))
    # DMX data has no CSPF/stars — use power draw (kWh) as the energy proxy: lower is
    # better, so invert onto the same 0..1 (higher = better) scale as CSPF/stars.
    power = _num(spec.get("power_kwh"))
    if power is not None:
        return max(0.0, min(1.0, 1.0 - (power - POWER_KWH_MIN) / (POWER_KWH_MAX - POWER_KWH_MIN)))
    return None


# --------------------------------------------------------------------------- #
# grounded reasons (values pulled ONLY from the record)
# --------------------------------------------------------------------------- #
def build_reasons(rec: dict[str, Any], profile: NeedProfile) -> list[str]:
    spec = _spec(rec)
    reasons: list[str] = []
    price = rec.get("effective_price")
    if isinstance(price, int):
        if profile.budget_max and price <= profile.budget_max:
            reasons.append(f"trong ngân sách ({price/1_000_000:.1f}tr)")
        else:
            reasons.append(f"giá {price/1_000_000:.1f}tr")
    noise = _num(spec.get("indoor_noise_min_db"))
    if noise is not None and noise <= 35:
        reasons.append(f"chạy êm ({noise:.0f} dB)")
    cspf = _num(spec.get("cspf"))
    stars = _num(spec.get("energy_stars"))
    if cspf is not None:
        reasons.append(f"tiết kiệm điện (CSPF {cspf:g})")
    elif stars is not None:
        reasons.append(f"nhãn năng lượng {stars:g} sao")
    if spec.get("inverter") is True:
        reasons.append("công nghệ Inverter")
    power = _num(spec.get("power_kwh"))
    if cspf is None and stars is None and power is not None:
        reasons.append(f"tiêu thụ điện {power:g} kWh")
    amin, amax = _num(spec.get("area_min_m2")), _num(spec.get("area_max_m2"))
    if amin is not None and amax is not None:
        reasons.append(f"phù hợp phòng {amin:g}-{amax:g}m²")
    rating = _num(rec.get("rating"))
    if rating is not None and rating >= 4.0:
        reasons.append(f"đánh giá {rating:g}/5")
    sold = rec.get("quantity_sold")
    if isinstance(sold, int) and sold >= 100:
        reasons.append(f"đã bán {sold:,}".replace(",", "."))
    return reasons


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _load_default_records() -> list[dict[str, Any]]:
    from antigravity import btc_catalog
    return btc_catalog.load_category("air_conditioner")


def rank_top(
    profile: NeedProfile, records: list[dict[str, Any]] | None = None, n: int = 3,
    pool: int | None = None,
) -> RankResult:
    """Filter -> score -> deterministic sort -> return top items.

    `pool` (>= n) returns extra scored candidates without changing the relaxation
    threshold (still driven by n) — a downstream semantic reranker reorders them and
    slices back to n. Default (None) returns exactly n, preserving prior behavior.
    """
    if records is None:
        records = _load_default_records()

    kept, rejected = filter_candidates(records, profile)
    relaxations: list[str] = []
    if len(kept) < n:
        for overrides, note in _relaxation_steps(profile):
            kept, rejected = filter_candidates(records, profile, **overrides)
            relaxations.append(note)
            if len(kept) >= n:
                break

    scored = score_all(kept, profile)
    # deterministic tie-break (real DMX signals, stock dropped): highest score, then
    # better-rated, then more-sold, then cheaper, then product_id.
    def _sort_key(t):
        rec = t[0]
        price = rec.get("effective_price")
        return (
            -t[1],
            -(_num(rec.get("rating")) or 0.0),
            -(rec.get("quantity_sold") or 0),
            price if isinstance(price, int) else 1 << 62,
            rec.get("product_id", ""),
        )
    scored.sort(key=_sort_key)

    items: list[RankedItem] = []
    for rec, total, breakdown, missing in scored[: (pool or n)]:
        items.append(RankedItem(
            product_id=rec.get("product_id", ""),
            brand=rec.get("brand"),
            effective_price=rec.get("effective_price"),
            total_score=round(total, 4),
            breakdown={k: round(v, 4) for k, v in breakdown.items()},
            reasons=build_reasons(rec, profile),
            missing_data=missing,
            spec=_spec(rec),
            source=rec.get("source", {}),
            name=rec.get("name"),
            image=rec.get("image"),
            url=rec.get("url"),
            rating=_num(rec.get("rating")),
            quantity_sold=rec.get("quantity_sold"),
            promotion=rec.get("promotion"),
            original_price=rec.get("original_price"),
            promotion_price=rec.get("promotion_price"),
            promotions=rec.get("promotions"),
        ))
    return RankResult(items=items, relaxations=relaxations,
                      rejected_summary=dict(sorted(rejected.items())),
                      total_candidates=len(records))
