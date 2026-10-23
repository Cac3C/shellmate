"""离线意图解析：关键词打分 + 槽位抽取 + 模板渲染。

选择离线优先的原因：
- 不依赖网络与 API Key，离线也能使用；
- 规则可解释，错误可定位，适合作为 LLM 不可用时的兜底；
- 与 LLM 输出共用 CommandPlan，便于对比两种后端的结果。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from shellmate.nlu.schema import CommandPlan

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
INTENTS_FILE = DATA_DIR / "intents.json"

PATH_RE = re.compile(r"(~/[^\s，。；、,;]+|/[^\s，。；、,;]+)")
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGTkmgt])(?:[Bb])?")
DAYS_RE = re.compile(r"(\d+)\s*(?:天|日)")
PATTERN_RE = re.compile(r"([A-Za-z0-9_*?.-]*\.(?:conf|cfg|log|json|txt|py|sh|md|c|h))")
NAME_RE = re.compile(r"名为\s*([A-Za-z0-9_*?.-]+)")
USER_RE = re.compile(r"用户\s*([A-Za-z0-9_.-]+)")
SERVICE_BEFORE_RE = re.compile(r"([A-Za-z0-9_@.-]+)\s*服务")
SERVICE_AFTER_RE = re.compile(r"服务\s*([A-Za-z0-9_@.-]+)")
PID_RE = re.compile(r"(?:进程|pid|kill)\s*(\d+)", re.I)
PERM_RE = re.compile(r"(?<![\d.])([0-7]{3,4})(?![\d.])")

DEFAULTS = {"path": ".", "days": "7", "pattern": "*"}

_ASCII_COMMAND_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*)(?:\s|$)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_FORK_BOMB_RE = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:\s*&[^}]*\}")

KNOWN_PROGRAMS = set(json.loads((DATA_DIR / "commands.json").read_text(encoding="utf-8"))["commands"]) | {
    "echo", "printf", "sudo", "doas", "env", "cd", "pwd", "dd", "mkfs",
    "shutdown", "reboot", "poweroff", "halt", "init", "apt", "apt-get",
    "dpkg", "dnf", "yum", "curl", "wget", "bash", "sh", "zsh", "pkill",
    "killall", "sed", "iptables", "touch", "ln", "true", "false", "sleep",
    "hostname", "whoami", "free", "uptime", "lscpu", "lsblk", "python3",
    "gcc", "g++", "vim", "nano", "less", "more", "watch", "nohup", "export",
    "source", "tar", "awk", "grep",
}


def _looks_like_shell_command(text: str) -> bool:
    """用户直接输入 shell 命令时优先按原样处理，保留 -R 等原始参数。"""
    if _CJK_RE.search(text):
        return False
    if _FORK_BOMB_RE.search(text):
        return True
    match = _ASCII_COMMAND_RE.match(text)
    if not match:
        return False
    program = match.group(1)
    return program in KNOWN_PROGRAMS or any(
        program.startswith(name + ".") for name in ("mkfs",)
    )

NO_MATCH_HINT = (
    "未识别该指令；目前支持磁盘、目录、文件查找、权限、进程、服务、"
    "用户、日志、端口、内核版本、清理编译产物。"
)


def load_intents(path: str | Path | None = None) -> list[dict]:
    data = json.loads(Path(path or INTENTS_FILE).read_text(encoding="utf-8"))
    return data["intents"]


def normalize(text: str) -> str:
    """全角转半角、压缩空白，保留大小写（路径大小写敏感）。"""
    return unicodedata.normalize("NFKC", text).strip()


def _match_score(intent: dict, text_lower: str) -> tuple[int, int]:
    score = 0
    hits = 0
    for keyword in intent.get("keywords", []):
        count = text_lower.count(keyword)
        if count:
            hits += 1
            score += len(keyword) * count
    return score, hits


def extract_slots(text: str, intent: dict) -> dict[str, str]:
    needed = set(intent.get("slots", []))
    slots: dict[str, str] = {}

    if "path" in needed:
        match = PATH_RE.search(text)
        if match:
            slots["path"] = match.group(1).rstrip("，。；、,;")

    if "size" in needed:
        match = SIZE_RE.search(text)
        if match:
            slots["size"] = f"{match.group(1)}{match.group(2).upper()}"

    if "days" in needed:
        match = DAYS_RE.search(text)
        if match:
            slots["days"] = match.group(1)

    if "pattern" in needed:
        match = PATTERN_RE.search(text)
        if match:
            pattern = match.group(1)
            if pattern.startswith("."):
                pattern = "*" + pattern
            slots["pattern"] = pattern
        else:
            match = NAME_RE.search(text)
            if match:
                slots["pattern"] = match.group(1)

    if "user" in needed:
        match = USER_RE.search(text)
        if match:
            slots["user"] = match.group(1)

    if "service" in needed:
        match = SERVICE_BEFORE_RE.search(text) or SERVICE_AFTER_RE.search(text)
        if match:
            slots["service"] = match.group(1)

    if "pid" in needed:
        match = PID_RE.search(text)
        if match:
            slots["pid"] = match.group(1)

    if "perm" in needed:
        match = PERM_RE.search(text)
        if match:
            slots["perm"] = match.group(1)

    for key in needed:
        if key not in slots and key in DEFAULTS:
            slots[key] = DEFAULTS[key]

    return slots


def render_from_intent(intent_name: str, slots: dict[str, str]) -> str | None:
    """用意图模板重新渲染命令；供记忆补丁使用。"""
    for intent in load_intents():
        if intent["name"] == intent_name:
            try:
                return intent["template"].format(**slots)
            except KeyError:
                return None
    return None


def parse(text: str, intents: list[dict] | None = None) -> CommandPlan:
    intents = intents if intents is not None else load_intents()
    normalized = normalize(text)
    lower = normalized.lower()

    if _looks_like_shell_command(normalized):
        return CommandPlan(
            raw_input=text,
            command=normalized,
            intent="raw_command",
            confidence=0.5,
            message="未匹配意图，按原始命令处理",
        )

    best_key: tuple[int, int, int] | None = None
    best_intent: dict | None = None
    for index, intent in enumerate(intents):
        score, hits = _match_score(intent, lower)
        key = (score, hits, -index)
        if best_key is None or key > best_key:
            best_key = key
            best_intent = intent

    if best_key is None or best_key[0] == 0 or best_intent is None:
        # 用户直接输入 shell 命令时按原样执行，方便 run/plan 和安全评估复用。
        if _ASCII_COMMAND_RE.match(normalized) and not _CJK_RE.search(normalized):
            return CommandPlan(
                raw_input=text,
                command=normalized,
                intent="raw_command",
                confidence=0.5,
                message="未匹配意图，按原始命令处理",
            )
        return CommandPlan(
            raw_input=text,
            command="",
            intent="",
            confidence=0.0,
            message=NO_MATCH_HINT,
        )

    score = best_key[0]
    slots = extract_slots(normalized, best_intent)
    missing = [name for name in best_intent.get("required", []) if not slots.get(name)]
    risk = {"level": best_intent.get("risk", "unknown"), "reasons": []}
    base = CommandPlan(
        raw_input=text,
        command="",
        intent=best_intent["name"],
        slots=slots,
        requires_root=best_intent.get("requires_root", False),
        risk=risk,
    )

    if missing:
        base.confidence = 0.2
        base.message = f"缺少必要参数：{', '.join(missing)}"
        return base

    base.confidence = round(min(0.95, 0.55 + score / 20), 2)
    base.command = best_intent["template"].format(**slots)
    return base
