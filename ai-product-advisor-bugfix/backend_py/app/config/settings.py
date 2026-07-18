"""
config/settings.py — cấu hình tập trung cho backend.

KHÔNG hardcode API key ở bất kỳ đâu. Người dùng tự điền vào `backend_py/.env`
(copy từ `.env.example`). dotenv chỉ nạp biến còn thiếu, không ghi đè biến
môi trường đã set sẵn từ shell/CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("GUARDRAILS_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
try:
    from guardrails.settings import settings as _guardrails_settings

    _guardrails_settings.disable_tracing = True
except Exception:  # noqa: BLE001 — không chặn khởi động app nếu guardrails đổi API nội bộ
    pass

from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend_py/
load_dotenv(BASE_DIR / ".env", override=False)

DATA_DIR = BASE_DIR / "data"
SCHEMAS_DIR = BASE_DIR / "schemas"

# --- Production catalog source: DMX JSON (KHÔNG dùng Excel) ---
PRODUCTS_DETAIL_JSON_PATH = DATA_DIR / "products_detail.json"
DMX_REGISTRY_PATH = SCHEMAS_DIR / "dmx_registry.json"

# --- Legacy Excel source (Spec_cate_gia.xlsx) — GIỮ LẠI chỉ để tham chiếu/
#     test hồi quy so sánh với dữ liệu cũ. KHÔNG được catalog_store hay bất
#     kỳ đường dẫn production nào import/gọi nữa kể từ khi chuyển sang DMX. ---
LEGACY_CATALOG_XLSX_PATH = DATA_DIR / "Spec_cate_gia.xlsx"
LEGACY_REGISTRY_PATH = SCHEMAS_DIR / "registry.json"

LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-6"
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "600"))

DEFAULT_TOP_N = int(os.getenv("DEFAULT_TOP_N", "3"))

FPT_TIMEOUT_SECONDS = float(os.getenv("FPT_TIMEOUT_SECONDS", "3"))

# --- Reranker (API-only, KHÔNG chạy model local) --------------------------
# Cross-encoder reranker gọi qua HTTP (schema chuẩn Jina/Cohere:
# {query, documents[]} -> {results[]{index, relevance_score}}). Cắm được cho
# FPT AI / Jina / Cohere / Voyage bằng cách đổi 3 biến URL/MODEL/KEY. TẮT mặc
# định để deploy không phụ thuộc cấu hình — chỉ bật khi đã set đủ env trên
# Render. Mọi lỗi/timeout/flag tắt -> fallback thứ tự rule-based (xem reranker.py).
RERANK_ENABLED = (os.getenv("RERANK_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")
RERANK_API_URL = os.getenv("RERANK_API_URL") or None
RERANK_MODEL = os.getenv("RERANK_MODEL") or None
RERANK_API_KEY = os.getenv("RERANK_API_KEY") or LLM_API_KEY
RERANK_TIMEOUT_SECONDS = float(os.getenv("RERANK_TIMEOUT_SECONDS", "3"))
# Trọng số hoà điểm: final = alpha*rule_score_norm + (1-alpha)*rerank_score.
RERANK_ALPHA = float(os.getenv("RERANK_ALPHA", "0.5"))
# Số ứng viên tối đa gửi lên API mỗi request (giới hạn chi phí/độ trễ).
RERANK_CANDIDATE_POOL = int(os.getenv("RERANK_CANDIDATE_POOL", "20"))


def require_llm_api_key() -> str:
    """Dùng khi cần gọi LLM thật (production) — không dùng trong test."""
    if not LLM_API_KEY:
        raise RuntimeError(
            "Thiếu API key cho LLM. Hãy điền vào backend_py/.env (copy từ .env.example), "
            "biến LLM_API_KEY hoặc ANTHROPIC_API_KEY, trước khi chạy pipeline với LLM thật. "
            "Khi test, truyền một llm giả lập (vd MockLLM của llama_index) thay vì gọi API thật."
        )
    return LLM_API_KEY
