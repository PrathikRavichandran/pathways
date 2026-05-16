"""Provider-pluggable LLM layer.

Three roles, each picks a model:
    fast  : intake extraction and slot filling. Low stakes, low latency.
    smart : draft synthesis. High stakes, model quality matters.
    audit : compliance check. Deterministic-ish, can be cheap.

Two providers today: anthropic (default) and gemini (free fallback).

Selection
---------
Provider:
    PATHWAYS_LLM_PROVIDER = anthropic | gemini      (default: anthropic)

Per-role model override (takes precedence over provider defaults):
    PATHWAYS_LLM_FAST_MODEL
    PATHWAYS_LLM_SMART_MODEL
    PATHWAYS_LLM_AUDIT_MODEL

API keys:
    ANTHROPIC_API_KEY
    GEMINI_API_KEY (or GOOGLE_API_KEY)

Demo mode
---------
If no API key is set for the selected provider, get_llm still returns a
client; the first .invoke() call raises LLMUnavailable. Callers are
expected to catch that and fall back to a deterministic template path so
the system remains testable and demo-runnable without an API key.
"""

from __future__ import annotations

import os
from typing import Literal, Protocol

Role = Literal["fast", "smart", "audit"]


class LLMUnavailable(RuntimeError):
    """Raised when an LLM call can't be made (no API key, model error,
    rate limit, etc). Callers should fall back to a deterministic path."""


class LLMClient(Protocol):
    def invoke(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """Single-turn completion. Returns the assistant message text.

        Raises LLMUnavailable on any failure (missing key, SDK error,
        network error, content filter, etc). Callers should treat this
        as a signal to use their deterministic fallback path.
        """
        ...


# Default models per provider per role.
_DEFAULTS: dict[str, dict[Role, str]] = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "smart": "claude-sonnet-4-6",
        "audit": "claude-haiku-4-5-20251001",
    },
    "gemini": {
        "fast": "gemini-2.5-flash",
        "smart": "gemini-2.5-pro",
        "audit": "gemini-2.5-flash",
    },
}


def _provider() -> str:
    return os.environ.get("PATHWAYS_LLM_PROVIDER", "anthropic").lower()


def _model_for(role: Role) -> str:
    """Resolve the model string for a role.

    Priority: PATHWAYS_LLM_{ROLE}_MODEL env override > provider default.
    """
    override = os.environ.get(f"PATHWAYS_LLM_{role.upper()}_MODEL")
    if override:
        return override
    provider = _provider()
    defaults = _DEFAULTS.get(provider, _DEFAULTS["anthropic"])
    return defaults[role]


# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------


class _AnthropicClient:
    def __init__(self, model: str) -> None:
        self._model = model
        self._client = None

    def _get(self):
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise LLMUnavailable(
                    "anthropic SDK not installed (pip install anthropic)"
                ) from e
            self._client = Anthropic(api_key=api_key)
        return self._client

    def invoke(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        try:
            client = self._get()
            resp = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text.strip()
        except LLMUnavailable:
            raise
        except Exception as e:
            raise LLMUnavailable(f"anthropic call failed: {e}") from e


# ---------------------------------------------------------------------------
# Gemini client (free fallback)
# ---------------------------------------------------------------------------


class _GeminiClient:
    def __init__(self, model: str) -> None:
        self._model = model
        self._client = None

    def _get(self):
        if self._client is None:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
                "GOOGLE_API_KEY"
            )
            if not api_key:
                raise LLMUnavailable(
                    "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set"
                )
            try:
                from google import genai
            except ImportError as e:
                raise LLMUnavailable(
                    "google-genai not installed (pip install google-genai)"
                ) from e
            self._client = genai.Client(api_key=api_key)
        return self._client

    def invoke(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        try:
            client = self._get()
            resp = client.models.generate_content(
                model=self._model,
                config={
                    "system_instruction": system,
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
                contents=user,
            )
            text = getattr(resp, "text", None) or ""
            return text.strip()
        except LLMUnavailable:
            raise
        except Exception as e:
            raise LLMUnavailable(f"gemini call failed: {e}") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_llm(role: Role) -> LLMClient:
    """Return an LLM client for the given role. Provider is resolved from
    env at call time so callers can swap providers via env without a
    rebuild."""
    provider = _provider()
    model = _model_for(role)
    if provider == "gemini":
        return _GeminiClient(model)
    return _AnthropicClient(model)
