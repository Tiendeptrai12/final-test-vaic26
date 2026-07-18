"""C8 Teach — side-branch concept explainer (locked logic).

Rules (see docs/capability_architecture.md, Scenario E):
  - Only fires on an explicit teach request (router INTENT_TEACH). Never auto-routes into
    Search/Rank.
  - Bare concept ("Inverter là gì?"): return a SHORT definition NOW, then offer to tie it to
    the user's purchase.
  - Decision form ("có đáng trả thêm cho Inverter không?"): needs the product spec + budget;
    if missing, ask for those two before concluding — no definition dump.

Definitions come from a CURATED Vietnamese glossary (grounded, $0) so we never hallucinate a
concept. Unknown terms return an honest "chưa có giải thích", not a made-up one.
"""
from __future__ import annotations

import re
from typing import Any

# term -> (định nghĩa ngắn, khi nào đáng quan tâm). Curated, không để LLM bịa.
GLOSSARY: dict[str, dict[str, str]] = {
    "inverter": {
        "aliases": r"inverter|biến\s*tần",
        "vi": "Công nghệ điều chỉnh công suất máy nén liên tục thay vì bật/tắt, giúp tiết "
              "kiệm điện và chạy êm hơn.",
        "matters": "Đáng khi bạn dùng nhiều giờ mỗi ngày — tiền điện tiết kiệm bù lại giá cao hơn.",
    },
    "btu": {
        "aliases": r"\bbtu\b",
        "vi": "Đơn vị công suất làm lạnh của máy lạnh. Số càng lớn làm lạnh càng khỏe "
              "(9000 BTU ≈ 1 HP, hợp phòng ~15m²).",
        "matters": "Quan trọng để chọn công suất đúng diện tích phòng.",
    },
    "hp": {
        "aliases": r"\bhp\b|ngựa|mã\s*lực",
        "vi": "Cách gọi công suất máy lạnh theo 'ngựa'. 1 HP ≈ 9000 BTU, hợp phòng nhỏ ~15m².",
        "matters": "Chọn HP theo diện tích: phòng càng lớn cần HP càng cao.",
    },
    "cspf": {
        "aliases": r"\bcspf\b",
        "vi": "Chỉ số hiệu suất năng lượng theo mùa của máy lạnh. Càng cao càng tiết kiệm điện.",
        "matters": "So sánh CSPF giữa các máy để biết máy nào tốn ít điện hơn.",
    },
    "ram": {
        "aliases": r"\bram\b",
        "vi": "Bộ nhớ tạm giúp máy chạy nhiều ứng dụng cùng lúc mượt mà. RAM lớn = đa nhiệm tốt.",
        "matters": "Đáng khi bạn chơi game nặng / mở nhiều app; dùng cơ bản thì 8GB là đủ.",
    },
    "refresh": {
        "aliases": r"tần\s*số\s*quét|\bhz\b|refresh\s*rate",
        "vi": "Số lần màn hình làm mới mỗi giây (Hz). 120Hz mượt hơn 60Hz khi lướt/chơi game.",
        "matters": "Đáng nếu bạn quan tâm độ mượt; xem phim/dùng cơ bản thì 60–90Hz đủ.",
    },
    "mah": {
        "aliases": r"\bmah\b|dung\s*lượng\s*pin",
        "vi": "Dung lượng pin. Số càng lớn pin càng lâu hết (5000mAh dùng ~1 ngày, 7000mAh trâu hơn).",
        "matters": "Đáng nếu bạn đi cả ngày ít sạc.",
    },
    "oled": {
        "aliases": r"\boled\b|\bamoled\b",
        "vi": "Loại màn hình cho màu sâu, đen thật và tiết kiệm điện hơn LCD/IPS.",
        "matters": "Đáng nếu bạn xem phim / quan tâm chất lượng hình.",
    },
}

_WORTH_RE = re.compile(r"có\s*đáng|đáng\s*(trả\s*thêm|tiền|mua|không)|nên\s*trả\s*thêm|"
                       r"bỏ\s*thêm\s*tiền", re.IGNORECASE)


def detect_term(text: str) -> str | None:
    low = (text or "").lower()
    for term, info in GLOSSARY.items():
        if re.search(info["aliases"], low):
            return term
    return None


def is_worth_it_question(text: str) -> bool:
    """Decision-form teach ('có đáng trả thêm cho X?') — needs product + budget context."""
    return bool(_WORTH_RE.search((text or "").lower()))


def teach(
    text: str, *, has_product: bool = False, has_budget: bool = False,
) -> dict[str, Any]:
    """Side-branch teach response. Never enters the recommendation pipeline.

    Returns {mode:"teach", term, definition|None, message, needs_context[]}.
    """
    term = detect_term(text)
    info = GLOSSARY.get(term or "")

    # Decision form: requires product spec + budget, else ask for exactly those.
    if is_worth_it_question(text):
        missing = [k for k, ok in (("mặt hàng/model", has_product), ("ngân sách", has_budget))
                   if not ok]
        if missing:
            return {
                "mode": "teach", "term": term, "definition": info["vi"] if info else None,
                "needs_context": missing,
                "message": (f"Để nói {('về ' + term) if term else 'điều này'} có đáng với bạn "
                            f"không, mình cần biết: {', '.join(missing)}. Bạn cho mình xin nhé?"),
            }
        # has context -> short def + hand back to advise (caller decides worth-it grounded)
        return {
            "mode": "teach", "term": term,
            "definition": info["vi"] if info else None, "needs_context": [],
            "message": ((info["vi"] + " " + info["matters"]) if info
                        else "Mình sẽ đánh giá dựa trên máy và ngân sách của bạn."),
        }

    # Bare concept: short definition NOW + offer to tie into a purchase.
    if info:
        return {
            "mode": "teach", "term": term, "definition": info["vi"], "needs_context": [],
            "message": (f"{info['vi']} {info['matters']} "
                        "Bạn đang xem sản phẩm nào để mình tư vấn có nên chọn tiêu chí này không?"),
        }

    # Unknown concept — honest, never fabricate a definition.
    return {
        "mode": "teach", "term": None, "definition": None, "needs_context": [],
        "message": "Mình chưa có sẵn giải thích cho khái niệm này. Bạn mô tả rõ hơn giúp mình nhé?",
    }
