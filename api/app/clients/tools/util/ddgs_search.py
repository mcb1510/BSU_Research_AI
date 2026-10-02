#!/usr/bin/env python3
"""CLI bridge for the DDGS-backed web_search tool.

Invoked as: ddgs_search.py '<json request>'
Request:  {"mode": "search", "query": "...", "max_results": 5}
       or {"mode": "read", "url": "..."}
Response: {"results": [{"title": "...", "url": "...", "snippet": "..."}]} on stdout
       or {"content": "..."} on stdout

Requires: pip install ddgs
"""
import json
import sys

from ddgs import DDGS

# Tried in order within a single process invocation (no extra subprocess cost).
# Google is the primary backend; the others are fallbacks for when it is
# rate-limited, blocked, or hits a transient TLS/network error.
SEARCH_BACKENDS = ["Google", "Bing", "DuckDuckGo", "Brave"]


def web_search(query: str, max_results: int = 5):
    """Search the web and return structured results.

    Tries each backend in SEARCH_BACKENDS in turn, returning the first one
    that succeeds. Raises the last error if every backend fails.
    """

    if not query.strip():
        return []

    last_error = None

    for backend in SEARCH_BACKENDS:
        try:
            results = DDGS().text(
                query,
                max_results=max_results,
                backend=backend,
            )

            return [
                {
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", ""),
                }
                for result in results
            ]
        except Exception as error:
            last_error = error
            continue

    raise last_error


def read_webpage(url: str):
    """Fetch a webpage and return its content as Markdown."""

    if not url.strip():
        return ""

    result = DDGS().extract(
        url,
        fmt="text_markdown",
    )

    return result.get("content", "")


def main():
    request = json.loads(sys.argv[1])
    mode = request.get("mode")

    if mode == "search":
        output = {"results": web_search(request.get("query", ""), request.get("max_results", 5))}
    elif mode == "read":
        output = {"content": read_webpage(request.get("url", ""))}
    else:
        raise ValueError(f"Unknown mode: {mode}")

    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
