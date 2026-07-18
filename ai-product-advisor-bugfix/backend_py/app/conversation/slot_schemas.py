"""
conversation/slot_schemas.py — 2 loại cấu hình tách biệt nhưng liên quan:

1. SlotSchema: slot nào cần HỎI KHÁCH HÀNG cho từng category (Module 1).
2. RangeSlotConfig: slot đó khớp với TRƯỜNG NÀO trong `spec` của sản phẩm
   và khớp bằng cách nào (Module 2 lọc, Module 3 chấm điểm).

Tách biệt 2 khái niệm này vì "budget_max" luôn là slot hỏi khách, nhưng
"room_area_m2" chỉ áp dụng cho air_conditioner, "household_size" áp dụng
cho refrigerator/washing_machine/dryer với TÊN SLOT GIỐNG NHAU nhưng field
nguồn trong spec khác nhau tuỳ category — cấu hình hoá để không phải viết
lại hàm riêng cho từng category (đây chính là điểm sửa so với bản Node cũ,
nơi category lạ bị rơi vào nhánh ranking của máy lạnh).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RangeKind = Literal["two_field", "text_range", "text_number_tolerance"]


@dataclass(frozen=True)
class RangeSlotConfig:
    slot_name: str
    kind: RangeKind
    # two_field: (min_spec_key, max_spec_key) — đã có sẵn 2 field số trong spec
    min_spec_key: str | None = None
    max_spec_key: str | None = None
    # text_range: 1 field string dạng "X - Y đơn vị", parse_range_generic lúc truy vấn
    spec_key: str | None = None
    # text_number_tolerance: 1 field string chỉ có 1 con số (vd dung tích),
    # coi là khớp nếu giá trị khách yêu cầu nằm trong [value*lo, value*hi]
    tolerance_lo: float = 0.7
    tolerance_hi: float = 1.5
    label: str = ""


@dataclass(frozen=True)
class SlotSchema:
    required: list[str]
    optional: list[str] = field(default_factory=list)
    range_slots: list[RangeSlotConfig] = field(default_factory=list)


# Slot chung cho MỌI category (không riêng ngành nào) — "brand" (thương
# hiệu ưu tiên, vd "Panasonic") là field CÓ THẬT trong dữ liệu sản phẩm
# (product["brand"]) nên lọc được an toàn, không phải suy diễn/bịa thông số.
_COMMON_OPTIONAL_SLOTS = ["budget_min", "brand"]

_DEFAULT_SCHEMA = SlotSchema(
    required=["category", "budget_max"],
    # battery_priority/portability_priority/use_case: soft preference định
    # tính (vd "pin trâu", "mỏng nhẹ", "để đi học") — áp dụng chung cho mọi
    # category chưa có schema riêng (laptop, tablet, smartphone...), KHÔNG
    # bắt buộc hỏi, chỉ lưu lại nếu khách tự nhắc tới.
    optional=[*_COMMON_OPTIONAL_SLOTS, "battery_priority", "portability_priority", "use_case"],
)

# ---------------------------------------------------------------------------
# CATEGORY_SLOT_SCHEMAS — đủ 14 ngành theo schemas/registry.json.
#
# QUAN TRỌNG: registry.json (nguồn Excel cũ) dùng slug riêng của nó (vd
# "refrigerator", "washing_machine"...) nhưng catalog PRODUCTION thật
# (products_detail.json, qua dmx_registry.json) dùng slug tự sinh từ đúng
# tên category tiếng Việt thật (vd "tu_lanh", "may_giat" — xem
# app/catalog/parse_specs.slugify_category_name). Muốn category thật sự
# được nhận diện, CATEGORY_SLOT_SCHEMAS PHẢI dùng đúng slug DMX thật, không
# phải slug cũ của registry.json — nếu không, get_slot_schema() sẽ không
# bao giờ khớp và category đó âm thầm rơi về _DEFAULT_SCHEMA.
#
# Ngoài ra, taxonomy DMX thật GỘP một vài ngành trong 14 ngành cũ vào cùng
# 1 category thật (không bịa ra category không tồn tại):
#   - "Micro karaoke" + "Micro thu âm điện thoại"        -> "micro" (1 category thật)
#   - "Máy tính để bàn" + "Màn hình máy tính" + "Máy in"  -> "pc_may_in" (1 category thật)
# Nên 14 ngành trong registry.json ánh xạ vào ĐÚNG 11 category thật
# (air_conditioner + 10 category dưới đây).
#
# `schemas/dmx_registry.json` hiện CHỈ có `spec_map` chi tiết (field số đã
# parse) cho "Máy lạnh". Các category khác dưới đây có slot hỏi khách (vd
# household_size, capacity_liters) nhưng CHƯA có RangeSlotConfig tương ứng
# — giá trị slot chỉ được lưu vào state làm context cho LLM, KHÔNG dùng để
# strict-match filter (đúng yêu cầu "không bịa thông số"). Khi BTC bổ sung
# spec_map cho category nào trong dmx_registry.json, chỉ cần thêm
# RangeSlotConfig tương ứng ở đây — không cần sửa code khác.
#
# Cấu hình dạng dict (category thật -> slot đặc thù cần hỏi), KHÔNG viết
# nhiều if/else theo category.
# ---------------------------------------------------------------------------

# category thật (DMX) -> 1-2 slot đặc thù cần hỏi thêm ngoài category+budget_max
_EXTRA_REQUIRED_SLOTS_BY_CATEGORY: dict[str, list[str]] = {
    "tu_lanh": ["household_size"],  # Tủ Lạnh
    "may_giat": ["household_size"],  # Máy giặt
    "may_say_quan_ao": ["household_size"],  # Máy sấy quần áo
    "may_rua_chen": ["household_size"],  # Máy rửa chén
    "tu_dong_tu_mat": ["capacity_liters"],  # Tủ mát, tủ đông
    "may_nuoc_nong": ["household_size"],  # Máy nước nóng
    "micro": ["portability_priority"],  # Micro karaoke + Micro thu âm điện thoại (gộp)
    "dong_ho_thong_minh": ["battery_priority"],  # Đồng hồ thông minh
    "pc_may_in": ["use_case"],  # Máy tính để bàn + Màn hình máy tính + Máy in (gộp)
    "may_tinh_bang": ["battery_priority", "portability_priority"],  # Máy tính bảng
}

CATEGORY_SLOT_SCHEMAS: dict[str, SlotSchema] = {
    # Máy lạnh — category thật duy nhất hiện có spec_map chi tiết (deep-parse)
    "air_conditioner": SlotSchema(
        required=["category", "budget_max", "room_area_m2", "installation_location"],
        optional=[*_COMMON_OPTIONAL_SLOTS, "noise_priority", "power_saving_priority", "sun_exposure"],
        range_slots=[
            RangeSlotConfig(
                slot_name="room_area_m2",
                kind="two_field",
                min_spec_key="area_min_m2",
                max_spec_key="area_max_m2",
                label="diện tích phòng",
            ),
        ],
    ),
    "default": _DEFAULT_SCHEMA,
}

# Sinh 10 schema còn lại từ bảng cấu hình dict phía trên — KHÔNG if/else lặp
# lại cho từng category; mỗi category chỉ khác nhau ở list slot đặc thù.
for _category, _extra_slots in _EXTRA_REQUIRED_SLOTS_BY_CATEGORY.items():
    CATEGORY_SLOT_SCHEMAS[_category] = SlotSchema(
        required=["category", "budget_max", *_extra_slots],
        optional=list(_COMMON_OPTIONAL_SLOTS),
    )


def get_slot_schema(category: str | None) -> SlotSchema:
    if category and category in CATEGORY_SLOT_SCHEMAS:
        return CATEGORY_SLOT_SCHEMAS[category]
    return _DEFAULT_SCHEMA

