from __future__ import annotations
"""Ollama provider — run local LLMs (Llama, Mistral, Gemma, Qwen, etc.)

Requires Ollama running locally:  https://ollama.com
    ollama serve
    ollama pull llama3.2
"""

import json
from typing import Generator

import requests

from .base import BaseProvider, LLMResponse, Message, ToolCall


class OllamaProvider(BaseProvider):
    """
    Local LLM provider via Ollama's OpenAI-compatible /api/chat endpoint.
    Tool use is supported for models that have it (llama3.1+, mistral-nemo, etc.)
    Falls back to JSON-prompted tool calling for models without native support.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        api_base: str = "http://localhost:11434",
        **kwargs,
    ):
        super().__init__(model, api_key=None, **kwargs)
        self.api_base = api_base.rstrip("/")
        self._native_tools = kwargs.get("native_tools", True)

    def _to_messages(self, messages: list[Message], system: str | None) -> list[dict]:
        result = []
        if system:
            result.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                result.append({
                    "role": "tool",
                    "content": m.content or "",
                    "tool_call_id": m.tool_call_id,
                })
            elif m.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                })
            else:
                result.append({"role": m.role, "content": m.content or ""})
        return result

    def _parse_tool_calls(self, raw) -> list[ToolCall]:
        calls = []
        if not raw:
            return calls
        for tc in raw:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            name = fn.get("name", "")
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=name, arguments=args))
        return calls

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": self._to_messages(messages, system),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools and self._native_tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        resp = requests.post(f"{self.api_base}/api/chat", json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()

        msg = data.get("message", {})
        content = msg.get("content") or None
        raw_tools = msg.get("tool_calls", [])
        tool_calls = self._parse_tool_calls(raw_tools)
        stop = "tool_use" if tool_calls else "end_turn"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage={
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
            },
        )

    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, LLMResponse]:
        payload: dict = {
            "model": self.model,
            "messages": self._to_messages(messages, system),
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools and self._native_tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        full_content = ""
        tool_calls: list[ToolCall] = []

        with requests.post(
            f"{self.api_base}/api/chat", json=payload, stream=True, timeout=300
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message", {})
                chunk = msg.get("content", "")
                if chunk:
                    full_content += chunk
                    yield chunk
                if data.get("done") and msg.get("tool_calls"):
                    tool_calls = self._parse_tool_calls(msg["tool_calls"])

        stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(content=full_content or None, tool_calls=tool_calls, stop_reason=stop)

    @property
    def supports_tools(self) -> bool:
        return self._native_tools

    def list_models(self) -> list[str]:
        """List locally available Ollama models."""
        resp = requests.get(f"{self.api_base}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
