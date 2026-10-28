"""Shared utilities."""

from __future__ import annotations

import sys
from typing import Any

# Try to import rich; fall back to plain text
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def make_console(stderr: bool = False) -> Any:
    if HAS_RICH:
        from rich.console import Console
        return Console(stderr=stderr)
    return None


def print_md(text: str, console: Any = None):
    """Render markdown text, or fall back to plain print."""
    if HAS_RICH and console:
        from rich.markdown import Markdown
        console.print(Markdown(text))
    else:
        print(text)


def print_info(msg: str, console: Any = None):
    if HAS_RICH and console:
        console.print(f"[dim]{msg}[/dim]")
    else:
        print(msg, file=sys.stderr)


def print_error(msg: str, console: Any = None):
    if HAS_RICH and console:
        console.print(f"[bold red]Error:[/bold red] {msg}")
    else:
        print(f"Error: {msg}", file=sys.stderr)


def print_tool_call(name: str, args: dict, console: Any = None):
    if HAS_RICH and console:
        import json
        args_str = json.dumps(args, indent=2) if args else ""
        console.print(f"[bold yellow]⚙ {name}[/bold yellow]", end="")
        if args_str and len(args_str) < 200:
            console.print(f" [dim]{args_str}[/dim]", end="")
        console.print()
    else:
        print(f"  [tool] {name}", file=sys.stderr)


def print_tool_result(name: str, result: str, duration_ms: int, console: Any = None):
    if HAS_RICH and console:
        preview = result[:120].replace("\n", "↵") if result else "(empty)"
        console.print(f"[dim]  ↳ {preview} ({duration_ms}ms)[/dim]")
    else:
        print(f"  [result] {result[:80]}", file=sys.stderr)


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"… (+{len(text) - max_len} chars)"
