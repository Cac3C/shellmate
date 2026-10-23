"""配置加载：环境变量覆盖配置文件，默认值兜底。

优先级（后续里程碑会再加 CLI 参数）：
    环境变量 > ~/.config/shellmate/config.json > 内置默认值
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from shellmate.paths import config_file

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class Config:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    timeout: float = 8.0
    offline: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    cfg_path = Path(path) if path is not None else config_file()

    if cfg_path.exists():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"配置文件格式错误：{cfg_path}")
        for key in ("base_url", "model", "api_key", "timeout", "offline"):
            if key in data:
                setattr(cfg, key, data[key])

    cfg.base_url = _env("SHELLMATE_BASE_URL", cfg.base_url)
    cfg.model = _env("SHELLMATE_MODEL", cfg.model)
    cfg.api_key = _env("SHELLMATE_API_KEY", cfg.api_key)

    timeout = os.environ.get("SHELLMATE_TIMEOUT")
    if timeout:
        cfg.timeout = float(timeout)

    offline = os.environ.get("SHELLMATE_OFFLINE")
    if offline is not None:
        cfg.offline = offline.strip().lower() not in ("", "0", "false", "no")

    return cfg
