"""Context window management for the Kiro agent.

Provides ContextManager, which monitors conversation-history token usage and
compresses the history when it grows too large, keeping the oldest context and
the most-recent exchanges while summarising everything in between.

Token estimation: 4 characters ≈ 1 token (conservative GPT-family heuristic).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .providers.base import Message, BaseProvider


def _msg_text(msg: Message) -> str:
    """Return the text content of a message, handling None gracefully."""
    return msg.content or ""


class ContextManager:
    """Manages conversation-history length to stay within LLM context limits.

    Parameters
    ----------
    max_context_tokens:
        Default upper bound used when no explicit threshold is supplied to
        method calls.  Defaults to 80 000 tokens.
    """

    CHARS_PER_TOKEN: int = 4  # 4 chars ≈ 1 token
    KEEP_HEAD: int = 2         # number of messages to preserve from the start
    KEEP_TAIL: int = 6         # number of recent messages to preserve

    def __init__(self, max_context_tokens: int = 80_000) -> None:
        self.max_context_tokens = max_context_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_tokens(self, messages: list[Message]) -> int:
        """Return an estimated token count for *messages*.

        Uses the heuristic: total characters / 4.
        Tool-call argument JSON is included in the estimate when present.
        """
        total_chars = 0
        for msg in messages:
            total_chars += len(_msg_text(msg))
            # Include serialised tool-call arguments in the estimate.
            if msg.tool_calls:
                import json as _json
                for tc in msg.tool_calls:
                    total_chars += len(tc.name)
                    total_chars += len(_json.dumps(tc.arguments or {}))
        return total_chars // self.CHARS_PER_TOKEN

    def token_warning(
        self,
        history: list[Message],
        threshold: int | None = None,
    ) -> str | None:
        """Return a human-readable warning when history exceeds 70 % of *threshold*.

        Returns ``None`` when usage is below the warning level.

        Parameters
        ----------
        history:
            The current conversation history.
        threshold:
            Token threshold to compare against.  Falls back to
            ``self.max_context_tokens`` when not supplied.
        """
        limit = threshold if threshold is not None else self.max_context_tokens
        used = self.estimate_tokens(history)
        pct = used / limit if limit > 0 else 0.0

        if pct >= 0.70:
            used_k = used / 1_000
            limit_k = limit / 1_000
            pct_int = int(pct * 100)
            return (
                f"⚠️  Context window {pct_int}% full "
                f"(~{used_k:.1f}k / {limit_k:.1f}k tokens). "
                "History will be compressed automatically if needed."
            )
        return None

    def maybe_compress(
        self,
        history: list[Message],
        threshold: int | None = None,
        provider: BaseProvider | None = None,
    ) -> list[Message]:
        """Return a (possibly compressed) copy of *history*.

        Compression is triggered when the estimated token count exceeds 80 % of
        *threshold*.  When triggered:

        1. The first ``KEEP_HEAD`` messages are preserved verbatim.
        2. The last ``KEEP_TAIL`` messages are preserved verbatim.
        3. All messages in between are summarised into a single ``user``-role
           message prefixed with ``[Context summary: …]``.

        If *provider* is supplied and there are middle messages to summarise,
        the provider's LLM is used to produce an intelligent summary that
        preserves key decisions, code, file modifications, and important facts.
        If the LLM call fails for any reason, the method falls back to the
        simple text-concatenation summary.

        If history is too short to split (head + tail would overlap or leave
        nothing to summarise), the original list is returned unchanged.

        Parameters
        ----------
        history:
            The current conversation history.
        threshold:
            Token threshold.  Falls back to ``self.max_context_tokens``.
        provider:
            Optional LLM provider for intelligent summarisation.  When
            ``None``, the built-in text-concatenation summariser is used.
        """
        limit = threshold if threshold is not None else self.max_context_tokens
        used = self.estimate_tokens(history)

        # Only compress when we exceed 80 % of the limit.
        if used < limit * 0.80:
            return history

        total = len(history)
        min_required = self.KEEP_HEAD + self.KEEP_TAIL + 1  # +1 for at least one middle msg

        if total < min_required:
            # Not enough messages to meaningfully compress; return as-is.
            return history

        head = history[: self.KEEP_HEAD]
        tail = history[total - self.KEEP_TAIL :]
        middle = history[self.KEEP_HEAD : total - self.KEEP_TAIL]

        if not middle:
            return history

        # Attempt LLM-based summarisation when a provider is available.
        summary_text: str | None = None
        if provider is not None:
            summary_text = self._llm_summarise(middle, provider)

        # Fall back to simple summarisation if LLM was not used or failed.
        if summary_text is None:
            summary_text = self._summarise(middle)

        summary_msg = self._make_summary_message(summary_text)

        return head + [summary_msg] + tail

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _llm_summarise(self, messages: list[Message], provider: Any) -> str | None:
        """Ask *provider* to summarise *messages*.

        Returns the summary string on success, or ``None`` if the call fails.
        """
        try:
            history_text = self._summarise(messages)  # compact plain-text version
            prompt = (
                "Summarize this conversation history concisely, preserving key decisions, "
                "code written, files modified, and important facts:\n"
                + history_text
            )

            # Build a minimal single-turn message list for the provider.
            from .providers.base import Message as _Message  # noqa: PLC0415

            response = provider.chat(
                messages=[_Message(role="user", content=prompt)],
                system=(
                    "You are a concise summarizer. Produce a compact but faithful summary "
                    "of the conversation. Preserve all technical details, filenames, "
                    "code snippets, and decisions."
                ),
            )

            if response and response.content:
                return response.content.strip()
            return None

        except Exception:
            # Any failure — network error, API error, etc. — falls back to
            # the simple summariser.
            return None

    def _summarise(self, messages: list[Message]) -> str:
        """Produce a plain-text summary of *messages* without an LLM call.

        Each message is rendered as a compact line.  This is intentionally
        lightweight — the goal is to preserve key facts in the context rather
        than produce a polished summary.
        """
        import json as _json

        lines: list[str] = []
        for msg in messages:
            role = msg.role.upper()
            content = _msg_text(msg).strip()

            # Truncate very long content to avoid blowing up the summary.
            if len(content) > 500:
                content = content[:497] + "…"

            if content:
                lines.append(f"[{role}]: {content}")

            # Mention tool calls so the model knows what happened.
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args_repr = _json.dumps(tc.arguments or {})
                    if len(args_repr) > 200:
                        args_repr = args_repr[:197] + "…"
                    lines.append(f"[TOOL CALL]: {tc.name}({args_repr})")

            # Capture tool results (role == "tool").
            if msg.role == "tool" and content:
                # Already captured via content above; skip duplicate.
                pass

        return "\n".join(lines)

    @staticmethod
    def _make_summary_message(summary_text: str) -> Message:
        """Wrap *summary_text* in a ``Message`` with role ``user``."""
        # Import here to avoid a circular import at module load time.
        from .providers.base import Message as _Message  # noqa: PLC0415

        return _Message(
            role="user",
            content=f"[Context summary: {summary_text}]",
        )
