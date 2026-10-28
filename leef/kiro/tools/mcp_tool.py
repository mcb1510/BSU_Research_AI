from __future__ import annotations
"""MCP (Model Context Protocol) tool loader stub.

Supports connecting to an MCP server via:
  - stdio  — launch a subprocess and communicate over its stdin/stdout using JSON-RPC 2.0
  - HTTP   — send JSON-RPC 2.0 requests to a running HTTP server

Example usage
-------------
    from kiro.tools.mcp_tool import load_mcp_tools

    # stdio MCP server
    load_mcp_tools(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"], registry)

    # HTTP MCP server
    load_mcp_tools("http://localhost:8080", registry)
"""

import json
import subprocess
import threading
import time
from typing import Any

from kiro.tools.base import BaseTool, ToolRegistry


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _make_request(method: str, params: dict, req_id: int) -> bytes:
    """Serialise a JSON-RPC 2.0 request to bytes (newline-terminated)."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": req_id,
    }
    return (json.dumps(payload) + "\n").encode()


def _parse_response(raw: str) -> dict:
    """Parse a raw JSON-RPC 2.0 response string."""
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from MCP server: {raw!r}") from exc


# ── MCPClient ─────────────────────────────────────────────────────────────────

class MCPClient:
    """Connect to an MCP server and call its tools via JSON-RPC 2.0.

    Parameters
    ----------
    server_command:
        List of strings used to launch a stdio MCP server
        (e.g. ``["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]``).
        Mutually exclusive with *server_url*.
    server_url:
        HTTP endpoint of a running MCP server
        (e.g. ``"http://localhost:8080"``).
        Mutually exclusive with *server_command*.
    timeout:
        Seconds to wait for a response (default 30).
    """

    def __init__(
        self,
        server_command: list[str] | None = None,
        server_url: str | None = None,
        timeout: float = 30.0,
    ):
        if server_command is None and server_url is None:
            raise ValueError("Provide either server_command or server_url.")
        if server_command is not None and server_url is not None:
            raise ValueError("Provide only one of server_command or server_url, not both.")

        self.server_command = server_command
        self.server_url = server_url
        self.timeout = timeout

        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._connected = False

    # ── Connection management ────────────────────────────────────────────────

    def connect(self) -> None:
        """Establish a connection to the MCP server.

        For stdio: spawns the subprocess.
        For HTTP: performs a lightweight connectivity check.
        """
        if self._connected:
            return

        if self.server_command is not None:
            self._connect_stdio()
        else:
            self._connect_http()

        self._connected = True

    def _connect_stdio(self) -> None:
        """Launch the MCP server as a subprocess."""
        try:
            self._process = subprocess.Popen(
                self.server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # binary mode — we handle encoding ourselves
            )
            # Give the process a moment to start up
            time.sleep(0.2)
            if self._process.poll() is not None:
                stderr_out = self._process.stderr.read().decode(errors="replace")
                raise RuntimeError(
                    f"MCP server process exited immediately.\nstderr: {stderr_out}"
                )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Could not launch MCP server: command not found — {self.server_command[0]!r}"
            ) from exc

    def _connect_http(self) -> None:
        """Verify the HTTP endpoint is reachable (best-effort)."""
        try:
            import requests  # type: ignore[import]
            resp = requests.get(self.server_url, timeout=self.timeout)  # type: ignore[arg-type]
            # Any HTTP response means the server is alive; errors are tolerated here
        except Exception:
            # Connection refused / DNS failure — surface as a warning but don't abort
            pass  # actual errors will surface on the first RPC call

    def close(self) -> None:
        """Terminate the subprocess (stdio only)."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                pass
            self._process = None
        self._connected = False

    def __enter__(self) -> "MCPClient":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Low-level RPC ────────────────────────────────────────────────────────

    def _rpc(self, method: str, params: dict, req_id: int) -> dict:
        """Send a JSON-RPC request and return the parsed response dict."""
        if not self._connected:
            self.connect()

        if self.server_command is not None:
            return self._rpc_stdio(method, params, req_id)
        else:
            return self._rpc_http(method, params, req_id)

    def _rpc_stdio(self, method: str, params: dict, req_id: int) -> dict:
        """Send a JSON-RPC message over the subprocess stdin/stdout."""
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("MCP stdio server process is not running.")

        request_bytes = _make_request(method, params, req_id)

        with self._lock:
            self._process.stdin.write(request_bytes)  # type: ignore[union-attr]
            self._process.stdin.flush()  # type: ignore[union-attr]

            # Read response lines until we get a complete JSON object
            raw_line = self._process.stdout.readline()  # type: ignore[union-attr]
            if not raw_line:
                raise RuntimeError("MCP server closed stdout without sending a response.")

        return _parse_response(raw_line.decode())

    def _rpc_http(self, method: str, params: dict, req_id: int) -> dict:
        """Send a JSON-RPC message over HTTP POST."""
        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'requests' package is required for HTTP MCP connections. "
                "Install it with: pip install requests"
            ) from exc

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }
        resp = requests.post(
            self.server_url,  # type: ignore[arg-type]
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Public API ───────────────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Ask the MCP server for its tool catalogue.

        Sends:
            {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1}

        Returns a list of tool definition dicts, each containing at minimum:
            {"name": str, "description": str, "inputSchema": dict}
        """
        response = self._rpc("tools/list", {}, req_id=1)
        if "error" in response:
            raise RuntimeError(f"MCP tools/list error: {response['error']}")
        result = response.get("result", {})
        # The MCP spec wraps the list under a "tools" key
        return result.get("tools", result) if isinstance(result, dict) else result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on the MCP server.

        Sends:
            {"jsonrpc": "2.0", "method": "tools/call",
             "params": {"name": name, "arguments": arguments}, "id": 2}

        Returns the raw ``result`` field from the JSON-RPC response.
        """
        response = self._rpc("tools/call", {"name": name, "arguments": arguments}, req_id=2)
        if "error" in response:
            raise RuntimeError(
                f"MCP tools/call error for {name!r}: {response['error']}"
            )
        return response.get("result")


# ── MCPToolAdapter ────────────────────────────────────────────────────────────

class MCPToolAdapter(BaseTool):
    """Wraps a single MCP tool definition so it can be used as a :class:`BaseTool`.

    Parameters
    ----------
    client:
        A connected :class:`MCPClient` instance.
    tool_def:
        The tool definition dict returned by :meth:`MCPClient.list_tools`.
    """

    def __init__(self, client: MCPClient, tool_def: dict):
        self._client = client
        self._tool_def = tool_def

    # BaseTool abstract properties -------------------------------------------

    @property
    def name(self) -> str:
        return self._tool_def["name"]

    @property
    def description(self) -> str:
        return self._tool_def.get("description", "(no description provided)")

    @property
    def parameters(self) -> dict:
        # MCP uses "inputSchema" (JSON Schema); fall back to empty object schema
        return self._tool_def.get(
            "inputSchema",
            {"type": "object", "properties": {}, "required": []},
        )

    # BaseTool abstract method ------------------------------------------------

    def execute(self, **kwargs: Any) -> str:
        """Forward the call to the MCP server and return a string result."""
        raw_result = self._client.call_tool(self.name, kwargs)
        if raw_result is None:
            return "(no output)"
        if isinstance(raw_result, str):
            return raw_result
        # MCP often returns {"content": [{"type": "text", "text": "..."}]}
        if isinstance(raw_result, dict):
            content = raw_result.get("content")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    else:
                        parts.append(json.dumps(item))
                return "\n".join(parts)
            return json.dumps(raw_result)
        return json.dumps(raw_result)


# ── Convenience loader ────────────────────────────────────────────────────────

def load_mcp_tools(
    server_command_or_url: list[str] | str,
    registry: ToolRegistry,
) -> list[str]:
    """Connect to an MCP server, enumerate its tools, and register them all.

    Parameters
    ----------
    server_command_or_url:
        Either a list of strings (stdio server command) or a URL string (HTTP server).
    registry:
        The :class:`~kiro.tools.base.ToolRegistry` to register tools into.

    Returns
    -------
    list[str]
        The names of the tools that were registered.

    Raises
    ------
    RuntimeError
        If the connection or tool listing fails.
    """
    if isinstance(server_command_or_url, str):
        client = MCPClient(server_url=server_command_or_url)
    else:
        client = MCPClient(server_command=server_command_or_url)

    client.connect()

    tool_defs = client.list_tools()
    registered: list[str] = []

    for tool_def in tool_defs:
        adapter = MCPToolAdapter(client=client, tool_def=tool_def)
        registry.register(adapter)
        registered.append(adapter.name)

    return registered
