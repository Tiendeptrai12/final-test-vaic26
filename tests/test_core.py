"""Unit tests for antigravity.core — ProductAdvisor logic. No external API calls."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from antigravity.core import ProductAdvisor, get_fpt_api_key, load_env


# --- load_env ---------------------------------------------------------------
def test_load_env_sets_variable(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TEST_CORE_VAR=hello123\n", encoding="utf-8")
    load_env(str(env))
    assert os.environ.get("TEST_CORE_VAR") == "hello123"
    os.environ.pop("TEST_CORE_VAR", None)


def test_load_env_skips_comments_and_blanks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nMY_KEY=val\n", encoding="utf-8")
    load_env(str(env))
    assert os.environ.get("MY_KEY") == "val"
    os.environ.pop("MY_KEY", None)


def test_load_env_missing_file_no_crash():
    load_env("nonexistent_file_path_xyz.env")  # should not raise


# --- get_fpt_api_key --------------------------------------------------------
def test_get_fpt_api_key_returns_env():
    with patch.dict(os.environ, {"FPT_API_KEY": "test_key_abc"}):
        assert get_fpt_api_key() == "test_key_abc"


def test_get_fpt_api_key_empty_when_unset():
    env = os.environ.copy()
    env.pop("FPT_API_KEY", None)
    with patch.dict(os.environ, env, clear=True):
        assert get_fpt_api_key() == ""


# --- ProductAdvisor ---------------------------------------------------------
class TestProductAdvisor:
    @pytest.fixture
    def advisor(self):
        return ProductAdvisor()

    def test_init_loads_configs(self, advisor):
        # guard_config should load from YAML
        assert isinstance(advisor.guard_config, dict)
        assert "guardrails_config" in advisor.guard_config

    def test_scan_catalog_returns_list(self, advisor):
        results = advisor._scan_catalog_with_llama("máy lạnh")
        assert isinstance(results, list)
        assert len(results) <= 3  # default similarity_top_k

    def test_scan_catalog_respects_limit(self, advisor):
        results = advisor._scan_catalog_with_llama("test")
        limit = advisor.researcher_config.get("llama_index_config", {}).get("similarity_top_k", 3)
        assert len(results) <= limit

    def test_generate_response_contains_product_names(self, advisor):
        catalog = [
            {"name": "Máy Lạnh Daikin", "price": "10,990,000đ"},
            {"name": "Tủ Lạnh Panasonic", "price": "14,500,000đ"},
        ]
        resp = advisor._generate_response("test query", catalog)
        assert "Máy Lạnh Daikin" in resp
        assert "Tủ Lạnh Panasonic" in resp

    def test_generate_response_empty_catalog(self, advisor):
        resp = advisor._generate_response("test", [])
        assert isinstance(resp, str)
        assert "Điện Máy Xanh" in resp

    def test_verify_with_guardrails_returns_safe(self, advisor):
        result = advisor._verify_with_guardrails("test response text")
        assert result["safe"] is True
        assert result["text"] == "test response text"
        assert isinstance(result["applied_validators"], list)

    def test_verify_with_guardrails_lists_validators(self, advisor):
        result = advisor._verify_with_guardrails("any text")
        validators = advisor.guard_config.get("guardrails_config", {}).get("validators", [])
        expected = [v["name"] for v in validators]
        assert result["applied_validators"] == expected

    def test_query_advisor_full_pipeline(self, advisor):
        result = advisor.query_advisor("Tìm máy lạnh inverter")
        assert result["query"] == "Tìm máy lạnh inverter"
        assert isinstance(result["response"], str)
        assert result["safety_checked"] is True
        assert isinstance(result["source_nodes"], list)

    def test_query_advisor_response_structure(self, advisor):
        result = advisor.query_advisor("tủ lạnh giá rẻ")
        required_keys = {"query", "response", "safety_checked", "source_nodes"}
        assert required_keys <= set(result.keys())

    def test_mock_catalog_has_expected_products(self, advisor):
        results = advisor._scan_catalog_with_llama("all")
        ids = [p["id"] for p in results]
        assert "1" in ids  # Máy Lạnh Daikin
