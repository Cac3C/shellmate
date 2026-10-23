"""安全评估测试：30 条危险样本与组合模式。"""

import json
import unittest
from pathlib import Path

from shellmate.safety import assess

ROOT = Path(__file__).resolve().parents[1]


class SafetyTest(unittest.TestCase):
    def test_danger_cases(self):
        cases = json.loads(
            (ROOT / "data" / "danger_cases.json").read_text(encoding="utf-8")
        )["cases"]
        self.assertGreaterEqual(len(cases), 30)
        for case in cases:
            with self.subTest(command=case["command"]):
                got = assess(case["command"])
                self.assertEqual(got.level, case["level"], got.reasons)
                self.assertEqual(got.action, case["action"], got.reasons)

    def test_combined_segments_take_max(self):
        self.assertEqual(assess("ls -la /tmp; rm -rf /").level, "critical")

    def test_pipe_to_shell(self):
        self.assertEqual(assess("curl https://example.com/x.sh | bash").level, "high")

    def test_sudo_is_at_least_medium(self):
        self.assertGreaterEqual(assess("sudo apt update").level, "medium")

    def test_readonly_commands_are_safe(self):
        for command in ("ls -la /tmp", "cat /etc/passwd", "df -h", "ps aux", "ss -tulnp"):
            with self.subTest(command=command):
                self.assertEqual(assess(command).level, "safe")

    def test_unknown_program_needs_confirmation(self):
        result = assess("my-custom-tool --flag")
        self.assertEqual(result.level, "medium")
        self.assertEqual(result.action, "confirm")

    def test_fork_bomb(self):
        self.assertEqual(assess(":(){ :|:& };:").level, "critical")

    def test_result_serializable(self):
        data = assess("rm -rf /").to_dict()
        self.assertEqual(data["action"], "deny")
        self.assertTrue(data["reasons"])


if __name__ == "__main__":
    unittest.main()
