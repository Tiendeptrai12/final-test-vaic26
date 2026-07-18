"""
tests/test_reranker.py — reranker generic + fallback an toàn.

Không gọi API thật: mock `_call_rerank_api` hoặc bật/tắt flag qua settings.
Kiểm 3 nhóm: (1) rerank đổi thứ tự khi bật + API ok, (2) fallback giữ nguyên
thứ tự khi tắt/lỗi/timeout, (3) generic cho cả 14 category (không crash, không
rẽ nhánh theo tên ngành).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.ranking import reranker
from app.ranking.rank_products import rank_products
from app.retrieval.filter_products import FilterResult

# Đúng 14 category theo registry.json (field "category").
ALL_CATEGORIES = [
    "air_conditioner", "refrigerator", "washing_machine", "dryer", "dishwasher",
    "freezer", "water_heater", "monitor", "desktop_pc", "tablet", "smartwatch",
    "printer", "karaoke_mic", "phone_mic",
]


def prod(id_, price, spec=None):
    return {
        "product_id": id_,
        "model_code": id_,
        "name": f"Sản phẩm {id_}",
        "brand": "BrandX",
        "effective_price": price,
        "spec": spec or {},
    }


def state_with(category, slots):
    return SimpleNamespace(category=category, slots=slots)


@pytest.fixture
def enable_rerank(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_API_URL", "https://fake/rerank")
    monkeypatch.setattr(settings, "RERANK_API_KEY", "fake-key")
    monkeypatch.setattr(settings, "RERANK_ALPHA", 0.5)
    monkeypatch.setattr(settings, "RERANK_CANDIDATE_POOL", 20)


# --- (1) rerank bật + API ok -> đổi thứ tự -------------------------------

def test_rerank_reorders_when_api_prefers_lower_ranked(monkeypatch, enable_rerank):
    # Rule-based: A > B > C theo total_score đầu vào (đặt sẵn).
    scored = [
        {"product_id": "A", "total_score": 90, "effective_price": 10, "product": prod("A", 10)},
        {"product_id": "B", "total_score": 80, "effective_price": 11, "product": prod("B", 11)},
        {"product_id": "C", "total_score": 70, "effective_price": 12, "product": prod("C", 12)},
    ]
    # API chấm C cao nhất -> blend đẩy C lên đầu.
    def fake_api(query, documents):
        return [
            {"index": 0, "relevance_score": 0.1},
            {"index": 1, "relevance_score": 0.2},
            {"index": 2, "relevance_score": 0.99},
        ]
    monkeypatch.setattr(reranker, "_call_rerank_api", fake_api)

    out = reranker.rerank_results("query", scored)
    assert out[0]["product_id"] == "C"
    assert out[0]["rerank_score"] == 0.99
    assert "final_score" in out[0]


# --- (2) fallback an toàn -------------------------------------------------

def test_fallback_when_disabled_keeps_order(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    scored = [{"product_id": "A", "total_score": 90}, {"product_id": "B", "total_score": 80}]
    out = reranker.rerank_results("q", scored)
    assert [r["product_id"] for r in out] == ["A", "B"]


def test_fallback_when_api_errors_keeps_order(monkeypatch, enable_rerank):
    monkeypatch.setattr(reranker, "_call_rerank_api", lambda q, d: None)  # mô phỏng timeout/500
    scored = [
        {"product_id": "A", "total_score": 90, "effective_price": 10, "product": prod("A", 10)},
        {"product_id": "B", "total_score": 80, "effective_price": 11, "product": prod("B", 11)},
    ]
    out = reranker.rerank_results("q", scored)
    assert [r["product_id"] for r in out] == ["A", "B"]


def test_fallback_single_candidate_no_api_call(monkeypatch, enable_rerank):
    called = {"n": 0}
    monkeypatch.setattr(reranker, "_call_rerank_api", lambda q, d: called.__setitem__("n", called["n"] + 1) or None)
    out = reranker.rerank_results("q", [{"product_id": "A", "total_score": 90}])
    assert [r["product_id"] for r in out] == ["A"]
    assert called["n"] == 0


def test_call_api_returns_none_without_config(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_API_URL", None)
    assert reranker._call_rerank_api("q", ["d"]) is None


# --- (3) generic cho cả 14 category --------------------------------------

def test_rerank_generic_all_14_categories(monkeypatch, enable_rerank):
    """Bật rerank + API đảo ngược thứ tự cho MỌI category — không rẽ nhánh
    theo tên ngành, không crash, contract RankingResult giữ nguyên."""
    def reverse_api(query, documents):
        # Chấm ngược: document cuối điểm cao nhất.
        n = len(documents)
        return [{"index": i, "relevance_score": (i + 1) / n} for i in range(n)]
    monkeypatch.setattr(reranker, "_call_rerank_api", reverse_api)

    for cat in ALL_CATEGORIES:
        retrieval = FilterResult(
            status="ok",
            products=[prod(f"{cat}-1", 10_000_000), prod(f"{cat}-2", 12_000_000)],
        )
        state = state_with(cat, {"budget_max": 20_000_000})
        result = rank_products(retrieval, state)
        assert result.status == "ok", cat
        assert result.results, cat
        assert result.results[0]["rank"] == 1, cat
        # rerank_score optional được gắn khi bật.
        assert "rerank_score" in result.results[0], cat


def test_rank_products_unaffected_when_rerank_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    retrieval = FilterResult(status="ok", products=[prod("P1", 10_000_000), prod("P2", 25_000_000)])
    state = state_with("desktop_pc", {"budget_max": 15_000_000})
    result = rank_products(retrieval, state)
    assert result.results[0]["product_id"] == "P1"
    assert "rerank_score" not in result.results[0]


def test_build_document_text_generic_no_category_branch():
    text = reranker.build_document_text(prod("X", 5_000_000, spec={"cong_suat": "1HP", "features": ["a", "b"]}))
    assert "Sản phẩm X" in text
    assert "BrandX" in text
    assert "cong_suat: 1HP" in text
