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
import os
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
    from antigravity.vector_db import search_few_shots
    from antigravity.few_shot import get_segment_guidelines_prompt, get_few_shot_prompt
    
    # 1. Retrieve matching few-shot examples from Qdrant
    few_shot_str = ""
    try:
        few_shots = search_few_shots(text, limit=2)
        few_shot_str = get_few_shot_prompt(few_shots)
    except Exception:
        pass
        
    # 2. Retrieve dynamic segment guidelines based on query category
    guideline = ""
    lower = text.lower()
    if "máy lạnh" in lower or "điều hòa" in lower:
        guideline = get_segment_guidelines_prompt("Máy lạnh")
    elif "tủ lạnh" in lower:
        guideline = get_segment_guidelines_prompt("Tủ lạnh")
    elif "laptop" in lower:
        guideline = get_segment_guidelines_prompt("Laptop")
    elif "pc" in lower or "máy tính" in lower:
        guideline = get_segment_guidelines_prompt("Pc, máy in")
        
    system_prompt = _SYSTEM_PROMPT
    if guideline:
        system_prompt += "\n" + guideline
    if few_shot_str:
        system_prompt += "\n\n" + few_shot_str

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
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
    prior_profile: dict[str, Any] | None = None, pool: int | None = None,
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

    result: RankResult = rank_top(profile, records=records, n=n, pool=pool)
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


def _rerank_doc(item: dict[str, Any]) -> str:
    """Compact text for the cross-encoder: only grounded fields, never invented."""
    s = item.get("spec") or {}
    bits = [str(item.get("name") or item.get("brand") or "")]
    if s.get("area_min_m2") is not None:
        bits.append(f"phòng {s.get('area_min_m2'):g}-{s.get('area_max_m2'):g}m2")
    if s.get("indoor_noise_min_db") is not None:
        bits.append(f"độ ồn {s.get('indoor_noise_min_db'):g}dB")
    if s.get("inverter") is True:
        bits.append("inverter tiết kiệm điện")
    if item.get("price") is not None:
        bits.append(f"giá {item['price']/1_000_000:.1f} triệu")
    return " ".join(bits)


def _rerank_items(query: str, items: list[dict[str, Any]], n: int, timeout: float) -> list[dict[str, Any]]:
    """Reorder code-approved candidates by FPT bge-reranker semantic relevance to the raw
    query, then take top n. SERVICE stage: only reorders items the code already filtered —
    never adds products or invents data (guardrail intact). On any failure, returns the
    code order unchanged (items[:n]) so the turn never blocks on a service call.
    """
    if len(items) <= n:
        return items[:n]
    try:
        from antigravity import fpt_services
        ranked = fpt_services.rerank(query, [_rerank_doc(it) for it in items], top_n=n, timeout=timeout)
    except Exception:  # noqa: BLE001 - service optional; degrade to code order
        return items[:n]
    if not ranked:
        return items[:n]
    return [items[idx] for idx, _score in ranked[:n]]


def _advise_from_comparison(comp: dict[str, Any]) -> str:
    """C7 conclusion after a comparison — grounded, from per-field winners only."""
    prods = comp.get("products", [])
    wins: dict[int, list[str]] = {}
    for row in comp.get("rows", []):
        wi = row.get("winner_idx")
        if wi is not None:
            wins.setdefault(wi, []).append(row["label"].lower())
    if not wins:
        return "Hai sản phẩm khá tương đương ở các chỉ số có dữ liệu; bạn ưu tiên tiêu chí nào nhất?"
    parts = []
    for idx, labels in wins.items():
        name = (prods[idx].get("name") or prods[idx].get("brand") or f"SP {idx+1}") if idx < len(prods) else f"SP {idx+1}"
        parts.append(f"{name} nhỉnh hơn về {', '.join(labels)}")
    return "So sánh theo dữ liệu: " + "; ".join(parts) + ". Bạn ưu tiên tiêu chí nào thì mình chốt giúp."


