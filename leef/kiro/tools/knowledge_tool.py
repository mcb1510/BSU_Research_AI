from __future__ import annotations
"""Knowledge base tool: index files/directories for semantic search using TF-IDF cosine similarity.

No external vector databases or ML libraries required — pure Python stdlib only.
Knowledge bases are stored as JSON files at ~/.kiro/knowledge/{name}.json.
"""

import json
import math
import os
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .base import BaseTool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWLEDGE_DIR = Path.home() / ".kiro" / "knowledge"

CHUNK_SIZE = 500       # target characters per chunk
CHUNK_OVERLAP = 50     # overlap between adjacent chunks

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".cache", "target", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", ".tox", "htmlcov", ".eggs", "*.egg-info",
}

# Binary-ish extensions to skip
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyd", ".class",
    ".db", ".sqlite", ".sqlite3",
    ".lock",  # lockfiles are usually binary-ish noise
}


# ---------------------------------------------------------------------------
# TF-IDF helpers (pure stdlib)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lower-case, split on non-alphanumeric, filter short tokens."""
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1]


def _term_freq(tokens: list[str]) -> dict[str, float]:
    """Compute raw term frequencies (count / total)."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF vectors."""
    if not vec_a or not vec_b:
        return 0.0
    # dot product over shared keys
    dot = sum(vec_a[k] * vec_b[k] for k in vec_a if k in vec_b)
    if dot == 0.0:
        return 0.0
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, source_path: str) -> list[dict[str, Any]]:
    """Split *text* into overlapping chunks, tracking line numbers.

    Returns a list of dicts:
      {
        "text": str,
        "source": str,
        "start_line": int,   # 1-indexed, inclusive
        "end_line": int,     # 1-indexed, inclusive
        "vector": dict[str, float],
      }
    """
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[dict[str, Any]] = []

    # Build a flat list of (line_index, char_content) so we can map
    # character positions back to line numbers cheaply.
    line_starts: list[int] = []  # character offset of the start of each line
    flat = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        flat.append(line)
        offset += len(line) + 1  # +1 for newline

    full_text = "\n".join(lines)
    total_chars = len(full_text)

    pos = 0
    while pos < total_chars:
        end = min(pos + CHUNK_SIZE, total_chars)
        chunk_text = full_text[pos:end]

        # Find start/end line numbers for this chunk
        # start_line: last line_start <= pos
        start_line = _char_to_line(line_starts, pos)
        end_line = _char_to_line(line_starts, max(end - 1, pos))

        tokens = _tokenize(chunk_text)
        vector = _term_freq(tokens)

        chunks.append({
            "text": chunk_text,
            "source": source_path,
            "start_line": start_line + 1,  # convert to 1-indexed
            "end_line": end_line + 1,
            "vector": vector,
        })

        # Advance by (CHUNK_SIZE - CHUNK_OVERLAP) but at least 1 char
        step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
        pos += step

    return chunks


def _char_to_line(line_starts: list[int], char_pos: int) -> int:
    """Binary search: return 0-indexed line index for *char_pos*."""
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= char_pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _kb_path(name: str) -> Path:
    return KNOWLEDGE_DIR / f"{name}.json"


