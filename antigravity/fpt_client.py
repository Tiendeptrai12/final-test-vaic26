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

# Provider registry. Both are OpenAI-compatible (/chat/completions, Bearer auth,
# choices[].message.content) so ONE client serves both. FPT = fast NLU slot
# extraction (Call A); z.ai (via NVIDIA integrate) = grounded explanation prose
# (Call B). Each reads its own key so both team keys are used, each where it fits.
PROVIDERS: dict[str, dict[str, str]] = {
    "fpt": {"base_url": BASE_URL, "key_env": "FPT_API_KEY"},
    "zai": {"base_url": "https://integrate.api.nvidia.com/v1", "key_env": "LLM_API_KEY"},
}

# fast model for NLU slot extraction. Picked from the live FPT model list
# (GET /v1/models) — the handoff's "google/gemma-3-12b-it" is NOT available.
# gemma-4-26B-A4B-it is an MoE (~4B active) => fastest correct-JSON extractor
# measured (~630ms vs 1.2s gemma-3-27b, 1.9s gpt-oss-20b), well under the 3s SLA.
NLU_MODEL = "gemma-4-26B-A4B-it"


class FPTError(RuntimeError):
    """Any failure talking to FPT (network, HTTP, malformed body, missing key)."""


def _api_key(key_env: str = "FPT_API_KEY") -> str:
    key = os.environ.get(key_env, "").strip()
    if not key:
        # standalone callers (scripts/nlu) don't import core, so .env may be unloaded.
        # Load it lazily once; no-op when core already loaded it (backend path).
        try:
            from antigravity.core import BASE_DIR, load_env
            load_env(os.path.join(BASE_DIR, ".env"))
        except Exception:
            pass
        key = os.environ.get(key_env, "").strip()
    if not key:
        raise FPTError(f"{key_env} not set in environment")
    return key


def chat_completion(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: float = 3.0,
    response_format: dict[str, Any] | None = None,
    base_url: str | None = None,
    provider: str = "fpt",
) -> str:
    """POST /chat/completions and return the first choice's message content.

    `provider` selects the endpoint + key from PROVIDERS ("fpt" | "zai"); an explicit
    `base_url` still overrides. Deterministic by default (temperature=0). Raises FPTError
    on any problem so the caller can degrade gracefully instead of blocking past the SLA.
    """
    cfg = PROVIDERS.get(provider, PROVIDERS["fpt"])
    resolved_url = base_url or cfg["base_url"]
    key = _api_key(cfg["key_env"])
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
        resolved_url.rstrip("/") + CHAT_PATH,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # FPT sits behind Cloudflare, which 403s (code 1010) the default
            # "Python-urllib" agent. Present a normal client UA.
            "User-Agent": "Mozilla/5.0 (compatible; DMX-Advisor/1.0)",
            "Accept": "application/json",
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
