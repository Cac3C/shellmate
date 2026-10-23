"""XDG 路径约定：配置放 ~/.config，运行时数据放 ~/.local/state。"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "shellmate"


def _xdg(env_name: str, default: Path) -> Path:
    base = os.environ.get(env_name)
    return Path(base) if base else default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def history_db() -> Path:
    return state_dir() / "history.db"


def audit_log() -> Path:
    return state_dir() / "audit.jsonl"


def ensure_state_dir() -> Path:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
