"""Configuration system — loads kiro.config.json and environment variables."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": None,          # Falls back to env var
    "api_base": None,         # For OpenAI-compatible APIs
    "temperature": 0.7,
    "max_tokens": 4096,
    "max_iterations": 25,
    "system_prompt": None,    # Falls back to Agent.DEFAULT_SYSTEM
    "theme": "dark",          # dark | light
    "show_tool_calls": True,
    "stream": True,
}

# Maps provider names to their API key env variable names
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    # Local providers don't need keys
    "ollama": None,
    "local": None,
    "lmstudio": None,
    "vllm": None,
}


class Config:
    """Holds the resolved runtime configuration."""

    def __init__(self, data: dict):
        self._data = {**DEFAULT_CONFIG, **data}
        # Resolve API key from env if not set
        if not self._data.get("api_key"):
            self._data["api_key"] = self._resolve_api_key()

    def _resolve_api_key(self) -> str | None:
        provider = self._data.get("provider", "openai").lower()
        env_var = PROVIDER_ENV_KEYS.get(provider)
        if env_var:
            return os.environ.get(env_var)
        return None

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __repr__(self):
        safe = {k: v for k, v in self._data.items() if k != "api_key"}
        if self._data.get("api_key"):
            safe["api_key"] = "***"
        return f"Config({safe})"


def load_config(config_path: str | Path | None = None) -> Config:
    """
    Load configuration from:
    1. kiro.config.json in the current directory (or specified path)
    2. ~/.kiro/config.json (user-level config)
    3. Defaults
    Environment variables override the config file for API keys.
    """
    data: dict = {}

    # User-level config
    user_config = Path.home() / ".kiro" / "config.json"
    if user_config.exists():
        try:
            data.update(json.loads(user_config.read_text()))
        except Exception:
            pass

    # Project-level config (overrides user config)
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    else:
        search_paths.extend([
            Path.cwd() / "kiro.config.json",
            Path.cwd() / ".kiro.json",
        ])

    for path in search_paths:
        if path.exists():
            try:
                data.update(json.loads(path.read_text()))
                break
            except Exception as e:
                print(f"Warning: Could not load config from {path}: {e}")

    # Environment variable overrides
    env_overrides = {
        "KIRO_PROVIDER": "provider",
        "KIRO_MODEL": "model",
        "KIRO_API_BASE": "api_base",
        "KIRO_TEMPERATURE": "temperature",
        "KIRO_MAX_TOKENS": "max_tokens",
    }
    for env_var, config_key in env_overrides.items():
        val = os.environ.get(env_var)
        if val:
            if config_key in ("temperature",):
                try:
                    val = float(val)
                except ValueError:
                    pass
            elif config_key in ("max_tokens", "max_iterations"):
                try:
                    val = int(val)
                except ValueError:
                    pass
            data[config_key] = val

    return Config(data)


def write_default_config(path: Path | None = None):
    """Write a default kiro.config.json to the current directory."""
    target = path or Path.cwd() / "kiro.config.json"
    config = {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 4096,
        "show_tool_calls": True,
        "stream": True,
        "_comment": (
            "provider can be: openai, anthropic, ollama, groq, together, "
            "lmstudio, vllm, openrouter, deepseek, mistral. "
            "api_key defaults to the provider's env variable (OPENAI_API_KEY, etc.)"
        ),
    }
    target.write_text(json.dumps(config, indent=2))
    return target
