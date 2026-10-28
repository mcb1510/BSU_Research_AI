from __future__ import annotations
"""Agent runtime — the core tool-calling loop.

An Agent holds:
  - A provider (LLM backend)
  - A tool registry
  - A conversation history
  - A system prompt

It runs the standard agentic loop:
  1. Send messages to LLM
  2. If the LLM wants to call tools → execute them → add results → loop
  3. When LLM replies without tool calls → return the final message

When the LLM returns multiple tool calls in a single response they are
executed concurrently via a ThreadPoolExecutor, reducing total latency
without any change to the observable result order.
"""

import concurrent.futures
import json
import time
import uuid
from typing import Callable, Generator, Any

from .providers.base import BaseProvider, Message, ToolCall, LLMResponse
from .tools.base import ToolRegistry
from .context import ContextManager


class AgentEvent:
    """Emitted during agent execution for streaming/UI use."""
    pass


class TextChunk(AgentEvent):
    def __init__(self, text: str):
        self.text = text

    def __repr__(self):
        return f"TextChunk({self.text!r})"


class ToolCallStart(AgentEvent):
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"ToolCallStart(name={self.name!r})"


class ToolCallResult(AgentEvent):
    def __init__(self, name: str, result: str, duration_ms: int):
        self.name = name
        self.result = result
        self.duration_ms = duration_ms

    def __repr__(self):
        return f"ToolCallResult(name={self.name!r}, duration={self.duration_ms}ms)"


class AgentDone(AgentEvent):
    def __init__(self, message: str | None, usage: dict):
        self.message = message
        self.usage = usage


