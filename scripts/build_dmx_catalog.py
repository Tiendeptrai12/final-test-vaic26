"""DMX catalog builder — real organizer data (products_detail.json) -> canonical JSONL.

Replaces the sparse-Excel path (build_btc_catalog.py, kept for BTC) with the richer DMX
drop: 13,754 SKU, 119 categories, 100% priced, plus name/image/url/rating/quantity_sold/
warranty/promotion. Value formats match the old parsers, so area/noise/BTU/inverter/year
parsing is reused from build_btc_catalog. NDA: raw json + outputs are gitignored.

P1 scope = aircon end-to-end on DMX data. Other categories: top-level fields still map,
spec stays raw until their canonical map is added.

Usage:
    python scripts/build_dmx_catalog.py            # all mapped categories (aircon)
    python scripts/build_dmx_catalog.py --category "Máy lạnh"
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from scripts.build_btc_catalog import (
    clean_str, parse_area, parse_btu, parse_inverter, parse_noise, parse_year,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT = os.path.join(BASE_DIR, "data", "raw", "dmx", "products_detail.json")
DEFAULT_OUTDIR = os.path.join(BASE_DIR, "data", "processed")

# category_name -> canonical category slug (extend as more categories are mapped)
CATEGORY_SLUG = {
    "Máy lạnh": "air_conditioner",
}


# --------------------------------------------------------------------------- #
# scalar parsers specific to the DMX json
# --------------------------------------------------------------------------- #
def parse_quantity_sold(v: Any) -> int | None:
    """'14,5k' -> 14500, '1.234' -> 1234, '' -> None."""
    s = clean_str(v)
    if not s:
        return None
    s = s.strip().lower().replace(" ", "")
    m = re.match(r"^([\d.,]+)k$", s)
    if m:
        num = float(m.group(1).replace(".", "").replace(",", "."))
        return int(num * 1000)
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def parse_rating(v: Any) -> float | None:
    s = clean_str(v)
    if not s:
        return None
    try:
        r = float(s.replace(",", "."))
        return r if 0 < r <= 5 else None
    except ValueError:
        return None


def parse_kwh(v: Any) -> float | None:
    """'0.84 kWh' -> 0.84."""
    s = clean_str(v)
    if not s:
        return None
    m = re.search(r"([\d.,]+)\s*kwh", s.lower())
    return float(m.group(1).replace(",", ".")) if m else None


def price_to_int(v: Any) -> int | None:
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# aircon spec map: DMX spec_product label -> canonical spec fields
# --------------------------------------------------------------------------- #
def _aircon_spec(sp: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out: dict[str, Any] = {}
    missing: list[str] = []

    amin, amax, _ = parse_area(sp.get("Phạm vi làm lạnh hiệu quả"))
    out["area_min_m2"], out["area_max_m2"] = amin, amax
    if amin is None or amax is None:
        missing.append("area")

    imin, imax, outdoor, _ = parse_noise(
        sp.get("Độ ồn trung bình (được đo trong phòng thí nghiệm)"))
    out["indoor_noise_min_db"], out["indoor_noise_max_db"] = imin, imax
    out["outdoor_noise_db"] = outdoor
    if imin is None:
        missing.append("noise")

    btu, _ = parse_btu(sp.get("Công suất làm lạnh"))
    out["cooling_capacity_btu"] = btu

    out["inverter"] = parse_inverter(sp.get("Inverter"))
    out["product_year"] = parse_year(sp.get("Dòng sản phẩm"))
    out["gas"] = clean_str(sp.get("Loại Gas"))
    out["power_kwh"] = parse_kwh(sp.get("Tiêu thụ điện"))          # energy signal (lower better)
    out["energy_tech"] = clean_str(sp.get("Công nghệ tiết kiệm điện"))
    out["machine_type"] = clean_str(sp.get("Loại máy"))
    # cspf/energy_stars not present in DMX data (unlike old Excel) -> leave absent
    return out, missing


SPEC_BUILDERS = {
    "air_conditioner": _aircon_spec,
}


# --------------------------------------------------------------------------- #
# record builder (top-level fields shared across all categories)
# --------------------------------------------------------------------------- #
def build_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    pid = clean_str(rec.get("product_id"))
    if not pid:
        return None
    cat_name = rec.get("category_name")
    slug = CATEGORY_SLUG.get(cat_name)

    original = price_to_int(rec.get("Giá gốc"))
    promo = price_to_int(rec.get("Giá khuyến mãi"))
    effective = promo or original
    warnings: list[str] = []
    if promo and original and promo > original:
        warnings.append("promotion_gt_original")

    spec: dict[str, Any] = {}
    missing: list[str] = []
    sp = rec.get("spec_product")
    if slug and isinstance(sp, dict) and slug in SPEC_BUILDERS:
        spec, missing = SPEC_BUILDERS[slug](sp)
    elif isinstance(sp, dict):
        spec = {}  # unmapped category: spec stays raw-less for now (top-level still usable)

    eligible = effective is not None and (not slug or "area" not in missing)

    return {
        "product_id": pid,
        "category": slug or cat_name,
        "name": clean_str(rec.get("tên sản phẩm")),
        "brand": clean_str(rec.get("brand")),
        "image": clean_str(rec.get("url_image")),
        "url": clean_str(rec.get("url")),
        "color": clean_str(rec.get("màu sắc")),
        "warranty": clean_str(rec.get("chính sách bảo hành")),
        "promotion": clean_str(rec.get("promotion")),
        "accessories": clean_str(rec.get("Phụ kiện đi kèm")),
        "rating": parse_rating(rec.get("rating_vote")),
        "quantity_sold": parse_quantity_sold(rec.get("quantity_sold")),
        "original_price": original,
        "promotion_price": promo,
        "effective_price": effective,
        "online_sale_only": bool(rec.get("onlineSaleOnly")),
        "stock_status": "unknown",                          # DMX data has no stock
        "spec": spec,
        "data_quality": {
            "eligible_for_demo": eligible,
            "missing_fields": missing,
            "warnings": warnings,
        },
        "source": {
            "type": "dmx_json",
            "category_id": rec.get("category_id"),
            "product_id": pid,
            "url": clean_str(rec.get("url")),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ap.add_argument("--category", default=None, help="category_name to build (default: all mapped)")
    args = ap.parse_args()

    # NDA source is uploaded out-of-band (Render Secret File); on a deploy where it is
    # not present yet, skip gracefully so the build succeeds and the app falls back to
    # the synthetic demo_catalog instead of hard-failing.
    if not os.path.exists(args.input):
        print(f"[build_dmx_catalog] input not found ({args.input}); "
              "skipping real-catalog build (will use CATALOG_DIR fallback)")
        return

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    wanted = {args.category} if args.category else set(CATEGORY_SLUG)
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for rec in data:
        if rec.get("category_name") not in wanted:
            continue
        built = build_record(rec)
        if built:
            by_slug.setdefault(built["category"], []).append(built)

    os.makedirs(args.outdir, exist_ok=True)
    report: dict[str, Any] = {}
    for slug, recs in by_slug.items():
        path = os.path.join(args.outdir, f"dmx_{slug}.all.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        eligible = [r for r in recs if r["data_quality"]["eligible_for_demo"]]
        with open(os.path.join(args.outdir, f"dmx_{slug}.eligible.json"), "w",
                  encoding="utf-8") as f:
            json.dump(eligible, f, ensure_ascii=False)
        report[slug] = {"total": len(recs), "eligible": len(eligible),
                        "with_price": sum(1 for r in recs if r["effective_price"])}
        print(f"{slug}: {len(recs)} SKU, {report[slug]['with_price']} priced, "
              f"{len(eligible)} eligible -> {os.path.basename(path)}")


if __name__ == "__main__":
    main()