def _load_kb(name: str) -> dict[str, Any] | None:
    """Load a knowledge base from disk; returns None if it doesn't exist."""
    p = _kb_path(name)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _save_kb(name: str, kb: dict[str, Any]) -> None:
    """Persist a knowledge base to disk."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    with _kb_path(name).open("w", encoding="utf-8") as fh:
        json.dump(kb, fh, ensure_ascii=False, indent=2)


def _is_binary_file(path: Path) -> bool:
    """Heuristic: check extension first, then sniff the first 8 KB."""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as fh:
            sample = fh.read(8192)
        # If >30% of bytes are non-printable (outside 0x09-0x0d, 0x20-0x7e) → binary
        non_printable = sum(
            1 for b in sample
            if not (0x09 <= b <= 0x0D or 0x20 <= b <= 0x7E)
        )
        return len(sample) > 0 and non_printable / len(sample) > 0.30
    except OSError:
        return True


# ---------------------------------------------------------------------------
# KnowledgeTool
# ---------------------------------------------------------------------------

class KnowledgeTool(BaseTool):
    """Index files/directories for semantic search using TF-IDF cosine similarity."""

    name = "knowledge"
    description = (
        "Index files/directories for semantic search and search across them by meaning. "
        "Use to find relevant code, docs, or notes without knowing exact filenames or keywords.\n"
        "Commands:\n"
        "  index  — index a file or directory into a named knowledge base\n"
        "  search — search across one or all knowledge bases by meaning\n"
        "  list   — show all indexed knowledge bases with file counts\n"
        "  remove — delete a knowledge base by name or context_id"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["index", "search", "list", "remove"],
                "description": "Action to perform.",
            },
            "name": {
                "type": "string",
                "description": "Name for the knowledge base (used with index/remove/search).",
            },
            "path": {
                "type": "string",
                "description": "File or directory path to index (required for 'index').",
            },
            "query": {
                "type": "string",
                "description": "Search query text (required for 'search').",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return for 'search'. Default 5.",
            },
            "context_id": {
                "type": "string",
                "description": "Target a specific knowledge base by its unique ID (used with 'search'/'remove').",
            },
        },
        "required": ["command"],
    }

    def __init__(self) -> None:
        # _store maps name → kb dict (lazy-loaded on first access per name)
        # We eagerly discover which KBs exist on disk but don't load them all.
        self._store: dict[str, dict[str, Any]] = {}
        self._load_all_from_disk()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all_from_disk(self) -> None:
        """Populate _store with metadata (no chunk data) for all on-disk KBs."""
        if not KNOWLEDGE_DIR.exists():
            return
        for p in KNOWLEDGE_DIR.glob("*.json"):
            name = p.stem
            if name not in self._store:
                kb = _load_kb(name)
                if kb is not None:
                    self._store[name] = kb

    def _get_kb(self, name: str) -> dict[str, Any] | None:
        """Return in-memory KB, loading from disk if needed."""
        if name in self._store:
            return self._store[name]
        kb = _load_kb(name)
        if kb is not None:
            self._store[name] = kb
        return kb

    def _find_by_context_id(self, context_id: str) -> str | None:
        """Return the name of the KB with matching context_id, or None."""
        for name, kb in self._store.items():
            if kb.get("context_id") == context_id:
                return name
        return None

    # ------------------------------------------------------------------
    # Public execute dispatcher
    # ------------------------------------------------------------------

    def execute(
        self,
        command: str,
        name: str | None = None,
        path: str | None = None,
        query: str | None = None,
        limit: int = 5,
        context_id: str | None = None,
    ) -> str:
        cmd = command.lower().strip()
        if cmd == "index":
            return self._cmd_index(name=name, path=path)
        elif cmd == "search":
            return self._cmd_search(query=query, name=name, context_id=context_id, limit=limit)
        elif cmd == "list":
            return self._cmd_list()
        elif cmd == "remove":
            return self._cmd_remove(name=name, context_id=context_id)
        else:
            return f"Error: Unknown command '{command}'. Use one of: index, search, list, remove."

    # ------------------------------------------------------------------
    # Command: index
    # ------------------------------------------------------------------

    def _cmd_index(self, name: str | None, path: str | None) -> str:
        if not path:
            return "Error: 'path' is required for the 'index' command."
        if not name:
            # Derive a name from the path's base name
            name = Path(path).expanduser().resolve().name or "unnamed"
            # Sanitise: keep only alphanumeric, dash, underscore
            name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)

        target = Path(path).expanduser().resolve()
        if not target.exists():
            return f"Error: Path does not exist: {path}"

        # Collect all text files to index
        if target.is_file():
            files_to_index = [target] if not _is_binary_file(target) else []
        else:
            files_to_index = list(self._walk_dir(target))

        if not files_to_index:
            return f"No indexable text files found at '{path}'."

        # Build / refresh the knowledge base
        cid = str(uuid.uuid4())
        # Preserve context_id if KB already exists
        existing = self._get_kb(name)
        if existing:
            cid = existing.get("context_id", cid)

        chunks: list[dict[str, Any]] = []
        indexed_files: set[str] = set()
        skipped = 0

        for fp in files_to_index:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue

            if not text.strip():
                continue

            file_chunks = _chunk_text(text, str(fp))
            chunks.extend(file_chunks)
            indexed_files.add(str(fp))

        if not chunks:
            return f"No content could be extracted from '{path}'."

        kb: dict[str, Any] = {
            "context_id": cid,
            "name": name,
            "source_path": str(target),
            "file_count": len(indexed_files),
            "chunk_count": len(chunks),
            "files": sorted(indexed_files),
            "chunks": chunks,
        }

        _save_kb(name, kb)
        self._store[name] = kb

        lines = [
            f"Indexed knowledge base '{name}' (id: {cid[:8]}…)",
            f"  Source : {target}",
            f"  Files  : {len(indexed_files)}",
            f"  Chunks : {len(chunks)}",
        ]
        if skipped:
            lines.append(f"  Skipped: {skipped} unreadable file(s)")
        return "\n".join(lines)

    def _walk_dir(self, root: Path):
        """Yield all non-binary files under *root*, skipping ignored dirs."""
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune ignored directories in-place so os.walk skips them
            dirnames[:] = [
                d for d in dirnames
                if d not in IGNORED_DIRS and not d.endswith(".egg-info")
            ]
            for fname in sorted(filenames):
                fp = Path(dirpath) / fname
                if not _is_binary_file(fp):
                    yield fp

    # ------------------------------------------------------------------
    # Command: search
    # ------------------------------------------------------------------

    def _cmd_search(
        self,
        query: str | None,
        name: str | None,
        context_id: str | None,
        limit: int,
    ) -> str:
        if not query:
            return "Error: 'query' is required for the 'search' command."

        limit = max(1, int(limit))

        # Determine which knowledge bases to search
        if context_id:
            kb_name = self._find_by_context_id(context_id)
            if kb_name is None:
                return f"Error: No knowledge base found with context_id '{context_id}'."
            search_names = [kb_name]
        elif name:
            kb = self._get_kb(name)
            if kb is None:
                return f"Error: Knowledge base '{name}' not found. Run 'knowledge index' first."
            search_names = [name]
        else:
            # Search all
            self._load_all_from_disk()
            search_names = list(self._store.keys())
            if not search_names:
                return "No knowledge bases found. Run 'knowledge index' to create one."

        query_tokens = _tokenize(query)
        query_vec = _term_freq(query_tokens)

        if not query_vec:
            return "Error: Query produced no searchable tokens."

        # Score all chunks across the selected KBs
        scored: list[tuple[float, str, dict[str, Any]]] = []

        for kb_name in search_names:
            kb = self._get_kb(kb_name)
            if kb is None:
                continue
            for chunk in kb.get("chunks", []):
                chunk_vec = chunk.get("vector", {})
                score = _cosine_similarity(query_vec, chunk_vec)
                if score > 0:
                    scored.append((score, kb_name, chunk))

        if not scored:
            scope = f"'{name}'" if name else "any knowledge base"
            return f"No relevant results found in {scope} for query: {query!r}"

        # Sort descending by score, take top-k
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        lines = [f"Top {len(top)} result(s) for: {query!r}", ""]
        for rank, (score, kb_name, chunk) in enumerate(top, 1):
            source = chunk.get("source", "unknown")
            start = chunk.get("start_line", "?")
            end = chunk.get("end_line", "?")
            snippet = chunk.get("text", "").strip()
            # Truncate long snippets for readability
            if len(snippet) > 300:
                snippet = snippet[:297] + "…"

            lines.append(f"[{rank}] score={score:.4f}  kb={kb_name}")
            lines.append(f"     file={source}  lines={start}-{end}")
            lines.append(f"     {snippet}")
            lines.append("")

        return "\n".join(lines).rstrip()

    # ------------------------------------------------------------------
    # Command: list
    # ------------------------------------------------------------------

    def _cmd_list(self) -> str:
        self._load_all_from_disk()

        if not self._store:
            return "No knowledge bases indexed yet. Use 'knowledge index' to create one."

        lines = [f"Knowledge bases ({len(self._store)} total):", ""]
        for name, kb in sorted(self._store.items()):
            cid = kb.get("context_id", "—")
            file_count = kb.get("file_count", "?")
            chunk_count = kb.get("chunk_count", "?")
            source = kb.get("source_path", "?")
            lines.append(f"  {name}")
            lines.append(f"    id     : {cid}")
            lines.append(f"    source : {source}")
            lines.append(f"    files  : {file_count}")
            lines.append(f"    chunks : {chunk_count}")
            lines.append("")

        return "\n".join(lines).rstrip()

    # ------------------------------------------------------------------
    # Command: remove
    # ------------------------------------------------------------------

    def _cmd_remove(self, name: str | None, context_id: str | None) -> str:
        if not name and not context_id:
            return "Error: Provide 'name' or 'context_id' to identify the knowledge base to remove."

        target_name = name
        if context_id and not target_name:
            target_name = self._find_by_context_id(context_id)
            if target_name is None:
                return f"Error: No knowledge base found with context_id '{context_id}'."

        assert target_name is not None  # satisfied by logic above

        kb = self._get_kb(target_name)
        if kb is None:
            return f"Error: Knowledge base '{target_name}' not found."

        p = _kb_path(target_name)
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            return f"Error deleting '{target_name}': {e}"

        self._store.pop(target_name, None)
        return f"Removed knowledge base '{target_name}'."
