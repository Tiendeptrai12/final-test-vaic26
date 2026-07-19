"""Dominant-vs-near-tie decision layer for the choose-factors flow.

After ranking produces a pool of candidate items, `decide()` scores each item ONLY
on the factors the user chose, then answers one question: is there a clear winner, or
a set of near-equal trade-offs?

  - dominant  -> one product beats the rest on the chosen factors -> suggest it alone.
  - near-tie  -> top few are within a small band (trade-offs, no easy winner) ->
                 present 3 so the user makes the final call.

Scoring is grounded: it prefers the ranking engine's own normalized `breakdown[weight_key]`
(price/noise/energy/capacity/rating/popularity/…). When a factor maps to a raw spec
string the engine can't weight (e.g. fridge "dung_tich_su_dung": "307 lít"), it parses
the number out and min-max normalizes across the pool — never inventing a value. A
factor with no data for an item scores a neutral 0.5 (neither rewarded nor punished).

All thresholds are env-overridable so they can be tuned during verification.
"""
from __future__ import annotations

import os
import re
from typing import Any

# tuning knobs (env-overridable)
DOMINANCE_ABS = float(os.environ.get("DECISION_DOMINANCE_ABS", "0.88"))   # top mean must clear this
DOMINANCE_GAP = float(os.environ.get("DECISION_DOMINANCE_GAP", "0.15"))   # …and beat #2 by this
TIE_BAND = float(os.environ.get("DECISION_TIE_BAND", "0.10"))            # top-3 within this = trade-off
TOP_N_TRADEOFF = 3

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _nums(v: Any) -> list[float]:
    """Every number in a spec value (handles '3 - 4 người', '307 lít', 8000)."""
    if isinstance(v, (int, float)):
        return [float(v)]
    if not isinstance(v, str):
        return []
    out = []
    for m in _NUM.findall(v):
        try:
            out.append(float(m.replace(".", "").replace(",", ".")) if m.count(".") > 1
                       else float(m.replace(",", ".")))
        except ValueError:
            continue
    return out


def _spec_number(item: dict[str, Any], spec_fields: list[str], higher_better: bool) -> float | None:
    """Pull one representative number for a factor from an item's spec. For a range
    ('3 - 4 người') take max when higher_better else min; try each field in order."""
    spec = item.get("spec") or {}
    for fld in spec_fields:
        if fld == "effective_price":
            p = item.get("price")
            if isinstance(p, (int, float)):
                return float(p)
        nums = _nums(spec.get(fld))
        if nums:
            return max(nums) if higher_better else min(nums)
    return None


def _minmax_norm(vals: list[float | None], higher_better: bool) -> list[float]:
    present = [v for v in vals if v is not None]
    if not present:
        return [0.5] * len(vals)
    lo, hi = min(present), max(present)
    out = []
    for v in vals:
        if v is None:
            out.append(0.5)
        elif hi <= lo:
            out.append(0.5)
        else:
            frac = (v - lo) / (hi - lo)
            out.append(frac if higher_better else 1.0 - frac)
    return out


def _factor_scores(items: list[dict[str, Any]], factor: dict[str, Any]) -> list[float]:
    """0..1 score per item for one factor. Engine breakdown first, else parse spec."""
    wk = factor.get("weight_key")
    # 1) engine already normalized this dimension -> use it directly
    if wk and all(isinstance((it.get("breakdown") or {}).get(wk), (int, float)) for it in items) and items:
        return [float((it["breakdown"])[wk]) for it in items]
    # 2) fall back to parsing the raw spec string, then pool min-max
    hb = bool(factor.get("higher_better", True))
    raw = [_spec_number(it, factor.get("spec_fields", []), hb) for it in items]
    return _minmax_norm(raw, hb)


def decide(items: list[dict[str, Any]], factors: list[dict[str, Any]],
           chosen: list[str]) -> dict[str, Any]:
    """Return {kind, items, ...}. kind ∈ {single, tradeoff, none}.

    `items` are API item dicts (from nlu._item_to_dict). `factors` is the category's
    factor list (factors_registry). `chosen` are the picked factor ids (budget may be
    "budget:tier" — the tier suffix is ignored here, budget scores via breakdown price).
    """
    if not items:
        return {"kind": "none", "items": []}

    chosen_ids = {c.partition(":")[0] for c in (chosen or [])}
    active = [f for f in factors if f.get("id") in chosen_ids] or factors
    if not active:
        return {"kind": "tradeoff", "items": items[:TOP_N_TRADEOFF]}

    # per-factor 0..1 columns, then per-item mean over chosen factors
    cols = {f["id"]: _factor_scores(items, f) for f in active}
    means: list[float] = []
    for i in range(len(items)):
        vals = [cols[fid][i] for fid in cols]
        means.append(sum(vals) / len(vals) if vals else 0.0)

    order = sorted(range(len(items)), key=lambda i: means[i], reverse=True)
    top = order[0]

    # tag each item with the chosen factor it scores highest on (for UI trade-off labels)
    def _winning_factor(i: int) -> str | None:
        best_fid, best_v = None, -1.0
        for f in active:
            v = cols[f["id"]][i]
            if v > best_v:
                best_v, best_fid = v, f["id"]
        return best_fid

    label_by_id = {f["id"]: f.get("simple_label") or f.get("spec_label") or f["id"] for f in active}

    def _tag(i: int) -> dict[str, Any]:
        it = dict(items[i])
        wf = _winning_factor(i)
        it["_factor_score"] = round(means[i], 3)
        it["_wins_on"] = label_by_id.get(wf) if wf else None
        return it

    # DOMINANCE: clear absolute score AND a real gap to #2
    if len(order) == 1 or (means[top] >= DOMINANCE_ABS and
                           means[top] - means[order[1]] >= DOMINANCE_GAP):
        return {"kind": "single", "items": [_tag(top)],
                "chosen_factors": sorted(chosen_ids)}

    # NEAR-TIE: top group within a small band -> present up to 3 trade-offs
    band = [i for i in order[:TOP_N_TRADEOFF] if means[top] - means[i] <= TIE_BAND]
    picked = band if len(band) >= 2 else order[:TOP_N_TRADEOFF]
    return {"kind": "tradeoff", "items": [_tag(i) for i in picked],
            "confirm": True, "chosen_factors": sorted(chosen_ids)}
