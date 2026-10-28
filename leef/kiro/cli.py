#!/usr/bin/env python3
"""Kiro CLI — interactive REPL and one-shot agent runner.

Usage:
    python -m kiro.cli                         # Start interactive REPL
    python -m kiro.cli "write hello world"     # One-shot command
    python -m kiro.cli --provider ollama --model llama3.2 "explain this code"
    python -m kiro.cli --provider anthropic "help me debug this"

Slash commands (in REPL):
    /help               Show all commands
    /model <name>       Switch model mid-session
    /provider <name>    Switch provider mid-session
    /system <text>      Change the system prompt
    /clear              Clear conversation history
    /context <path>     Add file/directory as context
    /context list       Show loaded context entries
    /context clear      Remove all context entries
    /tools              List available tools
    /history            Show conversation history
    /config             Show current configuration
    /agent <name>       Create and name a custom agent
    /pipeline           Show pipeline DSL help
    /run <file.py>      Run a pipeline script
    /save <file>        Save conversation to file
    /load <file>        Load conversation from file
    /exit               Quit
"""

from __future__ import annotations

import json
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Any

# Add parent dir to path so we can run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from kiro.config import load_config, write_default_config, Config
from kiro.providers import get_provider, BaseProvider
from kiro.tools.base import build_default_registry, ToolRegistry
from kiro.agent import Agent, TextChunk, ToolCallStart, ToolCallResult, AgentDone
from kiro.utils import (
    make_console, print_md, print_info, print_error,
    print_tool_call, print_tool_result, HAS_RICH
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.rule import Rule
    from rich.live import Live
    from rich.spinner import Spinner
except ImportError:
    pass

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.styles import Style
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


BANNER = """
╭──────────────────────────────────────────────╮
│  🤖  K i r o  C L I  — AI Agent Terminal    │
│  Type /help for commands  •  Ctrl+C to quit  │
╰──────────────────────────────────────────────╯"""

HELP_TEXT = """
[bold]Slash Commands:[/bold]

  [yellow]/help[/yellow]                  Show this help
  [yellow]/model[/yellow] <name>          Switch model  (e.g. /model gpt-4o)
  [yellow]/provider[/yellow] <name>       Switch provider (openai/anthropic/ollama/groq/...)
  [yellow]/system[/yellow] <text>         Change system prompt
  [yellow]/clear[/yellow]                 Clear conversation history
  [yellow]/context[/yellow] <path>        Add file or directory as context
  [yellow]/context list[/yellow]          Show all loaded context entries
  [yellow]/context clear[/yellow]         Remove all context entries from history
  [yellow]/tools[/yellow]                 List available tools
  [yellow]/history[/yellow]               Show conversation history
  [yellow]/config[/yellow]                Show current configuration
  [yellow]/save[/yellow] <file>           Save conversation to JSON file
  [yellow]/load[/yellow] <file>           Load conversation from JSON file
  [yellow]/pipeline[/yellow]              Show pipeline scripting examples
  [yellow]/models[/yellow]                List available Ollama models (if using Ollama)
  [yellow]/exit[/yellow]                  Quit

[bold]Tips:[/bold]
  • Press [bold]↑/↓[/bold] for history, [bold]Ctrl+C[/bold] to cancel current run
  • Set [bold]OPENAI_API_KEY[/bold], [bold]ANTHROPIC_API_KEY[/bold], etc. in your environment
  • Use [bold]kiro.config.json[/bold] in your project for persistent settings
"""

PIPELINE_HELP = """
[bold]Pipeline Scripting[/bold]

Create a Python file and run it with [yellow]/run <file>[/yellow]:

[dim]# my_pipeline.py[/dim]
[green]from kiro.pipeline import Pipeline, create_agent
from kiro.providers import get_provider
from kiro.tools.base import build_default_registry

provider = get_provider("openai", model="gpt-4o", api_key="sk-...")
pipeline = Pipeline(provider)

pipeline.add_stage("researcher", "Research the best Python web frameworks")
pipeline.add_stage(
    "implementer",
    "Build a simple REST API using: {researcher}",
    depends_on=["researcher"],
)
pipeline.add_stage(
    "reviewer",
    "Review this code and say NEEDS_CHANGES if it needs work:\\n{implementer}",
    depends_on=["implementer"],
    loop_to="implementer",
    loop_trigger="NEEDS_CHANGES",
    max_loop_iterations=3,
)

results = pipeline.run(
    on_text=lambda stage, text: print(f"[{stage}] {text}", end="", flush=True)
)
for name, result in results.items():
    print(f"\\n=== {name} ({result.duration_s:.1f}s) ===\\n{result.output}")
[/green]
"""

# Binary file detection: extensions we will never try to read as text.
_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac", ".ogg",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".pyc", ".pyo", ".pyd",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".sqlite", ".db",
}

