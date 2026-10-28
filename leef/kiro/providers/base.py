from __future__ import annotations
"""Abstract base class for all LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | list | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict = field(default_factory=dict)


class BaseProvider(ABC):
    """Abstract LLM provider. Implement this to add any new model backend."""

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        self.model = model
        self.api_key = api_key
        self.options = kwargs

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send messages and return a response. Blocking."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, LLMResponse]:
        """Stream text tokens. Yields str chunks; final return is LLMResponse."""
        ...

    @property
    def supports_tools(self) -> bool:
        return True

    def __repr__(self):
        return f"{self.__class__.__name__}(model={self.model!r})"
