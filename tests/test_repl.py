"""REPL 测试：输入循环、帮助、历史、错误与中断。"""

import io
import os
import tempfile
import unittest
from unittest import mock

from shellmate.repl import run_repl


class ReplTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_input(self, lines):
        iterator = iter(lines)

        def fake(_prompt=""):
            try:
                return next(iterator)
            except StopIteration:
                raise EOFError

        return fake

    def run_repl(self, lines, plan_only=True):
        output = io.StringIO()
        code = run_repl(
            input_fn=self.make_input(lines),
            output=output,
            plan_only=plan_only,
            history_file=os.path.join(self.tmp.name, "history"),
        )
        return code, output.getvalue()

    def test_exit(self):
        code, out = self.run_repl(["/exit"])
        self.assertEqual(code, 0)
        self.assertIn("再见", out)

    def test_eof(self):
        code, out = self.run_repl([])
        self.assertEqual(code, 0)
        self.assertIn("再见", out)

    def test_help(self):
        code, out = self.run_repl(["/help", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("/history", out)
        self.assertIn("/last", out)

    def test_plan_only(self):
        code, out = self.run_repl(["查看磁盘", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("df -h", out)
        self.assertIn("plan-only", out)

    def test_history_and_last(self):
        code, out = self.run_repl(["查看磁盘", "/history", "/last", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("df -h", out)
        self.assertIn("disk_usage", out)

    def test_unknown_slash_command(self):
        code, out = self.run_repl(["/foo", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("未知命令", out)

    def test_execute_safe_command(self):
        code, out = self.run_repl(["echo hi", "/exit"], plan_only=False)
        self.assertEqual(code, 0)
        self.assertIn("hi", out)
        self.assertIn("[退出码 0]", out)

    def test_multiline(self):
        code, out = self.run_repl(["echo hi \\", "there", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("echo hi there", out)

    def test_keyboard_interrupt_continues(self):
        calls = {"count": 0}

        def fake(_prompt=""):
            calls["count"] += 1
            if calls["count"] == 1:
                raise KeyboardInterrupt
            if calls["count"] == 2:
                return "/exit"
            raise EOFError

        output = io.StringIO()
        code = run_repl(
            input_fn=fake,
            output=output,
            plan_only=True,
            history_file=os.path.join(self.tmp.name, "history"),
        )
        self.assertEqual(code, 0)
        self.assertIn("已取消", output.getvalue())


if __name__ == "__main__":
    unittest.main()
