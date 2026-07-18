"""Build a SYNTHETIC ("giả lập") aircon demo catalog for the public Vercel deploy.

Why synthetic: the brief (Dien-May-Xanh-Enterprise-Problem-Brief.md, E2 line 142) requires
"mọi dữ liệu demo nên được giả lập hoặc anonymize", and data use is "chỉ trong hackathon /
cần NDA nếu dùng dữ liệu thật". So NO real DMX SKU/price/URL may ship to a public repo or a
public live URL. These records are fabricated: plausible spec distributions + price tiers so
the REAL pipeline (retrieval -> ranking -> z.ai/FPT explanation) runs on them exactly as it
would on the real catalog — a real AI demo, zero NDA exposure.

Output matches the dmx_<cat>.all.jsonl record shape the ranker reads (effective_price + the
spec keys area_*/indoor_noise_*/cooling_capacity_btu/inverter/power_kwh/...). stock_status is
always "unknown" (loader never invents availability). Deterministic (seeded) so re-runs are
identical. Regenerate: python scripts/build_demo_catalog.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUT = BASE_DIR / "demo_catalog" / "dmx_air_conditioner.all.jsonl"

# Public consumer aircon brands (manufacturers, not DMX-proprietary). Tier = price multiplier.
BRANDS = [
    ("Daikin", 1.35), ("Panasonic", 1.25), ("Mitsubishi", 1.30), ("LG", 1.10),
    ("Samsung", 1.10), ("Toshiba", 1.15), ("Sharp", 1.00), ("Casper", 0.80),
    ("Midea", 0.82), ("Gree", 0.85), ("Aqua", 0.88), ("Funiki", 0.72),
    ("Nagakawa", 0.75), ("TCL", 0.83), ("Comfee", 0.78),
]

# BTU tier -> (area_min, area_max, base_price VND, cooling_btu)
TIERS = [
    (9000, 10, 15, 8_500_000),
    (12000, 15, 20, 10_500_000),
    (18000, 20, 28, 15_500_000),
    (24000, 28, 40, 21_000_000),
]


def build(n: int = 50, seed: int = 26) -> list[dict]:
    rng = random.Random(seed)
    recs: list[dict] = []
    for i in range(n):
        brand, mult = rng.choice(BRANDS)
        btu, amin, amax, base = rng.choice(TIERS)
        inverter = rng.random() < 0.8
        # inverter costs more + runs quieter + lower kWh
        price = int(base * mult * (1.12 if inverter else 1.0) * rng.uniform(0.92, 1.08))
        price = round(price / 10_000) * 10_000  # tidy to 10k VND
        noise_min = round(rng.uniform(18, 24) - (4 if inverter else 0), 1)
        noise_max = round(noise_min + rng.uniform(6, 12), 1)
        power_kwh = round((btu / 12000) * (0.95 if inverter else 1.25) * rng.uniform(0.9, 1.1), 2)
        hp = {9000: "1 HP", 12000: "1.5 HP", 18000: "2 HP", 24000: "2.5 HP"}[btu]
        recs.append({
            "product_id": f"DEMO-AC-{i+1:03d}",
            "category": "air_conditioner",
            "name": f"Máy lạnh {brand} {'Inverter ' if inverter else ''}{hp} (demo giả lập)",
            "brand": brand,
            "image": None,
            "url": None,
            "color": "Trắng",
            "warranty": "Chính hãng (dữ liệu demo)",
            "promotion": None,
            "accessories": [],
            "rating": round(rng.uniform(4.2, 4.9), 1),
            "quantity_sold": rng.randint(20, 800),
            "original_price": price,
            "promotion_price": None,
            "effective_price": price,
            "online_sale_only": False,
            "stock_status": "unknown",
            "spec": {
                "area_min_m2": float(amin),
                "area_max_m2": float(amax),
                "indoor_noise_min_db": noise_min,
                "indoor_noise_max_db": noise_max,
                "outdoor_noise_db": round(rng.uniform(48, 58), 1),
                "cooling_capacity_btu": btu,
                "inverter": inverter,
                "product_year": rng.choice([2024, 2025, 2026]),
                "gas": rng.choice(["R-32", "R-410A"]),
                "power_kwh": power_kwh,
                "energy_tech": "Inverter" if inverter else "Cơ (non-inverter)",
                "machine_type": "1 chiều (chỉ làm lạnh)",
            },
            "data_quality": {"eligible_for_demo": True, "missing_fields": [], "warnings": []},
            "source": {"type": "synthetic", "note": "giả lập demo data — no real DMX SKU"},
        })
    return recs


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    recs = build()
    with OUT.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(recs)} synthetic records -> {OUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
