"""执行器测试：确认、拒绝、dry-run 与审计日志。"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shellmate.cli import main
from shellmate.executor import run_command
from shellmate.safety import RiskAssessment, assess


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.audit_file = Path(self.tmp.name) / "shellmate" / "audit.jsonl"

    def audit_lines(self) -> list[dict]:
        if not self.audit_file.exists():
            return []
        return [
            json.loads(line)
            for line in self.audit_file.read_text(encoding="utf-8").splitlines()
        ]

    def test_safe_command_executes_and_audits(self):
        result = run_command("echo shellmate-exec", assess("echo shellmate-exec"), yes=True)
        self.assertTrue(result.executed)
        self.assertEqual(result.decision, "executed")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("shellmate-exec", result.stdout)
        records = self.audit_lines()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["command"], "echo shellmate-exec")
        self.assertEqual(records[0]["decision"], "executed")

    def test_critical_denied_even_with_yes(self):
        result = run_command("rm -rf /", assess("rm -rf /"), yes=True)
        self.assertFalse(result.executed)
        self.assertEqual(result.decision, "denied")
        self.assertEqual(self.audit_lines()[0]["decision"], "denied")

    def test_dry_run_does_not_execute(self):
        target = Path(self.tmp.name) / "should-not-exist.txt"
        command = f"echo hi > {target}"
        result = run_command(command, assess(command), dry_run=True)
        self.assertEqual(result.decision, "dry-run")
        self.assertFalse(result.executed)
        self.assertFalse(target.exists())

    def test_high_requires_literal_yes(self):
        prompts = []

        def answer_no(prompt):
            prompts.append(prompt)
            return "no"

        result = run_command(
            "echo hi",
            RiskAssessment("high", "double-confirm", ["测试高风险"]),
            input_fn=answer_no,
        )
        self.assertEqual(result.decision, "cancelled")
        self.assertFalse(result.executed)
        self.assertIn("yes", prompts[0])

        result = run_command(
            "echo hi",
            RiskAssessment("high", "double-confirm", ["测试高风险"]),
            input_fn=lambda prompt: "yes",
        )
        self.assertEqual(result.decision, "executed")
        self.assertIn("hi", result.stdout)

    def test_medium_yes_skips_prompt(self):
        def fail(_prompt):
            raise AssertionError("--yes 不应再提示")

        result = run_command(
            "echo hi",
            RiskAssessment("medium", "confirm", ["测试"]),
            yes=True,
            input_fn=fail,
        )
        self.assertEqual(result.decision, "executed")

    def test_medium_prompt_cancel(self):
        result = run_command(
            "echo hi",
            RiskAssessment("medium", "confirm", ["测试"]),
            input_fn=lambda prompt: "n",
        )
        self.assertEqual(result.decision, "cancelled")
        self.assertFalse(result.executed)

    def test_empty_command(self):
        result = run_command("   ", assess("   "))
        self.assertEqual(result.decision, "empty")
        self.assertFalse(result.executed)

    def test_cli_plan_critical_exits_3(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["plan", "rm -rf /", "--json"])
        self.assertEqual(code, 3)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["risk"]["level"], "critical")

    def test_cli_run_critical_exits_3(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["run", "rm -rf /", "--yes"])
        self.assertEqual(code, 3)

    def test_cli_run_dry_run(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["run", "echo hi", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
