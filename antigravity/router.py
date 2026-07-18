"""C0 Scenario Router — classify each message into an intent + category, no state reset.

Deterministic keyword/regex routing ($0, fast, testable). Every message passes through here;
the pipeline uses the result to pick a capability chain (see docs/capability_architecture.md).
The router only *classifies* — it never rewrites the Need Profile or fetches data.

Output: RouteResult(intent, category, is_comparison, abstract_need, has_constraints).
Precedence matters: more specific intents win over the generic "explore".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from antigravity.comparison import detect_comparison_intent, extract_abstract_need

# intents map to scenario chains A–I in the architecture doc
INTENT_TEACH = "teach"                 # E  "X là gì / giải thích X"
INTENT_WHAT_IF = "what_if"             # I  "nếu ... thì sao"
INTENT_CHANGE_PRIORITY = "change_priority"  # H  "... quan trọng hơn ..."
INTENT_COMPATIBILITY = "compatibility"      # F  "A hợp B không"
INTENT_UPGRADE = "upgrade"             # G  "có nên nâng cấp / lên đời"
INTENT_COMPARE = "compare"             # D  "so sánh A và B"
INTENT_EXACT_LOOKUP = "exact_lookup"   # C  URL / product id / "mẫu ... này"
INTENT_SPECIFIC = "specific_need"      # B  có ràng buộc cụ thể
INTENT_EXPLORE = "explore"             # A  mơ hồ "muốn mua X"

# category_name (DMX) + which ranking engine handles it. Cụm ĐẶC HIỆU/nhiều từ phải
# đứng TRƯỚC cụm ngắn (vd "máy tính bảng"/"máy tính để bàn" trước "máy tính xách tay";
# "máy sấy quần áo" trước "máy giặt") để detect_category (khớp pattern đầu tiên) không
# gộp nhầm. ranker=None -> chưa có engine chấm điểm riêng, đi nhánh generic (vector rerank).
CATEGORY_PATTERNS = [
    ("Máy lạnh", "aircon", r"máy\s*lạnh|điều\s*hòa|điều\s*hoà"),
    ("Điện thoại", "phone", r"điện\s*thoại|smartphone|iphone|samsung galaxy|dt\b"),
    ("Máy tính bảng", "tablet", r"máy\s*tính\s*bảng|tablet|ipad"),
    ("Máy tính để bàn", None, r"máy\s*tính\s*để\s*bàn|desktop|pc\b|máy\s*bộ"),
    ("Màn hình máy tính", None, r"màn\s*hình(\s*máy\s*tính|\s*vi\s*tính|\s*pc)?|monitor"),
    ("Laptop", "laptop", r"laptop|máy\s*tính\s*xách\s*tay|notebook|macbook"),
    ("Máy sấy quần áo", None, r"máy\s*sấy(\s*quần\s*áo|\s*đồ|\s*áo\s*quần)?"),
    ("Máy rửa chén", None, r"máy\s*rửa\s*(chén|bát)"),
    ("Máy giặt", "washer", r"máy\s*giặt"),
    ("Tủ đông, tủ mát", None, r"tủ\s*đông|tủ\s*mát|tủ\s*(đông\s*)?mát"),
    ("Tủ lạnh", "fridge", r"tủ\s*lạnh"),
    ("Máy nước nóng", None, r"máy\s*nước\s*nóng|bình\s*nóng\s*lạnh|bình\s*nước\s*nóng"),
    ("Đồng hồ thông minh", None, r"đồng\s*hồ\s*thông\s*minh|smartwatch|smart\s*watch"),
    ("Micro", None, r"\bmicro\b|\bmic\b|mi-?crô"),
    ("Máy in", None, r"máy\s*in|printer"),
    ("Tivi", "tv", r"\btivi\b|\btv\b|smart\s*tv"),
]

_URL_RE = re.compile(r"https?://|dienmayxanh\.com", re.IGNORECASE)
_PID_RE = re.compile(r"\b\d{5,7}\b")            # DMX product_id looks like 336956
_TEACH_RE = re.compile(r"\blà\s*gì\b|\bnghĩa\s*là\b|\bgiải\s*thích\b|\bhiểu\s*(sao|thế\s*nào)\b",
                       re.IGNORECASE)
_WHATIF_RE = re.compile(r"\bnếu\b.+\b(thì|sao)\b|\bgiả\s*sử\b|\bví\s*dụ\s*tăng\b", re.IGNORECASE)
_PRIORITY_RE = re.compile(r"quan\s*trọng\s*hơn|ưu\s*tiên\b.+\bhơn|\bhơn\s*(là\s*)?(giá|độ|độ ồn)\b",
                          re.IGNORECASE)
# compatibility needs a TWO-item signal ("với") — a bare "hợp không" is single-product fit,
# not compatibility, so it must fall through to exact_lookup / fit evaluation.
_COMPAT_RE = re.compile(r"tương\s*thích|hợp\s*với|kết\s*nối\s*(được|với)|dùng\s*chung|gắn\s*được",
                        re.IGNORECASE)
_UPGRADE_RE = re.compile(r"nâng\s*cấp|lên\s*đời|có\s*nên\s*(đổi|thay|lên)|đổi\s*(lên|sang)\b",
                         re.IGNORECASE)
_LOOKUP_HINT_RE = re.compile(r"\bmẫu\b|\bmodel\b|\bcon\b\s*này|\bsản\s*phẩm\s*này\b", re.IGNORECASE)
# a constraint = a budget/size number or an explicit preference word
_CONSTRAINT_RE = re.compile(
    r"\d+\s*(triệu|tr|m2|m²|inch|lít|gb|hp)\b|dưới\s*\d|khoảng\s*\d|"
    r"ít\s*ồn|tiết\s*kiệm|chạy\s*êm|pin\s*(trâu|khỏe)|ngân\s*sách", re.IGNORECASE)


@dataclass
class RouteResult:
    intent: str
    category: str | None            # DMX category_name, e.g. "Máy lạnh"
    ranker: str | None              # "aircon" | "phone" | ... | None
    is_comparison: bool
    abstract_need: str | None       # concrete rerank phrase, if a soft lifestyle need
    has_constraints: bool


def detect_category(text: str) -> tuple[str | None, str | None]:
    low = (text or "").lower()
    for cat, ranker, pat in CATEGORY_PATTERNS:
        if re.search(pat, low):
            return cat, ranker
    return None, None


def route(text: str) -> RouteResult:
    """Classify a message. Deterministic; does not touch state."""
    t = text or ""
    low = t.strip().lower()
    cat, ranker = detect_category(t)
    is_cmp = detect_comparison_intent(t)
    abstract = extract_abstract_need(t)
    has_constraints = bool(_CONSTRAINT_RE.search(low))

    # precedence: specific intents before generic explore
    if _TEACH_RE.search(low):
        intent = INTENT_TEACH
    elif _WHATIF_RE.search(low):
        intent = INTENT_WHAT_IF
    elif _COMPAT_RE.search(low):
        intent = INTENT_COMPATIBILITY
    elif _UPGRADE_RE.search(low):
        intent = INTENT_UPGRADE
    elif _PRIORITY_RE.search(low):
        intent = INTENT_CHANGE_PRIORITY
    elif is_cmp:
        intent = INTENT_COMPARE
    elif _URL_RE.search(t) or _PID_RE.search(t) or _LOOKUP_HINT_RE.search(low):
        intent = INTENT_EXACT_LOOKUP
    elif has_constraints:
        intent = INTENT_SPECIFIC
    else:
        intent = INTENT_EXPLORE

    return RouteResult(
        intent=intent, category=cat, ranker=ranker, is_comparison=is_cmp,
        abstract_need=abstract, has_constraints=has_constraints,
    )
