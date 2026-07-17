"""Phase 3 NLU tests. fpt_client.chat_completion is MOCKED -> $0, no real API in CI.

One optional live smoke behind FPT_LIVE_SMOKE=1 (skipped by default).
"""
from __future__ import annotations

import json
import os

import pytest

from antigravity import nlu, fpt_client
from antigravity.aircon_ranking import NeedProfile


def _mock_llm(monkeypatch, payload):
    """Patch chat_completion to return `payload` (str returned as-is, else JSON-dumped)."""
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    def fake(model, messages, **kw):
        return body

    monkeypatch.setattr(fpt_client, "chat_completion", fake)


# --- coercion / unit parsing ------------------------------------------------
def test_coerce_numeric_fields():
    p = nlu.coerce_profile({
        "budget_max": 20000000, "area_m2": 18, "priority": "quiet",
        "inverter_required": True, "brands": ["Daikin"], "sunny": False,
        "room_type": "bedroom",
    })
    assert p == NeedProfile(
        budget_max=20000000, area_m2=18.0, priority="quiet", inverter_required=True,
        brands=["Daikin"], sunny=False, room_type="bedroom",
    )


def test_price_unit_strings():
    assert nlu._coerce_price("20 triệu") == 20_000_000
    assert nlu._coerce_price("15tr") == 15_000_000
    assert nlu._coerce_price("9.500.000") == 9_500_000
    assert nlu._coerce_price("1,5 triệu") == 1_500_000
    assert nlu._coerce_price(0) is None
    assert nlu._coerce_price(None) is None
    assert nlu._coerce_price(True) is None


def test_area_variants():
    assert nlu._coerce_area("18m2") == 18.0
    assert nlu._coerce_area("20,5 m²") == 20.5
    assert nlu._coerce_area(25) == 25.0
    assert nlu._coerce_area(0) is None


def test_invalid_enum_and_bool_to_none():
    p = nlu.coerce_profile({"priority": "banana", "room_type": "kitchen",
                            "inverter_required": "maybe"})
    assert p.priority is None and p.room_type is None and p.inverter_required is None


def test_brands_string_or_list():
    assert nlu.coerce_profile({"brands": "LG"}).brands == ["LG"]
    assert nlu.coerce_profile({"brands": ["Daikin", " ", "LG"]}).brands == ["Daikin", "LG"]
    assert nlu.coerce_profile({"brands": None}).brands == []


# --- JSON extraction --------------------------------------------------------
def test_parse_json_strips_code_fence():
    obj = nlu._parse_json('```json\n{"area_m2": 18}\n```')
    assert obj == {"area_m2": 18}


def test_parse_json_finds_embedded_object():
    obj = nlu._parse_json('Đây là kết quả: {"budget_max": 20000000} nhé')
    assert obj == {"budget_max": 20000000}


# --- extract_need_profile (mocked) ------------------------------------------
def test_extract_full(monkeypatch):
    _mock_llm(monkeypatch, {"budget_max": 20000000, "area_m2": 18, "priority": "quiet"})
    p, missing, raw = nlu.extract_need_profile("máy lạnh dưới 20 triệu phòng 18m2 ít ồn")
    assert p.budget_max == 20000000 and p.area_m2 == 18.0 and p.priority == "quiet"
    assert missing == []
    assert raw == {"budget_max": 20000000, "area_m2": 18, "priority": "quiet"}


def test_extract_code_switching(monkeypatch):
    _mock_llm(monkeypatch, {"budget_max": 15000000, "area_m2": 22, "brands": ["Daikin"]})
    p, missing, _ = nlu.extract_need_profile("need a quiet AC, budget 15tr, phòng 22m2")
    assert p.budget_max == 15000000 and p.area_m2 == 22.0 and p.brands == ["Daikin"]
    assert missing == []


def test_extract_missing_slots(monkeypatch):
    _mock_llm(monkeypatch, {"priority": "energy_saving"})  # no area, no budget
    p, missing, _ = nlu.extract_need_profile("tư vấn máy lạnh tiết kiệm điện")
    assert set(missing) == {"area_m2", "budget_max"}
    assert p.priority == "energy_saving"


def test_extract_malformed_json_fallback(monkeypatch):
    _mock_llm(monkeypatch, "sorry I cannot help with that")
    p, missing, raw = nlu.extract_need_profile("hello")
    assert p == NeedProfile()
    assert set(missing) == {"area_m2", "budget_max"}
    assert raw is None


def test_extract_llm_error_fallback(monkeypatch):
    def boom(*a, **k):
        raise fpt_client.FPTError("timeout")
    monkeypatch.setattr(fpt_client, "chat_completion", boom)
    p, missing, raw = nlu.extract_need_profile("máy lạnh 20 triệu 18m2")
    assert p == NeedProfile() and raw is None
    assert set(missing) == {"area_m2", "budget_max"}


