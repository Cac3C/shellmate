"""采集 ShellMate 运行环境。

结果是一个可直接 JSON 序列化的 dict，供 CLI、LLM 提示词和解释模块复用。
只做只读操作，不访问网络。
"""

from __future__ import annotations

import getpass
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path

MAX_CHILDREN = 20

PROJECT_MARKERS = {
    ".git": "git",
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "node",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "README.md": "docs",
}


def _os_release() -> dict[str, str]:
    try:
        return dict(platform.freedesktop_os_release())
    except (OSError, AttributeError):
        info: dict[str, str] = {}
        path = Path("/etc/os-release")
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key] = value.strip().strip('"')
        return info


def _disk(path: Path) -> dict:
    usage = shutil.disk_usage(path)
    gib = 1024 ** 3
    return {
        "path": str(path),
        "total_gb": round(usage.total / gib, 1),
        "used_gb": round(usage.used / gib, 1),
        "free_gb": round(usage.free / gib, 1),
        "used_percent": round(usage.used / usage.total * 100, 1),
    }


def _entries(path: Path) -> list[dict]:
    """列出工作目录顶层条目，并带上目录的子项数量。"""
    if not path.exists():
        return []
    result: list[dict] = []
    try:
        children = sorted(
            (p for p in path.iterdir() if not p.name.startswith(".")),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except OSError:
        return result

    for child in children:
        item = {"name": child.name, "type": "dir" if child.is_dir() else "file"}
        if child.is_dir():
            try:
                sub = sorted(p.name for p in child.iterdir() if not p.name.startswith("."))
            except OSError:
                sub = []
            item["child_count"] = len(sub)
            item["children"] = sub[:MAX_CHILDREN]
        result.append(item)
    return result


def _project(path: Path) -> dict:
    markers = [
        label for name, label in PROJECT_MARKERS.items()
        if (path / name).exists()
    ]
    return {
        "name": path.name,
        "markers": sorted(set(markers)),
    }


def collect_context(cwd: str | Path | None = None) -> dict:
    workdir = Path(cwd or Path.cwd()).expanduser().resolve()
    osrel = _os_release()
    return {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "user": getpass.getuser(),
        "home": str(Path.home()),
        "cwd": str(workdir),
        "distro": {
            "name": osrel.get("NAME", "unknown"),
            "version": osrel.get("VERSION_ID", ""),
            "pretty": osrel.get("PRETTY_NAME", osrel.get("NAME", "unknown")),
        },
        "kernel": platform.release(),
        "python": platform.python_version(),
        "shell": os.environ.get("SHELL", ""),
        "disk": _disk(workdir),
        "entries": _entries(workdir),
        "project": _project(workdir),
    }


def render_text(ctx: dict) -> str:
    distro = ctx["distro"]
    disk = ctx["disk"]
    project = ctx.get("project", {})
    markers = ", ".join(project.get("markers", [])) or "未识别"
    lines = [
        "ShellMate 环境上下文",
        f"  采集时间 : {ctx['collected_at']}",
        f"  主机/用户 : {ctx['hostname']} / {ctx['user']}",
        f"  发行版   : {distro['pretty']}",
        f"  内核     : {ctx['kernel']}",
        f"  Python   : {ctx['python']}",
        f"  当前目录 : {ctx['cwd']}",
        f"  项目     : {project.get('name', '')}（{markers}）",
        f"  磁盘     : {disk['total_gb']:.1f} GB 总 / "
        f"{disk['free_gb']:.1f} GB 可用 / {disk['used_percent']:.0f}% 已用",
        "",
        "目录内容:",
    ]
    for entry in ctx["entries"]:
        if entry["type"] == "dir":
            lines.append(f"  {entry['name']}/ ({entry['child_count']} 项)")
        else:
            lines.append(f"  {entry['name']}")
    if not ctx["entries"]:
        lines.append("  （空目录）")
    return "\n".join(lines)
