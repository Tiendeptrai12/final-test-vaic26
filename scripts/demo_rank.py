"""Offline demo of the aircon ranking engine on the real eligible catalog. No API/LLM.

Local dev tool — prints the Top-N with score breakdown + grounded reasons + relaxation
notes so you can eyeball behaviour before the NLU/explainer phases exist.

Usage:
    python scripts/demo_rank.py --budget 20000000 --area 18 --room bedroom \
        --priority quiet --inverter --brands Daikin Panasonic
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antigravity.aircon_ranking import NeedProfile, rank_top  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=None, help="budget_max (VND)")
    ap.add_argument("--budget-min", type=int, default=None)
    ap.add_argument("--area", type=float, default=None, help="room size m2")
    ap.add_argument("--room", choices=["bedroom", "living_room"], default=None)
    ap.add_argument("--priority", choices=["quiet", "fast_cooling", "energy_saving", "price"],
                    default=None)
    ap.add_argument("--sunny", action="store_true")
    ap.add_argument("--inverter", action="store_true")
    ap.add_argument("--brands", nargs="*", default=[])
    ap.add_argument("-n", type=int, default=3)
    args = ap.parse_args(argv)

    profile = NeedProfile(
        budget_max=args.budget, budget_min=args.budget_min, area_m2=args.area,
        room_type=args.room, sunny=args.sunny or None,
        priority=args.priority, inverter_required=args.inverter or None, brands=args.brands,
    )

    # Catalog loads ONCE at startup in the real app; only per-turn ranking counts
    # against the <5s SLA. Measure them separately so the number is honest.
    from antigravity import btc_catalog
    try:
        t_load = time.perf_counter()
        records = btc_catalog.load_category("air_conditioner")
        load_ms = (time.perf_counter() - t_load) * 1000
    except FileNotFoundError:
        print("ERROR: catalog not found. Run scripts/build_btc_catalog.py first.",
              file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    result = rank_top(profile, records=records, n=args.n)
    rank_ms = (time.perf_counter() - t0) * 1000

    print(f"Nhu cầu: {profile}")
    print(f"Ứng viên: {result.total_candidates} | startup load: {load_ms:.0f} ms (một lần) "
          f"| per-turn rank: {rank_ms:.2f} ms (SLA < 5000 ms)")
    if result.relaxations:
        print("Đã nới lỏng: " + "; ".join(result.relaxations))
    if not result.items:
        print("Không tìm được sản phẩm phù hợp.")
        print("Lý do loại (tổng hợp):", result.rejected_summary)
        return 0

    for rank, it in enumerate(result.items, 1):
        price = f"{it.effective_price/1_000_000:.1f}tr" if it.effective_price else "chưa có giá"
        print(f"\n#{rank}  [{it.product_id}] {it.brand or '?'} — {price} "
              f"(điểm {it.total_score})")
        print("   " + " · ".join(it.reasons) if it.reasons else "   (không có lý do)")
        print(f"   breakdown: {it.breakdown}")
        if it.missing_data:
            print(f"   thiếu dữ liệu: {it.missing_data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
