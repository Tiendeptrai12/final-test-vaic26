"""Post-hoc numeric-claim guardrail (ported from the teammate `guardrails-ai`
ClaimsVerified validator, re-implemented dependency-free / stdlib-only).

WHY: the explainer (Call B) is grounded by construction — it is fed only the
FACTS block built from ranked catalog records and told to invent nothing. But a
reasoning LLM can still drift a number (round 350k -> "300 nghìn", mistype a dB).
This module is the *verification* half of "grounded generation": every money /
spec number the LLM wrote is extracted and checked against the real numbers that
came out of the ranking engine + the user's own slots. Anything not matching a
known fact (within tolerance) is an unverified claim.

Anti-hallucination guarantee: prices/specs shown to the user are the catalog's,
never the model's. On any unverified number the caller degrades the free prose
back to the deterministic per-item `reasons[]` (same fail-safe the explainer
already uses on an FPT error), so a drifted number is never surfaced.

Public entry: `verify_explanation(text, items, profile) -> VerifyResult`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

# tolerances match the teammate validator: money allows light rounding
# ("gần 15 triệu" cho 14.990.000), specs must be near-exact.
MONEY_TOLERANCE = 0.03  # 3%
SPEC_TOLERANCE = 0.02   # 2%


# --------------------------------------------------------------------------- #
# claim extraction (money + spec mentions in the LLM prose)
# --------------------------------------------------------------------------- #
def _to_number(raw: str) -> float:
    return float(raw.replace(",", "."))


def extract_money_mentions(text: str | None) -> list[float]:
    """VND amounts the LLM wrote: "8.4 triệu" -> 8_400_000, "8.380.000" -> 8380000."""
    if not isinstance(text, str) or not text:
        return []
    results: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(tri[ệe]u|tr)\b", text, re.IGNORECASE):
        results.append(round(_to_number(m.group(1)) * 1_000_000))
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{3}){2,})\s*(đ|vnđ|vnd|₫)?", text, re.IGNORECASE):
        digits = re.sub(r"[.,]", "", m.group(1))
        results.append(float(digits))
    return results


@dataclass(frozen=True)
class SpecMention:
    value: float
    unit: str


_SPEC_UNIT_PATTERNS = [
    ("m²", re.compile(r"(\d+(?:[.,]\d+)?)\s*(m²|m2)(?![a-zA-Z0-9])", re.IGNORECASE)),
    ("dB", re.compile(r"(\d+(?:[.,]\d+)?)\s*(dB|db)(?![a-zA-Z0-9])", re.IGNORECASE)),
    ("lít", re.compile(r"(\d+(?:[.,]\d+)?)\s*(lít|lit)(?![a-zA-Z0-9])", re.IGNORECASE)),
    ("người", re.compile(r"(\d+(?:[.,]\d+)?)\s*người(?![a-zA-Z0-9])", re.IGNORECASE)),
]


def extract_spec_mentions(text: str | None) -> list[SpecMention]:
    if not isinstance(text, str) or not text:
        return []
    results: list[SpecMention] = []
    for unit, pattern in _SPEC_UNIT_PATTERNS:
        for m in pattern.finditer(text):
            results.append(SpecMention(value=_to_number(m.group(1)), unit=unit))
    return results


# --------------------------------------------------------------------------- #
# known facts (the ONLY numbers the LLM is allowed to state)
# --------------------------------------------------------------------------- #
@dataclass
class KnownFacts:
    money: set[float] = field(default_factory=set)
    spec: dict[str, set[float]] = field(
        default_factory=lambda: {"m²": set(), "dB": set(), "lít": set(), "người": set()})


def _add(store: set[float], v: Any) -> None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        store.add(float(v))


def build_known_facts(items: list[dict[str, Any]], profile: Any) -> KnownFacts:
    """Real numbers from the ranked items + the user's slots.

    Items carry the catalog's own `price` (effective) and `spec` block; profile
    carries budget_max/budget_min/area_m2. Pairwise price differences are added so
    the LLM may legitimately say "chênh lệch chỉ 300 nghìn" about two shown prices.
    """
    facts = KnownFacts()
    # user slots (profile is a NeedProfile dataclass or None)
    if profile is not None:
        _add(facts.money, getattr(profile, "budget_max", None))
        _add(facts.money, getattr(profile, "budget_min", None))
        _add(facts.spec["m²"], getattr(profile, "area_m2", None))

    prices: list[float] = []
    for it in items or []:
        p = it.get("price")
        if isinstance(p, (int, float)) and not isinstance(p, bool):
            facts.money.add(float(p))
            prices.append(float(p))
        s = it.get("spec") or {}
        for k in ("area_min_m2", "area_max_m2"):
            _add(facts.spec["m²"], s.get(k))
        for k in ("indoor_noise_min_db", "indoor_noise_max_db", "outdoor_noise_db"):
            _add(facts.spec["dB"], s.get(k))
        _add(facts.spec["lít"], s.get("capacity_liters"))

    for a, b in combinations(prices, 2):
        facts.money.add(abs(a - b))
    return facts


def _is_known(value: float, known: set[float], tolerance: float) -> bool:
    for k in known:
        if abs(value - k) / max(abs(k), 1.0) <= tolerance:
            return True
    return False


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
@dataclass
class VerifyResult:
    ok: bool
    unverified: list[dict[str, Any]] = field(default_factory=list)


def verify_explanation(text: str | None, items: list[dict[str, Any]], profile: Any) -> VerifyResult:
    """Extract every money/spec number in `text`, check each against known facts.

    Returns ok=True when the prose invents nothing. Otherwise `unverified` lists
    the offending values so the caller can degrade (drop the prose) and log.
    """
    if not isinstance(text, str) or not text.strip():
        return VerifyResult(ok=True)
    facts = build_known_facts(items, profile)
    unverified: list[dict[str, Any]] = []
    for v in extract_money_mentions(text):
        if not _is_known(v, facts.money, MONEY_TOLERANCE):
            unverified.append({"type": "money", "value": v})
    for s in extract_spec_mentions(text):
        if not _is_known(s.value, facts.spec.get(s.unit, set()), SPEC_TOLERANCE):
            unverified.append({"type": "spec", "value": s.value, "unit": s.unit})
    return VerifyResult(ok=not unverified, unverified=unverified)
