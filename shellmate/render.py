"""把 CommandPlan 渲染成终端可读文本。"""

from __future__ import annotations

from shellmate.nlu.schema import CommandPlan


def render_plan(plan: CommandPlan) -> str:
    lines = [
        f"输入   : {plan.raw_input}",
        f"意图   : {plan.intent or '（未识别）'}",
    ]
    if plan.command:
        lines.append(f"命令   : {plan.command}")
    lines.append(f"置信度 : {plan.confidence:.2f}")
    lines.append(f"来源   : {plan.source}")
    risk = plan.risk or {}
    if risk.get("level") and risk["level"] != "unknown":
        lines.append(f"风险   : {risk['level']} / {risk.get('action', '')}")
        for reason in risk.get("reasons", []):
            lines.append(f"  - {reason}")
    if plan.slots:
        slots = "  ".join(f"{key}={value}" for key, value in plan.slots.items())
        lines.append(f"槽位   : {slots}")
    if plan.message:
        lines.append(f"提示   : {plan.message}")
    return "\n".join(lines)
