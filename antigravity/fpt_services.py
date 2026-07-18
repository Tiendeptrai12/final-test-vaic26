"""FPT service-model tier: reranker + embeddings (the non-generative FPT models).

Separation of concerns (see docs/technical-spec): z.ai GLM-5.2 is the reasoning BRAIN
(Call B explanation); FPT hosts the fast SERVICE models used as scoring/utility functions:
  - bge-reranker-v2-m3  -> semantic relevance scoring (cross-encoder), POST /v1/rerank
  - Vietnamese_Embedding / multilingual-e5-large -> 1024-d vectors, POST /embeddings

Stdlib-only (urllib), reusing fpt_client's key/header handling. Every call has a hard
timeout and raises FPTError on failure so callers degrade gracefully (never block the turn).
These are utilities — they never generate product facts, so they can't hallucinate.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from antigravity.fpt_client import BASE_URL, FPTError, _api_key

RERANK_MODEL = "bge-reranker-v2-m3"
EMBED_MODEL = "Vietnamese_Embedding"  # 1024-d, VN-tuned; multilingual-e5-large also 1024-d


def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + path,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; DMX-Advisor/1.0)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise FPTError(f"HTTP {e.code} from FPT{path}: {e.read().decode('utf-8','replace')[:200]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise FPTError(f"FPT{path} request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise FPTError(f"FPT{path} returned non-JSON") from e


def rerank(
    query: str, documents: list[str], *, top_n: int | None = None,
    model: str = RERANK_MODEL, timeout: float = 3.0,
) -> list[tuple[int, float]]:
    """Return [(orig_index, relevance_score), ...] sorted most-relevant first.

    Cross-encoder scores each document against the query. Raises FPTError on failure.
    """
    if not documents:
        return []
    body: dict[str, Any] = {"model": model, "query": query, "documents": documents}
    if top_n is not None:
        body["top_n"] = top_n
    data = _post("/v1/rerank", body, timeout)
    results = data.get("results") or []
    return [(r["index"], r.get("relevance_score", 0.0)) for r in results]


def embed(
    texts: list[str], *, model: str = EMBED_MODEL, timeout: float = 3.0,
) -> list[list[float]]:
    """Return one 1024-d vector per input text. Raises FPTError on failure."""
    if not texts:
        return []
    data = _post("/embeddings", {"model": model, "input": texts}, timeout)
    return [row["embedding"] for row in data.get("data", [])]


def ping() -> dict[str, Any]:
    """Health probe for the service tier — used by /api/services/health."""
    out: dict[str, Any] = {}
    for name, fn in (
        ("rerank", lambda: rerank("máy lạnh êm", ["máy lạnh inverter êm", "tủ lạnh"], top_n=2)),
        ("embed", lambda: embed(["máy lạnh tiết kiệm điện"])),
    ):
        t = time.time()
        try:
            fn()
            out[name] = {"status": "ok", "latency_ms": round((time.time() - t) * 1000)}
        except Exception as e:  # noqa: BLE001 - health probe reports, never raises
            out[name] = {"status": "error", "detail": str(e)[:120]}
    return out
