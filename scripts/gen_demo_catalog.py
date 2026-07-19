"""Sinh demo_catalog cho các ngành fallback (generic ranker) — NDA-safe.

WHY: generic_ranking đọc raw NDA json (data/raw/dmx/products_detail.json) vốn KHÔNG
bundled lên Vercel, nên ngành ngoài máy lạnh/điện thoại trả rỗng trên live. Script này
sinh dữ liệu GIẢ LẬP (không phải SKU DMX thật) theo đúng schema canonical như
dmx_air_conditioner.all.jsonl, để load_category_records() nạp được trên Vercel.

Chạy: python scripts/gen_demo_catalog.py
Ghi ra: demo_catalog/dmx_<slug>.all.jsonl (1 record / dòng, UTF-8 sạch).

Số liệu là DEMO — reasons/ranking vẫn grounded trên chính số trong record (không LLM bịa).
Slug PHẢI khớp CATEGORY_SLUG trong antigravity/generic_ranking.py.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "demo_catalog"

# slug -> (prefix id, category_name hiển thị, [brand...], (giá_min, giá_max), spec_builder)
# spec_builder(idx, rng) -> dict spec đặc thù ngành (thông tin, không dùng để rank).
def _spec_tu_lanh(i, rng):
    lit = rng.choice([150, 180, 236, 280, 320, 360, 410, 460, 530])
    return {"capacity_liters": lit, "recommended_household": "2-4 người" if lit < 300 else "4-6 người",
            "inverter": True, "product_year": rng.choice([2024, 2025, 2026])}

def _spec_may_giat(i, rng):
    kg = rng.choice([7.5, 8.0, 9.0, 9.5, 10.0, 11.0, 12.0])
    return {"wash_capacity_kg": kg, "recommended_household": "2-4 người" if kg < 9 else "4-6 người",
            "inverter": True, "product_year": rng.choice([2024, 2025, 2026])}

def _spec_may_say(i, rng):
    kg = rng.choice([7.0, 8.0, 9.0, 10.0])
    return {"dry_capacity_kg": kg, "recommended_household": "2-4 người" if kg < 9 else "4-6 người",
            "dry_tech": rng.choice(["Bơm nhiệt", "Ngưng tụ", "Thông hơi"])}

def _spec_may_rua_chen(i, rng):
    sets = rng.choice([8, 10, 13, 14, 15])
    return {"place_settings": sets, "recommended_household": "2-4 người" if sets <= 10 else "4-6 người",
            "programs": rng.choice([5, 6, 7, 8])}

def _spec_nuoc_nong(i, rng):
    lit = rng.choice([15, 20, 22, 30])
    return {"capacity_liters": lit, "type": rng.choice(["Gián tiếp", "Trực tiếp"]),
            "recommended_household": "1-2 người" if lit <= 15 else "3-5 người"}

def _spec_tu_dong(i, rng):
    lit = rng.choice([100, 150, 200, 252, 300, 350, 450])
    return {"capacity_liters": lit, "kind": rng.choice(["Tủ đông", "Tủ mát", "Tủ đông mát"]),
            "product_year": rng.choice([2024, 2025, 2026])}

def _spec_tablet(i, rng):
    return {"screen_inch": rng.choice([8.7, 10.1, 10.9, 11.0, 12.4]),
            "battery_mah": rng.choice([5100, 6000, 7040, 8000, 10090]),
            "storage_gb": rng.choice([64, 128, 256]), "ram_gb": rng.choice([4, 6, 8])}

def _spec_watch(i, rng):
    return {"battery_life_days": rng.choice([1, 2, 5, 7, 14]),
            "screen_inch": rng.choice([1.3, 1.4, 1.6, 1.8]),
            "gps": rng.choice([True, False]), "waterproof": rng.choice(["5ATM", "IP68"])}

def _spec_micro(i, rng):
    return {"kind": rng.choice(["Micro karaoke không dây", "Micro thu âm điện thoại"]),
            "wireless": rng.choice([True, False]),
            "battery_hours": rng.choice([4, 6, 8, 10])}

def _spec_pc(i, rng):
    return {"cpu": rng.choice(["Core i3", "Core i5", "Core i7", "Ryzen 5", "Ryzen 7"]),
            "ram_gb": rng.choice([8, 16, 32]), "storage_gb": rng.choice([256, 512, 1024]),
            "use_case": rng.choice(["văn phòng", "đồ họa", "gaming"])}

def _spec_monitor(i, rng):
    return {"screen_inch": rng.choice([21.5, 23.8, 24.0, 27.0, 32.0]),
            "refresh_hz": rng.choice([60, 75, 100, 144, 165]),
            "panel": rng.choice(["IPS", "VA", "TN"]),
            "resolution": rng.choice(["1920x1080", "2560x1440", "3840x2160"])}

def _spec_may_in(i, rng):
    return {"tech": rng.choice(["Laser", "Phun", "Laser màu"]),
            "functions": rng.choice(["In", "In-Scan-Copy", "In-Scan-Copy-Fax"]),
            "wifi": rng.choice([True, False]), "duplex": rng.choice([True, False])}

CATEGORIES = {
    "tu_lanh":        ("FRG", "Tủ lạnh",            ["Samsung", "LG", "Toshiba", "Panasonic", "Aqua", "Sharp", "Electrolux"], (4_000_000, 22_000_000), _spec_tu_lanh),
    "may_giat":       ("WM",  "Máy giặt",           ["LG", "Samsung", "Panasonic", "Toshiba", "Electrolux", "Aqua"],        (4_500_000, 18_000_000), _spec_may_giat),
    "may_say_quan_ao":("DRY", "Máy sấy quần áo",    ["Electrolux", "LG", "Samsung", "Panasonic", "Bosch"],                  (6_000_000, 24_000_000), _spec_may_say),
    "may_rua_chen":   ("DW",  "Máy rửa chén",       ["Bosch", "Electrolux", "Panasonic", "Toshiba", "Malloca"],             (7_000_000, 28_000_000), _spec_may_rua_chen),
    "may_nuoc_nong":  ("WH",  "Máy nước nóng",      ["Ariston", "Panasonic", "Ferroli", "Kangaroo", "Centon"],              (1_500_000,  6_000_000), _spec_nuoc_nong),
    "tu_dong_tu_mat": ("FZ",  "Tủ đông, tủ mát",    ["Sanaky", "Aqua", "Alaska", "Hòa Phát", "Kangaroo"],                   (3_500_000, 16_000_000), _spec_tu_dong),
    "may_tinh_bang":  ("TAB", "Máy tính bảng",      ["Samsung", "Xiaomi", "Lenovo", "Apple", "Huawei"],                     (3_000_000, 25_000_000), _spec_tablet),
    "dong_ho_thong_minh":("SW","Đồng hồ thông minh",["Apple", "Samsung", "Xiaomi", "Huawei", "Garmin", "Amazfit"],          (700_000,  12_000_000), _spec_watch),
    "micro":          ("MIC", "Micro",              ["Shure", "Takstar", "AVLeader", "Boya", "JBL"],                        (300_000,   6_000_000), _spec_micro),
    "may_tinh_de_ban":("PC",  "Máy tính để bàn",    ["Dell", "HP", "Asus", "Acer", "Lenovo"],                               (7_000_000, 35_000_000), _spec_pc),
    "man_hinh_may_tinh":("MON","Màn hình máy tính", ["Dell", "LG", "Samsung", "Asus", "ViewSonic", "AOC"],                  (2_000_000, 15_000_000), _spec_monitor),
    "may_in":         ("PRT", "Máy in",             ["Canon", "HP", "Brother", "Epson"],                                    (2_200_000, 12_000_000), _spec_may_in),
}

N_PER_CATEGORY = 14


def build_record(slug: str, prefix: str, cat_name: str, brand: str, idx: int,
                 price_range: tuple[int, int], spec_fn, rng: random.Random) -> dict:
    lo, hi = price_range
    price = int(round(rng.randint(lo, hi) / 10_000) * 10_000)
    has_promo = rng.random() < 0.4
    promo_price = int(round(price * rng.uniform(0.85, 0.97) / 10_000) * 10_000) if has_promo else None
    effective = promo_price if promo_price else price
    return {
        "product_id": f"DEMO-{prefix}-{idx:03d}",
        "category": slug,
        "name": f"{cat_name} {brand} {rng.choice(['Basic','Plus','Pro','Max','Smart','Eco'])} {rng.choice(['A','B','S','X'])}{rng.randint(10,99)} (demo giả lập)",
        "brand": brand,
        "image": None,
        "url": None,
        "warranty": "Chính hãng (dữ liệu demo)",
        "promotion": "Giảm giá demo" if has_promo else None,
        "accessories": [],
        "rating": round(rng.uniform(3.8, 4.9), 1),
        "quantity_sold": rng.randint(30, 5000),
        "original_price": price,
        "promotion_price": promo_price,
        "effective_price": effective,
        "online_sale_only": False,
        "stock_status": "unknown",
        "spec": spec_fn(idx, rng),
        "data_quality": {"eligible_for_demo": True, "missing_fields": [], "warnings": []},
        "source": {"type": "synthetic", "note": "giả lập demo data — no real DMX SKU"},
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for slug, (prefix, cat_name, brands, price_range, spec_fn) in CATEGORIES.items():
        rng = random.Random(f"vaic26-{slug}")  # deterministic per ngành
        records = []
        for i in range(1, N_PER_CATEGORY + 1):
            brand = brands[(i - 1) % len(brands)]
            records.append(build_record(slug, prefix, cat_name, brand, i, price_range, spec_fn, rng))
        path = OUT_DIR / f"dmx_{slug}.all.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        total += len(records)
        print(f"  {path.name}: {len(records)} records")
    print(f"Done: {len(CATEGORIES)} ngành, {total} records -> {OUT_DIR}")


if __name__ == "__main__":
    main()
