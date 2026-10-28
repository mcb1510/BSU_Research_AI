from __future__ import annotations
"""LLM provider registry and factory."""

from .base import BaseProvider, LLMResponse, Message, ToolCall
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .ollama_provider import OllamaProvider

__all__ = [
    "BaseProvider",
    "LLMResponse",
    "Message",
    "ToolCall",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "get_provider",
]

# Maps short provider names to their classes
_PROVIDER_MAP = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
    # Aliases
    "gpt": OpenAIProvider,
    "claude": AnthropicProvider,
    "local": OllamaProvider,
}

# OpenAI-compatible API providers (name → default base URL)
OPENAI_COMPATIBLE = {
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
}


def get_provider(provider_name: str, model: str | None = None, **kwargs) -> BaseProvider:
    """
    Factory function to create a provider instance.

    Examples:
        get_provider("openai", model="gpt-4o", api_key="...")
        get_provider("anthropic", model="claude-3-5-sonnet-20241022", api_key="...")
        get_provider("ollama", model="llama3.2")
        get_provider("groq", model="llama-3.1-70b-versatile", api_key="...")
        get_provider("lmstudio", model="local-model")
    """
    name_lower = provider_name.lower()

    # Check if it's an OpenAI-compatible third-party provider
    if name_lower in OPENAI_COMPATIBLE:
        # Only use the default base_url if the caller didn't already supply one
        if "api_base" not in kwargs:
            kwargs["api_base"] = OPENAI_COMPATIBLE[name_lower]
        model = model or _default_model_for(name_lower)
        return OpenAIProvider(model=model, **kwargs)

    # Direct provider lookup
    cls = _PROVIDER_MAP.get(name_lower)
    if cls is None:
        raise ValueError(
            f"Unknown provider: {provider_name!r}. "
            f"Available: {sorted(_PROVIDER_MAP.keys()) + sorted(OPENAI_COMPATIBLE.keys())}"
        )

    model = model or _default_model_for(name_lower)
    return cls(model=model, **kwargs)


def _default_model_for(provider: str) -> str:
    defaults = {
        "openai": "gpt-4o",
        "gpt": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "claude": "claude-3-5-sonnet-20241022",
        "ollama": "llama3.2",
        "local": "llama3.2",
        "groq": "llama-3.1-70b-versatile",
        "together": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "fireworks": "accounts/fireworks/models/llama-v3p1-70b-instruct",
        "lmstudio": "local-model",
        "vllm": "default",
        "openrouter": "anthropic/claude-3.5-sonnet",
        "deepseek": "deepseek-chat",
        "mistral": "mistral-large-latest",
    }
    return defaults.get(provider, "gpt-4o")
