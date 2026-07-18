"""
catalog/dmx_registry.py — nạp `schemas/dmx_registry.json` (do BTC cung cấp),
mô tả cách map field thô của DMX (`products_detail.json`) sang field canonical
+ cách parse từng spec_key theo category.

Đây là nguồn cấu hình DUY NHẤT cho việc parse catalog DMX trong production —
không hardcode tên field/category nào trong code loader. dmx_registry.json
hiện chỉ có `spec_map` chi tiết cho category "Máy lạnh" (các category khác
sẽ được BTC bổ sung dần — xem field `_note`); category chưa có spec_map vẫn
nạp được đầy đủ field cấp 1 (giá, tên, brand...) và giữ nguyên spec thô,
chỉ là chưa lọc/rank được theo thông số kỹ thuật chi tiết.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.catalog.parse_specs import (
    clean_str,
    parse_btu,
    parse_inverter,
    parse_kwh,
    parse_noise_reading,
    parse_quantity_sold,
    parse_range_generic,
    parse_rating,
    parse_year,
    price_to_int,
    slugify_category_name,
)

DMX_SCHEMAS_DIR_NAME = "schemas"


class DmxRegistryError(Exception):
    """Raise khi dmx_registry.json thiếu hoặc cấu trúc không khớp mong đợi —
    KHÔNG được âm thầm bỏ qua hay tự suy diễn cấu hình."""


@dataclass(frozen=True)
class DmxSpecFieldMapping:
    source_key: str  # tên spec_key thô trong products_detail.json (vd "Phạm vi làm lạnh hiệu quả")
    target_keys: list[str]  # 1 hoặc nhiều field canonical được sinh ra
    parser: str  # tên parser, dispatch qua PARSER theo SINGLE/MULTI bên dưới


@dataclass(frozen=True)
class DmxCategoryConfig:
    category_name_vn: str  # "Máy lạnh"
    slug: str  # "air_conditioner"
    spec_map: list[DmxSpecFieldMapping]
    eligible_for_demo_rule: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class DmxRegistry:
    top_level_mapping: dict[str, Any]
    effective_price_rule: str
    categories: dict[str, DmxCategoryConfig]  # key = category_name_vn

    def category_config(self, category_name_vn: str) -> DmxCategoryConfig | None:
        return self.categories.get(category_name_vn)

    def slug_for(self, category_name_vn: str) -> str:
        cfg = self.categories.get(category_name_vn)
        if cfg:
            return cfg.slug
        return slugify_category_name(category_name_vn)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DmxRegistryError(message)


@lru_cache(maxsize=1)
def load_dmx_registry(path=None) -> DmxRegistry:
    from app.config.settings import DMX_REGISTRY_PATH

    registry_path = path or DMX_REGISTRY_PATH
    if not registry_path.exists():
        raise DmxRegistryError(
            f"Không tìm thấy dmx_registry.json tại {registry_path}. "
            "Đây là file cấu hình bắt buộc để nạp catalog DMX — không thể tự suy diễn mapping."
        )

    with open(registry_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    _require("top_level_mapping" in raw, "dmx_registry.json thiếu 'top_level_mapping'.")
    _require("categories" in raw, "dmx_registry.json thiếu 'categories'.")

    categories: dict[str, DmxCategoryConfig] = {}
    for name_vn, cfg in raw["categories"].items():
        _require("slug" in cfg, f"category '{name_vn}' trong dmx_registry.json thiếu 'slug'.")
        spec_map = []
        for source_key, mapping in cfg.get("spec_map", {}).items():
            _require(
                "keys" in mapping and "parser" in mapping,
                f"spec_map['{source_key}'] của category '{name_vn}' thiếu 'keys' hoặc 'parser'.",
            )
            spec_map.append(DmxSpecFieldMapping(source_key=source_key, target_keys=mapping["keys"], parser=mapping["parser"]))

        categories[name_vn] = DmxCategoryConfig(
            category_name_vn=name_vn,
            slug=cfg["slug"],
            spec_map=spec_map,
            eligible_for_demo_rule=cfg.get("eligible_for_demo"),
            note=cfg.get("note"),
        )

    return DmxRegistry(
        top_level_mapping=raw["top_level_mapping"],
        effective_price_rule=raw.get("effective_price", ""),
        categories=categories,
    )


# --- Parser dispatch — thuần dựa trên TÊN parser khai báo trong JSON, không
#     hardcode category nào. Thêm category mới dùng lại 1 trong các parser
#     này (hoặc thêm parser mới ở đây) mà KHÔNG cần sửa loader. ---

SINGLE_VALUE_PARSERS = {
    "parse_btu": parse_btu,
    "parse_inverter": parse_inverter,
    "parse_year": parse_year,
    "parse_kwh": parse_kwh,
    "clean_str": clean_str,
    "parse_rating": parse_rating,
    "parse_quantity_sold": parse_quantity_sold,
    "price_to_int": price_to_int,
}

MULTI_VALUE_PARSERS = {
    "parse_area": lambda raw: ((r.min, r.max) if (r := parse_range_generic(raw)) else (None, None)),
    "parse_noise": lambda raw: (
        (n.indoor_min_db, n.indoor_max_db, n.outdoor_db) if (n := parse_noise_reading(raw)) else (None, None, None)
    ),
}


def apply_spec_field_mapping(mapping: DmxSpecFieldMapping, raw_value: Any) -> dict[str, Any]:
    if len(mapping.target_keys) == 1 and mapping.parser in SINGLE_VALUE_PARSERS:
        return {mapping.target_keys[0]: SINGLE_VALUE_PARSERS[mapping.parser](raw_value)}

    if mapping.parser in MULTI_VALUE_PARSERS:
        values = MULTI_VALUE_PARSERS[mapping.parser](raw_value)
        return dict(zip(mapping.target_keys, values))

    raise DmxRegistryError(
        f"Parser '{mapping.parser}' không được hỗ trợ (spec field '{mapping.source_key}'). "
        "Thêm parser này vào SINGLE_VALUE_PARSERS/MULTI_VALUE_PARSERS trong app/catalog/dmx_registry.py."
    )
