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
from dataclasses import dataclass
from typing import Any

from antigravity import fpt_client
from antigravity.aircon_ranking import (
    PRIORITIES, ROOM_TYPES, NeedProfile, RankedItem, RankResult, rank_top,
)

# Hard cap for the optional few-shot/guideline enrichment lookup (Qdrant). Live-verify
# measured cold opens at ~15-17s and warm at ~3s — both too slow for a "nice to have"
# prompt addition, so this is capped tight and just skipped past on timeout.
FEW_SHOT_TIMEOUT = 0.5

# required slots are category-aware (see missing_slots): every ngành cần category + budget;
# mỗi ngành có thêm slot đặc thù riêng (CATEGORY_SLOT_SCHEMA). Follow-up hỏi ngược lấy
# đúng câu hỏi theo slot còn thiếu.
FOLLOWUP_QUESTIONS = {
    "category": "Bạn muốn mua sản phẩm gì ạ (máy lạnh, tủ lạnh, máy giặt, laptop...)?",
    "budget_max": "Ngân sách của bạn khoảng bao nhiêu (ví dụ 15 triệu)?",
    "area_m2": "Phòng bạn định lắp khoảng bao nhiêu m²?",
    "priority": "Bạn ưu tiên điều gì nhất: chạy êm, làm lạnh nhanh, tiết kiệm điện, hay giá rẻ?",
    "household_size": "Gia đình mình khoảng mấy người sử dụng ạ?",
    "capacity_liters": "Bạn cần dung tích khoảng bao nhiêu lít ạ?",
    "battery_priority": "Bạn có ưu tiên thời lượng pin lâu (pin trâu) không ạ?",
    "portability_priority": "Bạn có cần sản phẩm nhỏ gọn, dễ mang theo không ạ?",
    "usage": "Bạn dùng chủ yếu cho mục đích gì ạ (học tập, làm việc, chơi game...)?",
}

# ---------------------------------------------------------------------------
# NLU theo TỪNG NGÀNH — mỗi category_name có 1 slot đặc thù cần hỏi thêm ngoài
# (category + budget_max). Nguồn: 14 ngành registry.json (bản backend_py), đã
# gộp về đúng category_name DMX. Ngành nào không liệt kê ở đây -> chỉ cần
# category + budget (dùng _DEFAULT_EXTRA_SLOTS = ()).
#
# Cấu hình dạng dict (KHÔNG if/else theo ngành) — thêm ngành mới chỉ cần thêm
# 1 dòng ở đây + 1 pattern trong router.py + 1 chip ở frontend.
# ---------------------------------------------------------------------------
CATEGORY_SLOT_SCHEMA: dict[str, tuple[str, ...]] = {
    "Máy lạnh": ("area_m2",),
    "Tủ lạnh": ("household_size",),
    "Máy giặt": ("household_size",),
    "Máy sấy quần áo": ("household_size",),
    "Máy rửa chén": ("household_size",),
    "Máy nước nóng": ("household_size",),
    "Tủ đông, tủ mát": ("capacity_liters",),
    "Máy tính bảng": ("battery_priority",),
    "Đồng hồ thông minh": ("battery_priority",),
    "Micro": ("portability_priority",),
    "Máy tính để bàn": ("usage",),
    "Màn hình máy tính": ("usage",),
    "Máy in": ("usage",),
}

# DMX categories the advisor understands (map free text -> canonical category_name).
# 14 ngành chính thức (registry.json) + vài ngành phổ biến đã hoạt động sẵn.
KNOWN_CATEGORIES = (
    # 14 ngành chính thức
    "Máy lạnh", "Tủ lạnh", "Máy giặt", "Máy sấy quần áo", "Máy rửa chén",
    "Máy nước nóng", "Tủ đông, tủ mát", "Máy tính bảng", "Đồng hồ thông minh",
    "Micro", "Máy tính để bàn", "Màn hình máy tính", "Máy in",
    # ngành phổ biến giữ lại (đã có ranker/alias sẵn)
    "Điện thoại", "Laptop", "Tivi", "Nồi cơm điện", "Lò vi sóng",
    "Quạt các loại", "Máy lọc nước", "Máy hút bụi gia đình", "Bếp điện",
    "Loa, Tai nghe",
)

