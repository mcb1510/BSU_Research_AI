from __future__ import annotations
"""Search tools: grep (file content search) and web_search."""

import os
import re
import subprocess
from pathlib import Path

from .base import BaseTool
from .file_tools import is_ignored, load_gitignore_patterns


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a regex pattern in files. Returns matching lines with file paths and line numbers. "
        "Can filter by file glob pattern and limit results. "
        "Respects .gitignore and common ignore patterns."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to current directory.",
            },
            "include": {
                "type": "string",
                "description": "Glob pattern to filter files, e.g. '*.py', '*.{ts,tsx}'",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search. Default false.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return. Default 50.",
            },
        },
        "required": ["pattern"],
    }

    def execute(
        self,
        pattern: str,
        path: str = ".",
        include: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> str:
        search_path = Path(path).expanduser().resolve()
        flags = re.MULTILINE if case_sensitive else re.MULTILINE | re.IGNORECASE

        # Determine the root for .gitignore (use search_path when it's a dir,
        # otherwise its parent)
        root = search_path if search_path.is_dir() else search_path.parent
        gitignore_patterns = load_gitignore_patterns(root)

        results: list[str] = []

        if search_path.is_file():
            files_to_search = [search_path]
        else:
            if include:
                import glob as glob_mod
                glob_pattern = str(search_path / "**" / include)
                candidates = [
                    Path(f) for f in glob_mod.glob(glob_pattern, recursive=True)
                    if Path(f).is_file()
                ]
            else:
                candidates = [f for f in search_path.rglob("*") if f.is_file()]

            # Filter out ignored paths
            files_to_search = [
                f for f in candidates
                if not is_ignored(f, root, gitignore_patterns)
            ]

        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        for filepath in sorted(files_to_search):
            if len(results) >= max_results:
                break
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if len(results) >= max_results:
                    break
                if compiled.search(line):
                    results.append(f"{filepath}:{lineno}: {line.rstrip()}")

        if not results:
            return f"No matches found for '{pattern}' in {search_path}"

        output = "\n".join(results)
        if len(results) >= max_results:
            output += f"\n\n(Results truncated at {max_results} matches)"
        return output


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo and return a summary of results. "
        "Use for finding documentation, answering questions, researching libraries, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return. Default 5.",
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, num_results: int = 5) -> str:
        try:
            return self._ddg_search(query, num_results)
        except Exception as e:
            return f"Search failed: {e}"

    def _ddg_search(self, query: str, num_results: int) -> str:
        """Use DuckDuckGo Instant Answer API (no key needed)."""
        import urllib.request
        import urllib.parse
        import json

        # DuckDuckGo Instant Answer API
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        })
        url = f"https://api.duckduckgo.com/?{params}"

        req = urllib.request.Request(url, headers={"User-Agent": "kiro-cli/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        results = []

        # Abstract answer
        if data.get("AbstractText"):
            results.append(f"Summary: {data['AbstractText']}")
            if data.get("AbstractURL"):
                results.append(f"Source: {data['AbstractURL']}")
            results.append("")

        # Related topics
        for topic in data.get("RelatedTopics", [])[:num_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"• {topic['Text']}")
                if topic.get("FirstURL"):
                    results.append(f"  {topic['FirstURL']}")

        if not results:
            # Fall back to HTML scraping
            return self._ddg_html_search(query, num_results)

        return "\n".join(results) if results else f"No results found for: {query}"

    def _ddg_html_search(self, query: str, num_results: int) -> str:
        """Fallback: scrape DuckDuckGo HTML results."""
        import urllib.request
        import urllib.parse
        import html
        import re

        params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
        url = f"https://html.duckduckgo.com/html/?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; kiro-cli/1.0)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return f"Web search unavailable: {e}"

        # Extract result snippets
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL)
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', body, re.DOTALL)

        results = []
        for i, (title, snippet) in enumerate(zip(titles[:num_results], snippets[:num_results])):
            clean_title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            clean_snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet)).strip()
            results.append(f"{i + 1}. {clean_title}\n   {clean_snippet}")

        return "\n\n".join(results) if results else f"No results found for: {query}"
