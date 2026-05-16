"""Phase 5 tests: the provider-pluggable LLM layer.

Covers role-to-model resolution, env-driven provider switching, the
LLMUnavailable fallback contract (so demo mode without an API key
keeps working), and per-provider call routing.

We mock the actual SDK modules so the tests run offline.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Strip provider env so each test starts from a known baseline."""
    for k in [
        "PATHWAYS_LLM_PROVIDER",
        "PATHWAYS_LLM_FAST_MODEL",
        "PATHWAYS_LLM_SMART_MODEL",
        "PATHWAYS_LLM_AUDIT_MODEL",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# Role to model resolution
# ---------------------------------------------------------------------------


def test_default_provider_is_anthropic_with_role_defaults():
    from pathways.llm.provider import _model_for, _provider

    assert _provider() == "anthropic"
    assert _model_for("fast") == "claude-haiku-4-5-20251001"
    assert _model_for("smart") == "claude-sonnet-4-6"
    assert _model_for("audit") == "claude-haiku-4-5-20251001"


def test_gemini_provider_yields_gemini_role_defaults(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "gemini")
    from pathways.llm.provider import _model_for

    assert _model_for("fast") == "gemini-2.5-flash"
    assert _model_for("smart") == "gemini-2.5-pro"
    assert _model_for("audit") == "gemini-2.5-flash"


def test_per_role_model_env_overrides_provider_default(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_SMART_MODEL", "claude-opus-4-7")
    from pathways.llm.provider import _model_for

    assert _model_for("smart") == "claude-opus-4-7"
    # Other roles still use their defaults
    assert _model_for("fast") == "claude-haiku-4-5-20251001"


def test_unknown_provider_falls_back_to_anthropic_defaults(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "totally-fictional-vendor")
    from pathways.llm.provider import _model_for

    # Unknown provider name = unknown model namespace, so the resolver
    # falls back to anthropic so the system has somewhere safe to land.
    assert _model_for("fast") == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# get_llm dispatches to the right client class
# ---------------------------------------------------------------------------


def test_get_llm_returns_anthropic_client_by_default():
    from pathways.llm import get_llm
    from pathways.llm.provider import _AnthropicClient

    client = get_llm("smart")
    assert isinstance(client, _AnthropicClient)


def test_get_llm_returns_gemini_client_when_configured(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "gemini")
    from pathways.llm import get_llm
    from pathways.llm.provider import _GeminiClient

    client = get_llm("smart")
    assert isinstance(client, _GeminiClient)


# ---------------------------------------------------------------------------
# LLMUnavailable contract: no API key = predictable raise
# ---------------------------------------------------------------------------


def test_anthropic_invoke_raises_llmunavailable_without_key():
    from pathways.llm import LLMUnavailable, get_llm

    client = get_llm("fast")
    with pytest.raises(LLMUnavailable, match="ANTHROPIC_API_KEY"):
        client.invoke(system="s", user="u")


def test_gemini_invoke_raises_llmunavailable_without_key(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "gemini")
    from pathways.llm import LLMUnavailable, get_llm

    client = get_llm("fast")
    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        client.invoke(system="s", user="u")


# ---------------------------------------------------------------------------
# End-to-end with mocked SDKs
# ---------------------------------------------------------------------------


def _install_fake_anthropic(monkeypatch, captured: dict):
    """Inject a fake anthropic module that captures the call args and
    returns a fixed text response."""

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        def __init__(self, text):
            self.content = [_Block(text)]

    class _Messages:
        def __init__(self, captured):
            self._captured = captured

        def create(self, **kwargs):
            self._captured["call"] = kwargs
            return _Resp("anthropic-mock-reply")

    class _Client:
        def __init__(self, api_key=None):
            self._captured = captured
            self.messages = _Messages(captured)

    fake = types.SimpleNamespace(Anthropic=_Client)
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def test_anthropic_invoke_uses_resolved_model_and_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("PATHWAYS_LLM_SMART_MODEL", "claude-sonnet-4-6")
    captured: dict = {}
    _install_fake_anthropic(monkeypatch, captured)

    from pathways.llm import get_llm

    client = get_llm("smart")
    out = client.invoke(system="sys-prompt", user="user-msg", max_tokens=64)

    assert out == "anthropic-mock-reply"
    assert captured["call"]["model"] == "claude-sonnet-4-6"
    assert captured["call"]["system"] == "sys-prompt"
    assert captured["call"]["messages"] == [{"role": "user", "content": "user-msg"}]
    assert captured["call"]["max_tokens"] == 64


def test_anthropic_sdk_exception_becomes_llmunavailable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _Boom:
        def __init__(self, api_key=None):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("network down")

    fake = types.SimpleNamespace(Anthropic=_Boom)
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    from pathways.llm import LLMUnavailable, get_llm

    client = get_llm("fast")
    with pytest.raises(LLMUnavailable, match="anthropic call failed"):
        client.invoke(system="s", user="u")


def test_gemini_invoke_uses_resolved_model_and_returns_text(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict = {}

    class _Models:
        def __init__(self, captured):
            self._captured = captured

        def generate_content(self, **kwargs):
            self._captured["call"] = kwargs
            return types.SimpleNamespace(text="gemini-mock-reply")

    class _Client:
        def __init__(self, api_key=None):
            self.models = _Models(captured)

    fake_genai = types.SimpleNamespace(Client=_Client)
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    from pathways.llm import get_llm

    client = get_llm("smart")
    out = client.invoke(system="sys", user="usr", max_tokens=128)

    assert out == "gemini-mock-reply"
    assert captured["call"]["model"] == "gemini-2.5-pro"
    assert captured["call"]["contents"] == "usr"
    assert captured["call"]["config"]["system_instruction"] == "sys"
    assert captured["call"]["config"]["max_output_tokens"] == 128


def test_gemini_falls_back_to_google_api_key_alias(monkeypatch):
    monkeypatch.setenv("PATHWAYS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "alt-key")

    class _Client:
        def __init__(self, api_key=None):
            self.models = types.SimpleNamespace(
                generate_content=lambda **_: types.SimpleNamespace(text="ok")
            )

    fake_genai = types.SimpleNamespace(Client=_Client)
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    from pathways.llm import get_llm

    client = get_llm("fast")
    assert client.invoke(system="s", user="u") == "ok"


# ---------------------------------------------------------------------------
# Node demo-mode contract: LLMUnavailable -> deterministic fallback
# ---------------------------------------------------------------------------


def test_intake_node_uses_heuristic_when_llm_unavailable(monkeypatch):
    """Demo mode: with no key, intake must still extract a routing
    decision from the keyword heuristic instead of crashing."""
    from pathways.nodes import intake as intake_node
    from pathways.state import PathwaysState

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    state = PathwaysState(
        session_id="test-session",
        user_message="I need housing tonight",
    )
    # _extract should fall through to _heuristic_extract
    result = intake_node._extract(state)
    assert result["top_need"] == "housing"


def test_draft_node_uses_template_when_llm_unavailable(monkeypatch):
    """Demo mode: with no key, draft must still produce a valid reply
    from the bilingual template instead of crashing."""
    from pathways.nodes import draft as draft_node
    from pathways.state import IntakeProfile, PathwaysState, TopNeed

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    state = PathwaysState(
        session_id="test-session",
        user_message="housing please",
        intake=IntakeProfile(top_need=TopNeed.HOUSING),
    )
    out = draft_node.run(state)
    assert "draft_response" in out
    assert out["draft_response"]  # non-empty
    assert out["next_node"] == "audit"
