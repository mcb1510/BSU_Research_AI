from __future__ import annotations
"""Code intelligence tools: symbol extraction, symbol search, and pattern search."""

import ast
import os
import re
from pathlib import Path
from typing import Iterator

from .base import BaseTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".eggs", ".hg", ".svn",
}

_LANG_EXTENSIONS: dict[str, list[str]] = {
    "python":     [".py"],
    "javascript": [".js", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "js":         [".js", ".mjs", ".cjs"],
    "ts":         [".ts", ".tsx"],
}

_SOURCE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".cs", ".go", ".rb", ".rs", ".swift", ".kt", ".kts",
    ".php", ".scala", ".lua", ".r", ".sh", ".bash",
}


def _iter_source_files(root: Path, extensions: set[str] | None = None) -> Iterator[Path]:
    """Walk *root* recursively, yielding source files while skipping noise dirs."""
    ext_filter = extensions or _SOURCE_EXTENSIONS
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in ext_filter:
                yield fpath


def _extensions_for_language(language: str | None) -> set[str] | None:
    """Return the file-extension set for *language*, or None to mean 'all'."""
    if not language:
        return None
    return set(_LANG_EXTENSIONS.get(language.lower(), []))


# ---------------------------------------------------------------------------
# 1. DocumentSymbolsTool
# ---------------------------------------------------------------------------


