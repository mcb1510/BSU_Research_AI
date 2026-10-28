from __future__ import annotations
"""Anthropic provider — supports Claude 3.5, Claude 3, and future Claude models."""

import json
from typing import Generator

from .base import BaseProvider, LLMResponse, Message, ToolCall


class AnthropicProvider(BaseProvider):
    """Claude models via Anthropic API."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: str | None = None,
        **kwargs,
    ):
        super().__init__(model, api_key, **kwargs)
        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    @staticmethod
    def _parse_image_data(content: str) -> tuple[str, str, str] | None:
        """Parse an IMAGE_DATA marker string.

        Format: IMAGE_DATA:{mime_type}:{base64_data}:{question}

        Returns (mime_type, base64_data, question) or None if not an image marker.
        """
        if not content.startswith("IMAGE_DATA:"):
            return None
        rest = content[len("IMAGE_DATA:"):]
        parts = rest.split(":", 2)
        if len(parts) != 3:
            return None
        mime_type, b64_data, question = parts
        return mime_type, b64_data, question

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for m in messages:
            if m.role == "system":
                continue  # System prompt handled separately
            if m.role == "tool":
                # Tool result message
                result.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id,
                            "content": m.content or "",
                        }
                    ],
                })
            elif m.tool_calls:
                # Assistant message with tool calls
                content = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                result.append({"role": "assistant", "content": content})
            else:
                raw_content = m.content or ""
                parsed = self._parse_image_data(raw_content)
                if parsed is not None:
                    mime_type, b64_data, question = parsed
                    result.append({
                        "role": m.role,
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": b64_data,
                                },
                            },
                            {"type": "text", "text": question},
                        ],
                    })
                else:
                    result.append({"role": m.role, "content": raw_content})
        return result

    def _to_anthropic_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-style tool defs to Anthropic format."""
        result = []
        for t in tools:
            result.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _parse_response(self, response) -> LLMResponse:
        content_text = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input or {})
                )

        stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage={
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            },
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._to_anthropic_messages(messages),
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        response = self._client.messages.create(**kwargs)
        return self._parse_response(response)

    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, LLMResponse]:
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._to_anthropic_messages(messages),
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        full_text = ""
        tool_calls = []
        current_tool: dict | None = None
        current_input_str = ""

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                event_type = event.type if hasattr(event, "type") else ""

                if event_type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool = {"id": block.id, "name": block.name}
                        current_input_str = ""

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        full_text += delta.text
                        yield delta.text
                    elif delta.type == "input_json_delta" and current_tool:
                        current_input_str += delta.partial_json

                elif event_type == "content_block_stop":
                    if current_tool:
                        try:
                            args = json.loads(current_input_str or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(
                            ToolCall(
                                id=current_tool["id"],
                                name=current_tool["name"],
                                arguments=args,
                            )
                        )
                        current_tool = None
                        current_input_str = ""

        stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(content=full_text or None, tool_calls=tool_calls, stop_reason=stop)
