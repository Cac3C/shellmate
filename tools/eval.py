#!/usr/bin/env python3
"""离线解析评测：逐条比对 CommandPlan 的 intent 与 command。

用法：
    python3 tools/eval.py            # 只打印汇总与失败项
    python3 tools/eval.py --verbose  # 逐条打印
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shellmate.nlu.offline import parse  # noqa: E402

CASES_FILE = ROOT / "data" / "eval_cases.json"
THRESHOLD = 0.9


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线意图解析评测")
    parser.add_argument("--verbose", action="store_true", help="逐条打印结果")
    args = parser.parse_args(argv)

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    failures: list[tuple[dict, object]] = []
    passed = 0

    for case in cases:
        plan = parse(case["input"])
        ok = plan.intent == case["intent"] and plan.command == case["command"]
        if ok:
            passed += 1
        else:
            failures.append((case, plan))
        if args.verbose:
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {case['input']}")
            print(f"       期望: {case['intent']} | {case['command']}")
            print(f"       实际: {plan.intent or '-'} | {plan.command or '-'}")

    total = len(cases)
    accuracy = passed / total if total else 0.0
    print(f"评测用例 : {total}")
    print(f"通过     : {passed}")
    print(f"失败     : {total - passed}")
    print(f"准确率   : {accuracy * 100:.1f}%")

    for case, plan in failures:
        print(f"  FAIL {case['input']}")
        print(f"       期望: {case['intent']} | {case['command']}")
        print(f"       实际: {plan.intent or '-'} | {plan.command or '-'}")

    return 0 if accuracy >= THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
