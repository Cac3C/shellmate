"""ShellMate 命令行入口：解析、解释、执行与历史管理。"""

import argparse
import json
import sys

from shellmate import __version__

# 子命令 -> 一句话说明。
SUBCOMMANDS = {
    "plan": "把自然语言解析为命令计划（不执行）",
    "run": "解析并执行命令（带安全确认）",
    "explain": "逐段解释一条 shell 命令",
    "ctx": "显示本机与当前项目上下文",
    "history": "查看历史命令与会话",
    "last": "查看上一条命令计划",
    "forget": "清空历史记录",
    "repl": "进入交互式 REPL",
}


def cmd_ctx(args: argparse.Namespace) -> int:
    """打印本机与当前项目上下文。"""
    from shellmate.context import collect_context, render_text

    ctx = collect_context()
    if args.json:
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
    else:
        print(render_text(ctx))
    return 0


def resolve_plan(text: str, use_llm: bool = False):
    """解析顺序：历史指代 -> LLM（可选）-> 离线规则。"""
    from shellmate.memory import Memory, is_reference, resolve_reference
    from shellmate.nlu.offline import parse
    from shellmate.nlu.schema import CommandPlan

    memory = Memory()
    try:
        last = memory.last()
    finally:
        memory.close()

    plan = resolve_reference(text, last)
    if plan is not None:
        return plan

    if is_reference(text) and last is None:
        return CommandPlan(
            raw_input=text,
            command="",
            intent="",
            confidence=0.0,
            message="没有可复用的上一条命令",
        )

    if use_llm:
        from shellmate.nlu.llm import LLMError, parse_with_llm

        try:
            return parse_with_llm(text)
        except LLMError as exc:
            plan = parse(text)
            note = f"LLM 不可用：{exc}；已回退离线"
            plan.message = f"{note}；{plan.message}" if plan.message else note
            return plan

    return parse(text)


def cmd_plan(args: argparse.Namespace) -> int:
    """自然语言 -> CommandPlan，支持历史指代与可选 LLM，并给出安全评估。"""
    from shellmate.memory import Memory
    from shellmate.render import render_plan
    from shellmate.safety import assess

    text = " ".join(args.query)
    plan = resolve_plan(text, use_llm=bool(getattr(args, "llm", False)))
    assessment = inspect_risk(plan, assess)

    memory = Memory()
    try:
        if plan.command:
            memory.record(plan)
    finally:
        memory.close()

    print(plan.to_json() if args.json else render_plan(plan))
    return 3 if assessment is not None and assessment.action == "deny" else 0


def inspect_risk(plan, assess):
    """给 CommandPlan 附上风险评估；空命令返回 None。"""
    if not plan.command:
        return None
    assessment = assess(plan.command, plan.requires_root)
    plan.risk = assessment.to_dict()
    return assessment


def cmd_explain(args: argparse.Namespace) -> int:
    """逐段解释一条 shell 命令。"""
    from shellmate.explain import explain, render_explain

    result = explain(" ".join(args.query))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_explain(result))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """解析、安全评估、确认执行并写审计日志。"""
    from shellmate.executor import run_command
    from shellmate.memory import Memory
    from shellmate.render import render_plan
    from shellmate.safety import assess

    text = " ".join(args.query)
    plan = resolve_plan(text, use_llm=bool(getattr(args, "llm", False)))
    memory = Memory()
    if not plan.command:
        memory.close()
        print(render_plan(plan))
        return 2

    assessment = assess(plan.command, plan.requires_root)
    plan.risk = assessment.to_dict()
    if not args.json:
        print(f"命令   : {plan.command}")
        print(f"风险   : {assessment.level} / {assessment.action}")
        for reason in assessment.reasons:
            print(f"  - {reason}")
        print()

    result = run_command(
        plan.command,
        assessment,
        yes=args.yes,
        dry_run=args.dry_run,
    )
    memory.record(plan, executed=result.executed, exit_code=result.exit_code)
    memory.close()

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif result.decision == "cancelled":
        print()
        print("结果   : cancelled")
    elif result.decision == "executed":
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        print(f"[退出码 {result.exit_code}]")
    elif result.decision == "dry-run":
        print("结果   : dry-run，未执行")
    else:
        print(f"结果   : {result.decision}")

    if result.decision in ("denied", "cancelled", "empty", "error"):
        return 3 if assessment.action == "deny" else 2
    if result.decision == "executed" and result.exit_code not in (0, None):
        return 1
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """查看最近的历史命令。"""
    from shellmate.memory import Memory

    memory = Memory()
    rows = memory.history(args.limit)
    memory.close()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("暂无历史命令")
        return 0
    print(f"{'ID':<4} {'时间':<8} {'意图':<16} 命令")
    for row in rows:
        clock = row["created_at"][11:19]
        command = row["command"]
        if len(command) > 44:
            command = command[:42] + ".."
        print(f"{row['id']:<4} {clock:<8} {row['intent']:<16} {command}")
    return 0