_SYSTEM_PROMPT = (
    "Bạn là bộ trích xuất nhu cầu mua ĐIỆN MÁY (mọi ngành hàng, không chỉ máy lạnh). Đọc "
    "tin nhắn tiếng Việt của khách và trả về DUY NHẤT một object JSON, không giải thích, "
    "không markdown. Các khóa:\n"
    '  "category": tên ngành hàng hoặc null. Chọn đúng 1 trong: '
    + " | ".join(KNOWN_CATEGORIES) + " (vd 'máy lạnh'->\"Máy lạnh\", 'điện thoại/dt'->"
    '"Điện thoại", \'tủ lạnh\'->"Tủ lạnh", \'laptop\'->"Laptop"). Không rõ -> null.\n'
    '  "budget_max": số nguyên VND hoặc null (vd "dưới 20 triệu" -> 20000000)\n'
    '  "budget_min": số nguyên VND hoặc null\n'
    '  "usage": chuỗi ngắn hoàn cảnh/người dùng hoặc null (vd "cho trẻ em", "phòng ngủ", '
    '"chơi game", "gia đình 4 người")\n'
    '  "brands": mảng tên hãng hoặc [] (vd ["Daikin"], ["Samsung"])\n'
    '  "priority": "quiet"|"fast_cooling"|"energy_saving"|"price"|null (chỉ dùng cho máy lạnh: '
    "ít ồn->quiet, lạnh nhanh->fast_cooling, tiết kiệm điện->energy_saving, giá rẻ->price)\n"
    '  "area_m2": số m² hoặc null (CHỈ máy lạnh, vd "phòng 18m2" -> 18)\n'
    '  "room_type": "bedroom"|"living_room"|null (chỉ máy lạnh)\n'
    '  "sunny": true|false|null (chỉ máy lạnh, phòng nắng/hướng tây -> true)\n'
    '  "inverter_required": true|false|null (chỉ máy lạnh/tủ lạnh/máy giặt)\n'
    '  "household_size": số người dùng hoặc null (tủ lạnh/máy giặt/máy sấy/máy rửa chén/'
    'máy nước nóng, vd "nhà 4 người" -> 4)\n'
    '  "capacity_liters": số lít hoặc null (tủ đông, tủ mát, vd "300 lít" -> 300)\n'
    '  "battery_priority": true|false|null (đồng hồ thông minh/máy tính bảng: "pin trâu"/'
    '"pin lâu" -> true. KHÔNG bịa dung lượng pin mAh)\n'
    '  "portability_priority": true|false|null (micro/máy tính bảng: "nhỏ gọn"/"dễ mang" -> true)\n'
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


def _coerce_int(v: Any) -> int | None:
    """Số nguyên dương (số người dùng), chấp cả chuỗi "4 người" -> 4."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if v > 0 else None
    if isinstance(v, str):
        m = re.search(r"\d+", v)
        return int(m.group(0)) if m and int(m.group(0)) > 0 else None
    return None


def _coerce_priority_flag(v: Any) -> bool | None:
    """Slot ưu tiên định tính (pin lâu / nhỏ gọn): "high"/"trâu"/"có" -> True.
    KHÔNG suy ra số liệu cụ thể (mAh, gram) — chỉ tín hiệu định tính."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("high", "true", "yes", "có", "co", "trâu", "trau", "lâu", "lau", "gọn", "gon"):
            return True
        if s in ("low", "false", "no", "không", "khong"):
            return False
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


def _coerce_category(v: Any) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip().lower()
    for cat in KNOWN_CATEGORIES:
        if cat.lower() in s or s in cat.lower():
            return cat
    # loose aliases
    aliases = {"điện thoại": "Điện thoại", "smartphone": "Điện thoại", "dt": "Điện thoại",
               "điều hòa": "Máy lạnh", "máy tính": "Laptop", "tablet": "Máy tính bảng",
               "tv": "Tivi", "loa": "Loa, Tai nghe", "tai nghe": "Loa, Tai nghe"}
    for k, cat in aliases.items():
        if k in s:
            return cat
    return None


def _coerce_str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def coerce_profile(obj: dict[str, Any]) -> NeedProfile:
    """Validate/coerce a raw JSON dict into a NeedProfile. Unknown/invalid -> None."""
    return NeedProfile(
        category=_coerce_category(obj.get("category")),
        budget_max=_coerce_price(obj.get("budget_max")),
        budget_min=_coerce_price(obj.get("budget_min")),
        area_m2=_coerce_area(obj.get("area_m2")),
        usage=_coerce_str(obj.get("usage")),
        room_type=_coerce_enum(obj.get("room_type"), ROOM_TYPES),
        sunny=_coerce_bool(obj.get("sunny")),
        priority=_coerce_enum(obj.get("priority"), PRIORITIES),
        inverter_required=_coerce_bool(obj.get("inverter_required")),
        brands=_coerce_brands(obj.get("brands")),
        household_size=_coerce_int(obj.get("household_size")),
        capacity_liters=_coerce_area(obj.get("capacity_liters")),
        battery_priority=_coerce_priority_flag(obj.get("battery_priority")),
        portability_priority=_coerce_priority_flag(obj.get("portability_priority")),
    )


_PROFILE_FIELDS = ("category", "budget_max", "budget_min", "area_m2", "usage", "room_type",
                   "sunny", "priority", "inverter_required", "brands",
                   "household_size", "capacity_liters", "battery_priority", "portability_priority",
                   "factor_priorities")

# list-valued profile slots merge like `brands`: a non-empty new value wins, else keep prior
# (so factor choices from a prior turn survive when the follow-up doesn't re-send them).
_LIST_SLOTS = ("brands", "factor_priorities")


def merge_profiles(prior: NeedProfile, new: NeedProfile) -> NeedProfile:
    """Carry slots across turns: the new turn's value wins, else keep the prior.

    If the category changes, we reset all slots to avoid carrying over incompatible
    category-specific slots (e.g., area_m2 from Máy lạnh to Điện thoại).
    """
    if prior.category is not None and new.category is not None and prior.category != new.category:
        return new

    out: dict[str, Any] = {}
    for f in _PROFILE_FIELDS:
        nv, pv = getattr(new, f), getattr(prior, f)
        if f in _LIST_SLOTS:
            out[f] = nv if nv else pv
        else:
            out[f] = nv if nv is not None else pv
    return NeedProfile(**out)


def required_slots(_profile: NeedProfile) -> tuple[str, ...]:
    """Choose-factors flow: only the category is hard-required. Budget became a
    consideration factor (thấp/TB/cao) and the old per-ngành slots (diện tích, số
    người…) are now optional refinements the user can express via factor choices —
    so we no longer block the turn on them. `_LEGACY_REQUIRED_SLOTS` keeps the old
    behavior available for callers/tests that still want strict slot-filling."""
    return ("category",)


def legacy_required_slots(profile: NeedProfile) -> tuple[str, ...]:
    """Pre-choose-factors strict slots (category + budget + per-ngành extra)."""
    extra = CATEGORY_SLOT_SCHEMA.get(profile.category or "", ())
    return ("category", "budget_max", *extra)


def missing_slots(profile: NeedProfile) -> list[str]:
    """Required slots that are still null (drive hỏi-ngược follow-ups)."""
    return [s for s in required_slots(profile) if getattr(profile, s) is None]


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
    # Few-shot + segment guidelines are OPTIONAL enrichment (Qdrant/vector_db). Import and
    # call inside one guard so NLU still works if qdrant_client/vector_db is unavailable.
    # Live-verify finding: on a cold process, Qdrant's local storage.sqlite (125MB) takes
    # ~15-17s to mmap/open on first use, and even warm the LlamaIndex retrieval path costs
    # ~3s — either one alone can blow the <5s turn SLA for what is purely optional prompt
    # enrichment. Cap it with a hard deadline (FEW_SHOT_TIMEOUT) via a worker thread so a
    # slow/cold vector store degrades to "no enrichment" instead of stalling the whole turn.
    few_shot_str = ""
    guideline = ""
    lower = text.lower()
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

        def _lookup():
            from antigravity.vector_db import search_few_shots
            from antigravity.few_shot import get_segment_guidelines_prompt, get_few_shot_prompt
            fs = get_few_shot_prompt(search_few_shots(text, limit=2))
            seg = ("Máy lạnh" if ("máy lạnh" in lower or "điều hòa" in lower)
                   else "Tủ lạnh" if "tủ lạnh" in lower
                   else "Laptop" if "laptop" in lower
                   else "Pc, máy in" if ("pc" in lower or "máy tính" in lower)
                   else None)
            gl = get_segment_guidelines_prompt(seg) if seg else ""
            return fs, gl

        # NOT a `with` block on purpose: ThreadPoolExecutor.__exit__ calls shutdown(wait=True),
        # which would block until the slow/cold lookup finishes anyway — defeating the
        # timeout. shutdown(wait=False) lets this turn move on; the orphaned thread just
        # finishes in the background and its result is discarded.
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            few_shot_str, guideline = ex.submit(_lookup).result(timeout=FEW_SHOT_TIMEOUT)
        finally:
            ex.shutdown(wait=False)
    except _FutTimeout:
        pass  # cold/slow vector store -> skip enrichment this turn, never block on it
    except Exception:
        pass

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
        from antigravity.model_hub import hub
        raw = hub.call_agent(
            "nlu", messages, model=model, max_tokens=256, temperature=0.0, timeout=timeout,
            response_format={"type": "json_object"},
        )
        obj = _parse_json(raw)
    except (fpt_client.FPTError, json.JSONDecodeError):
        empty = NeedProfile()
        return empty, missing_slots(empty), None

    profile = coerce_profile(obj)
    return profile, missing_slots(profile), obj


# category_name -> ranker. Only aircon + phone have a dedicated engine so far; other
# categories fall through to CATEGORY_RANKER.get(cat) is None -> handled by caller
# (vector rerank only, no code ranking yet — see docs/capability_architecture.md).
CATEGORY_RANKER = {"Máy lạnh": "aircon", "Điện thoại": "phone"}


@dataclass
class _SimpleResult:
    """Uniform result shape so build_chat_response doesn't care which ranker ran."""
    items: list[Any]
    relaxations: list[str]


def _phone_need_from_profile(profile: NeedProfile):
    from antigravity.phone_ranking import PHONE_PRIORITIES, PhoneNeed
    # aircon priority vocab ("quiet"/"fast_cooling"/...) only "price" overlaps phone's
    # vocab; anything else -> no phone priority (weights stay balanced, never guessed).
    prio = profile.priority if profile.priority in PHONE_PRIORITIES else None
    return PhoneNeed(budget_max=profile.budget_max, budget_min=profile.budget_min,
                     priority=prio, brands=list(profile.brands))


def advise(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    prior_profile: dict[str, Any] | None = None, pool: int | None = None,
) -> dict[str, Any]:
    """Full turn: extract -> merge prior slots -> ask-if-missing -> rank (category-routed).

    `prior_profile` (dict from the previous turn's response) carries slots forward so a
    follow-up answer doesn't drop earlier needs. Returns a dict:
      {"status": "need_info", "profile": {...}, "missing": [...], "questions": [...]}
      {"status": "ok",        "profile": {...}, "result": <items+relaxations>}
    Ranking is routed by `profile.category`: "Máy lạnh" -> rank_top (aircon engine),
    "Điện thoại" -> phone_ranking.rank_phones. Other categories have no dedicated ranker
    yet — they return empty items (no-results terminal) rather than silently misranking
    with the wrong engine.
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

    result = _rank_profile(profile, records=records, n=n, pool=pool)
    return {"status": "ok", "profile": profile_dict, "result": result, "raw_llm": raw}


def _rank_profile(profile: NeedProfile, *, records: list[dict[str, Any]] | None = None,
                  n: int = 3, pool: int | None = None) -> Any:
    """Route a fully-resolved profile to its ranking engine and return a result with
    `.items` + `.relaxations`. Shared by advise() and the choose-factors flow so both
    rank identically. `profile.factor_priorities` flows into each engine's weights."""
    ranker = CATEGORY_RANKER.get(profile.category or "")
    if ranker == "phone":
        from antigravity import phone_ranking
        phone_records = records if records is not None else phone_ranking.load_default_records()
        items = phone_ranking.rank_phones(_phone_need_from_profile(profile), phone_records, n=n)
        return _SimpleResult(items=items, relaxations=[])
    if ranker == "aircon":
        # aircon engine reads profile.factor_priorities directly in _weights()
        return rank_top(profile, records=records, n=n, pool=pool)
    if profile.category:
        # Generic fallback engine: grounded price/rating/popularity signals. Chosen
        # factor weight_keys that this engine has (rating/popularity/price) boost here.
        from antigravity import generic_ranking
        gen_records = records if records is not None else \
            generic_ranking.load_category_records(profile.category)
        need = generic_ranking.GenericNeed(
            budget_max=profile.budget_max, budget_min=profile.budget_min,
            priority=profile.priority, brands=list(profile.brands),
            factor_priorities=list(profile.factor_priorities or []))
        items = generic_ranking.rank_generic(need, gen_records, n=n)
        return _SimpleResult(items=items, relaxations=[])
    # no category resolved at all -> honest empty, never a wrong-engine guess
    return _SimpleResult(items=[], relaxations=[])


# --------------------------------------------------------------------------- #
# API-facing response builder (stable JSON contract for POST /api/chat)
# --------------------------------------------------------------------------- #
def _item_to_dict(it: Any) -> dict[str, Any]:
    """Serialize a ranked item (aircon RankedItem or phone PhoneItem) for the API.

    Numbers come only from the record. Rankers differ in shape (phone has no image/
    quantity_sold/promotion/missing_data fields), so this dispatches on the concrete
    dataclass rather than assuming aircon's RankedItem everywhere.
    """
    if isinstance(it, RankedItem):
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
    # PhoneItem (phone_ranking) — same contract, fields it doesn't track go None/[]
    return {
        "product_id": it.product_id,
        "name": it.name,
        "brand": it.brand,
        "image": None,
        "url": it.url,
        "price": it.price,
        "rating": it.rating,
        "quantity_sold": None,
        "promotion": None,
        "reasons": it.reasons,
        "breakdown": it.breakdown,
        "missing_data": [],
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


def _build_chat_response_raw(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    explain: bool = True, prior_profile: dict[str, Any] | None = None,
    selected_products: list[dict[str, Any]] | None = None,
    chosen_factors: list[str] | None = None,
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

    # --- else: recommendation / choose-factors path (C1..C5) ---
    from antigravity import factors as _factors, decision as _decision

    # Extract needs ONCE (category, budget, brands…), then merge prior-turn slots and
    # apply this turn's factor choices. Doing it here (not via advise) keeps the flow to a
    # single LLM extraction even though we gate on the profile before ranking.
    profile, _m, raw = extract_need_profile(text, history, timeout=timeout)
    if prior_profile:
        profile = merge_profiles(NeedProfile(**prior_profile), profile)
    if chosen_factors and profile.category:
        profile = _factors.apply_factor_choices(profile, profile.category, chosen_factors)
    profile_dict = vars(profile)

    base: dict[str, Any] = {
        "query": text,
        "profile": profile_dict,
        "questions": [],
        "items": [],
        "relaxations": [],
        "explanation": None,
        "safety_checked": True,
    }

    # (1) category still unknown -> ask which product (the only hard-required slot now)
    if profile.category is None:
        base["mode"] = "need_info"
        base["questions"] = [FOLLOWUP_QUESTIONS["category"]]
        base["message"] = FOLLOWUP_QUESTIONS["category"]
        return base

    # (2) category known, factors defined, none chosen yet -> present the 4 factors
    #     (3-layer language + A/B/C/D). Skip straight to ranking if the user already
    #     picked (factor_priorities carried in profile) or sent choices this turn.
    if (_factors.has_factors(profile.category) and not profile.factor_priorities
            and not chosen_factors):
        payload = _factors.choose_factors_payload(profile.category)
        base["mode"] = "choose_factors"
        base["message"] = payload["message"]
        base["factors"] = payload["factors"]
        base["room_context"] = payload["room_context"]
        return base

    # (3) rank with the chosen factors' weight boosts
    use_reranker = os.environ.get("USE_RERANKER", "1").strip().lower() not in ("0", "false", "no")
    pool = max(n, 8) if use_reranker else None
    # over-fetch a bit more so the dominance/near-tie decision has a real pool to judge
    rank_n = max(n, 6)
    result: RankResult = _rank_profile(profile, records=records, n=rank_n, pool=pool)
    rerank_query = _cmp.priority_rerank_query(text, text)
    base["mode"] = "recommendation"
    pool_items = [_item_to_dict(it) for it in result.items]
    # SERVICE stage: bge-reranker reorders the code-approved pool by semantic relevance to
    # the raw query. Keep the fuller pool (rank_n) so the decision layer can still judge
    # dominance vs near-tie; falls back to code order on any failure.
    ranked_items = (_rerank_items(rerank_query, pool_items, rank_n, timeout)
                    if use_reranker else pool_items[:rank_n])
    base["relaxations"] = result.relaxations

    # DECISION: 1 dominant product vs 3 near-equal trade-offs, judged on the chosen factors.
    cat_factors = _factors.factors_for(profile.category)
    dec = _decision.decide(ranked_items, cat_factors, chosen_factors or [])
    base["items"] = dec["items"][:n] if dec["kind"] != "single" else dec["items"]
    base["decision"] = {"kind": dec["kind"], "confirm": dec.get("confirm", False)}

    if not base["items"]:
        # no-results terminal (guardrail code_rules.no_results_terminal): never fabricate
        base["message"] = ("Chưa có sản phẩm phù hợp với tiêu chí này. "
                           "Bạn thử nới ngân sách hoặc diện tích nhé.")
    else:
        if dec["kind"] == "single":
            base["message"] = "Sản phẩm này nổi trội hẳn theo ưu tiên của bạn — em gợi ý luôn:"
        elif dec["kind"] == "tradeoff":
            base["message"] = ("Có vài lựa chọn cân bằng (trade-off không lớn) — anh/chị "
                               "xem và chốt giúp em nhé:")
        else:
            base["message"] = "Đây là Top gợi ý phù hợp nhất với nhu cầu của bạn:"
        if result.relaxations:
            base["message"] += " (đã nới nhẹ tiêu chí: " + ", ".join(result.relaxations) + ")"
        if explain:
            from antigravity.explainer import explain_top
            # z.ai glm-5.2 (Call B) measures ~6s; give it headroom so the grounded
            # trade-off prose actually renders instead of silently degrading. Slightly
            # over the <5s target — switch EXPLAIN_PROVIDER=fpt (gemma ~2.6s) if the SLA
            # must hold hard. On any failure explain_top returns None and the per-item
            # reasons[] still carry the grounding.
            explanation = explain_top(base["items"], profile, query=text, timeout=8.0)
            # VERIFY half of grounded generation: even a grounded prompt can drift a
            # number. Check every money/spec figure the LLM wrote against the real numbers
            # from the ranked items + slots; on any unverified value drop the prose back to
            # the deterministic per-item reasons[] (same fail-safe as an explainer error).
            # Env-gated (default on) so it can be turned off for debugging: CLAIM_GUARD=0.
            if explanation and os.environ.get("CLAIM_GUARD", "1").strip().lower() not in ("0", "false", "no"):
                from antigravity.claim_verifier import verify_explanation
                vr = verify_explanation(explanation, base["items"], profile)
                if not vr.ok:
                    import logging
                    logging.getLogger(__name__).warning(
                        "claim guard dropped explanation; unverified=%s", vr.unverified)
                    explanation = None
            base["explanation"] = explanation
    return base


def build_chat_response(
    text: str, history: list[dict[str, str]] | None = None, *,
    records: list[dict[str, Any]] | None = None, n: int = 3, timeout: float = 3.0,
    explain: bool = True, prior_profile: dict[str, Any] | None = None,
    selected_products: list[dict[str, Any]] | None = None,
    chosen_factors: list[str] | None = None,
) -> dict[str, Any]:
    from antigravity.guardrails import check_input_safety, check_output_safety

    # 1. Run Input Guardrails
    safety_resp = check_input_safety(text)
    if safety_resp is not None:
        return safety_resp

    # 2. Run Normal Advisor Logic
    res = _build_chat_response_raw(
        text, history, records=records, n=n, timeout=timeout,
        explain=explain, prior_profile=prior_profile,
        selected_products=selected_products, chosen_factors=chosen_factors
    )

    # 3. Run Output Guardrails on the advisor messages
    if "message" in res and res["message"]:
        res["message"] = check_output_safety(res["message"])
    if "explanation" in res and res["explanation"]:
        res["explanation"] = check_output_safety(res["explanation"])

    return res
