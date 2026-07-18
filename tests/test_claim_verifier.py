"""Tests for the post-hoc numeric-claim guardrail (antigravity/claim_verifier.py).

Confirms grounded prose passes and drifted money/spec numbers are caught, so the
pipeline degrades a hallucinated explanation back to the deterministic reasons[].
"""
from antigravity.aircon_ranking import NeedProfile
from antigravity.claim_verifier import (
    extract_money_mentions,
    extract_spec_mentions,
    verify_explanation,
)

ITEMS = [
    {"price": 9530000, "spec": {"area_min_m2": 15, "area_max_m2": 22, "indoor_noise_min_db": 14.6}},
    {"price": 9180000, "spec": {"area_min_m2": 15, "area_max_m2": 22, "indoor_noise_min_db": 15.7}},
]
PROFILE = NeedProfile(budget_max=12000000, area_m2=18)


def test_extract_money_forms():
    assert 8_400_000 in extract_money_mentions("giá 8.4 triệu")
    assert 8380000.0 in extract_money_mentions("giá 8.380.000đ")


def test_extract_spec_units():
    units = {m.unit for m in extract_spec_mentions("18m2, 14.6 dB, 300 lít")}
    assert {"m²", "dB", "lít"} <= units


def test_grounded_prose_passes():
    text = "Casper 9.5 triệu, độ ồn 14.6 dB, hợp phòng 18m²."
    assert verify_explanation(text, ITEMS, PROFILE).ok


def test_fabricated_price_and_spec_caught():
    res = verify_explanation("Máy này giá 7.2 triệu, độ ồn 30 dB.", ITEMS, PROFILE)
    assert not res.ok
    kinds = {(u["type"], u.get("unit")) for u in res.unverified}
    assert ("money", None) in kinds
    assert ("spec", "dB") in kinds


def test_pairwise_price_difference_allowed():
    # 9.53tr - 9.18tr = 350k → the LLM may legitimately cite the gap
    assert verify_explanation("chênh lệch 350.000đ", ITEMS, PROFILE).ok


def test_budget_slot_is_known():
    # user's own budget (12 triệu) is a known fact, not a hallucination
    assert verify_explanation("trong ngân sách 12 triệu", ITEMS, PROFILE).ok


def test_empty_text_ok():
    assert verify_explanation("", ITEMS, PROFILE).ok
    assert verify_explanation(None, ITEMS, PROFILE).ok