# Directory names to always skip when recursing.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _is_binary_path(path: Path) -> bool:
    """Return True if the file extension suggests binary content."""
    return path.suffix.lower() in _BINARY_EXTENSIONS


def _read_context_file(path: Path) -> str | None:
    """Read a single text file and return its content, or None on failure."""
    if _is_binary_path(path):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _collect_context_directory(root: Path, max_files: int = 50) -> list[tuple[str, str]]:
    """Recursively collect (relative_path, content) for text files under *root*.

    Skips binaries, .git, node_modules, __pycache__, and stops at *max_files*.
    Returns a list of (path_str, content) tuples, relative to *root*.
    """
    results: list[tuple[str, str]] = []

    def _walk(directory: Path) -> None:
        if len(results) >= max_files:
            return
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if len(results) >= max_files:
                return
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                _walk(entry)
            elif entry.is_file():
                content = _read_context_file(entry)
                if content is not None:
                    rel = str(entry.relative_to(root))
                    results.append((rel, content))

    _walk(root)
    return results


class KiroCLI:
    """Interactive Kiro CLI session."""

    def __init__(self, config: Config):
        self.config = config
        self.console = make_console()
        self._setup_provider()
        self._setup_agent()
        self._prompt_session = self._make_prompt_session()

    def _setup_provider(self):
        provider_name = self.config.provider or "openai"
        model = self.config.model
        api_key = self.config.api_key
        api_base = self.config.api_base

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        try:
            self.provider = get_provider(provider_name, model=model, **kwargs)
        except Exception as e:
            self._error(f"Failed to initialize provider {provider_name!r}: {e}")
            self._error("Tip: Make sure your API key is set (e.g. OPENAI_API_KEY)")
            sys.exit(1)

    def _setup_agent(self):
        self.registry = build_default_registry(provider=self.provider)
        self.agent = Agent(
            provider=self.provider,
            registry=self.registry,
            system=self.config.system_prompt,
            max_iterations=self.config.max_iterations or 25,
            temperature=self.config.temperature or 0.7,
            max_tokens=self.config.max_tokens or 4096,
        )

    def _make_prompt_session(self):
        if not HAS_PROMPT_TOOLKIT:
            return None
        history_file = Path.home() / ".kiro" / "history"
        history_file.parent.mkdir(exist_ok=True)
        return PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
        )

    def _info(self, msg: str):
        print_info(msg, self.console)

    def _error(self, msg: str):
        print_error(msg, self.console)

    def _print(self, msg: str):
        if self.console:
            self.console.print(msg)
        else:
            print(msg)

    def _input(self, prompt_str: str) -> str:
        if HAS_PROMPT_TOOLKIT and self._prompt_session:
            return self._prompt_session.prompt(prompt_str)
        return input(prompt_str)

    # ── Context helpers ────────────────────────────────────────────────────────

    def _context_prefix(self, path: str) -> str:
        """Return the marker prefix for a context entry."""
        return f"[Context: {path}]"

    def _is_context_message(self, content: str | None) -> bool:
        """Return True if a message content looks like a context entry."""
        return bool(content and content.startswith("[Context:"))

    def _handle_context(self, arg: str) -> None:
        """Handle the /context subcommand logic."""
        if not arg:
            self._error(
                "Usage:\n"
                "  /context <path>   — load file or directory into context\n"
                "  /context list     — show loaded context entries\n"
                "  /context clear    — remove all context entries"
            )
            return

        sub = arg.strip()

        # ── /context list ──────────────────────────────────────────────────
        if sub == "list":
            entries = [
                (i, msg)
                for i, msg in enumerate(self.agent.history)
                if msg.role == "user" and self._is_context_message(msg.content)
            ]
            if not entries:
                self._info("No context entries in history.")
                return
            self._print(f"[bold]Context entries ({len(entries)}):[/bold]")
            for i, msg in entries:
                # Extract the [Context: <path>] header line
                first_line = (msg.content or "").split("\n", 1)[0]
                self._print(f"  [dim][{i}][/dim] {first_line}")
            return

        # ── /context clear ─────────────────────────────────────────────────
        if sub == "clear":
            from kiro.providers.base import Message
            before = len(self.agent.history)
            self.agent.history = [
                msg for msg in self.agent.history
                if not (msg.role == "user" and self._is_context_message(msg.content))
            ]
            removed = before - len(self.agent.history)
            self._info(f"Removed {removed} context entr{'y' if removed == 1 else 'ies'} from history.")
            return

        # ── /context <path> ────────────────────────────────────────────────
        path = Path(sub).expanduser()

        if not path.exists():
            self._error(f"Path not found: {sub}")
            return

        from kiro.providers.base import Message

        if path.is_file():
            content = _read_context_file(path)
            if content is None:
                self._error(f"Cannot read {sub} (binary or unreadable file).")
                return
            body = f"{self._context_prefix(sub)}\n{content}"
            self.agent.history.append(Message(role="user", content=body))
            lines = content.count("\n") + 1
            self._info(f"Added context from file: {sub} ({lines} lines)")

        elif path.is_dir():
            files = _collect_context_directory(path, max_files=50)
            if not files:
                self._error(f"No readable text files found under {sub}.")
                return

            sections: list[str] = [self._context_prefix(sub)]
            for rel, file_content in files:
                sections.append(f"\n--- {rel} ---\n{file_content}")

            body = "\n".join(sections)
            self.agent.history.append(Message(role="user", content=body))
            self._info(
                f"Added context from directory: {sub} "
                f"({len(files)} file{'s' if len(files) != 1 else ''})"
            )

        else:
            self._error(f"Path is neither a file nor a directory: {sub}")

    # ── Slash commands ─────────────────────────────────────────────────────────

    def handle_slash(self, line: str) -> bool:
        """
        Handle a slash command. Returns True if handled, False if not a slash command.
        """
        if not line.startswith("/"):
            return False

        parts = line[1:].split(" ", 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("exit", "quit", "bye"):
            self._print("[dim]Goodbye![/dim]")
            sys.exit(0)

        elif cmd == "help":
            if HAS_RICH and self.console:
                from rich.panel import Panel
                self.console.print(Panel(HELP_TEXT, title="Kiro Help", border_style="blue"))
            else:
                print(HELP_TEXT)

        elif cmd == "clear":
            self.agent.clear_history()
            self._info("Conversation history cleared.")

        elif cmd == "context":
            self._handle_context(arg)

        elif cmd == "model":
            if not arg:
                self._print(f"Current model: [bold]{self.provider.model}[/bold]")
            else:
                self.provider.model = arg
                self._info(f"Model switched to: {arg}")

        elif cmd == "provider":
            if not arg:
                self._print(f"Current provider: [bold]{self.provider.__class__.__name__}[/bold]")
            else:
                try:
                    old_key = self.provider.api_key
                    self.provider = get_provider(arg, api_key=old_key)
                    self.agent.provider = self.provider
                    self._info(f"Provider switched to: {arg} (model: {self.provider.model})")
                except Exception as e:
                    self._error(str(e))

        elif cmd == "system":
            if not arg:
                self._print(f"System: {self.agent.system}")
            else:
                self.agent.system = arg
                self._info("System prompt updated.")

        elif cmd == "tools":
            lines = ["[bold]Available tools:[/bold]"]
            for tool in self.registry.all_tools():
                lines.append(f"  [yellow]{tool.name}[/yellow] — {tool.description[:80]}")
            self._print("\n".join(lines))

        elif cmd == "history":
            if not self.agent.history:
                self._info("No conversation history.")
            else:
                for i, msg in enumerate(self.agent.history):
                    role = msg.role.upper()
                    content = str(msg.content or "")[:200]
                    self._print(f"[dim][{i}] {role}:[/dim] {content}")

        elif cmd == "config":
            cfg = {
                "provider": self.provider.__class__.__name__,
                "model": self.provider.model,
                "temperature": self.agent.temperature,
                "max_tokens": self.agent.max_tokens,
                "max_iterations": self.agent.max_iterations,
                "tools": len(self.registry),
                "history_length": len(self.agent.history),
                "usage": self.agent.total_usage,
            }
            self._print(json.dumps(cfg, indent=2))

        elif cmd == "models":
            if hasattr(self.provider, "list_models"):
                try:
                    models = self.provider.list_models()
                    self._print("Available models:\n" + "\n".join(f"  {m}" for m in models))
                except Exception as e:
                    self._error(f"Could not list models: {e}")
            else:
                self._error("list_models is only available for the Ollama provider.")

        elif cmd == "save":
            if not arg:
                self._error("Usage: /save <filename>")
            else:
                try:
                    from datetime import datetime, timezone
                    path = Path(arg)
                    messages = []
                    for m in self.agent.history:
                        entry: dict[str, Any] = {"role": m.role}
                        # content — may be str, list, or None
                        if m.content is not None:
                            entry["content"] = m.content
                        # assistant tool_calls
                        if m.tool_calls:
                            entry["tool_calls"] = [
                                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                for tc in m.tool_calls
                            ]
                        # tool result messages: tool_call_id links result to call
                        if m.tool_call_id is not None:
                            entry["tool_call_id"] = m.tool_call_id
                        if m.name is not None:
                            entry["name"] = m.name
                        messages.append(entry)
                    metadata = {
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "provider": self.provider.__class__.__name__,
                        "model": self.provider.model,
                    }
                    payload = {"metadata": metadata, "messages": messages}
                    path.write_text(json.dumps(payload, indent=2))
                    self._info(f"Saved {len(messages)} messages to {arg}")
                except Exception as e:
                    self._error(f"Save failed: {e}")

        elif cmd == "load":
            if not arg:
                self._error("Usage: /load <filename>")
            else:
                try:
                    from kiro.providers.base import Message, ToolCall
                    path = Path(arg)
                    raw = json.loads(path.read_text())

                    # Support both old format (plain list) and new format
                    # {metadata: {...}, messages: [...]}
                    metadata: dict[str, Any] = {}
                    if isinstance(raw, list):
                        msg_list = raw
                    elif isinstance(raw, dict) and "messages" in raw:
                        msg_list = raw["messages"]
                        metadata = raw.get("metadata", {})
                    else:
                        raise ValueError("Unrecognised file format.")

                    messages = []
                    for m in msg_list:
                        tc_list = None
                        if m.get("tool_calls"):
                            tc_list = [
                                ToolCall(
                                    id=tc["id"],
                                    name=tc["name"],
                                    arguments=tc["arguments"],
                                )
                                for tc in m["tool_calls"]
                            ]
                        messages.append(Message(
                            role=m["role"],
                            content=m.get("content"),
                            tool_calls=tc_list,
                            tool_call_id=m.get("tool_call_id"),
                            name=m.get("name"),
                        ))
                    self.agent.history = messages

                    if metadata:
                        saved_at = metadata.get("saved_at", "unknown time")
                        model = metadata.get("model", "unknown model")
                        # Trim ISO timestamp to date for readability
                        if "T" in saved_at:
                            saved_at = saved_at.split("T")[0]
                        self._info(
                            f"Loaded {len(messages)} messages "
                            f"(saved {saved_at} with {model})"
                        )
                    else:
                        self._info(f"Loaded {len(messages)} messages from {arg}")
                except Exception as e:
                    self._error(f"Load failed: {e}")

        elif cmd == "tangent":
            sub = arg.lower() if arg else ""
            if sub == "start":
                # Save a deep copy of current history and start fresh
                import copy
                self._tangent_stack.append(copy.deepcopy(self.agent.history))
                self.agent.clear_history()
                depth = len(self._tangent_stack)
                self._info(
                    f"Tangent started (depth {depth}). "
                    "Type /tangent end to return."
                )
            elif sub == "end":
                if not self._tangent_stack:
                    self._error("No active tangent. Use /tangent start to begin one.")
                else:
                    tangent_history = list(self.agent.history)
                    tangent_len = len(tangent_history)
                    self.agent.history = self._tangent_stack.pop()
                    depth = len(self._tangent_stack)
                    self._info(
                        f"Tangent ended ({tangent_len} messages in tangent). "
                        f"Restored previous conversation. "
                        f"Tangent depth: {depth}."
                    )
            else:
                depth = len(self._tangent_stack)
                if depth == 0:
                    self._print("No active tangent. Use [yellow]/tangent start[/yellow] to begin one.")
                else:
                    self._print(
                        f"Tangent depth: [bold]{depth}[/bold]. "
                        "Use [yellow]/tangent end[/yellow] to return to the previous conversation."
                    )

        elif cmd == "mcp":
            # /mcp load <command_or_url>
            # /mcp list
            mcp_parts = arg.split(None, 1) if arg else []
            mcp_sub = mcp_parts[0].lower() if mcp_parts else ""
            mcp_arg = mcp_parts[1].strip() if len(mcp_parts) > 1 else ""

            if mcp_sub == "load":
                if not mcp_arg:
                    self._error("Usage: /mcp load <server-command-or-url>")
                else:
                    try:
                        from kiro.tools.mcp_tool import load_mcp_tools
                        # Decide stdio vs HTTP: if it starts with http it's a URL
                        if mcp_arg.startswith("http://") or mcp_arg.startswith("https://"):
                            server: list[str] | str = mcp_arg
                        else:
                            # Parse as a shell-style command string
                            import shlex
                            server = shlex.split(mcp_arg)
                        registered = load_mcp_tools(server, self.registry)
                        if registered:
                            self._info(
                                f"Loaded {len(registered)} MCP tool(s): "
                                + ", ".join(registered)
                            )
                        else:
                            self._info("Connected to MCP server but no tools were returned.")
                    except Exception as e:
                        self._error(f"MCP load failed: {e}")

            elif mcp_sub == "list":
                mcp_tools = [
                    t for t in self.registry.all_tools()
                    if t.__class__.__name__ == "MCPToolAdapter"
                ]
                if not mcp_tools:
                    self._info("No MCP tools loaded. Use /mcp load <command_or_url>.")
                else:
                    lines = [f"[bold]MCP tools ({len(mcp_tools)}):[/bold]"]
                    for t in mcp_tools:
                        lines.append(
                            f"  [yellow]{t.name}[/yellow] — {t.description[:80]}"
                        )
                    self._print("\n".join(lines))

            else:
                self._print(
                    "[bold]MCP commands:[/bold]\n"
                    "  [yellow]/mcp load[/yellow] <cmd|url>   Load tools from an MCP server\n"
                    "  [yellow]/mcp list[/yellow]              List loaded MCP tools"
                )

        elif cmd == "pipeline":
            if HAS_RICH and self.console:
                from rich.panel import Panel
                self.console.print(Panel(PIPELINE_HELP, title="Pipeline Scripting", border_style="green"))
            else:
                print(PIPELINE_HELP)

        elif cmd == "run":
            if not arg:
                self._error("Usage: /run <file.py>")
            else:
                self._run_script(arg)

        elif cmd == "init":
            path = write_default_config()
            self._info(f"Created {path}")

        else:
            self._error(f"Unknown command: /{cmd}. Type /help for a list of commands.")

        return True

    def _run_script(self, path: str):
        """Execute a Python pipeline script."""
        p = Path(path)
        if not p.exists():
            self._error(f"File not found: {path}")
            return
        try:
            code = p.read_text()
            exec(compile(code, path, "exec"), {"__name__": "__main__"})
        except SystemExit:
            pass
        except Exception as e:
            self._error(f"Script error: {e}")

    # ── Token usage display ────────────────────────────────────────────────────

    def _print_usage(self, turn_usage: dict) -> None:
        """Print per-turn and cumulative token usage in a dim line."""
        turn_in = turn_usage.get("input_tokens", 0)
        turn_out = turn_usage.get("output_tokens", 0)
        total = self.agent.total_usage
        total_in = total.get("input_tokens", 0)
        total_out = total.get("output_tokens", 0)

        line = (
            f"[in: {turn_in:,} out: {turn_out:,} tokens"
            f" | total: {total_in:,} in / {total_out:,} out]"
        )

        if HAS_RICH and self.console:
            self.console.print(f"[dim]{line}[/dim]")
        else:
            print(line)

    # ── Agent execution ────────────────────────────────────────────────────────

    def run_query(self, user_input: str):
        """Run a single user query through the agent."""
        show_tools = self.config.get("show_tool_calls", True)

        if HAS_RICH and self.console:
            self.console.print()  # blank line before response

        text_buf = []
        last_usage: dict = {}

        try:
            for event in self.agent.run(user_input):
                if isinstance(event, TextChunk):
                    text_buf.append(event.text)
                    if HAS_RICH and self.console:
                        self.console.print(event.text, end="", markup=False, highlight=False)
                    else:
                        print(event.text, end="", flush=True)

                elif isinstance(event, ToolCallStart):
                    if show_tools:
                        if HAS_RICH and self.console:
                            self.console.print()  # newline before tool
                            print_tool_call(event.name, event.arguments, self.console)
                        else:
                            print(f"\n⚙ {event.name}", flush=True)

                elif isinstance(event, ToolCallResult):
                    if show_tools:
                        print_tool_result(event.name, event.result, event.duration_ms, self.console)
                    # Reset text buffer after tool use
                    text_buf = []

                elif isinstance(event, AgentDone):
                    last_usage = event.usage

        except KeyboardInterrupt:
            self._print("\n[dim](interrupted)[/dim]")

        if HAS_RICH and self.console:
            self.console.print()  # final newline

        # Display token usage for this turn
        self._print_usage(last_usage)

    # ── REPL ──────────────────────────────────────────────────────────────────

    def repl(self):
        """Start the interactive REPL."""
        if HAS_RICH and self.console:
            self.console.print(f"[bold cyan]{BANNER}[/bold cyan]")
            self.console.print(
                f"[dim]Provider: {self.provider.__class__.__name__}  "
                f"Model: {self.provider.model}  "
                f"Tools: {len(self.registry)}[/dim]\n"
            )
        else:
            print(BANNER)

        prompt_str = "you > "

        while True:
            try:
                user_input = self._input(prompt_str).strip()
            except (KeyboardInterrupt, EOFError):
                self._print("\n[dim]Goodbye![/dim]")
                break

            if not user_input:
                continue

            if self.handle_slash(user_input):
                continue

            self.run_query(user_input)


# ── Entry points ──────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kiro",
        description="Kiro CLI — AI agent with multi-LLM support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kiro                                          # Interactive REPL
  kiro "write a Python hello world"            # One-shot
  kiro --provider anthropic "explain recursion"
  kiro --provider ollama --model llama3.2 "help me debug this"
  kiro --provider groq --model llama-3.1-70b-versatile "fast task"
  kiro --provider lmstudio "local model task"  # LM Studio
  kiro init                                    # Write kiro.config.json
        """,
    )
    parser.add_argument("message", nargs="?", help="Message to send (omit for REPL mode)")
    parser.add_argument("--provider", "-p", help="LLM provider (openai/anthropic/ollama/groq/...)")
    parser.add_argument("--model", "-m", help="Model name")
    parser.add_argument("--api-key", "-k", help="API key (overrides env var)")
    parser.add_argument("--api-base", "-b", help="API base URL (for OpenAI-compatible APIs)")
    parser.add_argument("--system", "-s", help="System prompt override")
    parser.add_argument("--temperature", "-t", type=float, help="Temperature (0.0–1.0)")
    parser.add_argument("--max-tokens", type=int, help="Max output tokens")
    parser.add_argument("--no-tools", action="store_true", help="Disable tool use")
    parser.add_argument("--quiet", "-q", action="store_true", help="Hide tool call output")
    parser.add_argument("--config", "-c", help="Path to kiro.config.json")
    parser.add_argument("init", nargs="?", help="Write default kiro.config.json")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    # Handle 'kiro init' command
    if args.message == "init" or args.init == "init":
        path = write_default_config()
        print(f"Created {path}")
        return

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    overrides = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    if args.api_key:
        overrides["api_key"] = args.api_key
    if args.api_base:
        overrides["api_base"] = args.api_base
    if args.system:
        overrides["system_prompt"] = args.system
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.max_tokens:
        overrides["max_tokens"] = args.max_tokens
    if args.quiet:
        overrides["show_tool_calls"] = False

    from kiro.config import Config
    merged = Config({**config._data, **overrides})

    cli = KiroCLI(merged)

    if args.no_tools:
        cli.registry._tools.clear()

    if args.message and args.message != "init":
        # One-shot mode
        cli.run_query(args.message)
    else:
        # REPL mode
        cli.repl()


if __name__ == "__main__":
    main()
