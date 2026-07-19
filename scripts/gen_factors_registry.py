"""Generate antigravity/factors_registry.json — the per-category "yếu tố cân nhắc"
(consideration factors) that drive the simplified choose-factors flow.

Each category exposes MAX 4 factors. A factor carries 3 language layers:
  spec_label   (tầng 1: thông số thô)      — "dung tích lớn (>=400L)"
  simple_label (tầng 2: feature dễ hiểu)    — "đủ cho 4 người ăn"
  contextual   (tầng 3: ngữ cảnh/lifestyle) — ["gia đình lớn", "ký túc xá", ...]

Design note: the 3-layer language is EDITORIAL, so it lives hand-authored in
FACTOR_HINTS below (this is the deliverable content, not something safely
auto-derivable). This script's job is mechanical:
  1. validate every factor's spec_fields actually exist in schemas/registry.json
     (so a factor never references a field the catalog can't have);
  2. fill the budget-tier factor's quartile numbers from the price-segment table
     (few_shot.load_price_segments — Moc_Phan_Khuc quartiles q25/q50/q75);
  3. optionally enrich layer-c from the room-classification workbook vocabulary;
  4. emit antigravity/factors_registry.json (re-runnable; hand-edit the editorial
     layers after generation).

Run:  python -m scripts.gen_factors_registry
Idempotent — re-run any time specs/quartiles change, then eyeball the diff.

weight_key maps a factor onto an existing ranking-engine weight so the chosen
factor boosts the right dimension:
  aircon engine (Máy lạnh):  price | noise | energy | capacity
  generic engine (others):   price | popularity | rating
For generic categories the spec_fields + threshold still let decision.py parse
the raw spec string for the dominance test even when the ranker can only weight
price/popularity/rating (documented limitation).
"""
from __future__ import annotations

import collections
import json
import os
import sys
from typing import Any

# repo root on path so this runs both as -m and directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REGISTRY_PATH = os.path.join("schemas", "registry.json")
OUT_PATH = os.path.join("antigravity", "factors_registry.json")
ROOM_XLSX = "d:/download/DMX_phan_loai_san_pham_theo_phong1 (1).xlsx"

# Map the category_name the NLU/NeedProfile uses -> the registry category_code,
# so we can validate spec_fields against the right sheet. (NLU names differ
# slightly from registry sheet names, e.g. "Tủ lạnh" vs sheet "Tủ Lạnh".)
CATEGORY_CODE = {
    "Máy lạnh": "air_conditioner",
    "Tủ lạnh": "refrigerator",
    "Máy giặt": "washing_machine",
    "Máy sấy quần áo": "dryer",
    "Máy rửa chén": "dishwasher",
    "Máy nước nóng": "water_heater",
    "Tủ đông, tủ mát": "freezer",
    "Máy tính bảng": "tablet",
    "Đồng hồ thông minh": "smartwatch",
    "Micro": "phone_mic",   # phone_mic sheet has the richest spec set
    "Máy tính để bàn": "desktop_pc",
    "Màn hình máy tính": "monitor",
    "Máy in": "printer",
}

# Price-segment table keys these Vietnamese names; map NLU name -> segment name.
SEGMENT_NAME = {
    "Máy lạnh": "Máy lạnh",
    "Tủ lạnh": "Tủ lạnh",
    "Máy tính để bàn": "Pc, máy in",
    "Máy in": "Pc, máy in",
    "Màn hình máy tính": "Pc, máy in",
    "Laptop": "Laptop",
}

# The universal budget factor (added to every category). Quartile numbers filled
# in by the script; A/B/C/D options = thấp / trung bình / cao (+ tuỳ chọn).
BUDGET_FACTOR = {
    "id": "budget",
    "budget_tier": True,
    "weight_key": "price",
    "spec_fields": ["effective_price"],
    "higher_better": False,
    "spec_label": "Ngân sách (phân khúc giá)",
    "simple_label": "Chọn mức giá phù hợp túi tiền",
    "contextual": ["tiết kiệm", "cân đối", "đầu tư lâu dài"],
}

