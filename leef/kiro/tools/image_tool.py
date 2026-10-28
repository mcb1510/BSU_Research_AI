from __future__ import annotations
"""Image tool: read and encode image files for vision-capable models."""

import base64
from pathlib import Path

from .base import BaseTool

# Supported image formats and their MIME types
SUPPORTED_FORMATS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class ReadImageTool(BaseTool):
    name = "read_image"
    description = (
        "Read and analyze an image file. Encodes it as base64 and returns a description. "
        "Works with vision-capable models (GPT-4o, Claude 3, etc.). "
        "Supported formats: PNG, JPG, JPEG, GIF, WEBP."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the image file.",
            },
            "question": {
                "type": "string",
                "description": (
                    "Specific question to ask about the image. "
                    "Defaults to 'Describe this image in detail'."
                ),
            },
        },
        "required": ["path"],
    }

    def execute(
        self,
        path: str,
        question: str = "Describe this image in detail",
    ) -> str:
        p = Path(path).expanduser()

        # File existence check
        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Not a file: {path}"

        # Format check
        ext = p.suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            supported = ", ".join(SUPPORTED_FORMATS.keys())
            return (
                f"Error: Unsupported image format '{ext}'. "
                f"Supported formats: {supported}"
            )

        # Size check
        file_size = p.stat().st_size
        if file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            return (
                f"Error: File too large ({size_mb:.1f} MB). "
                f"Maximum allowed size is 10 MB."
            )

        # Read and encode
        try:
            image_bytes = p.read_bytes()
        except OSError as e:
            return f"Error reading {path}: {e}"

        mime_type = SUPPORTED_FORMATS[ext]
        b64_data = base64.b64encode(image_bytes).decode("ascii")

        # Return the special marker string that the agent runtime / providers detect.
        # Format: IMAGE_DATA:{mime_type}:{base64_data}:{question}
        # The question is appended last so colons inside it don't break parsing
        # (providers should split on ':' with maxsplit=3).
        return f"IMAGE_DATA:{mime_type}:{b64_data}:{question}"
