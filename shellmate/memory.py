"""SQLite 记忆：保存命令计划，并支持"再来一次/换路径/排序"等指代。"""

from __future__ import annotations

import getpass
import json
import re
import socket
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from shellmate.nlu.schema import CommandPlan
from shellmate.paths import history_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    cwd TEXT NOT NULL,
    host TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    raw_input TEXT NOT NULL,
    command TEXT NOT NULL,
    intent TEXT NOT NULL,
    slots TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    requires_root INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'unknown',
    executed INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    created_at TEXT NOT NULL
);
"""

AGAIN_WORDS = ("再来一次", "再执行一次", "重复上一条", "重复", "又一次", "again")
PATH_RE = re.compile(r"(?:换成|改为|换到)\s*(~/[^\s，。]+|/[^\s，。]+|\.)")
DAYS_RE = re.compile(r"(\d+)\s*(?:天|日)")
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGTkmgt])(?:[Bb])?")


def is_reference(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).strip()
    if any(word in normalized for word in AGAIN_WORDS):
        return True
    if "排序" in normalized and len(normalized) <= 20:
        return True
    path_match = PATH_RE.search(normalized)
    if path_match and path_match.start() == 0:
        return True
    if re.match(r"^(只要|只保留|只留|再)", normalized) and (
        "天内" in normalized or "大于" in normalized or "最近" in normalized
    ):
        return True
    return False


def _with_path(command: str, old: str | None, new: str) -> str:
    if old and old in command:
        return command.replace(old, new, 1)
    match = re.search(r"(~/[^\s]+|/[^\s]+)", command)
    if match:
        return command.replace(match.group(1), new, 1)
    return command


def _render_slots(intent: str, slots: dict) -> str | None:
    from shellmate.nlu.offline import render_from_intent

    return render_from_intent(intent, slots)


def resolve_reference(text: str, last: dict | None) -> CommandPlan | None:
    """把"再来一次/按大小排序/换成 /tmp/只要 3 天内的"补丁到上一条计划。"""
    if not last:
        return None

    normalized = unicodedata.normalize("NFKC", text)
    if not is_reference(normalized):
        return None

    command = last["command"]
    intent = last["intent"]
    slots = last.get("slots") or {}
    if isinstance(slots, str):
        try:
            slots = json.loads(slots)
        except json.JSONDecodeError:
            slots = {}
    slots = dict(slots)
    notes: list[str] = []
    changed = False

    if any(word in normalized for word in AGAIN_WORDS):
        notes.append("重放上一条命令")
        changed = True

    path_match = PATH_RE.search(normalized)
    if path_match:
        new_path = path_match.group(1)
        old_path = slots.get("path")
        slots["path"] = new_path
        if intent != "raw_command":
            rendered = _render_slots(intent, slots)
            if rendered:
                command = rendered
            else:
                command = _with_path(command, old_path, new_path)
        else:
            command = _with_path(command, old_path, new_path)
        notes.append(f"路径替换为 {new_path}")
        changed = True

    if "排序" in normalized:
        program = command.split()[0] if command.split() else ""
        if "sort" in command:
            notes.append("上一条命令已包含排序")
        elif program in ("du", "ls", "find", "ps", "sort"):
            command = command + " | sort -h"
            slots["sort"] = "size"
            notes.append("追加按大小排序")
        else:
            notes.append("上一条命令不支持排序")
        changed = True

    days_match = DAYS_RE.search(normalized)
    if days_match and ("天内" in normalized or "最近" in normalized):
        days = days_match.group(1)
        if intent == "recent_files" or "-mtime" in command:
            slots["days"] = days
            if intent == "recent_files":
                rendered = _render_slots(intent, slots)
                if rendered:
                    command = rendered
            else:
                command = re.sub(r"-mtime\s+-?\d+", f"-mtime -{days}", command)
            notes.append(f"时间过滤改为 {days} 天")
            changed = True
        else:
            notes.append("上一条命令不支持时间过滤")
            changed = True

    size_match = SIZE_RE.search(normalized)
    if size_match and "大于" in normalized:
        size = f"{size_match.group(1)}{size_match.group(2).upper()}"
        if intent == "large_files" or "-size" in command:
            slots["size"] = size
            if intent == "large_files":
                rendered = _render_slots(intent, slots)
                if rendered:
                    command = rendered
            else:
                command = re.sub(r"-size\s+\+?\S+", f"-size +{size}", command)
            notes.append(f"大小过滤改为 {size}")
            changed = True
        else:
            notes.append("上一条命令不支持大小过滤")
            changed = True

    if not changed:
        return None

    return CommandPlan(
        raw_input=text,
        command=command,
        intent=intent,
        slots=slots,
        confidence=0.95,
        source="memory",
        requires_root=bool(last.get("requires_root", False)),
        message="；".join(notes),
    )


class Memory:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else history_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.session_id = self._start_session()

    def _start_session(self) -> int:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "INSERT INTO sessions (started_at, cwd, host) VALUES (?, ?, ?)",
            (now, str(Path.cwd()), socket.gethostname()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def record(
        self,
        plan: CommandPlan,
        executed: bool = False,
        exit_code: int | None = None,
    ) -> int:
        risk_level = (plan.risk or {}).get("level", "unknown")
        cursor = self.conn.execute(
            """INSERT INTO commands
               (session_id, raw_input, command, intent, slots, confidence,
                source, requires_root, risk_level, executed, exit_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.session_id,
                plan.raw_input,
                plan.command,
                plan.intent,
                json.dumps(plan.slots, ensure_ascii=False),
                plan.confidence,
                plan.source,
                int(plan.requires_root),
                risk_level,
                int(executed),
                exit_code,
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def last(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM commands ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def history(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM commands ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def forget(self) -> int:
        cursor = self.conn.execute("DELETE FROM commands")
        self.conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self.conn.close()


def plan_from_row(row: dict) -> CommandPlan:
    slots = row.get("slots") or "{}"
    try:
        slots = json.loads(slots)
    except json.JSONDecodeError:
        slots = {}
    from shellmate.safety import ACTIONS

    level = row.get("risk_level", "unknown")
    return CommandPlan(
        raw_input=row["raw_input"],
        command=row["command"],
        intent=row["intent"],
        slots=slots,
        confidence=row["confidence"],
        source=row["source"],
        requires_root=bool(row.get("requires_root")),
        risk={"level": level, "action": ACTIONS.get(level, ""), "reasons": []},
        message="来自历史记录",
    )
