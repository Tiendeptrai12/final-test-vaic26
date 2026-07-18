"""C8 Teach tests — side branch, grounded glossary, context gating."""
from __future__ import annotations

from antigravity import teach as T


def test_detect_term_and_worth():
    assert T.detect_term("inverter là gì") == "inverter"
    assert T.detect_term("ram bao nhiêu là đủ") == "ram"
    assert T.detect_term("xyz là gì") is None
    assert T.is_worth_it_question("có đáng trả thêm cho oled không") is True
    assert T.is_worth_it_question("oled là gì") is False


def test_bare_concept_defines_now_then_offers():
    r = T.teach("inverter là gì")
    assert r["mode"] == "teach" and r["term"] == "inverter"
    assert r["definition"] and "sản phẩm nào" in r["message"]  # offer to tie into purchase
    assert r["needs_context"] == []


def test_worth_it_without_context_asks_product_and_budget():
    r = T.teach("có đáng trả thêm cho inverter không")
    assert set(r["needs_context"]) == {"mặt hàng/model", "ngân sách"}


def test_worth_it_with_context_concludes():
    r = T.teach("có đáng trả thêm cho inverter không", has_product=True, has_budget=True)
    assert r["needs_context"] == [] and r["definition"]


def test_unknown_term_is_honest_not_fabricated():
    r = T.teach("blkxyz là gì")
    assert r["term"] is None and r["definition"] is None
    assert "chưa có sẵn giải thích" in r["message"]
