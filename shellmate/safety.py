"""安全评估：按命令内容给出风险级别、动作与原因。

风险级别：
    safe / low   -> allow          直接执行
    medium       -> confirm        回车或 y 确认
    high         -> double-confirm 必须输入 yes
    critical     -> deny           拒绝执行（--yes 也不能越过）

评估不依赖模型，纯本地规则；LLM 生成的命令也必须过这一层。
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

LEVELS = ["safe", "low", "medium", "high", "critical"]
ACTIONS = {
    "safe": "allow",
    "low": "allow",
    "medium": "confirm",
    "high": "double-confirm",
    "critical": "deny",
}

READONLY = {
    "ls", "cat", "df", "du", "ps", "ss", "id", "uname", "journalctl",
    "head", "tail", "grep", "wc", "stat", "file", "which", "pwd", "date",
    "echo", "printf", "true", "false", "sleep", "hostname", "whoami",
    "free", "uptime", "lscpu", "lsblk", "find", "sort", "uniq", "cut", "wc",
}

PACKAGE_REMOVE = {"remove", "purge", "autoremove", "erase", "uninstall"}


@dataclass
class RiskAssessment:
    level: str = "safe"
    action: str = "allow"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "action": self.action,
            "reasons": list(self.reasons),
        }


def _segments(command: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*(?:\|\||&&|\||;|\n)\s*", command) if part.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _has_recursive(args: list[str]) -> bool:
    for arg in args:
        if arg in ("-r", "-R", "--recursive"):
            return True
        if arg.startswith("-") and not arg.startswith("--") and "r" in arg.lower():
            return True
    return False


def _assess_rm(args: list[str]) -> list[tuple[str, str]]:
    recursive = _has_recursive(args)
    targets = [arg for arg in args if not arg.startswith("-")]
    if recursive and any(t in ("/", "/*") or t.startswith("--no-preserve-root") for t in targets):
        return [("critical", "递归删除根目录")]
    if recursive:
        return [("high", "递归删除目录")]
    return [("medium", "删除文件")]


def _assess_segment(segment: str) -> list[tuple[str, str]]:
    tokens = _tokens(segment)
    if not tokens:
        return []
    found: list[tuple[str, str]] = []

    if tokens[0] in ("sudo", "doas"):
        found.append(("medium", "使用 sudo/doas 提权"))
        tokens = tokens[1:]
        if not tokens:
            return found

    if tokens[0] == "env":
        tokens = [t for t in tokens[1:] if "=" not in t]
        if not tokens:
            return found

    program = tokens[0]
    args = tokens[1:]
    base = program.rsplit("/", 1)[-1]

    if base == "rm":
        found.extend(_assess_rm(args))
    elif base.startswith("mkfs"):
        level = "critical" if any(a.startswith("/dev/") for a in args) else "high"
        found.append((level, "格式化文件系统"))
    elif base == "dd":
        if any(a.startswith("of=/dev/") for a in args):
            found.append(("critical", "向块设备写入数据"))
        else:
            found.append(("medium", "dd 直接写数据"))
    elif base in ("shutdown", "reboot", "poweroff", "halt"):
        found.append(("critical", "关机或重启系统"))
    elif base == "init" and args and args[0] in ("0", "6"):
        found.append(("critical", "切换运行级别到 0/6"))
    elif base == "chmod":
        recursive = _has_recursive(args)
        special = any(a == "777" for a in args)
        root_target = any(a in ("/", "/*") for a in args)
        if recursive and special and root_target:
            found.append(("critical", "递归把根目录权限改为 777"))
        elif recursive and special:
            found.append(("high", "递归把目录权限改为 777"))
        elif recursive:
            found.append(("medium", "递归修改权限"))
        elif special:
            found.append(("medium", "把权限改为 777"))
        else:
            found.append(("low", "修改权限"))
    elif base == "chown":
        found.append(("high" if _has_recursive(args) else "medium", "修改文件所有者"))
    elif base == "kill":
        found.append(("high" if "-9" in args else "medium", "向进程发送信号"))
    elif base in ("pkill", "killall"):
        found.append(("high", f"{base} 批量结束进程"))
    elif base in ("apt", "apt-get", "dnf", "yum", "zypper"):
        if any(a in PACKAGE_REMOVE for a in args):
            found.append(("high", "卸载软件包"))
        else:
            found.append(("medium", "安装或更新软件包"))
    elif base == "dpkg":
        found.append(("high" if any(a in ("-r", "-P", "--remove", "--purge") for a in args) else "medium", "dpkg 变更软件包"))
    elif base == "systemctl":
        action = next((a for a in args if not a.startswith("-")), "")
        if action in ("stop", "disable", "mask"):
            found.append(("high", f"systemctl {action} 服务"))
        elif action in ("restart", "start", "enable"):
            found.append(("medium", f"systemctl {action} 服务"))
        else:
            found.append(("safe", "查看服务状态"))
    elif base == "find":
        if "-delete" in args:
            found.append(("medium", "find -delete 删除匹配文件"))
        elif "-exec" in args and any("rm" in arg for arg in args):
            found.append(("high", "find -exec 调用删除命令"))
        else:
            found.append(("safe", "只读查找"))
    elif base == "sed":
        found.append(("medium" if "-i" in args or any(a.startswith("-i") for a in args) else "safe", "原地修改文件"))
    elif base in ("mv", "cp"):
        found.append(("medium", "移动或复制文件，可能覆盖目标"))
    elif base in ("mkdir", "touch", "ln"):
        found.append(("low", "创建文件或目录"))
    elif base == "make":
        found.append(("medium" if "clean" in args else "low", "执行构建或清理"))
    elif base in ("curl", "wget"):
        found.append(("low", "从网络下载"))
    elif base in ("bash", "sh", "zsh") and "-c" in args:
        found.append(("high", "通过 shell -c 执行字符串"))
    elif base == "eval":
        found.append(("high", "eval 执行动态字符串"))
    elif base == "iptables":
        found.append(("high" if any(a in ("-F", "--flush") for a in args) else "medium", "修改防火墙规则"))
    elif base == "xargs":
        if args and args[0] == "rm":
            found.append(("high", "通过 xargs 批量删除文件"))
        elif args and args[0] in ("sh", "bash", "zsh"):
            found.append(("high", "通过 xargs 调用 shell"))
        else:
            found.append(("medium", "xargs 批量处理输入"))
    elif base in READONLY:
        found.append(("safe", "只读命令"))
    else:
        found.append(("medium", "未知命令，按需确认"))

    return found


def assess(command: str, requires_root: bool = False) -> RiskAssessment:
    text = " ".join(command.strip().split())
    if not text:
        return RiskAssessment("safe", "allow", ["空命令"])

    pairs: list[tuple[str, str]] = []
    level = "safe"

    def add(new_level: str, reason: str) -> None:
        nonlocal level
        if LEVELS.index(new_level) > LEVELS.index(level):
            level = new_level
        if (new_level, reason) not in pairs:
            pairs.append((new_level, reason))

    # 组合模式
    if re.search(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:\s*&[^}]*\}", text):
        add("critical", "fork bomb")
    if re.search(r"(?:>|of=)\s*/dev/(?:sd|nvme|hd|vd|mmcblk)", text, re.I):
        add("critical", "写入块设备")
    if re.search(r"\|\s*(?:sudo\s+)?(?:ba|z|k)?sh\b", text):
        add("high", "管道到 shell 执行")
    if "$(" in text or "`" in text:
        add("medium", "包含命令替换")
    if re.search(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(?:\s|\*|$)", text):
        add("critical", "递归删除根目录")
    if re.search(r"\bchmod\s+-[a-z]*R[a-z]*\s+777\s+/(?:\s|$)", text):
        add("critical", "递归把根目录权限改为 777")

    for segment in _segments(text):
        for new_level, reason in _assess_segment(segment):
            add(new_level, reason)

    if requires_root and LEVELS.index(level) < LEVELS.index("medium"):
        add("medium", "需要 root 权限")

    reasons = [reason for reason_level, reason in pairs if reason_level == level]
    if not reasons:
        reasons = [reason for _, reason in pairs] or ["未发现风险特征"]

    return RiskAssessment(level, ACTIONS[level], reasons)
