"""Phase 4: LLM explainer (Call B of the flow) — grounded Top-3 trade-off prose.

Pipeline seam:  extract -> filter -> rank -> [EXPLAIN top-3 (grounded)]

Anti-hallucination by construction: the LLM is fed ONLY the numbers already computed
by the ranking engine (brand, price, noise dB, energy, area fit, inverter) as a compact
FACTS block, and is instructed to use nothing else. Prices/specs are never invented — they
come from the catalog via rank_top. On any FPT failure the caller falls back to the
deterministic code `reasons[]`, so a turn never blocks on the explainer.
"""
from __future__ import annotations

import os
from typing import Any

from antigravity import fpt_client
from antigravity.aircon_ranking import NeedProfile

# Call B (grounded trade-off prose) = the reasoning step, so it runs on the BRAIN model:
# GLM-5.2 (z.ai's model), but served via FPT infra with thinking DISABLED. Measured:
#   - GLM-5.2 on z.ai/NVIDIA endpoint: 7-19s (infra-bound) -> blows the <5s SLA
#   - GLM-5.2 on FPT + enable_thinking=false: ~1.6-2s, grounded prose -> holds SLA
# So same brain, faster endpoint, one key. FPT is otherwise the service tier (NLU gemma,
# bge-reranker/embeddings). To force the raw z.ai/NVIDIA endpoint instead (slower, richer),
# set EXPLAIN_PROVIDER=zai + EXPLAIN_MODEL=z-ai/glm-5.2. On any failure -> per-item reasons[].
_DEFAULT_MODELS = {"fpt": "GLM-5.2", "zai": "z-ai/glm-5.2"}
EXPLAIN_PROVIDER = os.environ.get("EXPLAIN_PROVIDER", "fpt")
EXPLAIN_MODEL = os.environ.get("EXPLAIN_MODEL") or _DEFAULT_MODELS.get(EXPLAIN_PROVIDER, "GLM-5.2")

# GLM is a reasoning model: without this it spends the whole token budget "thinking" and
# returns empty content (finish_reason=length). Disabling thinking makes it answer directly.
_GLM_NOTHINK = {"chat_template_kwargs": {"enable_thinking": False}}

# Hard cap for the optional "quy tắc ứng xử/pháp lý" rules lookup (Qdrant + local Vietnamese
# correction model). Live-verify measured this alone taking 22-169s cold (unauthenticated HF
# Hub model download) with no timeout — capped tight since it's pure enrichment, never core.
RULES_LOOKUP_TIMEOUT = 0.5

def _system_prompt(category: str | None) -> str:
    """Category-aware system prompt. Defaults to a generic 'điện máy' advisor so a fridge/
    TV/laptop turn is not mislabeled as a máy lạnh consult (the engine is now multi-category)."""
    role = f"tư vấn viên {category}" if category else "tư vấn viên điện máy"
    return (
        f"Bạn là {role} của Điện Máy Xanh. Bạn nhận một danh sách sản phẩm ĐÃ được "
        "hệ thống lọc và xếp hạng, kèm số liệu. Nhiệm vụ: viết đoạn tư vấn tiếng Việt ngắn gọn, "
        "tự nhiên, SO SÁNH ưu/nhược (trade-off) giữa các lựa chọn và nói rõ nên chọn cái nào cho "
        "nhu cầu của khách.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- CHỈ dùng đúng số liệu được cung cấp. TUYỆT ĐỐI không bịa giá, thông số, khuyến mãi, tồn kho.\n"
        "- Không có dữ liệu cho một mục nào đó thì không nhắc tới, không suy đoán.\n"
        "- Không bịa tên model/URL. Xưng hô lịch sự, 3-5 câu, không markdown, không bullet."
    )


def _facts_block(items: list[dict[str, Any]], profile: NeedProfile) -> str:
    """Compact grounded facts the LLM may use — nothing outside this can be stated."""
    lines: list[str] = []
    need: list[str] = []
    if profile.budget_max:
        need.append(f"ngân sách tối đa {profile.budget_max/1_000_000:.0f} triệu")
    if profile.area_m2:
        need.append(f"phòng {profile.area_m2:g}m²")
    if profile.priority:
        need.append(f"ưu tiên {profile.priority}")
    if profile.room_type:
        need.append(profile.room_type)
    lines.append("NHU CẦU KHÁCH: " + (", ".join(need) or "chưa rõ"))
    lines.append("SẢN PHẨM (đã xếp hạng, dùng đúng các số này):")
    for i, it in enumerate(items, 1):
        s = it.get("spec") or {}
        parts = [f"#{i} {it.get('brand') or it.get('product_id')}"]
        if it.get("price") is not None:
            parts.append(f"giá {it['price']/1_000_000:.1f} triệu")
        if s.get("indoor_noise_min_db") is not None:
            parts.append(f"độ ồn {s['indoor_noise_min_db']:g} dB")
        if s.get("cspf") is not None:
            parts.append(f"CSPF {s['cspf']:g}")
        elif s.get("energy_stars") is not None:
            parts.append(f"{s['energy_stars']:g} sao năng lượng")
        if s.get("area_min_m2") is not None and s.get("area_max_m2") is not None:
            parts.append(f"hợp phòng {s['area_min_m2']:g}-{s['area_max_m2']:g}m²")
        if s.get("inverter") is True:
            parts.append("Inverter")
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def explain_top(
    items: list[dict[str, Any]], profile: NeedProfile, *,
    query: str | None = None,
    model: str = EXPLAIN_MODEL, provider: str = EXPLAIN_PROVIDER,
    timeout: float = 4.0, max_tokens: int = 320,
) -> str | None:
    """Return grounded VN trade-off prose for the Top-N, or None on any failure.

    None => caller keeps the deterministic per-item reasons[] (graceful degrade).
    """
    if not items:
        return None

    # Live-verify finding: search_rules() (vector_db) triggers correct_text()'s lazy HF model
    # load (bmd1905/vietnamese-correction-v2, unauthenticated Hub) with NO timeout — measured
    # 22s-169s cold, alone blowing the <5s SLA. Same class of bug as the Call A few-shot
    # lookup; capped the same way: hard deadline via a worker thread, fail-open on timeout.
    rules_block = ""
    search_query = query
    if not search_query and items:
        brands = {it.get("brand") for it in items if it.get("brand")}
        if brands:
            search_query = " ".join(brands)
    if search_query:
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

            def _rules_lookup():
                from antigravity.vector_db import search_rules
                return search_rules(search_query, limit=2)

            ex = ThreadPoolExecutor(max_workers=1)
            try:
                rules = ex.submit(_rules_lookup).result(timeout=RULES_LOOKUP_TIMEOUT)
            finally:
                ex.shutdown(wait=False)  # don't block on a cold/slow lookup; let it die in bg
            if rules:
                rules_block = "\n\nQUY TẮC ỨNG XỬ/PHÁP LÝ BẮT BUỘC:\n" + "\n".join(f"- {r}" for r in rules)
        except _FutTimeout:
            pass
        except Exception:
            pass

    system_content = _system_prompt(getattr(profile, "category", None)) + rules_block
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": _facts_block(items, profile)},
    ]
    try:
        from antigravity.model_hub import hub
        text = hub.call_agent(
            "explainer", messages, model=model, max_tokens=max_tokens, temperature=0.3, timeout=timeout,
            provider=provider
        )
    except fpt_client.FPTError:
        return None
    text = (text or "").strip()
    return text or None
