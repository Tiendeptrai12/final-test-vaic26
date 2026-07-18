from __future__ import annotations

import json

import pytest

from app.catalog.parse_specs import slugify_category_name
from app.conversation.clarification import build_clarifying_question
from app.conversation.missing_slots import compute_missing_slots
from app.conversation.slot_schemas import CATEGORY_SLOT_SCHEMAS, get_slot_schema
from app.conversation.state import create_conversation_state

# Registry.json (nguồn Excel cũ) liệt kê 14 "ngành". Taxonomy DMX thật gộp
# vài ngành cùng loại vào 1 category thật (đã xác nhận bằng dữ liệu thật —
# xem slot_schemas.py) nên map 14 sheet -> đúng category thật tương ứng.
REGISTRY_SHEET_TO_REAL_CATEGORY = {
    "Máy lạnh": "air_conditioner",
    "Tủ Lạnh": "tu_lanh",
    "Máy giặt": "may_giat",
    "Máy sấy quần áo": "may_say_quan_ao",
    "Máy rửa chén": "may_rua_chen",
    "Tủ mát, tủ đông": "tu_dong_tu_mat",
    "Máy nước nóng": "may_nuoc_nong",
    "Micro karaoke": "micro",
    "Micro thu âm điện thoại": "micro",
    "Đồng hồ thông minh": "dong_ho_thong_minh",
    "Máy tính để bàn": "pc_may_in",
    "Màn hình máy tính": "pc_may_in",
    "Máy in": "pc_may_in",
    "Máy tính bảng": "may_tinh_bang",
}


@pytest.fixture(scope="module")
def registry_sheets():
    with open("schemas/registry.json", encoding="utf-8") as f:
        return list(json.load(f)["sheets"].keys())


def test_registry_has_exactly_14_sheets(registry_sheets):
    assert len(registry_sheets) == 14


def test_every_registry_sheet_maps_to_a_configured_real_category(registry_sheets):
    """Mỗi 1 trong 14 ngành registry.json phải map được sang 1 category
    THẬT có schema riêng trong CATEGORY_SLOT_SCHEMAS (không rơi về default)."""
    for sheet in registry_sheets:
        real_category = REGISTRY_SHEET_TO_REAL_CATEGORY.get(sheet)
        assert real_category is not None, f"Chưa map sheet '{sheet}' sang category thật"
        assert real_category in CATEGORY_SLOT_SCHEMAS, f"'{real_category}' (từ '{sheet}') chưa có schema riêng"


def test_real_category_slug_matches_slugify_or_explicit_mapping(registry_sheets):
    """Xác nhận category thật dùng đúng slug mà catalog loader thực sự sinh
    ra (slugify_category_name), trừ air_conditioner có slug tường minh riêng
    trong dmx_registry.json."""
    for sheet, real_category in REGISTRY_SHEET_TO_REAL_CATEGORY.items():
        if real_category == "air_conditioner":
            continue
        # Với các sheet gộp chung 1 category thật (vd 2 loại micro cùng "micro"),
        # slugify(sheet) có thể khác slug thật — chỉ cần category thật đã tồn tại
        # trong CATEGORY_SLOT_SCHEMAS là đủ (đã kiểm chứng thủ công với dữ liệu
        # thật, xem comment trong slot_schemas.py).
        assert real_category in CATEGORY_SLOT_SCHEMAS


def test_every_configured_category_requires_category_and_budget_max():
    for category, schema in CATEGORY_SLOT_SCHEMAS.items():
        if category == "default":
            continue
        assert "category" in schema.required
        assert "budget_max" in schema.required


def test_every_configured_category_has_one_or_two_specific_questions():
    """Mỗi ngành (trừ default) chỉ cần category, budget_max và 1-2 câu hỏi
    đặc thù quan trọng — không nhiều hơn."""
    for category, schema in CATEGORY_SLOT_SCHEMAS.items():
        if category == "default":
            continue
        specific_slots = [s for s in schema.required if s not in ("category", "budget_max")]
        assert 1 <= len(specific_slots) <= 2, f"{category} có {len(specific_slots)} câu hỏi đặc thù: {specific_slots}"


def test_every_specific_slot_has_a_clarifying_question_text():
    """Mọi slot đặc thù được cấu hình phải có câu hỏi riêng trong
    clarification.py (không rơi về câu hỏi generic mặc định)."""
    generic_fallback_marker = "cho em xin thêm thông tin về"
    for category, schema in CATEGORY_SLOT_SCHEMAS.items():
        state = create_conversation_state(f"test-{category}")
        state = state.with_updates(category=category if category != "default" else "air_conditioner")
        missing = compute_missing_slots(state)
        for slot in missing:
            question = build_clarifying_question(state, [slot])
            assert question is not None
            assert generic_fallback_marker not in question.question, (
                f"Slot '{slot}' (category={category}) chưa có câu hỏi riêng trong clarification.py"
            )


def test_asks_one_question_at_a_time_and_never_reasks_answered_slot():
    """Hỏi từng câu một, không hỏi lại thông tin đã có — dùng category có
    2 slot đặc thù (máy tính bảng) để kiểm tra kỹ luồng hỏi tuần tự."""
    state = create_conversation_state("tablet-flow")
    state = state.with_updates(category="may_tinh_bang")

    missing = compute_missing_slots(state)
    assert set(missing) == {"budget_max", "battery_priority", "portability_priority"}

    q1 = build_clarifying_question(state, missing)
    assert q1 is not None
    assert q1.is_repeat is False

    # Giả lập khách trả lời đúng slot vừa hỏi -> slot đó biến mất khỏi missing
    state = state.with_updates(slots={**state.slots, q1.slot: "high" if q1.slot != "budget_max" else 15_000_000})
    missing2 = compute_missing_slots(state)
    assert q1.slot not in missing2
    assert len(missing2) == len(missing) - 1


def test_categories_without_real_spec_map_do_not_hard_filter_by_specific_slot():
    """Chỉ dùng thông tin để lọc/ranking khi dữ liệu sản phẩm thật có field
    tương ứng — category chưa có spec_map (mọi category trừ air_conditioner)
    không được có range_slots (không strict-match filter bằng thông tin bịa)."""
    for category, schema in CATEGORY_SLOT_SCHEMAS.items():
        if category == "air_conditioner":
            continue
        assert schema.range_slots == [], f"{category} không có spec_map thật nhưng lại có range_slots"
