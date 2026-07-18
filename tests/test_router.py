"""C0 Router tests — deterministic intent + category classification."""
from __future__ import annotations

from antigravity import router as R


def test_intents_per_scenario():
    cases = {
        "tôi muốn mua máy lạnh": R.INTENT_EXPLORE,
        "máy lạnh dưới 15 triệu phòng 18m2 chạy êm": R.INTENT_SPECIFIC,
        "inverter là gì": R.INTENT_TEACH,
        "so sánh 2 tủ lạnh này": R.INTENT_COMPARE,
        "nếu tăng ngân sách lên 18 triệu thì sao": R.INTENT_WHAT_IF,
        "tiết kiệm điện quan trọng hơn độ êm": R.INTENT_CHANGE_PRIORITY,
        "màn hình này có hợp với pc không": R.INTENT_COMPATIBILITY,
        "có nên nâng cấp lên 55 inch không": R.INTENT_UPGRADE,
        "mẫu aqua này có phù hợp không": R.INTENT_EXACT_LOOKUP,
    }
    for text, intent in cases.items():
        assert R.route(text).intent == intent, text


def test_category_and_ranker():
    assert R.detect_category("máy lạnh phòng 18m2") == ("Máy lạnh", "aircon")
    assert R.detect_category("điện thoại pin trâu") == ("Điện thoại", "phone")
    assert R.detect_category("tủ lạnh 300 lít") == ("Tủ lạnh", "fridge")
    assert R.detect_category("cho tôi lời khuyên") == (None, None)


def test_url_and_pid_trigger_lookup():
    assert R.route("https://www.dienmayxanh.com/dieu-hoa/x").intent == R.INTENT_EXACT_LOOKUP
    assert R.route("sản phẩm 336956 giá bao nhiêu").intent == R.INTENT_EXACT_LOOKUP


def test_abstract_need_flagged():
    r = R.route("điện thoại cho trẻ em dưới 8 triệu")
    assert r.abstract_need is not None and r.ranker == "phone"


def test_router_does_not_crash_on_empty():
    r = R.route("")
    assert r.intent == R.INTENT_EXPLORE and r.category is None
