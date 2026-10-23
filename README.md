# ShellMate

作者：Cac3C（https://github.com/Cac3C）

ShellMate 是一个 Linux 命令行助手。你用中文说明要做什么，它生成一条 shell 命令，给出逐段解释和风险等级，再由你决定是否执行。计划和执行结果会写入本地历史，之后可以重放，也可以在上一条命令的基础上改路径、加排序或换时间范围。

它适合日常运维里那些知道要做什么、但不想反复查 man 手册的场景：查看磁盘和目录、找大文件、改权限、看服务、结束进程、清理构建产物。

## 工作方式

ShellMate 有两个解析后端：

- **离线规则**：意图库、关键词打分和槽位抽取，覆盖 15 类常见操作，不需要网络，也不依赖 API Key；
- **DeepSeek**：把中文需求、当前目录和项目信息放进提示词，让模型返回 JSON；没有 Key、网络失败、超时或 JSON 不合法时，回到离线规则。

两个后端都输出同一个 `CommandPlan`，包含命令、意图、槽位、置信度、来源和风险。风险由本地安全引擎重新评估，模型生成的命令不会直接执行。

## 功能

- 中文到命令：`plan` 只生成计划，`run` 走确认和执行流程；
- 命令解释：按管道、重定向和逻辑运算符分段，说明程序、选项、参数和内部命令；
- 五级风险：safe/low 直接执行，medium 确认一次，high 要求输入 yes，critical 拒绝；
- 审计日志：每次执行决策写入 `~/.local/state/shellmate/audit.jsonl`；
- 历史与指代：记录计划和执行结果，支持“再来一次”“按大小排序”“换成 /tmp”“只要 3 天内的”；
- 环境上下文：读取发行版、内核、用户、磁盘、当前目录和项目标记；
- Shell 集成：`shm` 函数、Ctrl+G 快捷键和交互式 REPL；
- 可选 LLM：有 Key 时处理更开放的说法，失败自动回退。

## 环境要求

- Linux
- Python 3.10 或更高版本
- 运行时不需要第三方 Python 包
- DeepSeek API Key 可选，只在显式使用 `--llm` 时需要

## 快速开始

```bash
git clone https://github.com/Cac3C/shellmate.git shellmate
cd shellmate

python3 -m shellmate --version
python3 -m shellmate ctx
python3 -m shellmate plan "查看磁盘使用情况"
python3 -m shellmate plan "找出 /var/log 下大于 100M 的文件"
python3 -m shellmate explain "find /var/log -type f -size +100M | xargs rm -f"
python3 -m shellmate run "echo hi" --dry-run
```

`run` 默认会按风险等级询问。`--yes` 只跳过 safe/low/medium 的确认，不能跳过 high 和 critical。

## 命令

| 命令 | 作用 |
|---|---|
| `shellmate ctx [--json]` | 显示发行版、内核、用户、磁盘、当前目录和项目标记 |
| `shellmate plan "..." [--json] [--offline\|--llm]` | 生成命令计划，不执行 |
| `shellmate run "..." [--yes] [--dry-run] [--llm]` | 评估、确认、执行并写审计日志 |
| `shellmate explain "命令" [--json]` | 逐段解释一条 shell 命令 |
| `shellmate history [--limit N] [--json]` | 查看历史记录 |
| `shellmate last` | 查看上一条计划 |
| `shellmate forget` | 清空历史 |
| `shellmate repl [--plan-only] [--llm]` | 进入交互式 REPL |

## 安全模型

| 级别 | 典型操作 | 动作 |
|---|---|---|
| safe / low | `ls`、`cat`、`df`、`ps`、只读 `find` | 直接执行 |
| medium | 删除单个文件、`chmod 777`、`sed -i`、`mv`、`cp` | 确认一次 |
| high | `rm -rf` 目录、`chmod -R 777`、`kill -9`、`apt remove` | 输入 `yes` |
| critical | `rm -rf /`、`mkfs`、`dd` 写块设备、fork bomb | 拒绝 |

规则会检查程序、参数和组合模式，例如递归删除、写入块设备、管道到 shell、命令替换和 `xargs rm`。多个片段取最高风险，原因只保留与最高级别对应的条目。

`--yes` 不能越过 high 和 critical。每次决策都会写入审计日志，包含时间、用户、命令、风险、动作、决策和退出码。

## 历史与指代

```bash
python3 -m shellmate plan "查看目录大小"   # du -sh .
python3 -m shellmate plan "按大小排序"     # du -sh . | sort -h
python3 -m shellmate plan "换成 /tmp"      # du -sh /tmp
python3 -m shellmate plan "再来一次"       # 重放上一条
```

时间过滤也支持：

```bash
python3 -m shellmate plan "找出 /home 下 7 天内修改的 .c 文件"
python3 -m shellmate plan "只要 3 天内的"
```

历史保存在 SQLite 中，默认路径是 `~/.local/state/shellmate/history.db`。

## DeepSeek（可选）

```bash
export SHELLMATE_API_KEY=你的Key
# 可选：export SHELLMATE_BASE_URL=https://api.deepseek.com
# 可选：export SHELLMATE_MODEL=deepseek-chat

python3 -m shellmate plan "统计 /home 各目录大小并按大小排序" --llm
```

也可以把 Key 写入 `~/.config/shellmate/config.json`，权限建议设为 600：

```json
{
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key": "你的Key",
  "timeout": 8.0
}
```

没有 Key、网络错误、超时或返回内容不合法时，ShellMate 会回退到离线解析，并在提示里说明原因。Key 不会写入代码仓库；使用 `--llm` 时，提示词会发送到配置的服务端。

## Shell 集成

```bash
source shellmate.sh
shm --version
shm plan "查看磁盘"
shm repl
```

- `Ctrl+G`：当前行非空时在行首加 `shm `，空行时插入 `shm repl`；
- 也可以直接用 `./bin/shm ...`，不依赖 `source`；
- REPL 支持 `/help`、`/history`、`/last`、`/exit`，行尾反斜杠可以续行，Ctrl+C 取消当前输入，Ctrl+D 退出。

## 演示

```bash
make demo
```

演示脚本在本地 state 目录中运行，不依赖 API Key，覆盖环境信息、自然语言生成、命令解释、历史指代、危险命令拒绝、高风险确认、构建清理和测试。

## 测试与评测

```bash
make test
python3 tools/eval.py
```

当前有 89 条单元测试、30 条离线解析评测、30 条危险命令样本和 10 条解释 golden。LLM 测试使用本地 HTTP mock，不访问真实网络。

## 目录

```text
shellmate/        CLI、上下文、解析、安全、执行、解释、记忆和 REPL
data/             意图库、命令知识、评测集和危险样本
tests/            单元测试与解释 golden
demo/             一键演示脚本
tools/eval.py     离线解析评测
bin/shm           可执行入口
shellmate.sh      bash 函数与 Ctrl+G 绑定
```

## 已知限制

- 离线规则覆盖 15 类操作，复杂或新奇的表达仍需要 LLM；
- 安全规则偏保守，个别正常命令也会要求确认；
- LLM 需要网络和额度，响应时间取决于服务端；
- 这是单用户命令行工具，没有图形界面和多用户隔离；
- 审计日志和历史数据库只保存在本机。

## License

MIT，版权归 Cac3C 所有。