# --------------------------------------------------------------------------- #
# Hand-authored 3-layer factors per category (max 3 spec-factors; budget is +1).
# spec_fields MUST be real registry keys (validated below).
# --------------------------------------------------------------------------- #
FACTOR_HINTS: dict[str, list[dict[str, Any]]] = {
    "Máy lạnh": [
        {"id": "quiet", "weight_key": "noise", "spec_fields": ["indoor_noise_min_db"],
         "higher_better": False, "threshold": {"op": "<=", "value": 25, "unit": "dB"},
         "spec_label": "Độ ồn thấp (≤25 dB)", "simple_label": "Chạy rất êm khi ngủ",
         "contextual": ["phòng ngủ", "phòng em bé", "làm việc khuya"]},
        {"id": "energy_saving", "weight_key": "energy", "spec_fields": ["cspf", "energy_stars"],
         "higher_better": True, "threshold": {"op": ">=", "value": 5, "unit": "CSPF"},
         "spec_label": "Tiết kiệm điện (CSPF cao / Inverter)", "simple_label": "Hoá đơn điện thấp",
         "contextual": ["dùng nhiều giờ/ngày", "gia đình tiết kiệm", "phòng bật cả ngày"]},
        {"id": "capacity", "weight_key": "capacity", "spec_fields": ["area_min_m2", "area_max_m2"],
         "higher_better": True, "threshold": {"op": ">=", "value": 20, "unit": "m²"},
         "spec_label": "Công suất lớn (phòng rộng)", "simple_label": "Làm lạnh nhanh phòng lớn",
         "contextual": ["phòng khách", "phòng > 20m²", "phòng nắng hướng tây"]},
    ],
    "Tủ lạnh": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["dung_tich_su_dung", "dung_tich_tong", "so_nguoi_su_dung"],
         "higher_better": True, "threshold": {"op": ">=", "value": 400, "unit": "L"},
         "spec_label": "Dung tích lớn (≥400L)", "simple_label": "Đủ trữ đồ cho 4+ người ăn",
         "contextual": ["gia đình đông", "ký túc xá", "tủ lạnh chung công ty"]},
        {"id": "energy_saving", "weight_key": "popularity", "spec_fields": ["dien_nang_tieu_thu", "energy_saving_technology"],
         "higher_better": False, "threshold": {"op": "<=", "value": 400, "unit": "kWh/năm"},
         "spec_label": "Tiết kiệm điện (Inverter)", "simple_label": "Chạy cả năm tốn ít điện",
         "contextual": ["dùng 24/7", "gia đình tiết kiệm", "hoá đơn điện thấp"]},
        {"id": "compact", "weight_key": "popularity", "spec_fields": ["dung_tich_su_dung", "so_nguoi_su_dung"],
         "higher_better": False, "threshold": {"op": "<=", "value": 200, "unit": "L"},
         "spec_label": "Nhỏ gọn (≤200L)", "simple_label": "Vừa cho 1-2 người, ít chiếm chỗ",
         "contextual": ["ở trọ", "sinh viên", "phòng nhỏ / văn phòng"]},
    ],
    "Máy giặt": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["khoi_luong_tai_chinh", "so_nguoi_su_dung"],
         "higher_better": True, "threshold": {"op": ">=", "value": 10, "unit": "kg"},
         "spec_label": "Khối lượng giặt lớn (≥10kg)", "simple_label": "Giặt được nhiều/mền lớn",
         "contextual": ["gia đình đông", "giặt chăn ga", "giặt ít lần/tuần"]},
        {"id": "energy_saving", "weight_key": "popularity", "spec_fields": ["dien_nang_tieu_thu", "inverter_type"],
         "higher_better": False, "threshold": {"op": "<=", "value": 60, "unit": "kWh/năm"},
         "spec_label": "Inverter tiết kiệm điện nước", "simple_label": "Bền, êm, tốn ít điện nước",
         "contextual": ["dùng lâu dài", "chung cư yên tĩnh", "tiết kiệm chi phí"]},
        {"id": "spin_speed", "weight_key": "popularity", "spec_fields": ["toc_do_quay_vat_toi_da"],
         "higher_better": True, "threshold": {"op": ">=", "value": 1200, "unit": "vòng/phút"},
         "spec_label": "Tốc độ vắt cao (≥1200 v/p)", "simple_label": "Quần áo khô nhanh hơn",
         "contextual": ["trời nồm ẩm", "ít nắng phơi", "cần khô nhanh"]},
    ],
    "Máy sấy quần áo": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["khoi_luong_tai_chinh", "so_nguoi_su_dung"],
         "higher_better": True, "threshold": {"op": ">=", "value": 9, "unit": "kg"},
         "spec_label": "Tải sấy lớn (≥9kg)", "simple_label": "Sấy nhiều đồ một lần",
         "contextual": ["gia đình đông", "sấy chăn mền", "nhà ít nắng"]},
        {"id": "energy_saving", "weight_key": "popularity", "spec_fields": ["dien_nang_tieu_thu", "energy_saving_technology"],
         "higher_better": False, "threshold": {"op": "<=", "value": 2, "unit": "kWh/lần"},
         "spec_label": "Bơm nhiệt tiết kiệm điện", "simple_label": "Sấy êm, tốn ít điện",
         "contextual": ["dùng thường xuyên", "tiết kiệm hoá đơn", "vải mỏng dễ hư"]},
    ],
    "Máy rửa chén": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["khay_chen", "output_capacity"],
         "higher_better": True, "threshold": {"op": ">=", "value": 13, "unit": "bộ"},
         "spec_label": "Sức chứa lớn (≥13 bộ)", "simple_label": "Rửa đủ chén cả nhà một mẻ",
         "contextual": ["gia đình đông", "hay tiếp khách", "nấu ăn nhiều"]},
        {"id": "quiet", "weight_key": "popularity", "spec_fields": ["noise"],
         "higher_better": False, "threshold": {"op": "<=", "value": 45, "unit": "dB"},
         "spec_label": "Vận hành êm (≤45 dB)", "simple_label": "Chạy đêm không ồn",
         "contextual": ["bếp mở nối phòng khách", "chung cư", "rửa ban đêm"]},
        {"id": "water_saving", "weight_key": "popularity", "spec_fields": ["tieu_thu_nuoc", "cong_nghe"],
         "higher_better": False, "threshold": {"op": "<=", "value": 12, "unit": "L/mẻ"},
         "spec_label": "Tiết kiệm nước", "simple_label": "Ít tốn nước hơn rửa tay",
         "contextual": ["dùng mỗi ngày", "tiết kiệm chi phí", "khu vực thiếu nước"]},
    ],
    "Máy nước nóng": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["dung_luong_dung_tich", "output_capacity"],
         "higher_better": True, "threshold": {"op": ">=", "value": 20, "unit": "L"},
         "spec_label": "Dung tích lớn (≥20L)", "simple_label": "Đủ nước nóng cho nhiều người tắm",
         "contextual": ["gia đình đông", "nhiều phòng tắm", "mùa đông dùng nhiều"]},
        {"id": "safety", "weight_key": "popularity", "spec_fields": ["tinh_nang_an_toan"],
         "higher_better": True, "threshold": {"op": ">=", "value": 3, "unit": "lớp"},
         "spec_label": "Nhiều lớp an toàn chống giật", "simple_label": "An tâm cho gia đình có trẻ nhỏ",
         "contextual": ["nhà có trẻ em", "người lớn tuổi", "ưu tiên an toàn"]},
    ],
    "Tủ đông, tủ mát": [
        {"id": "capacity", "weight_key": "popularity", "spec_fields": ["dung_tich_tong", "dung_tich_ngan_dong_mem"],
         "higher_better": True, "threshold": {"op": ">=", "value": 300, "unit": "L"},
         "spec_label": "Dung tích lớn (≥300L)", "simple_label": "Trữ đông số lượng lớn",
         "contextual": ["quán ăn / tạp hoá", "trữ thực phẩm dài ngày", "kinh doanh nhỏ"]},
        {"id": "energy_saving", "weight_key": "popularity", "spec_fields": ["dien_nang_tieu_thu", "energy_saving_technology"],
         "higher_better": False, "threshold": {"op": "<=", "value": 600, "unit": "kWh/năm"},
         "spec_label": "Tiết kiệm điện", "simple_label": "Chạy liên tục tốn ít điện",
         "contextual": ["cắm 24/7", "kinh doanh tiết kiệm", "hoá đơn điện thấp"]},
    ],
    "Máy tính bảng": [
        {"id": "battery", "weight_key": "popularity", "spec_fields": ["dung_luong_pin"],
         "higher_better": True, "threshold": {"op": ">=", "value": 8000, "unit": "mAh"},
         "spec_label": "Pin trâu (≥8000 mAh)", "simple_label": "Dùng cả ngày không lo sạc",
         "contextual": ["xem phim/học online", "đi công tác", "cho trẻ học"]},
        {"id": "performance", "weight_key": "popularity", "spec_fields": ["ram", "chip_xu_ly_cpu"],
         "higher_better": True, "threshold": {"op": ">=", "value": 8, "unit": "GB"},
         "spec_label": "Cấu hình mạnh (RAM ≥8GB)", "simple_label": "Chạy mượt game/đa nhiệm",
         "contextual": ["chơi game", "vẽ/ghi chú", "làm việc nhẹ"]},
        {"id": "storage", "weight_key": "popularity", "spec_fields": ["dung_luong_luu_tru"],
         "higher_better": True, "threshold": {"op": ">=", "value": 128, "unit": "GB"},
         "spec_label": "Bộ nhớ lớn (≥128GB)", "simple_label": "Lưu nhiều phim, app, tài liệu",
         "contextual": ["tải phim offline", "nhiều ứng dụng", "lưu ảnh/tài liệu"]},
    ],
    "Đồng hồ thông minh": [
        {"id": "battery", "weight_key": "popularity", "spec_fields": ["thoi_gian_su_dung", "dung_luong_pin"],
         "higher_better": True, "threshold": {"op": ">=", "value": 7, "unit": "ngày"},
         "spec_label": "Pin lâu (≥7 ngày)", "simple_label": "Sạc 1 lần dùng cả tuần",
         "contextual": ["ngại sạc thường xuyên", "đi du lịch", "đeo cả khi ngủ"]},
        {"id": "health", "weight_key": "popularity", "spec_fields": ["theo_doi_suc_khoe", "cam_bien"],
         "higher_better": True, "threshold": {"op": ">=", "value": 5, "unit": "chỉ số"},
         "spec_label": "Nhiều cảm biến sức khoẻ", "simple_label": "Đo nhịp tim, SpO2, giấc ngủ...",
         "contextual": ["theo dõi sức khoẻ", "người lớn tuổi", "tập thể thao"]},
        {"id": "sport", "weight_key": "popularity", "spec_fields": ["mon_the_thao", "dinh_vi"],
         "higher_better": True, "threshold": {"op": ">=", "value": 50, "unit": "môn"},
         "spec_label": "Nhiều chế độ thể thao + GPS", "simple_label": "Ghi lại quãng đường, bài tập",
         "contextual": ["chạy bộ / đạp xe", "gym", "leo núi / bơi"]},
    ],
    "Micro": [
        {"id": "battery", "weight_key": "popularity", "spec_fields": ["thoi_gian_su_dung", "dung_luong_pin_bo_phat"],
         "higher_better": True, "threshold": {"op": ">=", "value": 6, "unit": "giờ"},
         "spec_label": "Thời lượng pin dài (≥6h)", "simple_label": "Hát/quay cả buổi không hết pin",
         "contextual": ["quay video dài", "sự kiện", "livestream"]},
        {"id": "range", "weight_key": "popularity", "spec_fields": ["khoang_cach_truyen"],
         "higher_better": True, "threshold": {"op": ">=", "value": 20, "unit": "m"},
         "spec_label": "Khoảng cách truyền xa (≥20m)", "simple_label": "Di chuyển thoải mái khi nói",
         "contextual": ["sân khấu", "phòng lớn", "quay ngoài trời"]},
    ],
    "Máy tính để bàn": [
        {"id": "performance", "weight_key": "popularity", "spec_fields": ["ram", "loai_cpu", "so_nhan"],
         "higher_better": True, "threshold": {"op": ">=", "value": 16, "unit": "GB"},
         "spec_label": "Cấu hình mạnh (RAM ≥16GB)", "simple_label": "Chạy nặng, đa nhiệm mượt",
         "contextual": ["dựng phim/render", "chơi game nặng", "lập trình / ảo hoá"]},
        {"id": "storage", "weight_key": "popularity", "spec_fields": ["o_cung"],
         "higher_better": True, "threshold": {"op": ">=", "value": 512, "unit": "GB"},
         "spec_label": "Ổ cứng lớn/SSD nhanh", "simple_label": "Khởi động nhanh, lưu nhiều",
         "contextual": ["nhiều dữ liệu", "cần mở máy nhanh", "cài nhiều phần mềm"]},
        {"id": "office", "weight_key": "popularity", "spec_fields": ["ram", "loai_cpu"],
         "higher_better": False, "threshold": {"op": "<=", "value": 8, "unit": "GB"},
         "spec_label": "Cấu hình văn phòng cơ bản", "simple_label": "Đủ cho word, web, họp online",
         "contextual": ["văn phòng", "học tập", "gia đình dùng chung"]},
    ],
    "Màn hình máy tính": [
        {"id": "resolution", "weight_key": "popularity", "spec_fields": ["do_phan_giai", "kich_thuoc_man_hinh"],
         "higher_better": True, "threshold": {"op": ">=", "value": 27, "unit": "inch"},
         "spec_label": "Màn lớn / độ phân giải cao", "simple_label": "Hình sắc nét, không gian rộng",
         "contextual": ["làm đồ hoạ", "xem phim", "làm việc nhiều cửa sổ"]},
        {"id": "refresh", "weight_key": "popularity", "spec_fields": ["thoi_gian_dap_ung", "tam_nen"],
         "higher_better": True, "threshold": {"op": ">=", "value": 144, "unit": "Hz"},
         "spec_label": "Tần số quét cao (gaming)", "simple_label": "Chuyển động mượt, không xé hình",
         "contextual": ["chơi game", "eSports", "chuyển động nhanh"]},
        {"id": "color", "weight_key": "popularity", "spec_fields": ["do_phu_mau", "tam_nen"],
         "higher_better": True, "threshold": {"op": ">=", "value": 99, "unit": "% sRGB"},
         "spec_label": "Độ phủ màu chính xác", "simple_label": "Màu chuẩn cho thiết kế",
         "contextual": ["thiết kế / chỉnh ảnh", "dựng phim", "in ấn"]},
    ],
    "Máy in": [
        {"id": "speed", "weight_key": "popularity", "spec_fields": ["toc_do_in"],
         "higher_better": True, "threshold": {"op": ">=", "value": 30, "unit": "trang/phút"},
         "spec_label": "Tốc độ in nhanh (≥30 trang/phút)", "simple_label": "In số lượng lớn nhanh",
         "contextual": ["văn phòng in nhiều", "in tài liệu dày", "công ty"]},
        {"id": "cost_per_page", "weight_key": "popularity", "spec_fields": ["loai_muc_in", "cong_nghe"],
         "higher_better": True, "threshold": {"op": ">=", "value": 1, "unit": "bình mực"},
         "spec_label": "In tiết kiệm (mực in liên tục)", "simple_label": "Chi phí mỗi trang rất thấp",
         "contextual": ["in số lượng lớn", "tiết kiệm mực", "cửa hàng photo"]},
        {"id": "multifunction", "weight_key": "popularity", "spec_fields": ["loai_san_pham", "cong_nghe"],
         "higher_better": True, "threshold": {"op": ">=", "value": 1, "unit": "chức năng"},
         "spec_label": "Đa chức năng (in-scan-copy)", "simple_label": "Một máy làm mọi việc giấy tờ",
         "contextual": ["văn phòng nhỏ", "làm việc tại nhà", "cần scan/copy"]},
    ],
    # popular non-registry categories kept for UX parity (phone has a dedicated
    # ranker; laptop uses generic). Spec_fields not validated against registry
    # (no sheet) — flagged, kept minimal + budget-driven.
    "Điện thoại": [
        {"id": "battery", "weight_key": "battery", "spec_fields": ["battery_mah"],
         "higher_better": True, "threshold": {"op": ">=", "value": 5000, "unit": "mAh"},
         "spec_label": "Pin trâu (≥5000 mAh)", "simple_label": "Dùng thoải mái cả ngày",
         "contextual": ["đi cả ngày", "chơi game / xem phim", "ngại sạc"], "_no_registry": True},
        {"id": "storage", "weight_key": "storage", "spec_fields": ["storage_gb"],
         "higher_better": True, "threshold": {"op": ">=", "value": 256, "unit": "GB"},
         "spec_label": "Bộ nhớ lớn (≥256GB)", "simple_label": "Lưu nhiều ảnh, video, app",
         "contextual": ["chụp ảnh nhiều", "quay video 4K", "cài nhiều game"], "_no_registry": True},
        {"id": "performance", "weight_key": "ram", "spec_fields": ["ram_gb"],
         "higher_better": True, "threshold": {"op": ">=", "value": 8, "unit": "GB"},
         "spec_label": "Cấu hình mạnh (RAM ≥8GB)", "simple_label": "Mượt game nặng, đa nhiệm",
         "contextual": ["chơi game", "đa nhiệm", "dùng lâu dài"], "_no_registry": True},
    ],
    "Laptop": [
        {"id": "portable", "weight_key": "popularity", "spec_fields": ["weight"],
         "higher_better": False, "threshold": {"op": "<=", "value": 1.4, "unit": "kg"},
         "spec_label": "Mỏng nhẹ (≤1.4kg)", "simple_label": "Dễ mang theo cả ngày",
         "contextual": ["hay di chuyển", "sinh viên", "làm việc quán cafe"], "_no_registry": True},
        {"id": "performance", "weight_key": "popularity", "spec_fields": ["ram", "cpu"],
         "higher_better": True, "threshold": {"op": ">=", "value": 16, "unit": "GB"},
         "spec_label": "Cấu hình mạnh (RAM ≥16GB)", "simple_label": "Chạy nặng mượt mà",
         "contextual": ["đồ hoạ / lập trình", "chơi game", "đa nhiệm"], "_no_registry": True},
    ],
}