class DocumentSymbolsTool(BaseTool):
    name = "get_document_symbols"
    description = (
        "List all symbols (classes, functions, methods) defined in a source file. "
        "Returns each symbol's name, type (class/function/method), and line number. "
        "For Python files the AST is used for accuracy; for JS/TS files regex-based "
        "extraction is used. Pass top_level_only=true to skip methods/nested functions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the source file to inspect.",
            },
            "top_level_only": {
                "type": "boolean",
                "description": (
                    "When true, return only top-level symbols (classes and module-level "
                    "functions) and omit methods or nested definitions. Default false."
                ),
            },
        },
        "required": ["path"],
    }

    # -- public entry point --------------------------------------------------

    def execute(self, path: str, top_level_only: bool = False) -> str:
        fpath = Path(path).expanduser().resolve()
        if not fpath.exists():
            return f"Error: File not found: {path}"
        if not fpath.is_file():
            return f"Error: Path is not a file: {path}"

        ext = fpath.suffix.lower()
        if ext == ".py":
            return self._python_symbols(fpath, top_level_only)
        elif ext in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
            return self._js_ts_symbols(fpath, top_level_only)
        else:
            display_ext = ext if ext else "(no extension)"
            return f"Symbol extraction not supported for {display_ext} files"

    # -- Python (AST) --------------------------------------------------------

    def _python_symbols(self, fpath: Path, top_level_only: bool) -> str:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(fpath))
        except SyntaxError as e:
            return f"Error: Could not parse {fpath.name}: {e}"
        except Exception as e:
            return f"Error reading {fpath.name}: {e}"

        lines: list[str] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                lines.append(f"{node.name} (class) line {node.lineno}")
                if not top_level_only:
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            lines.append(f"  {child.name} (method) line {child.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append(f"{node.name} (function) line {node.lineno}")

        if not lines:
            return f"No symbols found in {fpath.name}"
        return "\n".join(lines)

    # -- JavaScript / TypeScript (regex) ------------------------------------

    def _js_ts_symbols(self, fpath: Path, top_level_only: bool) -> str:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error reading {fpath.name}: {e}"

        lines_src = source.splitlines()
        symbols: list[tuple[int, str, str, int]] = []  # (indent_level, name, kind, lineno)

        # Patterns (order matters — more specific first)
        patterns = [
            # class declarations: class Foo / class Foo extends Bar
            (0, re.compile(r"^(?P<ind>\s*)(?:export\s+(?:default\s+)?)?class\s+(?P<name>[A-Za-z_$][\w$]*)"),         "class"),
            # method shorthand inside class body: methodName( or async methodName(
            (1, re.compile(r"^(?P<ind>  +)(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\("), "method"),
            # function declarations: function foo(
            (0, re.compile(r"^(?P<ind>\s*)(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)"), "function"),
            # arrow / const functions: const foo = ( / const foo = async (
            (0, re.compile(r"^(?P<ind>\s*)(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("), "function"),
            # arrow assigned with arrow shorthand: const foo = x =>
            (0, re.compile(r"^(?P<ind>\s*)(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:[A-Za-z_$][\w$]*)\s*=>"), "function"),
        ]

        # Track class indentation levels to distinguish methods from functions
        class_indent_stack: list[int] = []

        for lineno, line in enumerate(lines_src, 1):
            for priority, rx, kind in patterns:
                m = rx.match(line)
                if not m:
                    continue
                name = m.group("name")
                indent = len(m.group("ind")) if "ind" in rx.groupindex else 0

                # Update class indent stack heuristically
                if kind == "class":
                    class_indent_stack.append(indent)
                elif kind == "method":
                    # Only treat as method if we're inside a class scope
                    if not class_indent_stack or indent <= class_indent_stack[-1]:
                        kind = "function"

                # top_level_only: skip methods and indented symbols
                if top_level_only and indent > 0:
                    break

                symbols.append((indent, name, kind, lineno))
                break  # first matching pattern wins per line

        if not symbols:
            return f"No symbols found in {fpath.name}"

        result_lines: list[str] = []
        for indent, name, kind, lineno in symbols:
            prefix = "  " if (kind == "method" or indent > 0) else ""
            result_lines.append(f"{prefix}{name} ({kind}) line {lineno}")

        return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# 2. SearchSymbolsTool
# ---------------------------------------------------------------------------


class SearchSymbolsTool(BaseTool):
    name = "search_symbols"
    description = (
        "Search for a symbol (class, function, method, variable) by name across the "
        "codebase. Returns file paths and line numbers where the symbol is defined. "
        "Searches definition patterns: 'def name', 'class name', 'function name', "
        "'const name =', etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol_name": {
                "type": "string",
                "description": "Name of the symbol to search for.",
            },
            "path": {
                "type": "string",
                "description": "Root directory (or file) to search in. Defaults to '.'.",
            },
            "language": {
                "type": "string",
                "description": (
                    "Restrict search to files of a specific language: "
                    "'python', 'javascript', 'typescript'. "
                    "Omit to search all source files."
                ),
            },
        },
        "required": ["symbol_name"],
    }

    # Definition patterns per language family
    _PYTHON_DEF_PATTERNS = [
        r"^\s*def\s+{name}\s*[\(:]",
        r"^\s*async\s+def\s+{name}\s*\(",
        r"^\s*class\s+{name}\s*[\(:]",
        r"^\s*{name}\s*=\s*",           # module-level assignment / variable
    ]

    _JS_TS_DEF_PATTERNS = [
        r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*{name}\s*\(",
        r"^\s*(?:export\s+(?:default\s+)?)?class\s+{name}\b",
        r"^\s*(?:export\s+)?(?:const|let|var)\s+{name}\s*=",
        r"^\s*(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?{name}\s*\(",  # method
    ]

    _GENERIC_PATTERNS = [
        r"\b{name}\s*[\(=:]",
    ]

    def execute(
        self,
        symbol_name: str,
        path: str = ".",
        language: str | None = None,
    ) -> str:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            return f"Error: Path not found: {path}"

        extensions = _extensions_for_language(language)
        files = [root] if root.is_file() else list(_iter_source_files(root, extensions))

        # Build per-extension regex lists
        py_exts  = {".py"}
        js_exts  = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}

        def _build_patterns(raw_list: list[str]) -> list[re.Pattern]:
            compiled = []
            for p in raw_list:
                try:
                    compiled.append(re.compile(p.format(name=re.escape(symbol_name))))
                except re.error:
                    pass
            return compiled

        py_patterns      = _build_patterns(self._PYTHON_DEF_PATTERNS)
        js_patterns      = _build_patterns(self._JS_TS_DEF_PATTERNS)
        generic_patterns = _build_patterns(self._GENERIC_PATTERNS)

        matches: list[str] = []
        MAX_MATCHES = 100

        for fpath in sorted(files):
            if len(matches) >= MAX_MATCHES:
                break
            ext = fpath.suffix.lower()
            if ext in py_exts:
                patterns = py_patterns
            elif ext in js_exts:
                patterns = js_patterns
            else:
                patterns = generic_patterns

            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for lineno, line in enumerate(text.splitlines(), 1):
                if len(matches) >= MAX_MATCHES:
                    break
                for rx in patterns:
                    if rx.search(line):
                        matches.append(f"{fpath}:{lineno}: {line.rstrip()}")
                        break  # one match per line

        if not matches:
            return f"No definitions of '{symbol_name}' found in {root}"

        output = "\n".join(matches)
        if len(matches) >= MAX_MATCHES:
            output += f"\n\n(Results truncated at {MAX_MATCHES} matches)"
        return output


# ---------------------------------------------------------------------------
# 3. PatternSearchTool
# ---------------------------------------------------------------------------


