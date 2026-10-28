from __future__ import annotations
"""Shell execution tool."""

import os
import subprocess
import shlex
from .base import BaseTool


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Execute a shell command and return its stdout, stderr, and exit code. "
        "Use for running scripts, build tools, git commands, package managers, etc. "
        "Commands run in the current working directory unless cwd is specified."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command. Defaults to current directory.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 60. Max 300.",
            },
            "env": {
                "type": "object",
                "description": "Additional environment variables to set (merged with current env).",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["command"],
    }

    # Commands that are never allowed
    BLOCKED = {
        "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero",
        "> /dev/sda", ":(){ :|:& };:", "chmod -R 777 /",
    }

    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
    ) -> str:
        # Basic safety check
        for blocked in self.BLOCKED:
            if blocked in command:
                return f"Error: Blocked command detected: {blocked!r}"

        timeout = min(timeout, 300)
        work_dir = cwd or os.getcwd()

        run_env = os.environ.copy()
        if env:
            run_env.update({str(k): str(v) for k, v in env.items()})

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=timeout,
                env=run_env,
            )
            output_parts = []
            if result.stdout:
                output_parts.append(f"stdout:\n{result.stdout.rstrip()}")
            if result.stderr:
                output_parts.append(f"stderr:\n{result.stderr.rstrip()}")
            output_parts.append(f"exit_code: {result.returncode}")
            return "\n\n".join(output_parts) if output_parts else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
