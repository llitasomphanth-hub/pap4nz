"""Raw answer packet adapter. No business logic or message decisions."""
from __future__ import annotations

import json
import time
from typing import Any

from .db_logic import execute, fetch_one


def ensure_answer_packet_tables() -> None:
    execute("""CREATE TABLE IF NOT EXISTS frontend_answer_packets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        action TEXT NOT NULL DEFAULT '',
        user_key TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL,
        answer_json TEXT NOT NULL
    )""")


def build_answer_packet(*, action: str = "", payload: dict[str, Any] | None = None,
                        answer: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {"action": str(action or ""), "raw": payload or {}, "answer": answer or {}}


def record_answer_packet(*, action: str = "", payload: dict[str, Any] | None = None,
                         answer_packet: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    ensure_answer_packet_tables()
    data = payload if isinstance(payload, dict) else {}
    packet = answer_packet if isinstance(answer_packet, dict) else {}
    user_key = str(data.get("permanent_user_key") or data.get("user_id") or "")
    saved = execute("INSERT INTO frontend_answer_packets (created_at, action, user_key, payload_json, answer_json) VALUES (?, ?, ?, ?, ?)",
                    (int(time.time()), str(action or ""), user_key,
                     json.dumps(data, ensure_ascii=False, default=str),
                     json.dumps(packet, ensure_ascii=False, default=str)))
    return {"ok": True, "answer_packet_id": saved.get("lastrowid"), "source": "frontend_answer_packets", "answer_packet": packet}


def latest_answer_packet(*, action: str = "", session_id: str = "", user_id: str = "", **_: Any) -> dict[str, Any]:
    ensure_answer_packet_tables()
    row = fetch_one("SELECT * FROM frontend_answer_packets WHERE action=? ORDER BY id DESC LIMIT 1", (str(action or ""),))
    if not row:
        return {"ok": False, "code": "NOT_FOUND", "answer_packet": {}, "source": "frontend_answer_packets"}
    try:
        packet = json.loads(row.get("answer_json") or "{}")
    except Exception:
        packet = {"raw": row.get("answer_json")}
    return {"ok": True, "answer_packet": packet, "source": "frontend_answer_packets", "record": row}


__all__ = ["build_answer_packet", "ensure_answer_packet_tables", "record_answer_packet", "latest_answer_packet"]