def cmd_last(args: argparse.Namespace) -> int:
    """查看上一条命令计划。"""
    from shellmate.memory import Memory, plan_from_row
    from shellmate.render import render_plan

    memory = Memory()
    row = memory.last()
    memory.close()
    if not row:
        print("暂无历史命令")
        return 1
    print(render_plan(plan_from_row(row)))
    print(f"时间   : {row['created_at']}")
    return 0


def cmd_repl(args: argparse.Namespace) -> int:
    """进入交互式 REPL。"""
    from shellmate.repl import run_repl

    return run_repl(use_llm=args.llm, plan_only=args.plan_only)


def cmd_forget(args: argparse.Namespace) -> int:
    """清空历史记录。"""
    from shellmate.memory import Memory

    memory = Memory()
    count = memory.forget()
    memory.close()
    print(f"已清空 {count} 条历史记录")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shellmate",
        description="ShellMate：把中文指令转换成可解释、可审计的 shell 命令",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"shellmate {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, help_text in SUBCOMMANDS.items():
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        if name == "ctx":
            sub.add_argument("--json", action="store_true", help="以 JSON 输出")
            sub.set_defaults(handler=cmd_ctx)
        elif name == "plan":
            sub.add_argument("query", nargs="+", help="自然语言指令")
            sub.add_argument("--json", action="store_true", help="输出 CommandPlan JSON")
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument("--offline", action="store_true", help="强制离线解析")
            mode.add_argument("--llm", action="store_true", help="调用 DeepSeek 生成，失败回退离线")
            sub.set_defaults(handler=cmd_plan)
        elif name == "explain":
            sub.add_argument("query", nargs="+", help="要解释的 shell 命令")
            sub.add_argument("--json", action="store_true", help="输出 JSON")
            sub.set_defaults(handler=cmd_explain)
        elif name == "history":
            sub.add_argument("--limit", type=int, default=10, help="显示条数")
            sub.add_argument("--json", action="store_true", help="输出 JSON")
            sub.set_defaults(handler=cmd_history)
        elif name == "last":
            sub.set_defaults(handler=cmd_last)
        elif name == "forget":
            sub.set_defaults(handler=cmd_forget)
        elif name == "repl":
            sub.add_argument("--llm", action="store_true", help="优先使用 DeepSeek")
            sub.add_argument("--plan-only", action="store_true", help="只展示计划，不执行")
            sub.set_defaults(handler=cmd_repl)
        elif name == "run":
            sub.add_argument("query", nargs="+", help="自然语言指令或原始命令")
            sub.add_argument(
                "--yes", action="store_true", help="跳过中低风险确认（不能跳过 HIGH/CRITICAL）"
            )
            sub.add_argument("--dry-run", action="store_true", help="只评估不执行")
            sub.add_argument("--json", action="store_true", help="输出结果 JSON")
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument("--offline", action="store_true", help="强制离线解析")
            mode.add_argument("--llm", action="store_true", help="调用 DeepSeek 生成，失败回退离线")
            sub.set_defaults(handler=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
