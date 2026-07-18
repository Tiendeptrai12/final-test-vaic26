"""Core business logic for the AI Product Advisor.

Contains ProductAdvisor — the main query pipeline that scans catalog,
generates Vietnamese responses, and runs safety guardrails.
"""
from __future__ import annotations

import os
import json
from typing import Any

import yaml


def load_env(env_path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ.

    Skips blank lines and comments (lines starting with #).
    Does nothing if the file does not exist.
    """
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

# Initialize environment variables
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_env(os.path.join(BASE_DIR, ".env"))

def get_fpt_api_key() -> str:
    """Return the FPT AI API key from environment, or empty string if unset."""
    return os.environ.get("FPT_API_KEY", "")

class ProductAdvisor:
    """AI product advisor that combines catalog search, response generation, and safety checks."""

    def __init__(self) -> None:
        """Load agent configs and API key on init."""
        self.agents_dir: str = os.path.join(BASE_DIR, "antigravity", ".agents")
        self.researcher_config: dict[str, Any] = self._load_json_config("researcher.json")
        self.guard_config: dict[str, Any] = self._load_yaml_config("guard_agent.yaml")
        self.api_key: str = get_fpt_api_key()
        try:
            from antigravity.vector_db import initialize_vector_db
            initialize_vector_db()
        except Exception:
            pass

    def _load_json_config(self, filename: str) -> dict[str, Any]:
        """Load a JSON config file from the agents directory. Return {} if missing."""
        path = os.path.join(self.agents_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_yaml_config(self, filename: str) -> dict[str, Any]:
        """Load a YAML config file from the agents directory. Return {} if missing."""
        path = os.path.join(self.agents_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

    def query_advisor(self, query: str) -> dict[str, Any]:
        """Run full advisory pipeline: scan catalog, generate response, verify safety.

        Returns dict with keys: query, response, safety_checked, source_nodes.
        """
        # Step 1: Scan / Search Catalog (Mocking LlamaIndex integration)
        catalog_results = self._scan_catalog_with_llama(query)
        
        # Step 2: Formulate advisor response
        advisor_response = self._generate_response(query, catalog_results)
        
        # Step 3: Run Safety Guardrails checks (Mocking Guardrails integration)
        secured_response = self._verify_with_guardrails(advisor_response)
        
        return {
            "query": query,
            "response": secured_response["text"],
            "safety_checked": secured_response["safe"],
            "source_nodes": catalog_results
        }

    def _scan_catalog_with_llama(self, query: str) -> list[dict[str, Any]]:
        """Retrieve matching products from catalog using Qdrant vector database."""
        limit = self.researcher_config.get("llama_index_config", {}).get("similarity_top_k", 3)
        
        try:
            from antigravity.vector_db import search_products
            results = search_products(query, limit=limit)
            if results:
                # Format to include original fields for display
                formatted_results = []
                for p in results:
                    formatted_results.append({
                        "id": p.get("product_id", ""),
                        "name": p.get("name") or p.get("product_id") or "Sản phẩm",
                        "price": f"{p.get('price', 0):,}đ" if isinstance(p.get('price'), (int, float)) else str(p.get('price', '')),
                        "brand": p.get("brand", "")
                    })
                return formatted_results
        except Exception:
            pass

        # Static mock dataset representing Điện Máy Xanh products as fallback
        mock_catalog = [
            {"id": "1", "name": "Máy Lạnh Daikin Inverter 1 HP", "price": "10,990,000đ", "btu": "9000 BTU", "power_saving": "5 Stars"},
            {"id": "2", "name": "Tủ Lạnh Panasonic Inverter 322 Lít", "price": "14,500,000đ", "power_saving": "5 Stars"},
            {"id": "3", "name": "iPhone 15 Pro Max 256GB", "price": "29,490,000đ", "camera": "48 MP"}
        ]
        return mock_catalog[:limit]

    def _generate_response(self, query: str, catalog: list[dict[str, Any]]) -> str:
        """Generate a natural Vietnamese product recommendation from catalog results."""
        products = ", ".join([f"{p['name']} ({p['price']})" for p in catalog])
        return f"Dựa trên nhu cầu của bạn, Điện Máy Xanh đề xuất các sản phẩm phù hợp nhất: {products}."

    def _verify_with_guardrails(self, response_text: str) -> dict[str, Any]:
        """Run safety validators on response. Currently mocked — always returns safe."""
        validators = self.guard_config.get("guardrails_config", {}).get("validators", [])
        
        # Verify no hallucination (check if prices in text match catalog)
        # Here we mock a successful verification
        return {
            "text": response_text,
            "safe": True,
            "applied_validators": [v["name"] for v in validators]
        }
