"""历史记忆与指代测试。"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shellmate.cli import main
from shellmate.memory import Memory, is_reference, resolve_reference
from shellmate.nlu.offline import parse


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.memory = Memory()
        self.addCleanup(self.memory.close)

    def record(self, text: str):
        plan = parse(text)
        self.memory.record(plan)
        return plan

    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(argv)
        return code, stdout.getvalue()

    def test_record_and_last(self):
        self.record("查看目录大小")
        row = self.memory.last()
        self.assertIsNotNone(row)
        self.assertEqual(row["command"], "du -sh .")
        self.assertEqual(json.loads(row["slots"])["path"], ".")

    def test_persists_across_connections(self):
        self.record("查看目录大小")
        other = Memory()
        try:
            self.assertEqual(other.last()["command"], "du -sh .")
        finally:
            other.close()

    def test_history_order_and_limit(self):
        self.record("查看磁盘使用情况")
        self.record("查看内核版本")
        rows = self.memory.history(limit=10)
        self.assertEqual(rows[0]["command"], "uname -r")
        self.assertEqual(rows[1]["command"], "df -h")
        self.assertEqual(len(self.memory.history(limit=1)), 1)

    def test_forget_clears_commands(self):
        self.record("查看磁盘使用情况")
        self.assertEqual(self.memory.forget(), 1)
        self.assertIsNone(self.memory.last())

    def test_reference_again(self):
        self.record("查看目录大小")
        plan = resolve_reference("再来一次", self.memory.last())
        self.assertEqual(plan.command, "du -sh .")
        self.assertEqual(plan.source, "memory")

    def test_reference_path(self):
        self.record("查看目录大小")
        plan = resolve_reference("换成 /tmp", self.memory.last())
        self.assertEqual(plan.command, "du -sh /tmp")
        self.assertEqual(plan.slots["path"], "/tmp")

    def test_reference_sort(self):
        self.record("查看目录大小")
        plan = resolve_reference("按大小排序", self.memory.last())
        self.assertEqual(plan.command, "du -sh . | sort -h")

    def test_reference_time(self):
        self.record("找出 /home 下 7 天内修改的 .c 文件")
        plan = resolve_reference("只要 3 天内的", self.memory.last())
        self.assertIn("-mtime -3", plan.command)

    def test_reference_size(self):
        self.record("找出 /var/log 下大于 100M 的文件")
        plan = resolve_reference("只要大于 1G 的", self.memory.last())
        self.assertIn("-size +1G", plan.command)

    def test_reference_without_last(self):
        self.assertIsNone(resolve_reference("再来一次", None))
        self.assertTrue(is_reference("再来一次"))
        self.assertTrue(is_reference("按大小排序"))
        self.assertFalse(is_reference("查看磁盘使用情况"))

    def test_cli_flow(self):
        code, _ = self.run_cli(["plan", "查看目录大小"])
        self.assertEqual(code, 0)
        code, out = self.run_cli(["plan", "按大小排序"])
        self.assertEqual(code, 0)
        self.assertIn("| sort -h", out)
        code, out = self.run_cli(["history", "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertIn("du -sh . | sort -h", out)

    def test_cli_last_and_forget(self):
        self.run_cli(["plan", "查看内核版本"])
        code, out = self.run_cli(["last"])
        self.assertEqual(code, 0)
        self.assertIn("uname -r", out)
        code, out = self.run_cli(["forget"])
        self.assertEqual(code, 0)
        self.assertIn("已清空", out)
        code, out = self.run_cli(["history"])
        self.assertEqual(code, 0)
        self.assertIn("暂无历史命令", out)


if __name__ == "__main__":
    unittest.main()
