from __future__ import annotations

# อ่านเขียน DB กลาง
# ใช้ DB_PATH เดิมจาก CHAT_DB หรือ fallback เดิมของ webapp.py ห้ามสร้างฐานข้อมูลใหม่เอง

import os
import sqlite3
from pathlib import Path
from typing import Any, Sequence

DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")
_CONTEXT: dict[str, Any] = {}


def configure_db_logic(*, db_path: str | Path | None = None, source: str = "") -> dict[str, Any]:
    """Configure the shared SQLite path used by all logic modules."""
    global DB_PATH
    if db_path is not None:
        DB_PATH = str(db_path)
    _CONTEXT["db_path"] = DB_PATH
    if source:
        _CONTEXT["source"] = source
    return dict(_CONTEXT)


def get_db_context() -> dict[str, Any]:
    _CONTEXT.setdefault("db_path", DB_PATH)
    return dict(_CONTEXT)


def get_conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the central SQLite DB with sqlite3.Row for column-name access."""
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    conn = get_conn()
    try:
        return conn.execute(sql, tuple(params)).fetchone()
    finally:
        conn.close()


def fetch_all(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    conn = get_conn()
    try:
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def execute(sql: str, params: Sequence[Any] = ()) -> dict[str, int]:
    conn = get_conn()
    try:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return {"rowcount": int(cur.rowcount), "lastrowid": int(cur.lastrowid or 0)}
    finally:
        conn.close()
