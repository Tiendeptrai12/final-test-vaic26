"""
server.py — FastAPI, giữ NGUYÊN API contract của backend Node cũ
(`POST /api/conversation/message`, `GET /api/conversation/{id}/state`,
`POST /api/conversation/{id}/reset`) để frontend (đã viết sẵn, gọi JSON
field cụ thể như `data.status`, `data.reply`, `data.items`...) chạy được
mà không cần sửa gì.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.catalog.catalog_store import get_catalog
from app.conversation import nlu_lexicon
from app.conversation.clarification import choose_next_slot_to_ask
from app.conversation.missing_slots import compute_missing_slots
from app.conversation.nlu_prompt import build_nlu_prompt
from app.conversation.state import ConversationState, create_conversation_state
from app.conversation.turn import process_turn
from app.explanation.llm_factory import get_default_llm
from app.pipeline import AdviceResult, advise_for_state

logger = logging.getLogger("ai_product_advisor")

app = FastAPI(title="AI Product Advisor API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_sessions: dict[str, ConversationState] = {}

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.on_event("startup")
async def _warm_up_on_startup() -> None:
    """Warm-up catalog (đọc + parse products_detail.json 1 lần, thay vì để
    request đầu tiên gánh chi phí này) và LLM client (get_default_llm() đã
    cache bằng @lru_cache — dựng sẵn HTTP client 1 lần). Không chặn khởi
    động app nếu thiếu API key (dev/test không có .env)."""
    try:
        get_catalog()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog_warmup_failed exception_type=%s", type(exc).__name__)
    try:
        get_default_llm()
    except Exception as exc:  # noqa: BLE001 — thiếu API key khi dev/test -> bỏ qua, không crash startup
        logger.warning("llm_warmup_skipped exception_type=%s", type(exc).__name__)


def _get_or_create_session(session_id: str) -> ConversationState:
    if session_id not in _sessions:
        _sessions[session_id] = create_conversation_state(session_id)
    return _sessions[session_id]


def _sanitize_state(state: ConversationState) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "category": state.category,
        "slots": state.slots,
        "missing_slots": compute_missing_slots(state),
        "asked_slots": state.asked_slots,
        "rejected_fields": state.rejected_fields,
        "turn_count": state.turn_count,
    }


def _format_item(item: dict) -> dict:
    return {
        "product_id": item.get("product_id"),
        "model_code": item.get("model_code"),
        "name": item.get("name"),
        "brand": item.get("brand"),
        "image": item.get("image"),
        "url": item.get("url"),
        "effective_price": item.get("effective_price"),
        "headline": item.get("headline"),
        "pros": item.get("pros") or [],
        "cons": item.get("cons") or [],
        "recommendation_reason": item.get("recommendation_reason"),
        "matched_reasons": item.get("matched_reasons") or [],
        "tradeoffs": item.get("tradeoffs") or [],
        "missing_data": item.get("missing_data") or [],
        "data_source": item.get("data_source") or {"product_id": item.get("product_id"), "model_code": item.get("model_code"), "url": item.get("url")},
        "llm_explanation_missing": bool(item.get("llm_explanation_missing")),
    }


def _format_ranking(ranking) -> dict | None:
    if not ranking or not getattr(ranking, "results", None):
        return None
    return {
        "results": [
            {
                "rank": r.get("rank"),
                "product_id": r.get("product_id"),
                "model_code": r.get("model_code"),
                "name": r.get("name"),
                "brand": r.get("brand"),
                "image": r.get("image"),
                "url": r.get("url"),
                "effective_price": r.get("effective_price"),
                "total_score": r.get("total_score"),
                "matched_reasons": r.get("matched_reasons"),
                "tradeoffs": r.get("tradeoffs"),
                "data_source": {"product_id": r.get("product_id"), "model_code": r.get("model_code"), "url": r.get("url")},
            }
            for r in ranking.results
        ]
    }


def _build_reply_text(result: AdviceResult) -> str:
    if result.status == "blocked":
        return result.message or "Không có nội dung giải thích hợp lệ sau kiểm tra guardrail. Xin vui lòng thử lại."
    reply = result.summary or "Dưới đây là các sản phẩm phù hợp nhất với nhu cầu của bạn:"
    if result.status == "corrected" and result.corrections:
        reply += f" (⚠️ {len(result.corrections)} thông tin đã được sửa bởi hệ thống kiểm tra để đảm bảo chính xác)"
    return reply


def _build_api_response(session_id: str, state: ConversationState, result: AdviceResult) -> dict[str, Any]:
    base = {"session_id": session_id, "state": _sanitize_state(state)}

    if result.status == "not_ready":
        return {**base, "status": "not_ready", "reply": "Chưa đủ thông tin để tư vấn. Vui lòng cung cấp thêm.", "missing_slots": result.missing_slots or []}

    if result.status == "no_results":
        return {**base, "status": "no_results", "reply": result.message or "Rất tiếc, không tìm thấy sản phẩm phù hợp với yêu cầu của bạn trong catalog hiện tại."}

    if result.status == "llm_error":
        return {**base, "status": "llm_error", "reply": "Đã xảy ra lỗi khi gọi AI diễn giải. Dưới đây là kết quả xếp hạng thuần túy từ dữ liệu thật.", "error": result.message, "ranking": _format_ranking(result.ranking)}

    if result.status == "llm_parse_error":
        return {**base, "status": "llm_parse_error", "reply": "AI trả kết quả không đúng định dạng. Dưới đây là kết quả xếp hạng thuần từ dữ liệu thật.", "ranking": _format_ranking(result.ranking)}

    return {
        **base,
        "status": result.status,
        "reply": _build_reply_text(result),
        "summary": result.summary or None,
        "items": [_format_item(i) for i in (result.items or [])],
        "corrections": result.corrections or [],
        "rejected_items": result.rejected_items or [],
        "validation_status": result.status,
        "ranking_meta": {
            "total_scored": len(result.ranking.results) if result.ranking and result.ranking.results else 0,
            "relaxed_steps": (result.ranking.relaxed_steps if result.ranking else []) or [],
        }
        if result.ranking
        else None,
    }


class MessageRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/conversation/message")
async def post_message(body: MessageRequest):
    if not body.session_id or not body.message:
        raise HTTPException(status_code=400, detail="Thiếu session_id hoặc message.")

    state = _get_or_create_session(body.session_id)
    missing_slots = compute_missing_slots(state)

    known_categories = None
    try:
        known_categories = get_catalog().keys()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog_lookup_failed stage=nlu exception_type=%s", type(exc).__name__)

    # Slot vừa được hỏi ở lượt trước (nếu có) — dùng để diễn giải đúng câu
    # trả lời NGẮN (vd "4" cho household_size, "có"/"không" cho slot ưu
    # tiên) mà không cần gọi FPT.
    expected_slot_choice = choose_next_slot_to_ask(state, missing_slots)
    expected_slot = expected_slot_choice.slot if expected_slot_choice else None

    # 1) Chạy dict/regex tất định TRƯỚC — không tốn thời gian gọi mạng.
    raw_extraction: dict[str, Any] = nlu_lexicon.parse_message_deterministic(
        body.message, known_categories=known_categories, expected_slot=expected_slot
    )

    # 2) CHỈ gọi FPT-AI khi dict/regex "không hiểu" — tức là KHÔNG trích
    #    được field nào HOẶC vẫn chưa xác định được category trong khi
    #    category vẫn còn thiếu (raw_extraction có field khác không có
    #    nghĩa là category đã được giải quyết — phải tiếp tục nhận diện
    #    category, không dừng lại chỉ vì raw_extraction khác rỗng).
    #    Đây là lời gọi FPT DUY NHẤT được phép dùng cho request này; nếu
    #    dùng ở đây, giai đoạn giải thích bên dưới sẽ KHÔNG gọi FPT nữa.
    still_missing_category = state.category is None and "category" not in raw_extraction
    llm_call_used_for_nlu = False
    if not raw_extraction or still_missing_category:
        llm_call_used_for_nlu = True
        try:
            llm = get_default_llm()
            system, user = build_nlu_prompt(state, missing_slots, body.message)
            completion = llm.complete(f"{system}\n\n{user}")
            stripped = re.sub(r"^```json\s*|^```\s*|```\s*$", "", completion.text.strip(), flags=re.IGNORECASE | re.MULTILINE)
            llm_extraction = json.loads(stripped.strip())
            # Gộp thêm vào kết quả tất định đã có (nếu có) thay vì ghi đè
            # toàn bộ — giữ lại field dict/regex đã chắc chắn nhận diện được.
            raw_extraction = {**llm_extraction, **raw_extraction} if raw_extraction else llm_extraction
        except Exception as exc:  # noqa: BLE001 — FPT lỗi/chậm/JSON sai -> vẫn tiếp tục, không chết request
            logger.warning("nlu_llm_call_failed stage=nlu_extraction exception_type=%s", type(exc).__name__)

    turn = process_turn(state, raw_extraction)
    state = turn.state
    _sessions[body.session_id] = state

    if turn.status == "need_clarification":
        return {
            "session_id": body.session_id,
            "status": "need_clarification",
            "reply": turn.clarifying_question.question if turn.clarifying_question else "Vui lòng cung cấp thêm thông tin.",
            "clarifying_question": (
                {"slot": turn.clarifying_question.slot, "question": turn.clarifying_question.question, "is_repeat": turn.clarifying_question.is_repeat}
                if turn.clarifying_question
                else None
            ),
            "state": _sanitize_state(state),
        }

    try:
        llm = get_default_llm()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # 3) Giai đoạn giải thích: nếu NLU đã dùng hết ngân sách 1 lần gọi FPT,
    #    bỏ qua LLM hoàn toàn (skip_llm=True) — dùng ngay lời giải thích tạo
    #    từ matched_reasons/tradeoffs. Ngược lại, advise_for_state() tự gọi
    #    FPT đúng 1 lần và tự fallback nội bộ nếu FPT lỗi/timeout/JSON sai
    #    (xem pipeline.py) — tổng cộng KHÔNG BAO GIỜ vượt quá 1 lần gọi FPT.
    result = advise_for_state(state, llm=llm, skip_llm=llm_call_used_for_nlu)
    _sessions[body.session_id] = state
    return _build_api_response(body.session_id, state, result)


@app.get("/api/conversation/{session_id}/state")
async def get_state(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session không tồn tại.")
    return {"session_id": session_id, "state": _sanitize_state(_sessions[session_id])}


@app.post("/api/conversation/{session_id}/reset")
async def reset_session(session_id: str):
    _sessions[session_id] = create_conversation_state(session_id)
    return {"session_id": session_id, "status": "reset", "state": _sanitize_state(_sessions[session_id])}


# Mount SAU CÙNG (sau mọi route /api/...) — index.html dùng đường dẫn tương
# đối ("style.css", "app.js" ở cùng cấp), nên phải mount ở "/" với html=True
# để "/" trả về index.html và "/style.css", "/app.js" được phục vụ đúng vị
# trí frontend mong đợi, mà không che các route /api/... đã đăng ký trước.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
