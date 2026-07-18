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

# Call B (grounded prose) runs on z.ai glm-5.2 via NVIDIA integrate — teammate's key.
# Call A (NLU, fast JSON) stays on FPT gemma. Split uses both team keys where each fits.
# On any z.ai failure the caller falls back to deterministic code reasons[], so a turn
# never blocks. Override via EXPLAIN_MODEL / EXPLAIN_PROVIDER env if needed.
EXPLAIN_MODEL = os.environ.get("EXPLAIN_MODEL", "z-ai/glm-5.2")
EXPLAIN_PROVIDER = os.environ.get("EXPLAIN_PROVIDER", "zai")

_SYSTEM = (
    "Bạn là tư vấn viên máy lạnh của Điện Máy Xanh. Bạn nhận một danh sách sản phẩm ĐÃ được "
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
    model: str = EXPLAIN_MODEL, provider: str = EXPLAIN_PROVIDER,
    timeout: float = 4.0, max_tokens: int = 320,
) -> str | None:
    """Return grounded VN trade-off prose for the Top-N, or None on any failure.

    None => caller keeps the deterministic per-item reasons[] (graceful degrade).
    """
    if not items:
        return None
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _facts_block(items, profile)},
    ]
    try:
        text = fpt_client.chat_completion(
            model, messages, max_tokens=max_tokens, temperature=0.3, timeout=timeout,
            provider=provider,
        )
    except fpt_client.FPTError:
        return None
    text = (text or "").strip()
    return text or None
