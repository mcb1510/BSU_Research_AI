from __future__ import annotations
"""AWS CLI tool — wraps the `aws` CLI binary to manage AWS resources."""

import json
import shlex
import subprocess
from typing import Any

from .base import BaseTool


# Operations that are considered destructive and require explicit confirmation.
# Keys are (service, operation) tuples; a service of "*" matches any service.
_DESTRUCTIVE_OPS: set[tuple[str, str]] = {
    ("s3", "delete-bucket"),
    ("s3", "rb"),                        # alias for delete-bucket
    ("s3api", "delete-bucket"),
    ("s3api", "delete-objects"),
    ("ec2", "terminate-instances"),
    ("ec2", "delete-vpc"),
    ("ec2", "delete-subnet"),
    ("ec2", "delete-security-group"),
    ("ec2", "delete-key-pair"),
    ("lambda", "delete-function"),
    ("lambda", "delete-layer-version"),
    ("dynamodb", "delete-table"),
    ("dynamodb", "batch-write-item"),     # can perform mass deletes
    ("iam", "delete-user"),
    ("iam", "delete-role"),
    ("iam", "delete-policy"),
    ("iam", "delete-group"),
    ("iam", "detach-role-policy"),
    ("cloudformation", "delete-stack"),
    ("rds", "delete-db-instance"),
    ("rds", "delete-db-cluster"),
    ("ecs", "delete-cluster"),
    ("ecs", "delete-service"),
    ("eks", "delete-cluster"),
    ("sns", "delete-topic"),
    ("sqs", "delete-queue"),
}


def _is_destructive(service: str, operation: str) -> bool:
    """Return True if (service, operation) is on the destructive blocklist."""
    return (service.lower(), operation.lower()) in _DESTRUCTIVE_OPS


def _build_cmd(
    service: str,
    operation: str,
    params: dict[str, Any] | None,
    region: str,
    profile: str | None,
) -> list[str]:
    """Assemble the aws CLI argument list (no shell=True needed)."""
    cmd: list[str] = ["aws", service, operation, "--region", region]

    if profile:
        cmd += ["--profile", profile]

    if params:
        for key, value in params.items():
            # Skip the internal 'confirm' sentinel — never pass it to the CLI.
            if key == "confirm":
                continue

            flag = f"--{key}" if not key.startswith("-") else key

            if isinstance(value, bool):
                # Boolean flags: --flag (present) or omitted (absent)
                if value:
                    cmd.append(flag)
            elif isinstance(value, (dict, list)):
                # Complex values are serialised to JSON for the CLI.
                cmd += [flag, json.dumps(value)]
            else:
                cmd += [flag, str(value)]

    return cmd


def _try_pretty_json(text: str) -> str:
    """If *text* looks like JSON, return a pretty-printed version; else raw."""
    stripped = text.strip()
    if not stripped:
        return text
    if stripped[0] in ("{", "["):
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            pass
    return text


class AWSCliTool(BaseTool):
    """Execute AWS CLI commands against real AWS services."""

    name = "use_aws"
    description = (
        "Execute AWS CLI commands. Use for managing AWS resources: "
        "S3, EC2, Lambda, DynamoDB, IAM, CloudFormation, RDS, ECS, EKS, "
        "SNS, SQS, and more. Destructive operations (delete-bucket, "
        "terminate-instances, delete-function, …) require passing "
        "confirm='yes' in the params object."
    )
    parameters = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": (
                    "AWS service name, e.g. 's3', 'ec2', 'lambda', "
                    "'dynamodb', 'iam', 'cloudformation'."
                ),
            },
            "operation": {
                "type": "string",
                "description": (
                    "CLI operation name, e.g. 'list-buckets', "
                    "'describe-instances', 'get-function'."
                ),
            },
            "params": {
                "type": "object",
                "description": (
                    "Optional key-value pairs passed as CLI flags. "
                    "Use 'confirm': 'yes' to authorise destructive operations. "
                    "Example: {'bucket': 'my-bucket', 'key': 'file.txt'}."
                ),
                "additionalProperties": True,
            },
            "region": {
                "type": "string",
                "description": "AWS region. Defaults to 'us-east-1'.",
            },
            "profile": {
                "type": "string",
                "description": "AWS named profile from ~/.aws/credentials.",
            },
        },
        "required": ["service", "operation"],
    }

    def execute(
        self,
        service: str,
        operation: str,
        params: dict[str, Any] | None = None,
        region: str = "us-east-1",
        profile: str | None = None,
    ) -> str:
        service = service.strip()
        operation = operation.strip()
        params = params or {}

        # ── Safety gate ──────────────────────────────────────────────────────
        if _is_destructive(service, operation):
            confirmed = str(params.get("confirm", "")).strip().lower()
            if confirmed != "yes":
                return (
                    f"Error: '{service} {operation}' is a destructive operation "
                    "and has been blocked for safety.\n"
                    "To proceed, include {'confirm': 'yes'} in the params object."
                )

        # ── Build command ─────────────────────────────────────────────────────
        cmd = _build_cmd(service, operation, params, region, profile)

        # ── Execute ───────────────────────────────────────────────────────────
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            return (
                "Error: 'aws' CLI not found. "
                "Install it with: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
            )
        except subprocess.TimeoutExpired:
            return "Error: AWS CLI command timed out after 60s."
        except Exception as exc:
            return f"Error: Unexpected error running AWS CLI: {type(exc).__name__}: {exc}"

        # ── Return result ─────────────────────────────────────────────────────
        if result.returncode == 0:
            output = result.stdout or "(command succeeded with no output)"
            return _try_pretty_json(output)

        # Non-zero exit — return stderr (or stdout if stderr is empty).
        error_text = result.stderr.strip() or result.stdout.strip() or "(no output)"
        return f"Error (exit {result.returncode}):\n{error_text}"
