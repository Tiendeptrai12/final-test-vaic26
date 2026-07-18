"""Phase 3: Vietnamese free text -> NeedProfile (the first real LLM call).

Pipeline seam:  [LLM extract needs] -> code check slots -> code filter -> code rank -> LLM explain

`extract_need_profile` prompts gemma-3-12b-it for STRICT JSON matching the NeedProfile
fields, then validates/coerces it in code — the LLM never emits prices or specs (those come
only from rank_top), so it cannot hallucinate product numbers. Anything the LLM is unsure of
becomes None. Missing required slots (area_m2, budget_max) drive Vietnamese follow-up
questions in code — this is the "hỏi ngược" judging criterion.

`advise(text)` wires extract -> ask-if-missing -> rank_top. Kept OFF the mock path; the API
only uses it when CATALOG_SOURCE=btc.
"""
from __future__ import annotations

import json
import re
from typing import Any

from antigravity import fpt_client
from antigravity.aircon_ranking import (
    PRIORITIES, ROOM_TYPES, NeedProfile, RankedItem, RankResult, rank_top,
)

# slots that gate a follow-up question when null (decided in Phase 3 planning)
REQUIRED_SLOTS = ("area_m2", "budget_max")

FOLLOWUP_QUESTIONS = {
    "area_m2": "Phòng bạn định lắp khoảng bao nhiêu m²?",
    "budget_max": "Ngân sách của bạn khoảng bao nhiêu (ví dụ 15 triệu)?",
    "priority": "Bạn ưu tiên điều gì nhất: chạy êm, làm lạnh nhanh, tiết kiệm điện, hay giá rẻ?",
}

_SYSTEM_PROMPT = (
    "Bạn là bộ trích xuất nhu cầu mua máy lạnh. Đọc tin nhắn tiếng Việt của khách và trả về "
    "DUY NHẤT một object JSON, không giải thích, không markdown. Các khóa:\n"
    '  "budget_max": số nguyên VND hoặc null (vd "dưới 20 triệu" -> 20000000)\n'
    '  "budget_min": số nguyên VND hoặc null\n'
    '  "area_m2": số m² hoặc null (vd "phòng 18m2" -> 18)\n'
    '  "room_type": "bedroom" | "living_room" | null\n'
    '  "sunny": true | false | null (phòng nắng/hướng tây -> true)\n'
    '  "priority": "quiet" | "fast_cooling" | "energy_saving" | "price" | null '
    '(ít ồn->quiet, lạnh nhanh->fast_cooling, tiết kiệm điện->energy_saving, giá rẻ->price)\n'
    '  "inverter_required": true | false | null\n'
    '  "brands": mảng tên hãng hoặc [] (vd ["Daikin"])\n'
    "Không suy đoán giá/thông số sản phẩm. Không chắc -> null. Chỉ JSON."
)

# fallback price-unit parser if the LLM returns a string like "20 triệu" instead of a number
_TRIEU = re.compile(r"([\d.,]+)\s*(tri[ệe]u|tr)\b", re.IGNORECASE)