def _advise_from_fit(fit: dict[str, Any]) -> str:
    """C7 conclusion after a fit evaluation."""
    v = fit.get("verdict")
    name = fit.get("name") or "Sản phẩm này"
    fails = [r["criterion"].lower() for r in fit.get("rows", []) if r.get("ok") is False]
    if v == "phù hợp":
        return f"{name} phù hợp với nhu cầu của bạn ở các tiêu chí đã kiểm."
    if v == "không phù hợp":
        return f"{name} chưa phù hợp: chưa đạt {', '.join(fails) or 'một số tiêu chí'}."
    if v == "chưa đủ dữ liệu":
        return f"Chưa đủ dữ liệu để khẳng định {name} có phù hợp không."
    return f"{name} phù hợp một phần; một số tiêu chí chưa có dữ liệu."


def build_chat_response(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    explain: bool = True, prior_profile: dict[str, Any] | None = None,
    selected_products: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap advise() into a flat, frontend-friendly, JSON-safe contract.

    Routes every message through C0 Router, then dispatches to the matching capability
    (teach / compare / compatibility / upgrade / fit) or the recommendation path. Shape:
      {query, mode, message, profile, safety_checked,
       items[], questions[], relaxations[], explanation,        # recommendation
       comparison{} | evaluation{} | teach{}}                   # mode-specific
    Prices/specs come ONLY from code engines, never from the LLM. Advisor never handles
    ordering/shipping/payment — items carry the dienmayxanh.com `url`.
    """
    from antigravity import router, comparison as _cmp, evaluation as _ev, teach as _teach

    sp = selected_products or []
    prof0 = prior_profile or {}
    r = router.route(text)

    # --- C8 Teach: side branch, never enters the pipeline ---
    if r.intent == router.INTENT_TEACH:
        t = _teach.teach(text, has_product=bool(sp),
                         has_budget=prof0.get("budget_max") is not None)
        return {"query": text, "mode": "teach", "message": t["message"], "teach": t,
                "profile": prof0, "safety_checked": True}

    # --- C6 Compare (needs >=2 resolved products) -> Advise ---
    if r.intent == router.INTENT_COMPARE and len(sp) >= 2:
        comp = _cmp.compare(sp)
        return {"query": text, "mode": "comparison", "comparison": comp,
                "message": _advise_from_comparison(comp), "profile": prof0,
                "safety_checked": True}

    # --- C6 Compatibility -> Advise ---
    if r.intent == router.INTENT_COMPATIBILITY and len(sp) >= 2:
        comp = _ev.evaluate_compatibility(sp[0], sp[1])
        return {"query": text, "mode": "compatibility", "evaluation": comp,
                "message": comp["note"], "profile": prof0, "safety_checked": True}

    # --- C6 Upgrade -> Advise ---
    if r.intent == router.INTENT_UPGRADE and len(sp) >= 2:
        comp = _ev.evaluate_upgrade(sp[0], sp[1])
        return {"query": text, "mode": "upgrade", "evaluation": comp,
                "message": comp["why"], "profile": prof0, "safety_checked": True}

    # --- C6 Fit (single exact product + need) -> Advise ---
    if r.intent == router.INTENT_EXACT_LOOKUP and sp:
        fit = _ev.evaluate_fit(sp[0], budget_max=prof0.get("budget_max"),
                               area_m2=prof0.get("area_m2"))
        return {"query": text, "mode": "fit", "evaluation": fit,
                "message": _advise_from_fit(fit), "profile": prof0, "safety_checked": True}

    # --- else: recommendation path (C1..C5) ---
    # abstract lifestyle need -> front-load it as the top reranker criterion
    rerank_query = _cmp.priority_rerank_query(text, text)

    # Reranker service (bge) reorders a bigger candidate pool by semantic relevance to the
    # raw query, then we slice to n. Env-gated (default on). pool = extra candidates fetched
    # without changing the filter/relaxation threshold.
    use_reranker = os.environ.get("USE_RERANKER", "1").strip().lower() not in ("0", "false", "no")
    pool = max(n, 8) if use_reranker else None
    out = advise(text, history, records=records, n=n, timeout=timeout,
                 prior_profile=prior_profile, pool=pool)
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
    pool_items = [_item_to_dict(it) for it in result.items]
    # SERVICE stage: bge-reranker reorders the code-approved pool by semantic relevance to
    # the raw query, then slice to n. Falls back to code order on any failure.
    base["items"] = _rerank_items(rerank_query, pool_items, n, timeout) if use_reranker else pool_items[:n]
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
