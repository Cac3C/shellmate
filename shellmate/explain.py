"""命令解释器：把 shell 命令拆成段，解释程序、选项、参数与整体风险。"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from shellmate.safety import assess

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
COMMANDS_FILE = DATA_DIR / "commands.json"
COMMANDS: dict[str, dict] = json.loads(
    COMMANDS_FILE.read_text(encoding="utf-8")
)["commands"]

OPERATORS = {
    "|": "管道：把左侧输出作为右侧输入",
    "||": "逻辑或：左侧失败时才执行右侧",
    "&&": "逻辑与：左侧成功时才执行右侧",
    ";": "顺序执行：无论前一条是否成功都执行下一条",
    ">": "覆盖重定向：把输出写入文件，覆盖原内容",
    ">>": "追加重定向：把输出追加到文件末尾",
    "<": "输入重定向：从文件读取标准输入",
    "2>": "错误重定向：把标准错误写入文件",
    "2>&1": "把标准错误合并到标准输出",
    "&>": "把标准输出和标准错误一起重定向",
    "|&": "管道，同时合并标准错误",
    "&": "放到后台执行",
}

REDIRECT_OPS = {">", ">>", "<", "2>", "&>"}
VALUE_OPTIONS = {
    "find": {"-type", "-name", "-size", "-mtime", "-exec"},
    "xargs": {"-n", "-I"},
    "tail": {"-n"},
    "head": {"-n"},
    "cut": {"-d", "-f"},
    "mkdir": {"-m"},
    "chmod": {"-m"},
    "tar": {"-f"},
}


def split_tokens(command: str) -> list[tuple[str, str]]:
    """按引号和 shell 操作符切分，保留操作符本身。"""
    tokens: list[tuple[str, str]] = []
    buffer: list[str] = []
    quote: str | None = None
    i = 0

    def flush() -> None:
        text = "".join(buffer).strip()
        if text:
            tokens.append(("word", text))
        buffer.clear()

    while i < len(command):
        char = command[i]

        if quote:
            buffer.append(char)
            if char == quote and command[i - 1] != "\\":
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
            buffer.append(char)
            i += 1
            continue

        previous_is_space = i == 0 or command[i - 1].isspace()

        if command.startswith("2>&1", i) and previous_is_space:
            flush()
            tokens.append(("op", "2>&1"))
            i += 4
            continue

        two = command[i:i + 2]
        if two in ("&&", "||", ">>", "&>", "|&") or (
            two == "2>" and previous_is_space
        ):
            flush()
            tokens.append(("op", two))
            i += 2
            continue

        if char in "|;&<>":
            flush()
            tokens.append(("op", char))
            i += 1
            continue

        buffer.append(char)
        i += 1

    flush()
    return tokens


def _split_args(args: list[str], program: str) -> tuple[list[dict], list[str]]:
    spec = COMMANDS.get(program, {})
    known = spec.get("options", {})
    value_options = VALUE_OPTIONS.get(program, set())
    consumed: set[int] = set()
    options: list[dict] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and arg != "-":
            flag = arg
            description: str | None = None

            if arg in known:
                description = known[arg]
            elif arg.startswith("--") and arg.split("=", 1)[0] in known:
                flag = arg.split("=", 1)[0]
                description = known[flag]
            elif not arg.startswith("--") and len(arg) > 2:
                parts = []
                for char in arg[1:]:
                    key = "-" + char
                    if key in known:
                        parts.append(f"{key} {known[key]}")
                    else:
                        parts = []
                        break
                if parts:
                    description = "；".join(parts)

            if description is None:
                description = "未知选项"

            consumed.add(i)
            next_is_value = (
                i + 1 < len(args)
                and not args[i + 1].startswith("-")
            ) or (
                flag == "-mtime"
                and i + 1 < len(args)
                and re.fullmatch(r"-\d+", args[i + 1]) is not None
            )
            if flag in value_options and next_is_value:
                flag = f"{flag} {args[i + 1]}"
                consumed.add(i + 1)
                i += 1

            options.append({"flag": flag, "description": description})
        i += 1

    positional = [
        arg for index, arg in enumerate(args)
        if index not in consumed and not arg.startswith("-")
    ]
    return options, positional


def analyze_command(text: str) -> dict:
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return {"type": "command", "text": text}

    program = Path(tokens[0]).name
    args = tokens[1:]
    spec = COMMANDS.get(program)
    summary = spec["summary"] if spec else "未知命令（命令知识库未收录）"

    notes: list[str] = []
    inner = None
    positional: list[str] = []
    if program == "xargs":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            if args[index] in ("-n", "-I") and index + 1 < len(args):
                index += 2
            else:
                index += 1
        options, _ = _split_args(args[:index], program)
        inner_tokens = args[index:]
        if inner_tokens:
            inner_name = Path(inner_tokens[0]).name
            inner_spec = COMMANDS.get(inner_name)
            inner_options, _ = _split_args(inner_tokens[1:], inner_name)
            inner = {
                "program": inner_name,
                "summary": inner_spec["summary"] if inner_spec else "未知命令",
                "options": inner_options,
            }
            notes.append(
                "把左侧输出作为参数交给 " + " ".join(inner_tokens) + " 执行"
            )
    else:
        options, positional = _split_args(args, program)

    return {
        "type": "command",
        "text": text,
        "program": program,
        "summary": summary,
        "options": options,
        "args": positional,
        "notes": notes,
        "inner": inner,
    }


def build_steps(tokens: list[tuple[str, str]]) -> list[dict]:
    steps: list[dict] = []
    buffer: list[str] = []
    after_redirect = False

    def flush() -> None:
        text = " ".join(buffer).strip()
        if text:
            steps.append(analyze_command(text))
        buffer.clear()

    for kind, text in tokens:
        if kind == "op":
            flush()
            steps.append({
                "type": "operator",
                "text": text,
                "description": OPERATORS.get(text, "shell 操作符"),
            })
            after_redirect = text in REDIRECT_OPS
        elif after_redirect:
            steps.append({"type": "target", "text": text})
            after_redirect = False
        else:
            buffer.append(text)

    flush()
    return steps


def explain(command: str) -> dict:
    steps = build_steps(split_tokens(command))
    segments = [step for step in steps if step["type"] == "command"]
    operators = [step["text"] for step in steps if step["type"] == "operator"]
    return {
        "command": command,
        "steps": steps,
        "segments": segments,
        "operators": operators,
        "risk": assess(command).to_dict(),
    }


def render_explain(result: dict) -> str:
    risk = result["risk"]
    lines = [
        f"命令 : {result['command']}",
        f"风险 : {risk['level']} / {risk['action']}",
    ]
    for reason in risk.get("reasons", []):
        lines.append(f"  - {reason}")

    index = 0
    for step in result["steps"]:
        if step["type"] == "operator":
            lines.append("")
            lines.append(f"  {step['text']}  {step['description']}")
            continue
        if step["type"] == "target":
            lines.append(f"      -> {step['text']}（重定向目标）")
            continue

        index += 1
        lines.append("")
        lines.append(f"  [{index}] {step['text']}")
        lines.append(f"      用途 : {step['summary']}")
        for option in step["options"]:
            lines.append(f"      选项 : {option['flag']:<16} {option['description']}")
        if step["args"]:
            lines.append(f"      参数 : {', '.join(step['args'])}")
        for note in step["notes"]:
            lines.append(f"      提示 : {note}")
        if step.get("inner"):
            inner = step["inner"]
            lines.append(f"      内部 : {inner['program']} — {inner['summary']}")
            for option in inner.get("options", []):
                lines.append(f"             {option['flag']:<12} {option['description']}")
    return "\n".join(lines)
