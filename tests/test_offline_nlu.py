"""离线意图解析测试。"""

import contextlib
import io
import json
import unittest
from pathlib import Path

from shellmate.cli import main
from shellmate.nlu.offline import load_intents, parse

ROOT = Path(__file__).resolve().parents[1]


class OfflineNluTest(unittest.TestCase):
    def test_intent_library_size(self):
        self.assertGreaterEqual(len(load_intents()), 12)

    def test_command_library_size(self):
        data = json.loads((ROOT / "data" / "commands.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["commands"]), 20)

    def test_disk_usage(self):
        plan = parse("查看磁盘使用情况")
        self.assertEqual(plan.intent, "disk_usage")
        self.assertEqual(plan.command, "df -h")
        self.assertGreaterEqual(plan.confidence, 0.55)

    def test_large_files_slots(self):
        plan = parse("找出 /var/log 下大于 100M 的文件")
        self.assertEqual(plan.intent, "large_files")
        self.assertEqual(plan.command, "find /var/log -type f -size +100M")
        self.assertEqual(plan.slots["path"], "/var/log")
        self.assertEqual(plan.slots["size"], "100M")

    def test_recent_files_defaults_and_pattern(self):
        plan = parse("找出 /home 下 7 天内修改的 .c 文件")
        self.assertEqual(plan.intent, "recent_files")
        self.assertEqual(plan.command, "find /home -type f -name '*.c' -mtime -7")
        self.assertEqual(plan.slots["days"], "7")

    def test_change_permissions(self):
        plan = parse("把 /tmp/x 权限改成 777")
        self.assertEqual(plan.intent, "change_permissions")
        self.assertEqual(plan.command, "chmod 777 /tmp/x")

    def test_clean_build(self):
        plan = parse("清理当前目录的编译产物")
        self.assertEqual(plan.intent, "clean_build")
        self.assertEqual(plan.command, "make clean")

    def test_unknown_input_has_low_confidence(self):
        plan = parse("帮我写一首诗")
        self.assertEqual(plan.intent, "")
        self.assertEqual(plan.command, "")
        self.assertLess(plan.confidence, 0.55)
        self.assertTrue(plan.message)

    def test_missing_required_slot(self):
        plan = parse("找出 /var/log 下大于的文件")
        self.assertEqual(plan.intent, "large_files")
        self.assertEqual(plan.command, "")
        self.assertLess(plan.confidence, 0.55)
        self.assertIn("size", plan.message)

    def test_eval_suite_passes(self):
        cases = json.loads(
            (ROOT / "data" / "eval_cases.json").read_text(encoding="utf-8")
        )["cases"]
        passed = 0
        for case in cases:
            plan = parse(case["input"])
            if plan.intent == case["intent"] and plan.command == case["command"]:
                passed += 1
        self.assertGreaterEqual(len(cases), 30)
        self.assertGreaterEqual(passed / len(cases), 0.9)

    def test_cli_plan_json(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["plan", "查看磁盘使用情况", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["intent"], "disk_usage")
        self.assertEqual(data["command"], "df -h")
        self.assertEqual(data["source"], "offline")

    def test_cli_plan_text(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["plan", "查看内核版本"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("uname -r", text)
        self.assertIn("kernel_version", text)


if __name__ == "__main__":
    unittest.main()
