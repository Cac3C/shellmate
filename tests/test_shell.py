"""Shell 集成测试：shm 函数、Ctrl+G 绑定、bin/shm 与管道 REPL。"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "--rcfile", str(ROOT / "shellmate.sh"), "-ic", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )


class ShellIntegrationTest(unittest.TestCase):
    def test_shm_is_function(self):
        result = run_bash("type shm")
        self.assertIn("shm", result.stdout)
        self.assertIn("python3 -m shellmate", result.stdout)

    def test_shm_version(self):
        result = run_bash("shm --version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shellmate 0.1.0", result.stdout)

    def test_shm_plan(self):
        result = run_bash('shm plan "查看磁盘"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("df -h", result.stdout)

    def test_ctrl_g_binding(self):
        result = run_bash("bind -X")
        self.assertIn("__shm_ctrl_g", result.stdout)
        self.assertIn("C-g", result.stdout)

    def test_bin_shm(self):
        result = subprocess.run(
            [str(ROOT / "bin" / "shm"), "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shellmate 0.1.0", result.stdout)

    def test_repl_pipe(self):
        result = subprocess.run(
            ["python3", "-m", "shellmate", "repl", "--plan-only"],
            cwd=ROOT,
            input="查看磁盘\n/exit\n",
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("df -h", result.stdout)


if __name__ == "__main__":
    unittest.main()