# --- follow-up templates ----------------------------------------------------
def test_followups_are_vietnamese_questions():
    qs = nlu.followups(["area_m2", "budget_max"])
    assert len(qs) == 2 and all(q.endswith("?") for q in qs)


# --- advise() wiring --------------------------------------------------------
def _rec(pid, price, amin, amax, noise, cspf, brand="Daikin"):
    return {
        "product_id": pid, "brand": brand, "effective_price": price,
        "category": "air_conditioner", "stock_status": "unknown",
        "spec": {"area_min_m2": amin, "area_max_m2": amax, "indoor_noise_min_db": noise,
                 "cspf": cspf, "energy_stars": None, "inverter": True, "features": []},
        "data_quality": {"eligible_for_demo": True, "missing_fields": [], "warnings": []},
        "source": {"type": "btc_excel", "sheet": "Máy lạnh", "source_row": 2, "sku": pid},
    }


def test_advise_need_info(monkeypatch):
    _mock_llm(monkeypatch, {"priority": "quiet"})
    out = nlu.advise("máy lạnh chạy êm")
    assert out["status"] == "need_info"
    assert set(out["missing"]) == {"area_m2", "budget_max"}
    assert out["questions"]


def test_advise_ok_ranks(monkeypatch):
    _mock_llm(monkeypatch, {"budget_max": 20000000, "area_m2": 18, "priority": "quiet"})
    records = [
        _rec("A", 10_000_000, 15, 20, 30, 6.2),
        _rec("B", 18_000_000, 15, 20, 42, 4.5),
        _rec("C", 12_000_000, 15, 20, 33, 5.5),
    ]
    out = nlu.advise("máy lạnh dưới 20 triệu phòng 18m2 ít ồn", records=records)
    assert out["status"] == "ok"
    assert len(out["result"].items) >= 1
    # quietest (A, 30dB) should top a quiet-priority ranking
    assert out["result"].items[0].product_id == "A"


# --- build_chat_response (API contract) -------------------------------------
def test_chat_response_recommendation(monkeypatch):
    _mock_llm(monkeypatch, {"budget_max": 20000000, "area_m2": 18, "priority": "quiet"})
    records = [
        _rec("A", 10_000_000, 15, 20, 30, 6.2),
        _rec("B", 18_000_000, 15, 20, 42, 4.5),
    ]
    resp = nlu.build_chat_response("máy lạnh 20 triệu phòng 18m2 êm", records=records)
    assert resp["mode"] == "recommendation"
    assert resp["items"] and resp["items"][0]["product_id"] == "A"
    assert "price" in resp["items"][0] and "reasons" in resp["items"][0]
    assert resp["safety_checked"] is True
    # JSON-serializable (no dataclasses leak into the contract)
    json.dumps(resp, ensure_ascii=False)


def test_chat_response_need_info(monkeypatch):
    _mock_llm(monkeypatch, {"priority": "quiet"})
    resp = nlu.build_chat_response("máy lạnh chạy êm")
    assert resp["mode"] == "need_info"
    assert resp["message"] and resp["questions"]
    assert resp["items"] == []


def test_chat_response_no_results(monkeypatch):
    _mock_llm(monkeypatch, {"budget_max": 1_000_000, "area_m2": 18})  # too cheap
    resp = nlu.build_chat_response("máy lạnh 1 triệu phòng 18m2",
                                   records=[_rec("A", 10_000_000, 15, 20, 30, 6.2)])
    assert resp["mode"] == "recommendation" and resp["items"] == []
    assert "Chưa có sản phẩm phù hợp" in resp["message"]


def test_chat_endpoint_gate_mock_default(monkeypatch):
    """CATALOG_SOURCE unset -> endpoint keeps the mock path (data-free, Vercel-safe)."""
    from antigravity import btc_catalog
    monkeypatch.setattr(btc_catalog, "is_btc_enabled", lambda: False)
    from fastapi.testclient import TestClient
    from antigravity.views import router
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(router, prefix="/api")
    r = TestClient(app).post("/api/chat", json={"query": "máy lạnh"})
    assert r.status_code == 200 and "response" in r.json()  # mock shape


# --- optional live smoke ----------------------------------------------------
@pytest.mark.skipif(os.environ.get("FPT_LIVE_SMOKE") != "1",
                    reason="live FPT smoke disabled (set FPT_LIVE_SMOKE=1)")
def test_live_smoke():
    p, missing, raw = nlu.extract_need_profile("máy lạnh dưới 20 triệu phòng 18m2 ít ồn")
    assert p.budget_max == 20000000 and p.area_m2 == 18.0 and p.priority == "quiet"
