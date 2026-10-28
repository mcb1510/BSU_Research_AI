from __future__ import annotations
"""File system tools: read, write, glob, directory listing."""

import os
import fnmatch
from pathlib import Path

from .base import BaseTool


# ---------------------------------------------------------------------------
# .gitignore helpers (shared with search_tools via import)
# ---------------------------------------------------------------------------

def load_gitignore_patterns(root: Path) -> list[str]:
    """Read .gitignore from *root* and return a list of non-comment, non-empty patterns."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns: list[str] = []
    try:
        for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    except Exception:
        pass
    return patterns


# Directories that are always ignored regardless of .gitignore
_ALWAYS_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".cache", "target", ".idea", ".vscode",
})


def is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """Return True if *path* should be ignored.

    Checks:
    1. Whether any component of the path is in the hardcoded IGNORE_DIRS set.
    2. Whether any component or the relative path string matches a .gitignore pattern
       using :mod:`fnmatch`.
    """
    # 1. Hardcoded ignore dirs — check every component of the absolute path
    for part in path.parts:
        if part in _ALWAYS_IGNORE_DIRS:
            return True

    # 2. .gitignore patterns
    if not patterns:
        return False

    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path

    rel_str = str(rel)
    # Check the full relative path string and each individual component
    candidates = [rel_str, rel.name] + list(rel.parts)

    for pattern in patterns:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern):
                return True
        # Also match against just the file/dir name for patterns like "*.pyc"
        if fnmatch.fnmatch(path.name, pattern):
            return True

    return False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file. Optionally specify start/end line numbers (1-indexed). "
        "Returns file content as a string."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-indexed, optional).",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read inclusive (1-indexed, optional).",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"Error: File not found: {path}"
            if not p.is_file():
                return f"Error: Not a file: {path}"

            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)

            if start_line is not None or end_line is not None:
                s = (start_line or 1) - 1
                e = end_line if end_line else len(lines)
                lines = lines[s:e]
                content = "".join(lines)

            # Add line numbers if file is large
            if len(lines) > 50:
                numbered = []
                offset = (start_line or 1) - 1
                for i, line in enumerate(lines):
                    numbered.append(f"{offset + i + 1:4d} | {line}")
                content = "".join(numbered)

            return content or "(empty file)"
        except Exception as e:
            return f"Error reading {path}: {e}"


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write content to a file. Creates the file and any parent directories if they don't exist. "
        "Supports four modes:\n"
        "  • 'overwrite' (default) — replace the entire file.\n"
        "  • 'append' — add content to the end of the file.\n"
        "  • 'str_replace' — find old_str in the file and replace it with new_str. "
        "Set replace_all=true to replace every occurrence (default: first only).\n"
        "  • 'insert' — insert content at insert_line (0-indexed). "
        "If insert_line is omitted the content is appended to the end.\n"
        "The legacy append=true parameter is still accepted and maps to mode='append'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file.",
            },
            "content": {
                "type": "string",
                "description": "Content to write. Required for 'overwrite', 'append', and 'insert' modes.",
            },
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append", "str_replace", "insert"],
                "description": (
                    "Write mode. Default 'overwrite'. "
                    "'str_replace' requires old_str; 'insert' uses insert_line."
                ),
            },
            "old_str": {
                "type": "string",
                "description": "Exact string to find and replace. Required when mode='str_replace'.",
            },
            "new_str": {
                "type": "string",
                "description": "Replacement string used with mode='str_replace'.",
            },
            "insert_line": {
                "type": "integer",
                "description": (
                    "0-indexed line number to insert content before. "
                    "Used with mode='insert'. Omit to append to end."
                ),
            },
            "replace_all": {
                "type": "boolean",
                "description": (
                    "If true, replace all occurrences of old_str. "
                    "Used with mode='str_replace'. Default false."
                ),
            },
            # Legacy parameter — kept for backward compatibility
            "append": {
                "type": "boolean",
                "description": "Deprecated. Use mode='append' instead. If true, appends content.",
            },
        },
        "required": ["path"],
    }

    def execute(
        self,
        path: str,
        content: str = "",
        mode: str = "overwrite",
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
        replace_all: bool = False,
        # Legacy param
        append: bool = False,
    ) -> str:
        # Backward compat: legacy append=True maps to mode='append'
        if append and mode == "overwrite":
            mode = "append"

        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)

            # ------------------------------------------------------------------
            # overwrite
            # ------------------------------------------------------------------
            if mode == "overwrite":
                p.write_text(content, encoding="utf-8")
                return f"Wrote {path} ({len(content)} bytes)"

            # ------------------------------------------------------------------
            # append
            # ------------------------------------------------------------------
            if mode == "append":
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(content)
                return f"Appended to {path} ({len(content)} bytes)"

            # ------------------------------------------------------------------
            # str_replace
            # ------------------------------------------------------------------
            if mode == "str_replace":
                if old_str is None:
                    return "Error: old_str is required for mode='str_replace'"
                if not p.exists():
                    return f"Error: File not found: {path}"
                original = p.read_text(encoding="utf-8")
                replacement = new_str if new_str is not None else ""
                if old_str not in original:
                    return f"Error: old_str not found in {path}"
                if replace_all:
                    updated = original.replace(old_str, replacement)
                    count = original.count(old_str)
                else:
                    updated = original.replace(old_str, replacement, 1)
                    count = 1
                p.write_text(updated, encoding="utf-8")
                return (
                    f"Replaced {count} occurrence(s) in {path} "
                    f"({len(updated)} bytes total)"
                )

            # ------------------------------------------------------------------
            # insert
            # ------------------------------------------------------------------
            if mode == "insert":
                if p.exists():
                    existing = p.read_text(encoding="utf-8")
                    lines = existing.splitlines(keepends=True)
                    # Ensure last line ends with newline so the inserted block
                    # starts on a fresh line when appending.
                    if lines and not lines[-1].endswith("\n"):
                        lines[-1] += "\n"
                else:
                    lines = []

                # Ensure content ends with a newline
                insert_content = content if content.endswith("\n") else content + "\n"

                if insert_line is None:
                    # Append to end
                    lines.append(insert_content)
                else:
                    idx = max(0, min(insert_line, len(lines)))
                    lines.insert(idx, insert_content)

                updated = "".join(lines)
                p.write_text(updated, encoding="utf-8")
                pos = "end" if insert_line is None else f"line {insert_line}"
                return f"Inserted content at {pos} in {path} ({len(updated)} bytes total)"

            return f"Error: Unknown mode '{mode}'. Use overwrite, append, str_replace, or insert."

        except Exception as e:
            return f"Error writing {path}: {e}"


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Find files matching a glob pattern. Returns a newline-separated list of matching paths. "
        "Respects .gitignore and common ignore patterns (.git, node_modules, __pycache__, etc.)"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern e.g. '**/*.py', 'src/**/*.ts', '*.json'",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from. Defaults to current directory.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return. Default 100.",
            },
        },
        "required": ["pattern"],
    }

    # Kept for direct reference by other code; is_ignored() also uses _ALWAYS_IGNORE_DIRS
    IGNORE_DIRS = _ALWAYS_IGNORE_DIRS

    def execute(self, pattern: str, path: str | None = None, limit: int = 100) -> str:
        import glob as glob_module

        root = Path(path or ".").expanduser().resolve()
        full_pattern = str(root / pattern)

        try:
            matches = glob_module.glob(full_pattern, recursive=True)
        except Exception as e:
            return f"Error: {e}"

        # Load .gitignore patterns from the root directory
        gitignore_patterns = load_gitignore_patterns(root)

        # Filter using is_ignored() which covers both IGNORE_DIRS and .gitignore patterns
        filtered = [
            m for m in matches
            if not is_ignored(Path(m), root, gitignore_patterns)
        ]

        filtered.sort()
        filtered = filtered[:limit]

        if not filtered:
            return f"No files found matching '{pattern}' in {root}"
        return "\n".join(filtered)


class DirectoryTool(BaseTool):
    name = "list_directory"
    description = "List the contents of a directory. Shows files and subdirectories."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list. Defaults to current directory.",
            },
            "depth": {
                "type": "integer",
                "description": "How deep to recurse. 0 = just the given directory. Default 0.",
            },
        },
        "required": [],
    }

    IGNORE = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea"}

    def execute(self, path: str = ".", depth: int = 0) -> str:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            return f"Error: Path does not exist: {path}"
        if not root.is_dir():
            return f"Error: Not a directory: {path}"

        lines = [str(root)]
        self._walk(root, "", depth, 0, lines)
        return "\n".join(lines)

    def _walk(self, directory: Path, prefix: str, max_depth: int, current_depth: int, lines: list):
        if current_depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return

        for i, entry in enumerate(entries):
            if entry.name in self.IGNORE:
                continue
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.is_dir() and current_depth < max_depth:
                extension = "    " if is_last else "│   "
                self._walk(entry, prefix + extension, max_depth, current_depth + 1, lines)
