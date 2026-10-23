"""LLM 后端测试：本地 mock HTTP 服务，不访问真实网络。"""

import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from shellmate.cli import main
from shellmate.config import Config
from shellmate.nlu.llm import LLMError, parse_with_llm

CONTEXT = {
    "user": "alice",
    "hostname": "workstation",
    "distro": {"pretty": "Ubuntu 24.04 LTS"},
    "kernel": "6.8.0-31-generic",
    "cwd": "/home/alice/project",
    "entries": [{"name": "src", "type": "dir"}],
    "project": {"name": "project", "markers": ["git", "python"]},
}


def completion(content: str) -> bytes:
    return json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode()


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        self.server.requests.append(json.loads(body))
        if self.server.delay:
            time.sleep(self.server.delay)
        if self.server.responses:
            status, payload = self.server.responses.pop(0)
        else:
            status, payload = 500, b"no response"
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class LLMTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.server.responses = []
        self.server.requests = []
        self.server.delay = 0
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.config = Config(
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            model="mock",
            api_key="test-key",
            timeout=2.0,
        )

    def queue(self, content: str, status: int = 200):
        self.server.responses.append((status, completion(content)))

    def test_success(self):
        self.queue(json.dumps({
            "command": "ls -la /tmp",
            "intent": "list_tmp",
            "slots": {"path": "/tmp"},
            "confidence": 0.9,
            "requires_root": False,
            "explanation": "列出 /tmp 内容",
        }))
        plan = parse_with_llm("看看 /tmp", self.config, CONTEXT)
        self.assertEqual(plan.command, "ls -la /tmp")
        self.assertEqual(plan.source, "llm")
        self.assertEqual(plan.slots["path"], "/tmp")
        self.assertEqual(plan.risk["level"], "safe")
        self.assertIn("内核 6.8.0-31-generic", self.server.requests[0]["messages"][0]["content"])
        self.assertIn("项目标记", self.server.requests[0]["messages"][0]["content"])

    def test_markdown_fence(self):
        content = "```json\n" + json.dumps({
            "command": "df -h", "intent": "disk", "slots": {},
            "confidence": 0.8, "requires_root": False, "explanation": "磁盘",
        }) + "\n```"
        self.queue(content)
        plan = parse_with_llm("查看磁盘", self.config, CONTEXT)
        self.assertEqual(plan.command, "df -h")

    def test_invalid_then_valid_retry(self):
        self.queue("not json")
        self.queue(json.dumps({
            "command": "uname -r", "intent": "kernel", "slots": {},
            "confidence": 0.9, "requires_root": False, "explanation": "内核",
        }))
        plan = parse_with_llm("内核版本", self.config, CONTEXT)
        self.assertEqual(plan.command, "uname -r")
        self.assertEqual(len(self.server.requests), 2)

    def test_invalid_twice_raises(self):
        self.queue("not json")
        self.queue("still not json")
        with self.assertRaises(LLMError):
            parse_with_llm("x", self.config, CONTEXT)

    def test_http_error(self):
        self.server.responses.append((500, b"boom"))
        with self.assertRaises(LLMError):
            parse_with_llm("x", self.config, CONTEXT, retries=0)

    def test_missing_key(self):
        config = Config(base_url=self.config.base_url, api_key="", timeout=1)
        with self.assertRaises(LLMError) as context:
            parse_with_llm("x", config, CONTEXT)
        self.assertIn("API Key", str(context.exception))

    def test_timeout(self):
        self.server.delay = 0.6
        config = Config(
            base_url=self.config.base_url,
            model="mock",
            api_key="test",
            timeout=0.2,
        )
        with self.assertRaises(LLMError):
            parse_with_llm("x", config, CONTEXT, retries=0)

    def test_dangerous_command_still_assessed(self):
        self.queue(json.dumps({
            "command": "rm -rf /", "intent": "cleanup", "slots": {},
            "confidence": 0.9, "requires_root": True, "explanation": "清理",
        }))
        plan = parse_with_llm("清空根目录", self.config, CONTEXT)
        self.assertEqual(plan.command, "rm -rf /")
        self.assertEqual(plan.risk["level"], "critical")
        self.assertEqual(plan.risk["action"], "deny")

    def test_cli_llm_success(self):
        self.queue(json.dumps({
            "command": "du -sh /home/* | sort -h", "intent": "home_usage",
            "slots": {"path": "/home"}, "confidence": 0.9,
            "requires_root": False, "explanation": "统计各用户目录",
        }))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp.name}), \
                mock.patch("shellmate.nlu.llm.load_config", return_value=self.config):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["plan", "统计 /home 下各用户目录大小", "--llm"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("来源   : llm", text)
        self.assertIn("du -sh /home/* | sort -h", text)

    def test_cli_fallback_on_error(self):
        self.server.responses.append((500, b"boom"))
        self.server.responses.append((500, b"boom"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp.name}), \
                mock.patch("shellmate.nlu.llm.load_config", return_value=self.config):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["plan", "查看磁盘使用情况", "--llm"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("已回退离线", text)
        self.assertIn("df -h", text)


if __name__ == "__main__":
    unittest.main()
