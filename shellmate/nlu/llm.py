"""DeepSeek / OpenAI 兼容后端的命令生成。

设计要点：
- 只负责"自然语言 -> CommandPlan"，不信任模型输出：结果必须再过 safety.assess；
- 无 Key、网络错误、超时、JSON 不合法时抛 LLMError，由 CLI 回退离线解析；
- 提示词注入本机上下文（发行版、内核、用户、cwd、项目标记），减少瞎编路径。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from shellmate.config import Config, load_config
from shellmate.context import collect_context
from shellmate.nlu.schema import CommandPlan
from shellmate.safety import assess


class LLMError(RuntimeError):
    """LLM 不可用或输出不合法。"""


SYSTEM_PROMPT = """你是 ShellMate，一名 Linux 命令行助手。
把用户的中文需求转换成一条可执行的 bash 命令。

只输出一个 JSON 对象，不要 markdown，不要额外文字。字段：
- command: string，单条 bash 命令
- intent: string，简短的英文标识
- slots: object，命令中用到的参数（值必须是字符串）
- confidence: number，0 到 1
- requires_root: boolean
- explanation: string，一句中文说明

规则：
1. 只生成只读或低风险命令；禁止 rm -rf /、mkfs、dd 写块设备等破坏性命令。
2. 不确定时降低 confidence，并在 explanation 中说明。
3. 不要使用 sudo，除非用户明确要求。
4. 命令必须能在 bash 中直接执行。

本机上下文：
{context}
"""

CONTEXT_LIMIT = 900


def build_context_summary(ctx: dict | None = None) -> str:
    ctx = ctx if ctx is not None else collect_context()
    distro = ctx.get("distro", {}).get("pretty", "unknown")
    entries = [
        entry["name"] + ("/" if entry.get("type") == "dir" else "")
        for entry in ctx.get("entries", [])[:8]
    ]
    markers = ctx.get("project", {}).get("markers", [])
    lines = [
        f"用户 {ctx.get('user')}@{ctx.get('hostname')}，{distro}，内核 {ctx.get('kernel')}",
        f"当前目录 {ctx.get('cwd')}",
        f"目录前几项：{', '.join(entries) or '无'}",
        f"项目标记：{', '.join(markers) or '无'}",
    ]
    text = "\n".join(lines)
    return text[:CONTEXT_LIMIT]


def build_messages(text: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        {"role": "user", "content": text},
    ]


def _post(config: Config, messages: list[dict], timeout: float) -> str:
    url = config.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 512,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:160]
        exc.close()
        raise LLMError(f"HTTP {exc.code}：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"网络错误：{exc}") from exc

    try:
        data = json.loads(body)
        return data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("接口返回格式不符合预期") from exc


def _extract_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("模型没有返回 JSON 对象")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMError("模型返回的不是 JSON 对象")
    return data


def _to_plan(text: str, data: dict) -> CommandPlan:
    command = data.get("command", "")
    if not isinstance(command, str) or not command.strip():
        raise LLMError("模型输出缺少 command")

    slots = data.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}
    slots = {str(key): str(value) for key, value in slots.items()}

    try:
        confidence = float(data.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    explanation = data.get("explanation", "")
    if not isinstance(explanation, str):
        explanation = str(explanation)

    plan = CommandPlan(
        raw_input=text,
        command=command.strip(),
        intent=str(data.get("intent") or "llm_command"),
        slots=slots,
        confidence=confidence,
        source="llm",
        requires_root=bool(data.get("requires_root", False)),
        message=explanation,
    )
    # 不信任模型：LLM 生成的命令同样要过本地安全引擎。
    plan.risk = assess(plan.command, plan.requires_root).to_dict()
    return plan


def parse_with_llm(
    text: str,
    config: Config | None = None,
    context: dict | None = None,
    retries: int = 1,
) -> CommandPlan:
    config = config if config is not None else load_config()
    if not config.api_key:
        raise LLMError("未配置 API Key")

    messages = build_messages(text, build_context_summary(context))
    last_error: LLMError | None = None
    content = ""

    for attempt in range(retries + 1):
        try:
            content = _post(config, messages, config.timeout)
            return _to_plan(text, _extract_json(content))
        except LLMError as exc:
            last_error = exc
            if attempt < retries:
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "上一次输出不合法。请只输出一个 JSON 对象，必须包含非空 command 字段。",
                })

    raise last_error or LLMError("LLM 调用失败")
