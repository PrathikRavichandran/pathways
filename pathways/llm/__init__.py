"""Provider-pluggable LLM layer.

Public API: get_llm(role), LLMClient, LLMUnavailable.
See pathways/llm/provider.py for the contract and selection rules.
"""

from pathways.llm.provider import LLMClient, LLMUnavailable, Role, get_llm

__all__ = ["LLMClient", "LLMUnavailable", "Role", "get_llm"]
