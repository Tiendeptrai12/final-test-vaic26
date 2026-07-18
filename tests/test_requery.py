"""Requery agent tests — mocked FPT, fail-open. No API in CI."""
from __future__ import annotations

import json
from antigravity import requery, fpt_client


def test_inbound_rewrite_normalizes(monkeypatch):
    monkeypatch.setattr(fpt_client, "chat_completion",
        lambda *a, **k: json.dumps({"rewritten_query": "điều hòa dưới 20 triệu phòng 18m²",
                                    "user_terms": ["đh", "êm"]}))
    out = requery.rewrite_inbound("đh dưới 20tr phòng 18m2 chạy êm")
    assert out["rewritten_query"].startswith("điều hòa")
    assert out["user_terms"] == ["đh", "êm"]


def test_inbound_fails_open(monkeypatch):
    def boom(*a, **k): raise fpt_client.FPTError("timeout")
    monkeypatch.setattr(fpt_client, "chat_completion", boom)
    out = requery.rewrite_inbound("máy lạnh 20 triệu")
    assert out["rewritten_query"] == "máy lạnh 20 triệu" and out["user_terms"] == []


def test_inbound_malformed_json_fails_open(monkeypatch):
    monkeypatch.setattr(fpt_client, "chat_completion", lambda *a, **k: "not json")
    out = requery.rewrite_inbound("abc")
    assert out["rewritten_query"] == "abc"


def test_outbound_naturalizes(monkeypatch):
    monkeypatch.setattr(fpt_client, "chat_completion",
        lambda *a, **k: "Với phòng nhỏ chạy êm của mình, Daikin 15.4 triệu là hợp nhất ạ.")
    items = [{"name": "Daikin X", "price": 15_400_000, "rating": 4.8,
              "reasons": ["chạy êm (19 dB)"], "spec": {}}]
    out = requery.naturalize_response("phòng nhỏ chạy êm", items,
                                      user_terms=["chạy êm"], fallback_message="fb")
    assert "Daikin" in out and out != "fb"


def test_outbound_no_items_returns_fallback():
    assert requery.naturalize_response("x", [], fallback_message="fb") == "fb"


def test_outbound_fails_open(monkeypatch):
    def boom(*a, **k): raise fpt_client.FPTError("timeout")
    monkeypatch.setattr(fpt_client, "chat_completion", boom)
    items = [{"name": "A", "price": 1, "spec": {}}]
    assert requery.naturalize_response("x", items, fallback_message="fb") == "fb"
