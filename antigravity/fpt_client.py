"""Thin OpenAI-compatible client for FPT AI Factory (the ONLY allowed LLM provider).

Stdlib-only (urllib) so no new dependency ships to the on-prem box. One public call:
`chat_completion(model, messages, ...) -> str` returns the assistant message content.

Key is read from FPT_API_KEY (loaded into os.environ by core.load_env). Latency is the
real constraint (SLA <3s/turn), so callers pass a hard timeout; on any failure this raises
`FPTError` and the caller falls back to a "hỏi lại" clarification rather than hanging.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://mkp-api.fptcloud.com"
CHAT_PATH = "/chat/completions"

# fast/cheap model for NLU slot extraction (per project handoff)
NLU_MODEL = "google/gemma-3-12b-it"


class FPTError(RuntimeError):
    """Any failure talking to FPT (network, HTTP, malformed body, missing key)."""


def _api_key() -> str:
    key = os.environ.get("FPT_API_KEY", "").strip()
    if not key:
        raise FPTError("FPT_API_KEY not set in environment")
    return key


def chat_completion(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: float = 3.0,
    response_format: dict[str, Any] | None = None,
    base_url: str = BASE_URL,
) -> str:
    """POST /chat/completions and return the first choice's message content.

    Deterministic by default (temperature=0). Raises FPTError on any problem so the
    caller can degrade gracefully instead of blocking past the latency SLA.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + CHAT_PATH,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # non-2xx
        detail = e.read().decode("utf-8", "replace")[:300]
        raise FPTError(f"HTTP {e.code} from FPT: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:  # network / timeout
        raise FPTError(f"FPT request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise FPTError("FPT returned non-JSON body") from e

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise FPTError(f"unexpected FPT response shape: {body}") from e
