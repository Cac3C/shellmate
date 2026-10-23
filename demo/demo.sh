#!/usr/bin/env bash
# ShellMate 一键演示：离线运行，不依赖 API Key。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE="$(mktemp -d)"
cleanup() { rm -rf "$STATE"; }
trap cleanup EXIT

export XDG_STATE_HOME="$STATE"
export SHELLMATE_OFFLINE=1
export PYTHONIOENCODING=utf-8
unset SHELLMATE_API_KEY

step() { printf '\n===== %s =====\n' "$1"; }

step "1. 版本与环境"
python3 -m shellmate --version
printf 'kernel: '; uname -r
printf 'user  : '; whoami

step "2. 自然语言生成命令"
python3 -m shellmate plan "查看磁盘使用情况" --offline

step "3. 命令逐段解释"
python3 -m shellmate explain "find /var/log -type f -size +100M | xargs rm -f"

step "4. 记忆与指代"
python3 -m shellmate plan "查看目录大小" --offline
python3 -m shellmate plan "按大小排序" --offline
python3 -m shellmate plan "换成 /tmp" --offline

step "5. 危险命令拒绝"
python3 -m shellmate run "rm -rf /" --yes
printf '[退出码 %s]\n' "$?"

step "6. 高风险二次确认（输入 no）"
printf 'no\n' | python3 -m shellmate run "chmod -R 777 /tmp/demo"
printf '[退出码 %s]\n' "$?"

step "7. 清理当前目录的编译产物"
python3 -m shellmate plan "清理编译产物" --offline

step "8. 安全执行与测试"
python3 -m shellmate run "echo demo-ok" --yes
printf '[退出码 %s]\n' "$?"
make test
