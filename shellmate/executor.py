"""执行器：根据安全评估结果确认、执行并写审计日志。"""

from __future__ import annotations

import getpass
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime

from shellmate.paths import audit_log, ensure_state_dir
from shellmate.safety import RiskAssessment, assess

PROMPT_MEDIUM = "确认执行？[y/N] "
PROMPT_HIGH = "高风险操作，输入 yes 继续: "


@dataclass
class RunResult:
    command: str
    level: str
    action: str
    decision: str
    executed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def append_audit(result: RunResult) -> None:
    ensure_state_dir()
    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "user": getpass.getuser(),
        **result.to_dict(),
    }
    with audit_log().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _execute(command: str, timeout: float) -> tuple[bool, int | None, str, str]:
    try:
        process = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return True, process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as exc:
        return True, None, exc.stdout or "", f"执行超时（{timeout}s）"
    except OSError as exc:
        return False, None, "", str(exc)


def run_command(
    command: str,
    assessment: RiskAssessment | None = None,
    *,
    yes: bool = False,
    dry_run: bool = False,
    input_fn=input,
    timeout: float = 30.0,
    audit: bool = True,
) -> RunResult:
    assessment = assessment if assessment is not None else assess(command)
    result = RunResult(
        command=command,
        level=assessment.level,
        action=assessment.action,
        decision="pending",
        executed=False,
        reasons=list(assessment.reasons),
    )

    if not command.strip():
        result.decision = "empty"
        result.stderr = "没有可执行的命令"
        if audit:
            append_audit(result)
        return result

    if dry_run:
        result.decision = "dry-run"
        if audit:
            append_audit(result)
        return result

    if assessment.action == "deny":
        result.decision = "denied"
        if audit:
            append_audit(result)
        return result

    if assessment.action == "confirm" and not yes:
        answer = input_fn(PROMPT_MEDIUM).strip().lower()
        if answer not in ("y", "yes"):
            result.decision = "cancelled"
            if audit:
                append_audit(result)
            return result

    if assessment.action == "double-confirm":
        answer = input_fn(PROMPT_HIGH).strip()
        if answer != "yes":
            result.decision = "cancelled"
            if audit:
                append_audit(result)
            return result

    executed, exit_code, stdout, stderr = _execute(command, timeout)
    result.executed = executed
    result.exit_code = exit_code
    result.stdout = stdout
    result.stderr = stderr
    result.decision = "executed" if executed else "error"
    if audit:
        append_audit(result)
    return result
