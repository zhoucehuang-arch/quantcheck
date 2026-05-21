from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def get_root() -> Path:
    return Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))


ROOT = get_root()


def load_env(root: Path | None = None, *, override: bool = False) -> Dict[str, str]:
    """Load simple KEY=VALUE pairs from .env into os.environ.

    The project intentionally keeps .env parsing small: comments and blank lines
    are ignored, values are not shell-expanded, and existing environment values
    win by default.
    """
    env: dict[str, str] = {}
    env_path = (root or get_root()) / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        env[key] = value
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    return env


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default