def _coerce_price(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = int(v)
        return n if n > 0 else None
    if isinstance(v, str):
        m = _TRIEU.search(v)
        if m:
            num = float(m.group(1).replace(".", "").replace(",", "."))
            return int(num * 1_000_000)
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else None
    return None


def _coerce_area(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    if isinstance(v, str):
        m = re.search(r"[\d.,]+", v)
        if m:
            val = float(m.group(0).replace(",", "."))
            return val if val > 0 else None
    return None


def _coerce_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "có", "co"):
            return True
        if s in ("false", "no", "không", "khong"):
            return False
    return None


def _coerce_enum(v: Any, allowed: tuple[str, ...]) -> str | None:
    if isinstance(v, str) and v.strip().lower() in allowed:
        return v.strip().lower()
    return None


def _coerce_brands(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(b).strip() for b in v if str(b).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _parse_json(raw: str) -> dict[str, Any]:
    """Best-effort: strip ```json fences, then grab the outermost {...}."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise json.JSONDecodeError("not an object", s, 0)
    return obj


def coerce_profile(obj: dict[str, Any]) -> NeedProfile:
    """Validate/coerce a raw JSON dict into a NeedProfile. Unknown/invalid -> None."""
    return NeedProfile(
        budget_max=_coerce_price(obj.get("budget_max")),
        budget_min=_coerce_price(obj.get("budget_min")),
        area_m2=_coerce_area(obj.get("area_m2")),
        room_type=_coerce_enum(obj.get("room_type"), ROOM_TYPES),
        sunny=_coerce_bool(obj.get("sunny")),
        priority=_coerce_enum(obj.get("priority"), PRIORITIES),
        inverter_required=_coerce_bool(obj.get("inverter_required")),
        brands=_coerce_brands(obj.get("brands")),
    )


_PROFILE_FIELDS = ("budget_max", "budget_min", "area_m2", "room_type", "sunny",
                   "priority", "inverter_required", "brands")


def merge_profiles(prior: NeedProfile, new: NeedProfile) -> NeedProfile:
    """Carry slots across turns: the new turn's value wins, else keep the prior.

    This is the multi-turn "hỏi ngược" fix — when the user answers a follow-up ("18m2,
    20 triệu") the earlier slots (priority=quiet) are not lost. Server stays stateless;
    the client resends `profile` each turn.
    """
    out: dict[str, Any] = {}
    for f in _PROFILE_FIELDS:
        nv, pv = getattr(new, f), getattr(prior, f)
        if f == "brands":
            out[f] = nv if nv else pv
        else:
            out[f] = nv if nv is not None else pv
    return NeedProfile(**out)


def missing_slots(profile: NeedProfile) -> list[str]:
    """Required slots that are still null (drive hỏi-ngược follow-ups)."""
    return [s for s in REQUIRED_SLOTS if getattr(profile, s) is None]


def followups(slots: list[str]) -> list[str]:
    return [FOLLOWUP_QUESTIONS[s] for s in slots if s in FOLLOWUP_QUESTIONS]


def extract_need_profile(
    text: str, history: list[dict[str, str]] | None = None, *,
    model: str = fpt_client.NLU_MODEL, timeout: float = 3.0,
) -> tuple[NeedProfile, list[str], dict[str, Any] | None]:
    """text -> (NeedProfile, missing_slots, raw_llm_json).

    On any LLM/JSON failure returns an empty profile so every required slot reads as
    missing and the caller asks the user to restate (fail-safe, never fabricates).
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})

    try:
        raw = fpt_client.chat_completion(
            model, messages, max_tokens=256, temperature=0.0, timeout=timeout,
            response_format={"type": "json_object"},
        )
        obj = _parse_json(raw)
    except (fpt_client.FPTError, json.JSONDecodeError):
        empty = NeedProfile()
        return empty, missing_slots(empty), None

    profile = coerce_profile(obj)
    return profile, missing_slots(profile), obj


def advise(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    prior_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full BTC turn: extract -> merge prior slots -> ask-if-missing -> rank_top.

    `prior_profile` (dict from the previous turn's response) carries slots forward so a
    follow-up answer doesn't drop earlier needs. Returns a dict:
      {"status": "need_info", "profile": {...}, "missing": [...], "questions": [...]}
      {"status": "ok",        "profile": {...}, "result": RankResult}
    """
    profile, _missing, raw = extract_need_profile(text, history, timeout=timeout)
    if prior_profile:
        profile = merge_profiles(NeedProfile(**prior_profile), profile)
    missing = missing_slots(profile)
    profile_dict = vars(profile)

    if missing:
        return {
            "status": "need_info",
            "profile": profile_dict,
            "missing": missing,
            "questions": followups(missing),
            "raw_llm": raw,
        }

    result: RankResult = rank_top(profile, records=records, n=n)
    return {"status": "ok", "profile": profile_dict, "result": result, "raw_llm": raw}


# --------------------------------------------------------------------------- #
# API-facing response builder (stable JSON contract for POST /api/chat)
# --------------------------------------------------------------------------- #
def _item_to_dict(it: RankedItem) -> dict[str, Any]:
    """Serialize a RankedItem for the API. Numbers come only from the record."""
    return {
        "product_id": it.product_id,
        "name": it.name,
        "brand": it.brand,
        "image": it.image,
        "url": it.url,
        "price": it.effective_price,
        "rating": it.rating,
        "quantity_sold": it.quantity_sold,
        "promotion": it.promotion,
        "reasons": it.reasons,
        "breakdown": it.breakdown,
        "missing_data": it.missing_data,
        "spec": it.spec,
    }


def build_chat_response(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    explain: bool = True, prior_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap advise() into a flat, frontend-friendly, JSON-safe contract.

    Shape:
      {query, mode: "need_info"|"recommendation", message, questions[], profile{},
       items[], relaxations[], explanation, safety_checked}
    Prices/specs come ONLY from ranked records (code), never from the LLM. `explanation`
    is grounded Top-3 trade-off prose (Call B); None if disabled or the explainer fails
    (deterministic per-item reasons[] still carry the grounding).
    """
    out = advise(text, history, records=records, n=n, timeout=timeout,
                 prior_profile=prior_profile)
    base: dict[str, Any] = {
        "query": text,
        "profile": out.get("profile", {}),
        "questions": [],
        "items": [],
        "relaxations": [],
        "explanation": None,
        "safety_checked": True,
    }

    if out["status"] == "need_info":
        qs = out.get("questions", [])
        base["mode"] = "need_info"
        base["message"] = " ".join(qs) or "Bạn bổ sung thêm thông tin giúp mình nhé."
        base["questions"] = qs
        return base

    result: RankResult = out["result"]
    base["mode"] = "recommendation"
    base["items"] = [_item_to_dict(it) for it in result.items]
    base["relaxations"] = result.relaxations
    if not result.items:
        # no-results terminal (guardrail code_rules.no_results_terminal): never fabricate
        base["message"] = ("Chưa có sản phẩm phù hợp với tiêu chí này. "
                           "Bạn thử nới ngân sách hoặc diện tích nhé.")
    else:
        base["message"] = "Đây là Top gợi ý phù hợp nhất với nhu cầu của bạn:"
        if result.relaxations:
            base["message"] += " (đã nới nhẹ tiêu chí: " + ", ".join(result.relaxations) + ")"
        if explain:
            from antigravity.explainer import explain_top
            profile = NeedProfile(**out["profile"])
            # z.ai glm-5.2 (Call B) measures ~6s; give it headroom so the grounded
            # trade-off prose actually renders instead of silently degrading. Slightly
            # over the <5s target — switch EXPLAIN_PROVIDER=fpt (gemma ~2.6s) if the SLA
            # must hold hard. On any failure explain_top returns None and the per-item
            # reasons[] still carry the grounding.
            base["explanation"] = explain_top(base["items"], profile, timeout=8.0)
    return base
