from __future__ import annotations
"""Web fetch tool: fetch and extract readable content from a URL."""

import html
import re
import urllib.error
import urllib.request
from typing import Any

from .base import BaseTool

# Browser-like User-Agent so sites don't block the request
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Truncated mode character limit
_TRUNCATE_LIMIT = 8000

# Lines of context around each match in selective mode
_CONTEXT_LINES = 10


def _strip_html(raw: str) -> str:
    """Convert HTML to clean readable text.

    Steps:
    1. Remove <script> and <style> blocks entirely (content is not useful).
    2. Replace block-level tags with newlines to preserve paragraph structure.
    3. Strip every remaining HTML tag.
    4. Decode HTML entities (e.g. &amp; → &, &nbsp; → space).
    5. Collapse runs of whitespace / blank lines.
    """
    # 1. Drop script / style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)

    # 2. Block tags → newlines so paragraphs don't merge
    block_tags = r"</?(?:p|div|br|li|tr|h[1-6]|blockquote|article|section|header|footer|nav|main)[^>]*>"
    text = re.sub(block_tags, "\n", text, flags=re.IGNORECASE)

    # 3. Strip all remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # 4. Decode HTML entities
    text = html.unescape(text)

    # 5. Collapse horizontal whitespace on each line, then collapse blank lines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Collapse runs of more than two consecutive blank lines into one
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 2:
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


def _selective_extract(text: str, search_terms: str) -> str:
    """Return lines around every line that contains any of the search terms.

    Matches are case-insensitive.  Context is ±_CONTEXT_LINES lines.
    Overlapping windows are merged; a '...' separator is inserted between
    non-adjacent windows.
    """
    lines = text.splitlines()
    total = len(lines)

    # Find all matching line indices
    terms = [t.strip().lower() for t in search_terms.split() if t.strip()]
    if not terms:
        # No real terms — fall back to truncated output
        return text[:_TRUNCATE_LIMIT]

    match_indices: list[int] = []
    for i, line in enumerate(lines):
        low = line.lower()
        if any(term in low for term in terms):
            match_indices.append(i)

    if not match_indices:
        return f"(No lines matched search terms: {search_terms!r})\n\n" + text[:_TRUNCATE_LIMIT]

    # Build merged windows
    windows: list[tuple[int, int]] = []  # (start, end) inclusive
    for idx in match_indices:
        start = max(0, idx - _CONTEXT_LINES)
        end = min(total - 1, idx + _CONTEXT_LINES)
        if windows and start <= windows[-1][1] + 1:
            # Merge with the previous window
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))

    # Assemble output
    parts: list[str] = []
    for w_start, w_end in windows:
        parts.append("\n".join(lines[w_start : w_end + 1]))

    return "\n...\n".join(parts)


class WebFetchTool(BaseTool):
    """Fetch and extract readable content from a URL."""

    name = "web_fetch"
    description = (
        "Fetch and extract readable content from a URL. Returns the page as clean text. "
        "Use 'truncated' mode (default) for a quick look at the first 8000 characters, "
        "'full' for the entire page, or 'selective' with search_terms to extract only the "
        "sections relevant to specific keywords."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "mode": {
                "type": "string",
                "enum": ["truncated", "full", "selective"],
                "description": (
                    "Extraction mode. "
                    "'truncated' (default) — first 8000 characters; "
                    "'full' — entire page; "
                    "'selective' — lines near search_terms matches."
                ),
            },
            "search_terms": {
                "type": "string",
                "description": (
                    "Space-separated keywords used in 'selective' mode to find relevant sections. "
                    "Ignored in other modes."
                ),
            },
        },
        "required": ["url"],
    }

    def execute(
        self,
        url: str,
        mode: str = "truncated",
        search_terms: str | None = None,
        **_kwargs: Any,
    ) -> str:
        # ------------------------------------------------------------------ #
        # 1. Fetch                                                             #
        # ------------------------------------------------------------------ #
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes: bytes = resp.read()
                content_type: str = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return f"Error fetching {url!r}: HTTP {exc.code} {exc.reason}"
        except urllib.error.URLError as exc:
            return f"Error fetching {url!r}: {exc.reason}"
        except TimeoutError:
            return f"Error fetching {url!r}: request timed out after 15 s"
        except Exception as exc:  # noqa: BLE001
            return f"Error fetching {url!r}: {type(exc).__name__}: {exc}"

        # ------------------------------------------------------------------ #
        # 2. Decode                                                            #
        # ------------------------------------------------------------------ #
        # Determine charset from Content-Type header, fall back to utf-8
        charset = "utf-8"
        ct_lower = content_type.lower()
        charset_match = re.search(r"charset=([^\s;]+)", ct_lower)
        if charset_match:
            charset = charset_match.group(1).strip().strip('"')

        try:
            raw_text = raw_bytes.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            raw_text = raw_bytes.decode("utf-8", errors="replace")

        # ------------------------------------------------------------------ #
        # 3. HTML → clean text                                                 #
        # ------------------------------------------------------------------ #
        is_html = (
            "html" in ct_lower
            or raw_text.lstrip()[:100].lower().startswith("<!doctype html")
            or "<html" in raw_text[:500].lower()
        )

        if is_html:
            text = _strip_html(raw_text)
        else:
            text = raw_text  # plain text / JSON / XML — return as-is

        # ------------------------------------------------------------------ #
        # 4. Apply mode                                                        #
        # ------------------------------------------------------------------ #
        mode = (mode or "truncated").lower()

        if mode == "full":
            return text

        if mode == "selective":
            if search_terms:
                return _selective_extract(text, search_terms)
            # No terms provided — behave like truncated
            return text[:_TRUNCATE_LIMIT]

        # Default: truncated
        if len(text) <= _TRUNCATE_LIMIT:
            return text

        return text[:_TRUNCATE_LIMIT] + f"\n\n... [truncated — {len(text) - _TRUNCATE_LIMIT} more characters]"