class PatternSearchTool(BaseTool):
    name = "pattern_search"
    description = (
        "Search for a structural code pattern across files. Smarter than raw regex — "
        "understands basic code structure such as function definitions, class definitions, "
        "import statements, function calls, and assignments.\n\n"
        "Supported patterns:\n"
        "  function_def           — all function/method definitions\n"
        "  class_def              — all class definitions\n"
        "  import                 — all import statements\n"
        "  function_call:<name>   — calls to a specific function, e.g. function_call:print\n"
        "  assignment:<name>      — assignments to a variable, e.g. assignment:result\n"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Structural pattern to search for. One of: "
                    "'function_def', 'class_def', 'import', "
                    "'function_call:<name>', 'assignment:<name>'."
                ),
            },
            "path": {
                "type": "string",
                "description": "Root directory (or file) to search in. Defaults to '.'.",
            },
            "language": {
                "type": "string",
                "description": (
                    "Restrict search to a specific language: "
                    "'python', 'javascript', 'typescript'. "
                    "Omit to search all source files."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return. Default 20.",
            },
        },
        "required": ["pattern"],
    }

    # ------------------------------------------------------------------
    # Pattern → regex maps (per language family)
    # ------------------------------------------------------------------

    _PYTHON_PATTERNS: dict[str, str] = {
        "function_def": r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
        "class_def":    r"^\s*class\s+([A-Za-z_]\w*)\s*[\(:]",
        "import":       r"^\s*(?:import|from)\s+\S",
    }

    _JS_PATTERNS: dict[str, str] = {
        "function_def": (
            r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("
            r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("
            r"|^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\("
        ),
        "class_def":    r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)\b",
        "import":       r"^\s*(?:import\s|require\s*\()",
    }

    _GENERIC_PATTERNS: dict[str, str] = {
        "function_def": r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|\bdef\s+([A-Za-z_]\w*)\s*\(",
        "class_def":    r"\bclass\s+([A-Za-z_$][\w$]*)\b",
        "import":       r"^\s*(?:import|from|require|include|use)\b",
    }

    def execute(
        self,
        pattern: str,
        path: str = ".",
        language: str | None = None,
        limit: int = 20,
    ) -> str:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            return f"Error: Path not found: {path}"

        # Parse compound patterns like 'function_call:print'
        base_pattern, _, arg = pattern.partition(":")
        base_pattern = base_pattern.strip().lower()
        arg = arg.strip()

        extensions = _extensions_for_language(language)
        files = [root] if root.is_file() else list(_iter_source_files(root, extensions))

        # Pick regex table based on language / file extension heuristic
        py_exts = {".py"}
        js_exts = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}

        def _get_regex(fpath: Path) -> re.Pattern | None:
            ext = fpath.suffix.lower()
            if ext in py_exts:
                table = self._PYTHON_PATTERNS
            elif ext in js_exts:
                table = self._JS_PATTERNS
            else:
                table = self._GENERIC_PATTERNS

            if base_pattern in ("function_def", "class_def", "import"):
                raw = table.get(base_pattern)
                if not raw:
                    return None
                try:
                    return re.compile(raw, re.MULTILINE)
                except re.error:
                    return None

            elif base_pattern == "function_call":
                if not arg:
                    return None
                name = re.escape(arg)
                # Python / generic: name( …  or  name (
                if ext in py_exts:
                    raw = rf"\b{name}\s*\("
                elif ext in js_exts:
                    raw = rf"\b{name}\s*\("
                else:
                    raw = rf"\b{name}\s*\("
                try:
                    return re.compile(raw)
                except re.error:
                    return None

            elif base_pattern == "assignment":
                if not arg:
                    return None
                name = re.escape(arg)
                if ext in py_exts:
                    raw = rf"^\s*{name}\s*="
                elif ext in js_exts:
                    raw = rf"(?:const|let|var)\s+{name}\s*=|^\s*{name}\s*="
                else:
                    raw = rf"\b{name}\s*="
                try:
                    return re.compile(raw, re.MULTILINE)
                except re.error:
                    return None

            return None

        # Validate pattern name early
        valid_bases = {"function_def", "class_def", "import", "function_call", "assignment"}
        if base_pattern not in valid_bases:
            return (
                f"Error: Unknown pattern '{pattern}'. "
                f"Supported: function_def, class_def, import, "
                f"function_call:<name>, assignment:<name>"
            )

        if base_pattern in ("function_call", "assignment") and not arg:
            return f"Error: Pattern '{base_pattern}' requires a name argument, e.g. '{base_pattern}:my_func'"

        matches: list[str] = []

        for fpath in sorted(files):
            if len(matches) >= limit:
                break
            rx = _get_regex(fpath)
            if rx is None:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if len(matches) >= limit:
                    break
                if rx.search(line):
                    matches.append(f"{fpath}:{lineno}: {line.rstrip()}")

        if not matches:
            desc = pattern if not arg else f"{base_pattern}:{arg}"
            return f"No matches for pattern '{desc}' in {root}"

        output = "\n".join(matches)
        if len(matches) >= limit:
            output += f"\n\n(Results truncated at {limit} matches)"
        return output