def _load_registry_fields() -> dict[str, set[str]]:
    reg = json.load(open(REGISTRY_PATH, encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for cfg in reg["sheets"].values():
        code = cfg.get("category")
        keys: set[str] = set()
        for m in cfg.get("deep_fields", []):
            keys.add(m["key"])
        for m in cfg.get("mappings", []):
            keys.add(m["key"])
        if code:
            out[code] = keys
    return out


def _room_vocab() -> dict[str, list[str]]:
    """category_name(registry 'Danh mục gốc') -> top room labels. Best-effort;
    returns {} if the workbook is absent (script still emits the registry)."""
    if not os.path.exists(ROOM_XLSX):
        return {}
    try:
        import openpyxl
    except ImportError:
        return {}
    wb = openpyxl.load_workbook(ROOM_XLSX, data_only=True)
    cat_rooms: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for ws in wb.worksheets:
        if ws.title.startswith("00"):
            continue
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 4:
                continue
            room, cat = row[0], row[3]
            if cat and room:
                cat_rooms[str(cat).strip()][str(room).strip()] += 1
    return {c: [r for r, _ in cnt.most_common(3)] for c, cnt in cat_rooms.items()}


def _budget_tiers(nlu_name: str, segments: dict) -> dict[str, int] | None:
    seg_name = SEGMENT_NAME.get(nlu_name)
    # try direct, then loose match against the segment table
    s = None
    if seg_name and seg_name in segments:
        s = segments[seg_name]
    else:
        for k, v in segments.items():
            if nlu_name.lower() in k.lower() or k.lower() in nlu_name.lower():
                s = v
                break
    if not s:
        return None
    # low/mid/premium = q25/q50/q75 -> thấp / trung bình / cao
    return {"low": int(s["budget"]), "mid": int(s["mid"]), "high": int(s["premium"])}


def main() -> None:
    reg_fields = _load_registry_fields()
    rooms = _room_vocab()
    from antigravity.few_shot import load_price_segments
    segments = load_price_segments()

    out: dict[str, Any] = {"_generated_by": "scripts/gen_factors_registry.py",
                           "_note": "Layer-c (contextual) is editorial — hand-edit after generation.",
                           "categories": {}}
    warnings: list[str] = []

    for nlu_name, factors in FACTOR_HINTS.items():
        code = CATEGORY_CODE.get(nlu_name)
        known = reg_fields.get(code, set()) if code else set()
        clean_factors = []
        for f in factors:
            f = dict(f)
            no_reg = f.pop("_no_registry", False)
            if not no_reg and known:
                missing = [sf for sf in f["spec_fields"] if sf not in known]
                if missing:
                    warnings.append(f"[{nlu_name}] factor '{f['id']}' references non-registry "
                                    f"spec_fields {missing} (kept — verify DMX has them)")
            clean_factors.append(f)

        # budget factor: fill quartile tiers if available
        budget = dict(BUDGET_FACTOR)
        tiers = _budget_tiers(nlu_name, segments)
        if tiers:
            budget["tiers"] = tiers
        else:
            warnings.append(f"[{nlu_name}] no price-segment quartiles found; budget factor "
                            f"will fall back to free-text budget entry")
        # cap total factors at 4 (spec-factors first, budget always included)
        final = clean_factors[:3] + [budget]

        # enrich layer-c from room vocab where the category is room-dependent
        room_terms = rooms.get(nlu_name) or rooms.get(code or "", [])
        entry: dict[str, Any] = {"factors": final}
        if room_terms:
            entry["room_context"] = room_terms
        out["categories"][nlu_name] = entry

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"Wrote {OUT_PATH}: {len(out['categories'])} categories")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print("  -", w)


if __name__ == "__main__":
    main()
