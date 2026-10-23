"""交互式 REPL：在终端里连续使用 ShellMate。"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

from shellmate.executor import run_command
from shellmate.memory import Memory, plan_from_row
from shellmate.paths import ensure_state_dir
from shellmate.render import render_plan
from shellmate.safety import assess

HELP = """可用命令：
  /help     显示本帮助
  /history  最近 5 条历史
  /last     查看上一条计划
  /exit     退出（也可按 Ctrl+D）
其他输入按自然语言或 shell 命令解析；--plan-only 时只展示不执行。"""


def _setup_readline(history_file: Path):
    try:
        import readline
    except ImportError:
        return None
    try:
        if history_file.exists():
            readline.read_history_file(str(history_file))
        readline.set_history_length(1000)
    except OSError:
        pass
    return readline


def _read_multiline(line: str, input_fn) -> str:
    parts = [line[:-1]]
    while True:
        try:
            extra = input_fn("... ")
        except (EOFError, KeyboardInterrupt):
            break
        if not extra:
            break
        if extra.endswith("\\"):
            parts.append(extra[:-1])
            continue
        parts.append(extra)
        break
    return " ".join(part.strip() for part in parts if part.strip())


def run_repl(
    input_fn=None,
    output=None,
    use_llm: bool = False,
    plan_only: bool = False,
    history_file: Path | None = None,
) -> int:
    input_fn = input_fn or builtins.input
    out = output or sys.stdout
    history_file = Path(history_file) if history_file else ensure_state_dir() / "repl_history"
    readline = _setup_readline(history_file)
    memory = Memory()

    def emit(text: str = "") -> None:
        print(text, file=out)

    emit("ShellMate REPL（/help 查看帮助，/exit 或 Ctrl+D 退出）")

    try:
        while True:
            try:
                line = input_fn("shellmate> ")
            except EOFError:
                emit()
                break
            except KeyboardInterrupt:
                emit("\n（已取消，Ctrl+D 退出）")
                continue

            line = line.strip()
            if not line:
                continue
            if line.endswith("\\"):
                line = _read_multiline(line, input_fn)
            if not line:
                continue

            if line in ("/exit", "/quit", "exit", "quit"):
                break
            if line == "/help":
                emit(HELP)
                continue
            if line == "/history":
                rows = memory.history(5)
                if not rows:
                    emit("暂无历史命令")
                for row in rows:
                    emit(f"  {row['id']:<4} {row['intent']:<16} {row['command']}")
                continue
            if line == "/last":
                row = memory.last()
                emit(render_plan(plan_from_row(row)) if row else "暂无历史命令")
                continue
            if line.startswith("/"):
                emit(f"未知命令：{line}（/help 查看帮助）")
                continue

            try:
                from shellmate.cli import resolve_plan

                plan = resolve_plan(line, use_llm=use_llm)
                assessment = assess(plan.command, plan.requires_root) if plan.command else None
                if assessment is not None:
                    plan.risk = assessment.to_dict()
                emit()
                emit(render_plan(plan))
                if not plan.command:
                    continue

                if plan_only:
                    memory.record(plan)
                    emit("（plan-only：未执行）")
                    continue

                result = run_command(plan.command, assessment)
                memory.record(plan, executed=result.executed, exit_code=result.exit_code)
                if result.decision == "executed":
                    if result.stdout:
                        emit(result.stdout.rstrip("\n"))
                    if result.stderr:
                        emit(result.stderr.rstrip("\n"))
                    emit(f"[退出码 {result.exit_code}]")
                else:
                    emit(f"结果   : {result.decision}")
            except KeyboardInterrupt:
                emit("\n（已取消）")
            except Exception as exc:  # pragma: no cover - 交互环境的兜底
                emit(f"错误   : {exc}")
    finally:
        if readline is not None:
            try:
                readline.write_history_file(str(history_file))
            except OSError:
                pass
        memory.close()

    emit("再见。")
    return 0
