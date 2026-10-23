"""命令解释器测试：分段、选项、重定向与 10 条 golden。"""

import contextlib
import io
import json
import unittest
from pathlib import Path

from shellmate.cli import main
from shellmate.explain import explain

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"


def structure(result: dict) -> dict:
    return {
        "command": result["command"],
        "segments": [
            {
                "program": step["program"],
                "options": [option["flag"] for option in step["options"]],
                "args": step["args"],
                "inner": step["inner"]["program"] if step.get("inner") else None,
            }
            for step in result["segments"]
        ],
        "operators": result["operators"],
        "targets": [step["text"] for step in result["steps"] if step["type"] == "target"],
        "risk": result["risk"]["level"],
    }


class ExplainTest(unittest.TestCase):
    def test_pipeline_segments(self):
        result = explain("find /var/log -type f -size +100M | xargs rm -f")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["program"], "find")
        self.assertEqual(result["segments"][1]["program"], "xargs")
        self.assertEqual(result["segments"][1]["inner"]["program"], "rm")
        self.assertEqual(result["operators"], ["|"])
        self.assertEqual(result["risk"]["level"], "high")

    def test_redirect_target(self):
        result = explain("cat /etc/passwd > /tmp/users.txt")
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["operators"], [">"])
        targets = [s["text"] for s in result["steps"] if s["type"] == "target"]
        self.assertEqual(targets, ["/tmp/users.txt"])

    def test_and_operator(self):
        result = explain("du -sh /var/log && df -h")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["operators"], ["&&"])

    def test_combined_short_options(self):
        result = explain("ls -lh /tmp")
        segment = result["segments"][0]
        self.assertEqual([o["flag"] for o in segment["options"]], ["-lh"])
        self.assertEqual(segment["args"], ["/tmp"])
        self.assertIn("-l", segment["options"][0]["description"])

    def test_find_value_options(self):
        result = explain("find /var/log -type f -size +100M")
        segment = result["segments"][0]
        self.assertEqual(
            [o["flag"] for o in segment["options"]], ["-type f", "-size +100M"]
        )
        self.assertEqual(segment["args"], ["/var/log"])

    def test_unknown_command(self):
        result = explain("my-custom-tool --flag /tmp")
        segment = result["segments"][0]
        self.assertEqual(segment["program"], "my-custom-tool")
        self.assertIn("未知命令", segment["summary"])
        self.assertIn("未知选项", segment["options"][0]["description"])

    def test_empty_command(self):
        result = explain("")
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["risk"]["level"], "safe")

    def test_golden_files(self):
        files = sorted(GOLDEN.glob("explain_*.json"))
        self.assertEqual(len(files), 10)
        for path in files:
            with self.subTest(file=path.name):
                expected = json.loads(path.read_text(encoding="utf-8"))
                actual = structure(explain(expected["command"]))
                self.assertEqual(actual, expected)

    def test_cli_json(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["explain", "ls -lh /tmp", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["segments"][0]["program"], "ls")
        self.assertEqual(data["risk"]["level"], "safe")

    def test_cli_text(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["explain", "find /var/log -type f -size +100M | xargs rm -f"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("风险", text)
        self.assertIn("xargs", text)
        self.assertIn("内部 : rm", text)


if __name__ == "__main__":
    unittest.main()
