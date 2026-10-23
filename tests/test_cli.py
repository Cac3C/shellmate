"""CLI 冒烟测试：版本、帮助与错误命令。"""

import contextlib
import io
import unittest

from shellmate import __version__
from shellmate.cli import SUBCOMMANDS, main


class CliTest(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, stdout.getvalue()

    def test_version(self):
        code, out = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), f"shellmate {__version__}")

    def test_help_lists_all_subcommands(self):
        code, out = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        for name in SUBCOMMANDS:
            self.assertIn(name, out)

    def test_unknown_command_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                main(["no-such-command"])
        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
