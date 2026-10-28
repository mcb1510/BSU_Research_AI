from __future__ import annotations
"""OpenAI provider — supports GPT-4o, GPT-4, GPT-3.5, and OpenAI-compatible APIs."""

import json
from typing import Generator

from .base import BaseProvider, LLMResponse, Message, ToolCall


class OpenAIProvider(BaseProvider):
    """
    Supports:
      - OpenAI API  (api_base = None)
      - Any OpenAI-compatible API (set api_base to your endpoint)
        e.g. LM Studio, vLLM, Groq, Together, Fireworks, etc.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs,
    ):
        super().__init__(model, api_key, **kwargs)
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("Install openai: pip install openai")

        self._client = OpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=api_base,
        )

    @staticmethod
    def _parse_image_data(content: str) -> tuple[str, str, str] | None:
        """Parse an IMAGE_DATA marker string.

        Format: IMAGE_DATA:{mime_type}:{base64_data}:{question}

        Returns (mime_type, base64_data, question) or None if not an image marker.
        """
        if not content.startswith("IMAGE_DATA:"):
            return None
        # Strip the leading tag and split into at most 3 parts so that colons
        # inside the question are preserved.
        rest = content[len("IMAGE_DATA:"):]
        parts = rest.split(":", 2)
        if len(parts) != 3:
            return None
        mime_type, b64_data, question = parts
        return mime_type, b64_data, question

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for m in messages:
            msg: dict = {"role": m.role}
            if m.content is not None:
                parsed = self._parse_image_data(m.content)
                if parsed is not None:
                    mime_type, b64_data, question = parsed
                    msg["content"] = [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_data}",
                            },
                        },
                    ]
                else:
                    msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
            result.append(msg)
        return result

    def _parse_tool_calls(self, raw) -> list[ToolCall]:
        calls = []
        if not raw:
            return calls
        for tc in raw:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return calls

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(self._to_openai_messages(messages))

        kwargs = dict(
            model=self.model,
            messages=all_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls = self._parse_tool_calls(getattr(msg, "tool_calls", None))
        stop = "tool_use" if tool_calls else choice.finish_reason or "end_turn"

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
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
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(self._to_openai_messages(messages))

        kwargs = dict(
            model=self.model,
            messages=all_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            kwargs["tool_choice"] = "auto"

        full_content = ""
        tool_call_chunks: dict[int, dict] = {}

        with self._client.chat.completions.create(**kwargs) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                if delta.content:
                    full_content += delta.content
                    yield delta.content
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_chunks:
                            tool_call_chunks[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name or "" if tc.function else "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_call_chunks[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_call_chunks[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_call_chunks[idx]["arguments"] += tc.function.arguments

        tool_calls = []
        for chunk in sorted(tool_call_chunks.values(), key=lambda x: list(tool_call_chunks.values()).index(x)):
            try:
                args = json.loads(chunk["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=chunk["id"], name=chunk["name"], arguments=args))

        stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(content=full_content or None, tool_calls=tool_calls, stop_reason=stop)
