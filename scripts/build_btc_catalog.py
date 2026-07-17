"""Stage 2: registry-driven cleaner/extractor for the BTC workbook.

One code path for all 14 sheets. Reads `schemas/registry.json` (built in Stage 1)
to map each sheet's columns -> canonical keys, applies shared normalizers, and runs
deep parsers only where the registry marks `deep_parse: true` (air_conditioner).

Outputs, per category:
    data/processed/btc_<category>.all.jsonl        every record
    data/processed/btc_<category>.eligible.json    eligible_for_demo == true
    artifacts/btc_quality_report.json              aggregate stats only

Deterministic: same workbook -> byte-identical output. UTF-8, ensure_ascii=False.
No real product record is ever printed to stdout/stderr.

Usage:
    python scripts/build_btc_catalog.py \
        --input data/raw/Spec_cate_gia.xlsx \
        --outdir data/processed \
        --report artifacts/btc_quality_report.json [--sheet "Máy lạnh"]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import openpyxl

MISSING_TOKENS = {"", "-", "null", "none", "n/a", "na",
                  "đang cập nhật", "hãng không công bố", "không công bố"}
PLACEHOLDER_WEB_ID = "9999"


# --------------------------------------------------------------------------- #
# scalar normalizers
# --------------------------------------------------------------------------- #
def clean_str(value: Any) -> str | None:
    """Trim; map known missing tokens -> None."""
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    return s or None


def split_list(value: Any) -> list[str]:
    """'a | b |  | a' -> ['a', 'b'] (trim, drop empty, dedupe keep order)."""
    s = clean_str(value)
    if s is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in s.split("|"):
        p = part.strip()
        if p and p not in seen and p.lower() not in MISSING_TOKENS:
            seen.add(p)
            out.append(p)
    return out


def parse_price(value: Any) -> int | None:
    """Digits only; <=0 -> None; non-numeric -> None."""
    s = clean_str(value)
    if s is None:
        return None
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    n = int(digits)
    return n if n > 0 else None


def parse_year(value: Any) -> int | None:
    s = clean_str(value)
    if s is None:
        return None
    m = re.search(r"(19|20)\d{2}", s)
    return int(m.group(0)) if m else None


def parse_inverter(value: Any) -> bool | None:
    s = clean_str(value)
    if s is None:
        return None
    low = s.lower()
    # Check non-inverter FIRST — "non-inverter" contains "inverter"
    if "non-inverter" in low or "không inverter" in low:
        return False
    if "inverter" in low:
        return True
    return None


def parse_area(value: Any) -> tuple[float | None, float | None, str | None]:
    """'Từ 30 - 40m²' -> (30,40); 'Dưới 15m²' -> (0,15). Ignore trailing m³ part."""
    s = clean_str(value)
    if s is None:
        return None, None, None
    head = s.split("(", 1)[0]  # drop '(từ 80 đến 120m³)'
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)", head)
    if m:
        return _f(m.group(1)), _f(m.group(2)), None
    if re.search(r"dưới", head, re.IGNORECASE):
        m2 = re.search(r"(\d+(?:[.,]\d+)?)", head)
        if m2:
            return 0.0, _f(m2.group(1)), None
    return None, None, f"unparsed_area:{s[:40]}"


def parse_energy(value: Any) -> tuple[int | None, float | None, str | None]:
    """'5 sao (Hiệu suất năng lượng 6.23)' -> (5, 6.23)."""
    s = clean_str(value)
    if s is None:
        return None, None, None
    stars_m = re.search(r"(\d+)\s*sao", s, re.IGNORECASE)
    cspf_m = re.search(r"(\d+(?:[.,]\d+)?)\s*\)?\s*$", s)
    cspf_in = re.search(r"([0-9]+(?:[.,][0-9]+))\s*\)", s)
    stars = int(stars_m.group(1)) if stars_m else None
    cspf = _f(cspf_in.group(1)) if cspf_in else (_f(cspf_m.group(1)) if cspf_m else None)
    if stars is None and cspf is None:
        return None, None, f"unparsed_energy:{s[:40]}"
    return stars, cspf, None


def parse_noise(value: Any) -> tuple[float | None, float | None, float | None, str | None]:
    """'Dàn lạnh: 45/34/29 dB - Dàn nóng: 51 dB' -> (29,45,51).
    Single value 'Dàn lạnh: 38 dB' -> (38,38,None)."""
    s = clean_str(value)
    if s is None:
        return None, None, None, None
    parts = re.split(r"[-–]\s*(?=dàn nóng)", s, flags=re.IGNORECASE)
    indoor_nums: list[float] = []
    outdoor: float | None = None
    for part in parts:
        nums = [_f(n) for n in re.findall(r"\d+(?:[.,]\d+)?", part)]
        if re.search(r"dàn nóng", part, re.IGNORECASE):
            if nums:
                outdoor = nums[-1]
        elif re.search(r"dàn lạnh", part, re.IGNORECASE):
            indoor_nums = nums
    if not indoor_nums and outdoor is None:
        allnums = [_f(n) for n in re.findall(r"\d+(?:[.,]\d+)?", s)]
        if not allnums:
            return None, None, None, f"unparsed_noise:{s[:40]}"
        indoor_nums = allnums
    imin = min(indoor_nums) if indoor_nums else None
    imax = max(indoor_nums) if indoor_nums else None
    return imin, imax, outdoor, None


def parse_btu(value: Any) -> tuple[int | None, str | None]:
    """Only when the cell actually carries a BTU figure."""
    s = clean_str(value)
    if s is None:
        return None, None
    m = re.search(r"([\d.,]+)\s*btu", s, re.IGNORECASE)
    if not m:
        return None, None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return (int(digits) if digits else None), None


def _f(x: str) -> float:
    return float(x.replace(",", "."))


# --------------------------------------------------------------------------- #
# record building
# --------------------------------------------------------------------------- #
def _cell(row: dict[str, Any], col: str) -> Any:
    return row.get(col)


def build_record(sheet: str, info: dict[str, Any], row: dict[str, Any],
                 source_row: int) -> dict[str, Any] | None:
    warnings: list[str] = []

    sku = clean_str(_cell(row, "sku"))
    if sku is None:
        return None  # no product_id -> skip (counted by caller)

    web_id = clean_str(_cell(row, "productidweb"))
    if web_id == PLACEHOLDER_WEB_ID:
        web_id = None
        warnings.append("placeholder_productidweb")

    original = parse_price(_cell(row, "giá gốc"))
    promo = parse_price(_cell(row, "giá khuyến mãi"))
    if promo is not None and original is not None and promo > original:
        warnings.append("promotion_gt_original")
    effective = promo if promo else original

    spec: dict[str, Any] = {}
    for m in info["mappings"]:
        col, key, typ = m["source_column"], m["key"], m["type"]
        spec[key] = split_list(_cell(row, col)) if typ == "list" else clean_str(_cell(row, col))

    # deep parse (aircon only)
    if info["deep_parse"]:
        y = parse_year(_cell(row, "Dòng sản phẩm"))
        amin, amax, aw = parse_area(_cell(row, "Phạm vi sử dụng"))
        stars, cspf, ew = parse_energy(_cell(row, "Nhãn năng lượng"))
        imin, imax, outdoor, nw = parse_noise(_cell(row, "Độ ồn"))
        btu, _ = parse_btu(_cell(row, "Công suất đầu ra"))
        inv = parse_inverter(_cell(row, "Loại Inverter")) \
            or parse_inverter(_cell(row, "Công nghệ tiết kiệm điện"))
        spec.update({
            "product_year": y, "area_min_m2": amin, "area_max_m2": amax,
            "cooling_capacity_btu": btu, "energy_stars": stars, "cspf": cspf,
            "indoor_noise_min_db": imin, "indoor_noise_max_db": imax,
            "outdoor_noise_db": outdoor, "inverter": inv,
        })
        for w in (aw, ew, nw):
            if w:
                warnings.append(w)

    record = {
        "product_id": sku,
        "product_web_id": web_id,
        "model_code": clean_str(_cell(row, "model_code")),
        "category": info["category"],
        "brand": clean_str(_cell(row, "brand")),
        "brand_id": clean_str(_cell(row, "brand_id")),
        "category_code": clean_str(_cell(row, "category_code")),
        "original_price": original,
        "promotion_price": promo,
        "effective_price": effective,
        "promotions": split_list(_cell(row, "khuyến mãi quà")),
        "stock_status": "unknown",
        "stock_by_location": {},
        "spec": spec,
        "source": {"type": "btc_excel", "sheet": sheet, "source_row": source_row, "sku": sku},
        "data_quality": {"eligible_for_demo": False, "missing_fields": [], "warnings": warnings},
    }
    record["data_quality"]["eligible_for_demo"] = _eligible(record, info)
    return record


def _eligible(rec: dict[str, Any], info: dict[str, Any]) -> bool:
    if not rec["product_id"]:
        return False
    if not rec["effective_price"] or rec["effective_price"] <= 0:
        return False
    if not info["deep_parse"]:
        return True  # base rule for categories without deep parse
    s = rec["spec"]
    return all([
        (s.get("product_year") or 0) >= 2025,
        s.get("area_min_m2") is not None and s.get("area_max_m2") is not None,
        s.get("inverter") is not None,
        s.get("energy_stars") is not None or s.get("cspf") is not None,
        s.get("indoor_noise_min_db") is not None,
        bool(s.get("features") or s.get("cooling_technology")
             or s.get("energy_saving_technology")),
    ])


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def _rows(ws) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    it = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(it)]
    rows: list[tuple[int, dict[str, Any]]] = []
    for i, raw in enumerate(it, start=2):
        rows.append((i, {header[j]: raw[j] for j in range(len(header)) if j < len(raw)}))
    return header, rows


def process(input_path: Path, outdir: Path, report_path: Path,
            only_sheet: str | None = None) -> dict[str, Any]:
    schemas_dir = Path(__file__).resolve().parent.parent / "schemas"
    registry = json.loads((schemas_dir / "registry.json").read_text(encoding="utf-8"))
    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    outdir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"totals": {}, "by_sheet": {}}
    grand_input = grand_eligible = 0

    for ws in wb.worksheets:
        sheet = ws.title
        if sheet not in registry["sheets"]:
            raise ValueError(f"sheet '{sheet}' missing from registry")
        if only_sheet and sheet != only_sheet:
            continue
        info = registry["sheets"][sheet]
        _, rows = _rows(ws)

        records: list[dict[str, Any]] = []
        seen_sku: set[str] = set()
        dup = no_sku = 0
        warn_counter: Counter[str] = Counter()
        prices: list[int] = []
        years: Counter[int] = Counter()
        completeness: dict[str, int] = defaultdict(int)
        placeholder = promo_gt = 0

        for source_row, row in rows:
            rec = build_record(sheet, info, row, source_row)
            if rec is None:
                no_sku += 1
                continue
            if rec["product_id"] in seen_sku:
                dup += 1
                continue
            seen_sku.add(rec["product_id"])
            records.append(rec)
            for w in rec["data_quality"]["warnings"]:
                warn_counter[w] += 1
            if "placeholder_productidweb" in rec["data_quality"]["warnings"]:
                placeholder += 1
            if "promotion_gt_original" in rec["data_quality"]["warnings"]:
                promo_gt += 1
            if rec["effective_price"]:
                prices.append(rec["effective_price"])
            for k, v in rec["spec"].items():
                if v not in (None, [], ""):
                    completeness[k] += 1
            if info["deep_parse"] and rec["spec"].get("product_year"):
                years[rec["spec"]["product_year"]] += 1

        cat = info["category"]
        all_path = outdir / f"btc_{cat}.all.jsonl"
        elig_path = outdir / f"btc_{cat}.eligible.json"
        with all_path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        eligible = [r for r in records if r["data_quality"]["eligible_for_demo"]]
        elig_path.write_text(
            json.dumps(eligible, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

        report["by_sheet"][sheet] = {
            "category": cat,
            "input_rows": len(rows),
            "rows_without_sku": no_sku,
            "unique_sku": len(records),
            "duplicate_sku": dup,
            "with_effective_price": len(prices),
            "eligible": len(eligible),
            "placeholder_productidweb": placeholder,
            "promotion_gt_original": promo_gt,
            "warnings_by_type": dict(sorted(warn_counter.items())),
            "year_distribution": dict(sorted(years.items())),
            "price_min": min(prices) if prices else None,
            "price_median": int(statistics.median(prices)) if prices else None,
            "price_max": max(prices) if prices else None,
            "field_completeness": dict(sorted(completeness.items())),
        }
        grand_input += len(rows)
        grand_eligible += len(eligible)

    report["totals"] = {
        "sheets_processed": len(report["by_sheet"]),
        "input_rows": grand_input,
        "eligible": grand_eligible,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    wb.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw/Spec_cate_gia.xlsx", type=Path)
    ap.add_argument("--outdir", default="data/processed", type=Path)
    ap.add_argument("--report", default="artifacts/btc_quality_report.json", type=Path)
    ap.add_argument("--sheet", default=None)
    args = ap.parse_args(argv)
    if not args.input.exists():
        print(f"ERROR: input workbook not found: {args.input}", file=sys.stderr)
        return 2
    report = process(args.input, args.outdir, args.report, args.sheet)
    t = report["totals"]
    print(f"processed {t['sheets_processed']} sheet(s), {t['input_rows']} input rows, "
          f"{t['eligible']} eligible. report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
