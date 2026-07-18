"""
ranking/reranker.py — bước RERANK generic cho MỌI category (không hardcode
theo tên ngành). API-ONLY: gọi cross-encoder reranker qua HTTP, KHÔNG tải/
chạy model local (để backend chạy nổi trên Render free tier — không OOM).

Nguyên tắc an toàn cho live: mọi lỗi (flag tắt / thiếu cấu hình / timeout /
HTTP lỗi / JSON sai / <2 ứng viên) đều fallback GIỮ NGUYÊN thứ tự rule-based
đầu vào, KHÔNG bao giờ raise ra pipeline. Timeout ngắn để không treo request.

Schema API theo chuẩn Jina/Cohere rerank (cắm được FPT/Jina/Cohere/Voyage):
    request : {"model": ..., "query": <str>, "documents": [<str>, ...]}
    response: {"results": [{"index": <int>, "relevance_score": <float>}, ...]}
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Số spec field tối đa nhét vào document text (giữ payload gọn, tránh vượt
# giới hạn token của reranker). Generic — không quan tâm category nào.
_MAX_SPEC_FIELDS = 20


def build_query_text(state: Any) -> str:
    """Sinh câu truy vấn generic từ slot khách đã cung cấp (không đọc tên
    category để rẽ nhánh). category + các slot có giá trị -> chuỗi mô tả nhu cầu."""
    parts: list[str] = []
    category = getattr(state, "category", None)
    if category:
        parts.append(str(category))
    slots = getattr(state, "slots", None) or {}
    for key, value in slots.items():
        if value is None or value == "" or key == "category":
            continue
        parts.append(f"{key}: {value}")
    return "; ".join(parts) if parts else "gợi ý sản phẩm phù hợp"


def build_document_text(result: dict[str, Any]) -> str:
    """Document text generic cho 1 sản phẩm: name + brand + giá + các cặp
    spec key:value. Đọc field từ dữ liệu thật, KHÔNG hardcode field theo
    category (giống pattern generic của rank_products)."""
    product = result.get("product") or result.get("source") or result
    parts: list[str] = []
    name = product.get("name") or result.get("name")
    if name:
        parts.append(str(name))
    brand = product.get("brand") or result.get("brand")
    if brand:
        parts.append(f"thương hiệu {brand}")
    price = product.get("effective_price") or result.get("effective_price")
    if price:
        parts.append(f"giá {price}")

    spec = product.get("spec") or {}
    if isinstance(spec, dict):
        for key, value in list(spec.items())[:_MAX_SPEC_FIELDS]:
            if value is None or value == "":
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value[:5])
            parts.append(f"{key}: {value}")
    return ". ".join(parts)


def _call_rerank_api(query: str, documents: list[str]) -> list[dict[str, Any]] | None:
    """Gọi HTTP reranker. Trả list [{index, relevance_score}] hoặc None nếu
    lỗi (caller sẽ fallback). httpx import trong hàm để tránh phụ thuộc lúc
    import module khi rerank tắt."""
    if not settings.RERANK_API_URL or not settings.RERANK_API_KEY:
        return None
    try:
        import httpx
    except Exception:  # noqa: BLE001 — httpx thiếu -> fallback, không chết
        logger.warning("reranker: httpx không khả dụng, bỏ qua rerank")
        return None

    payload: dict[str, Any] = {"query": query, "documents": documents}
    if settings.RERANK_MODEL:
        payload["model"] = settings.RERANK_MODEL
    headers = {"Authorization": f"Bearer {settings.RERANK_API_KEY}"}

    try:
        resp = httpx.post(
            settings.RERANK_API_URL,
            json=payload,
            headers=headers,
            timeout=settings.RERANK_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — timeout/HTTP/JSON lỗi -> fallback
        logger.warning("reranker: gọi API lỗi (%s), fallback rule-based", exc)
        return None

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        logger.warning("reranker: response thiếu 'results', fallback rule-based")
        return None
    return results


def _norm_rule_score(score: Any) -> float:
    try:
        return max(0.0, min(1.0, float(score) / 100.0))
    except (TypeError, ValueError):
        return 0.5


def rerank_results(query: str, scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nhận list result đã chấm điểm rule-based (mỗi phần tử có 'total_score'),
    trả list ĐÃ sắp lại theo điểm hoà (rule + rerank). Fallback giữ nguyên
    thứ tự đầu vào nếu rerank tắt/lỗi. Gắn thêm field optional 'rerank_score'
    (không phá contract cũ)."""
    if not settings.RERANK_ENABLED:
        return scored
    if len(scored) < 2:
        return scored

    pool = scored[: settings.RERANK_CANDIDATE_POOL]
    rest = scored[settings.RERANK_CANDIDATE_POOL :]
    documents = [build_document_text(r) for r in pool]

    api_results = _call_rerank_api(query, documents)
    if not api_results:
        return scored  # fallback: thứ tự rule-based nguyên vẹn

    alpha = settings.RERANK_ALPHA
    for item in api_results:
        idx = item.get("index")
        raw = item.get("relevance_score", item.get("score"))
        if not isinstance(idx, int) or idx < 0 or idx >= len(pool) or raw is None:
            continue
        try:
            rerank_score = float(raw)
        except (TypeError, ValueError):
            continue
        target = pool[idx]
        target["rerank_score"] = rerank_score
        rule_norm = _norm_rule_score(target.get("total_score"))
        target["final_score"] = alpha * rule_norm + (1 - alpha) * rerank_score

    # Ứng viên không được API chấm (thiếu index) -> dùng điểm rule-norm làm
    # final_score để không bị đẩy xuống oan.
    for r in pool:
        if "final_score" not in r:
            r["final_score"] = _norm_rule_score(r.get("total_score"))

    pool.sort(
        key=lambda r: (
            -r.get("final_score", 0.0),
            r["effective_price"] if r.get("effective_price") is not None else float("inf"),
            r.get("product_id", ""),
        )
    )
    return pool + rest
