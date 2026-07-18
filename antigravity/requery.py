"""Requery agent — two-pass rewriter (spec: antigravity/.agents/requery_agent/SKILL.md).

Pass 1 (inbound): messy Vietnamese -> clean LLM-friendly query + the user's own words.
Pass 2 (outbound): grounded pipeline result -> natural Vietnamese answer that reuses the
user's words and states the technical source/reasons behind the pick.

FPT has no dedicated NLP-rewrite model, so both passes are a generative LLM. Both fail OPEN:
on any error the turn continues with the original text / existing message. This agent rewrites
LANGUAGE, never FACTS — prices/specs/Top-3 come only from the code pipeline.
"""
from __future__ import annotations

import json
from typing import Any

from antigravity import fpt_client

INBOUND_MODEL = "gemma-4-26B-A4B-it"   # fast; only normalizes
OUTBOUND_MODEL = "gemma-4-31B-it"      # natural VN prose

_INBOUND_SYSTEM = (
    "Bạn là bộ chuẩn hoá câu hỏi mua điện máy. Viết lại tin nhắn tiếng Việt của khách thành "
    "MỘT câu hỏi rõ ràng, dễ cho hệ thống hiểu, KHÔNG đổi nghĩa và KHÔNG thêm thông tin khách "
    "chưa nói (đừng tự bịa ngân sách, diện tích, hãng). Mở rộng viết tắt (đh->điều hòa, "
    "tr/triệu->số tiền, m2->m²), sửa lỗi gõ. Giữ nguyên từ tiếng Anh nếu khách dùng. "
    'Trả về DUY NHẤT JSON: {"rewritten_query": "...", "user_terms": ["..."]}. '
    "user_terms = các từ đáng chú ý khách đã dùng (để trả lời echo lại)."
)

_OUTBOUND_SYSTEM = (
    "Bạn là tư vấn viên Điện Máy Xanh. Viết lại kết quả (đã có sẵn số liệu) thành câu trả lời "
    "tiếng Việt tự nhiên, thân thiện. YÊU CẦU:\n"
    "- Dùng lại chính từ ngữ khách đã dùng cho gần gũi.\n"
    "- Nêu rõ LÝ DO/NGUỒN kỹ thuật vì sao chọn (giá, độ ồn dB, diện tích phù hợp, tiêu thụ "
    "điện, đánh giá, đã bán) — chỉ dùng đúng số được cung cấp, TUYỆT ĐỐI không bịa.\n"
    "- Thiếu dữ liệu thì nói 'chưa có dữ liệu', không suy đoán.\n"
    "- Tối đa tiếng Việt. Chỉ giữ tiếng Anh khi: quá phổ thông (inverter, laptop, wifi), quá "
    "chuyên ngành không có từ Việt (CSPF, BTU, OLED), khách yêu cầu tiếng Anh, hoặc khách đã "
    "dùng từ đó. 3-6 câu, lịch sự, không markdown, không bullet."
)


def rewrite_inbound(text: str, *, timeout: float = 2.0) -> dict[str, Any]:
    """Pass 1. Return {"rewritten_query", "user_terms"}. Fails open to the original text."""
    fallback = {"rewritten_query": text, "user_terms": []}
    if not text or not text.strip():
        return fallback
    messages = [
        {"role": "system", "content": _INBOUND_SYSTEM},
        {"role": "user", "content": text},
    ]
    try:
        raw = fpt_client.chat_completion(
            INBOUND_MODEL, messages, max_tokens=256, temperature=0.0, timeout=timeout,
            response_format={"type": "json_object"},
        )
        obj = json.loads(raw)
    except (fpt_client.FPTError, json.JSONDecodeError, TypeError):
        return fallback
    if not isinstance(obj, dict):
        return fallback
    rq = obj.get("rewritten_query")
    terms = obj.get("user_terms")
    return {
        "rewritten_query": rq if isinstance(rq, str) and rq.strip() else text,
        "user_terms": [str(t) for t in terms] if isinstance(terms, list) else [],
    }


def _facts_for_response(items: list[dict[str, Any]]) -> str:
    """Compact grounded facts the outbound rewrite may use — nothing beyond this."""
    lines = []
    for i, it in enumerate(items, 1):
        s = it.get("spec") or {}
        parts = [f"#{i} {it.get('name') or it.get('brand') or it.get('product_id')}"]
        if it.get("price") is not None:
            parts.append(f"giá {it['price']/1_000_000:.1f} triệu")
        if it.get("rating") is not None:
            parts.append(f"đánh giá {it['rating']}/5")
        for r in (it.get("reasons") or [])[:4]:
            parts.append(str(r))
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def naturalize_response(
    user_message: str, items: list[dict[str, Any]], *,
    user_terms: list[str] | None = None, fallback_message: str = "",
    timeout: float = 4.0,
) -> str:
    """Pass 2. Grounded items -> natural Vietnamese answer. Fails open to fallback_message."""
    if not items:
        return fallback_message
    ctx = (
        f"Tin nhắn khách: {user_message}\n"
        f"Từ khách hay dùng: {', '.join(user_terms or [])}\n"
        f"Sản phẩm đã chọn (dùng đúng số này):\n{_facts_for_response(items)}"
    )
    messages = [
        {"role": "system", "content": _OUTBOUND_SYSTEM},
        {"role": "user", "content": ctx},
    ]
    try:
        text = fpt_client.chat_completion(
            OUTBOUND_MODEL, messages, max_tokens=400, temperature=0.3, timeout=timeout,
        )
    except fpt_client.FPTError:
        return fallback_message
    text = (text or "").strip()
    return text or fallback_message
