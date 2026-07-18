"""C6 Evaluate — fit / compatibility / incremental-upgrade (grounded, deterministic).

Contextual comparison lives in comparison.py; this module adds the other three C6 modes.
Every verdict is built only from real record fields — when a needed field is missing, the
verdict is honest ("chưa đủ dữ liệu"), never fabricated. Output feeds C7 Advise.

Product dicts are the canonical/ranked shape (price, spec{...}, name, url) or raw DMX; both
`price` and `effective_price`/`Giá …` are accepted.
"""
from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _price(p: dict[str, Any]) -> int | None:
    for k in ("price", "effective_price", "Giá khuyến mãi", "Giá gốc"):
        v = p.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return None


def _spec(p: dict[str, Any]) -> dict[str, Any]:
    return p.get("spec") or p.get("spec_product") or {}


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"[\d.,]+", v)
        if m:
            return float(m.group(0).replace(".", "").replace(",", ".")) if v.strip()[0].isdigit() \
                else float(m.group(0).replace(",", "."))
    return None


# --------------------------------------------------------------------------- #
# 1. Fit evaluation — does this product fit the user's need?
# --------------------------------------------------------------------------- #
def evaluate_fit(
    product: dict[str, Any], *, budget_max: int | None = None, area_m2: float | None = None,
    min_storage_gb: float | None = None, min_ram_gb: float | None = None,
) -> dict[str, Any]:
    """Grounded fit verdict + per-criterion rows. Only checks constraints that were given."""
    spec = _spec(product)
    rows: list[dict[str, Any]] = []
    hard_fail = False
    unknown = 0

    def check(label, ok, detail):
        nonlocal hard_fail, unknown
        if ok is None:
            unknown += 1
        elif not ok:
            hard_fail = True
        rows.append({"criterion": label, "ok": ok, "detail": detail})

    price = _price(product)
    if budget_max is not None:
        if price is None:
            check("Ngân sách", None, "chưa có giá")
        else:
            check("Ngân sách", price <= budget_max,
                  f"giá {price/1_000_000:.1f}tr" + ("" if price <= budget_max else " > ngân sách"))

    if area_m2 is not None:
        amin = _num(spec.get("area_min_m2")) or _num(spec.get("Phạm vi làm lạnh hiệu quả"))
        amax = _num(spec.get("area_max_m2"))
        if amin is None or amax is None:
            check("Diện tích", None, "chưa có phạm vi làm lạnh")
        else:
            ok = amin - 1 <= area_m2 <= amax + 1
            check("Diện tích", ok, f"hợp {amin:g}-{amax:g}m² (phòng {area_m2:g}m²)")

    if min_storage_gb is not None:
        st = _num(spec.get("storage_gb")) or _num(spec.get("Dung lượng lưu trữ"))
        check("Bộ nhớ", None if st is None else st >= min_storage_gb,
              f"{st:g}GB" if st else "chưa có dữ liệu")

    if min_ram_gb is not None:
        ram = _num(spec.get("ram_gb")) or _num(spec.get("RAM"))
        check("RAM", None if ram is None else ram >= min_ram_gb,
              f"{ram:g}GB" if ram else "chưa có dữ liệu")

    if hard_fail:
        verdict = "không phù hợp"
    elif unknown and not any(r["ok"] for r in rows):
        verdict = "chưa đủ dữ liệu"
    elif unknown:
        verdict = "phù hợp một phần"
    else:
        verdict = "phù hợp"
    return {"mode": "fit", "product_id": product.get("product_id"),
            "name": product.get("name") or product.get("tên sản phẩm"),
            "verdict": verdict, "rows": rows}


# --------------------------------------------------------------------------- #
# 2. Compatibility — can two items work together?
# --------------------------------------------------------------------------- #
def _ports(p: dict[str, Any]) -> str:
    s = _spec(p)
    blob = " ".join(str(v) for k, v in s.items()
                    if re.search(r"cổng|kết\s*nối|port|ngõ", k, re.IGNORECASE))
    return blob.lower()


def evaluate_compatibility(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Grounded-ish compatibility. Honest 'chưa đủ dữ liệu' when port/connection fields absent."""
    pa, pb = _ports(a), _ports(b)
    if not pa and not pb:
        verdict, note = "chưa đủ dữ liệu", "Chưa có thông tin cổng/kết nối để khẳng định."
    else:
        common = re.findall(r"hdmi|usb-?c|usb|type-?c|displayport|dp|vga|3\.5mm|bluetooth|wifi",
                            pa + " " + pb)
        shared = set(re.findall(r"hdmi|usb-?c|usb|type-?c|displayport|dp|vga|bluetooth|wifi", pa)) \
            & set(re.findall(r"hdmi|usb-?c|usb|type-?c|displayport|dp|vga|bluetooth|wifi", pb))
        if shared:
            verdict, note = "tương thích", f"Cùng hỗ trợ: {', '.join(sorted(shared))}."
        elif common:
            verdict, note = "cần adapter", "Có cổng nhưng không trùng chuẩn — có thể cần adapter."
        else:
            verdict, note = "chưa đủ dữ liệu", "Không xác định được chuẩn kết nối chung."
    return {"mode": "compatibility", "verdict": verdict, "note": note,
            "items": [a.get("name") or a.get("tên sản phẩm"),
                      b.get("name") or b.get("tên sản phẩm")]}


# --------------------------------------------------------------------------- #
# 3. Incremental upgrade — is upgrading worth the extra money?
# --------------------------------------------------------------------------- #
def evaluate_upgrade(
    current: dict[str, Any], candidate: dict[str, Any], *,
    gain_keys: tuple[str, ...] = ("storage_gb", "ram_gb", "battery_mah", "screen_inch",
                                  "cspf", "area_max_m2"),
) -> dict[str, Any]:
    """Compare incremental spec gains vs price delta. Grounded verdict for C7 Advise."""
    cs, ns = _spec(current), _spec(candidate)
    pc, pn = _price(current), _price(candidate)
    gains: list[str] = []
    for k in gain_keys:
        cv, nv = _num(cs.get(k)), _num(ns.get(k))
        if cv is not None and nv is not None and nv > cv:
            gains.append(f"{k}: {cv:g} → {nv:g}")

    delta = (pn - pc) if (pc and pn) else None
    if not gains and delta is not None and delta > 0:
        verdict = "chưa nên nâng cấp"
        why = "Máy mới đắt hơn nhưng không cải thiện thông số đáng kể."
    elif gains and delta is not None and delta <= 0:
        verdict = "nên nâng cấp"
        why = "Máy mới tốt hơn mà không đắt hơn."
    elif gains and delta is not None:
        verdict = "nên nâng cấp nếu cần"
        why = f"Trả thêm {delta/1_000_000:.1f}tr đổi lấy: {', '.join(gains)}."
    elif gains:
        verdict = "nên nâng cấp nếu cần"
        why = f"Cải thiện: {', '.join(gains)} (chưa đủ dữ liệu giá để cân đối)."
    else:
        verdict = "chưa đủ bằng chứng"
        why = "Thiếu thông số để so sánh lợi ích nâng cấp."
    return {"mode": "upgrade", "verdict": verdict, "why": why, "gains": gains,
            "price_delta": delta}
