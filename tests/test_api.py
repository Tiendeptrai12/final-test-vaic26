"""Integration tests for FastAPI endpoints in antigravity.views."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app

client = TestClient(app)


# --- /api/health ------------------------------------------------------------
class TestHealthEndpoint:
    def test_health_returns_200(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_status_field(self):
        data = client.get("/api/health").json()
        assert data["status"] == "healthy"

    def test_health_reports_api_key_status(self):
        data = client.get("/api/health").json()
        assert data["fpt_api_key"] in ("Configured", "Missing")


# --- /api/chat --------------------------------------------------------------
class TestChatEndpoint:
    def test_chat_returns_200_with_valid_query(self):
        resp = client.post("/api/chat", json={"query": "Tìm máy lạnh inverter"})
        assert resp.status_code == 200

    def test_chat_response_structure(self):
        resp = client.post("/api/chat", json={"query": "tủ lạnh"})
        data = resp.json()
        assert "query" in data
        assert "response" in data
        assert "safety_checked" in data
        assert "source_nodes" in data

    def test_chat_echoes_query(self):
        q = "laptop cho sinh viên"
        data = client.post("/api/chat", json={"query": q}).json()
        assert data["query"] == q

    def test_chat_safety_checked_true(self):
        data = client.post("/api/chat", json={"query": "máy giặt"}).json()
        assert data["safety_checked"] is True

    def test_chat_source_nodes_is_list(self):
        data = client.post("/api/chat", json={"query": "điện thoại"}).json()
        assert isinstance(data["source_nodes"], list)

    def test_chat_response_is_vietnamese(self):
        data = client.post("/api/chat", json={"query": "máy lạnh"}).json()
        assert "Điện Máy Xanh" in data["response"]

    def test_chat_empty_query_returns_400(self):
        resp = client.post("/api/chat", json={"query": ""})
        assert resp.status_code == 400

    def test_chat_whitespace_query_returns_400(self):
        resp = client.post("/api/chat", json={"query": "   "})
        assert resp.status_code == 400

    def test_chat_missing_query_field_returns_422(self):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 422

    def test_chat_wrong_method_not_200(self):
        resp = client.get("/api/chat")
        assert resp.status_code in (404, 405)  # static mount may intercept as 404


# --- static frontend serving ------------------------------------------------
class TestStaticServing:
    def test_root_serves_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
