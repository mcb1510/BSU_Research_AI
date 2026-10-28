from __future__ import annotations
"""Tool registry and base class.

Each tool is a Python class that:
  1. Declares a JSON Schema description (for the LLM)
  2. Implements an execute() method (for the runtime)
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name as it appears in LLM function calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for the tool's input parameters."""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Run the tool and return a string result."""
        ...

    def schema(self) -> dict:
        """Return the OpenAI-style function schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def __repr__(self):
        return f"Tool({self.name!r})"


class ToolRegistry:
    """Holds all registered tools and dispatches calls."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        """Return all tool schemas for passing to an LLM."""
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call by name."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'. Available tools: {sorted(self._tools.keys())}"
        try:
            result = tool.execute(**arguments)
            return str(result) if result is not None else "(no output)"
        except TypeError as e:
            return f"Error: Invalid arguments for tool '{name}': {e}"
        except Exception as e:
            return f"Error executing tool '{name}': {type(e).__name__}: {e}"

    def __len__(self):
        return len(self._tools)

    def __repr__(self):
        return f"ToolRegistry({sorted(self._tools.keys())})"


def build_default_registry(provider=None) -> ToolRegistry:
    """Create a ToolRegistry with all built-in tools registered.

    Pass provider to enable the spawn_agent/spawn_pipeline tools.
    """
    from .file_tools import ReadFileTool, WriteFileTool, GlobTool, DirectoryTool
    from .shell_tools import ShellTool
    from .search_tools import GrepTool, WebSearchTool
    from .todo_tool import TodoListTool
    from .email_tool import SendEmailTool
    from .agent_tool import SpawnAgentTool, SpawnPipelineTool
    from .web_fetch_tool import WebFetchTool
    from .knowledge_tool import KnowledgeTool
    from .aws_tool import AWSCliTool
    from .image_tool import ReadImageTool
    from .code_tools import DocumentSymbolsTool, SearchSymbolsTool, PatternSearchTool

    registry = ToolRegistry()
    for tool in [
        ReadFileTool(),
        WriteFileTool(),
        GlobTool(),
        DirectoryTool(),
        ShellTool(),
        GrepTool(),
        WebSearchTool(),
        WebFetchTool(),
        TodoListTool(),
        SendEmailTool(),
        KnowledgeTool(),
        AWSCliTool(),
        ReadImageTool(),
        DocumentSymbolsTool(),
        SearchSymbolsTool(),
        PatternSearchTool(),
        SpawnAgentTool(parent_provider=provider, parent_registry=None),
        SpawnPipelineTool(parent_provider=provider, parent_registry=None),
    ]:
        registry.register(tool)
    return registry