class Agent:
    """
    An autonomous agent that calls tools until it produces a final answer.

    Usage:
        agent = Agent(provider, registry, system="You are helpful.")
        for event in agent.run("Write a hello world in Python"):
            if isinstance(event, TextChunk):
                print(event.text, end="", flush=True)
    """

    DEFAULT_SYSTEM = (
        "You are Kiro, an AI agent. You help with coding, file management, shell commands, "
        "and any development task. You use tools when needed and reason step by step. "
        "Be concise in your final answers."
    )

    def __init__(
        self,
        provider: BaseProvider,
        registry: ToolRegistry,
        system: str | None = None,
        name: str = "kiro",
        max_iterations: int = 25,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        on_event: Callable[[AgentEvent], None] | None = None,
    ):
        self.provider = provider
        self.registry = registry
        self.system = system or self.DEFAULT_SYSTEM
        self.name = name
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.on_event = on_event

        self.history: list[Message] = []
        self.total_usage: dict = {"input_tokens": 0, "output_tokens": 0}
        self.context_manager = ContextManager()

    def add_user_message(self, content: str):
        """Add a user message to conversation history."""
        self.history.append(Message(role="user", content=content))

    def clear_history(self):
        """Reset conversation history (keep system prompt)."""
        self.history = []

    def run(self, user_message: str) -> Generator[AgentEvent, None, str | None]:
        """
        Run the agentic loop for a single user turn.
        Yields AgentEvent objects (TextChunk, ToolCallStart, ToolCallResult, AgentDone).
        Returns the final assistant message text.

        When the LLM returns multiple tool calls in one response they are
        dispatched concurrently (up to 4 workers) so independent tools such as
        parallel file reads or web searches don't block each other.
        """
        self.add_user_message(user_message)
        final_text = None

        for iteration in range(self.max_iterations):
            tools = self.registry.schemas() if self.registry else None

            # Compress history if the context window is getting full.
            self.history = self.context_manager.maybe_compress(
                self.history, self.max_tokens * 20, provider=self.provider
            )

            # Stream the response
            full_text = ""
            response: LLMResponse | None = None

            try:
                # Use blocking chat() — more reliable across all providers/Python versions.
                # Streaming display is handled by printing chunks as they arrive via chat().
                # For true streaming UX we wrap chat() in a thread for local models.
                response = self.provider.chat(
                    messages=self.history,
                    tools=tools,
                    system=self.system,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                if response.content:
                    full_text = response.content
                    event = TextChunk(full_text)
                    yield event
                    if self.on_event:
                        self.on_event(event)

            except Exception as e:
                error_msg = f"LLM error: {e}"
                yield TextChunk(error_msg)
                yield AgentDone(message=error_msg, usage=self.total_usage)
                return error_msg

            # Track token usage
            if response.usage:
                self.total_usage["input_tokens"] += response.usage.get("input_tokens", 0)
                self.total_usage["output_tokens"] += response.usage.get("output_tokens", 0)

            # Add assistant message to history
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls if response.tool_calls else None,
            )
            self.history.append(assistant_msg)

            # If no tool calls, we're done
            if not response.tool_calls:
                final_text = response.content

                # Some local models return empty content after tool results —
                # synthesize a brief confirmation so the user sees something.
                if not final_text and iteration > 0:
                    # Look at last tool result to build a summary
                    last_tool = self.history[-1] if self.history else None
                    if last_tool and last_tool.role == "tool":
                        final_text = last_tool.content
                    else:
                        final_text = "Done."
                    event = TextChunk(final_text)
                    yield event
                    if self.on_event:
                        self.on_event(event)

                done_event = AgentDone(message=final_text, usage=self.total_usage)
                yield done_event
                if self.on_event:
                    self.on_event(done_event)
                return final_text

            # ----------------------------------------------------------------
            # Execute tool calls.
            #
            # If the LLM returned a single tool call run it directly to avoid
            # the overhead of spinning up a thread pool.
            #
            # If the LLM returned multiple tool calls, dispatch them all at
            # once with a ThreadPoolExecutor so independent tools (e.g. reading
            # several files, or running web searches in parallel) don't block
            # each other.  Results are collected in the original call order so
            # the conversation history remains deterministic.
            # ----------------------------------------------------------------

            tool_calls = response.tool_calls

            # Emit ToolCallStart events for all calls before executing any of
            # them, so the UI can show the user what's about to happen.
            for tc in tool_calls:
                start_event = ToolCallStart(name=tc.name, arguments=tc.arguments)
                yield start_event
                if self.on_event:
                    self.on_event(start_event)

            def _execute_single(tc: ToolCall) -> tuple[ToolCall, str, int]:
                """Execute one tool call and return (tc, result, duration_ms)."""
                t0 = time.perf_counter()
                result = self.registry.execute(tc.name, tc.arguments)
                duration_ms = int((time.perf_counter() - t0) * 1000)
                return tc, result, duration_ms

            if len(tool_calls) == 1:
                # Fast path — no threading overhead for the common single-tool case
                tc, result, duration_ms = _execute_single(tool_calls[0])
                execution_results = [(tc, result, duration_ms)]
            else:
                # Parallel path — run all tool calls concurrently
                max_workers = min(len(tool_calls), 4)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all calls and preserve submission order via futures list
                    futures = [executor.submit(_execute_single, tc) for tc in tool_calls]
                    # Collect results in original order (as_completed would reorder them)
                    execution_results = [f.result() for f in futures]

            # Yield result events and build history messages
            tool_results: list[Message] = []
            for tc, result, duration_ms in execution_results:
                result_event = ToolCallResult(
                    name=tc.name, result=result, duration_ms=duration_ms
                )
                yield result_event
                if self.on_event:
                    self.on_event(result_event)

                tool_results.append(
                    Message(
                        role="tool",
                        content=result,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

            # Add all tool results to history
            self.history.extend(tool_results)

        # Exceeded max iterations
        timeout_msg = f"[Agent reached max iterations ({self.max_iterations})]"
        yield TextChunk(timeout_msg)
        yield AgentDone(message=timeout_msg, usage=self.total_usage)
        return timeout_msg

    def chat(self, user_message: str) -> str:
        """Blocking version of run(). Returns the final response string."""
        final = None
        for event in self.run(user_message):
            if isinstance(event, AgentDone):
                final = event.message
        return final or ""

    @property
    def token_warning(self) -> str | None:
        """Return a warning string if history is >70% of the context budget, else None."""
        return self.context_manager.token_warning(self.history, self.max_tokens * 20)

    def __repr__(self):
        return (
            f"Agent(name={self.name!r}, provider={self.provider!r}, "
            f"tools={len(self.registry)}, history={len(self.history)} messages)"
        )
