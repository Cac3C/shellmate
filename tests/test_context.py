"""环境上下文测试。"""

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from shellmate.cli import main
from shellmate.context import collect_context, render_text


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        (self.root / "README.md").write_text("demo", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (self.root / "Makefile").write_text("test:\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        self.ctx = collect_context(self.root)

    def test_required_keys(self):
        for key in (
            "collected_at", "hostname", "user", "home", "cwd", "distro",
            "kernel", "python", "shell", "disk", "entries", "project",
        ):
            self.assertIn(key, self.ctx)

    def test_user_and_kernel(self):
        self.assertTrue(self.ctx["user"])
        self.assertTrue(self.ctx["kernel"])
        self.assertTrue(self.ctx["hostname"])

    def test_entries(self):
        names = {item["name"] for item in self.ctx["entries"]}
        self.assertEqual(names, {"README.md", "pyproject.toml", "Makefile", "src", "tests"})
        src = next(item for item in self.ctx["entries"] if item["name"] == "src")
        self.assertEqual(src["type"], "dir")
        self.assertEqual(src["child_count"], 1)
        self.assertIn("main.py", src["children"])

    def test_project_markers(self):
        markers = set(self.ctx["project"]["markers"])
        self.assertEqual(self.ctx["project"]["name"], self.root.name)
        self.assertEqual(markers, {"git", "docs", "python", "make"})

    def test_json_serializable(self):
        encoded = json.dumps(self.ctx, ensure_ascii=False)
        self.assertIn(self.ctx["kernel"], encoded)

    def test_collect_is_fast(self):
        start = time.monotonic()
        collect_context(self.root)
        self.assertLess(time.monotonic() - start, 1.0)

    def test_render_text(self):
        text = render_text(self.ctx)
        self.assertIn("ShellMate 环境上下文", text)
        self.assertIn(self.ctx["kernel"], text)
        self.assertIn("当前目录", text)
        self.assertIn("README.md", text)
        self.assertIn("git", text)

    def test_cli_ctx_json(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["ctx", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["user"], self.ctx["user"])
        self.assertEqual(parsed["kernel"], self.ctx["kernel"])

    def test_cli_ctx_text(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["ctx"])
        self.assertEqual(code, 0)
        self.assertIn("当前目录", stdout.getvalue())
        self.assertIn("项目", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
