"""CommandPlan：解析结果的统一数据结构。

离线规则、后续的 LLM 后端和记忆补丁都产出同一个结构，便于测试、序列化和
安全引擎统一处理。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class CommandPlan:
    raw_input: str
    command: str
    intent: str
    slots: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "offline"
    requires_root: bool = False
    risk: dict = field(default_factory=lambda: {"level": "unknown", "reasons": []})
    explain: list = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
