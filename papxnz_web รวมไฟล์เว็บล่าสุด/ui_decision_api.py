from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

UI_DECISION_DB = os.environ.get("UI_DECISION_DB", "/root/ui_decision.sqlite3")

router = APIRouter(prefix="/ui-api", tags=["ui-api"])


def configure_ui_decision_api(db_path: str | Path | None = None) -> dict[str, Any]:
    global UI_DECISION_DB
    if db_path:
        UI_DECISION_DB = str(db_path)
    _ensure_tables()
    return {"ok": True, "db_path": UI_DECISION_DB}


@router.get("/health")
def health() -> dict[str, Any]:
    _ensure_tables()
    return {"ok": True, "code": "READY", "message": "ui api ready", "db_path": UI_DECISION_DB}


@router.post("/answer")
async def answer(request: Request):
    payload = await request.json()
    result = build_answer(payload)
    event_id = record_answer(result)
    result["event_id"] = event_id
    result["ui"]["event_id"] = event_id
    return JSONResponse(status_code=result["http_status"], content=result)


@router.get("/answer/latest")
def latest_answer():
    item = get_latest_answer()
    if not item:
        return {"ok": True, "item": None, "ui": {"status": "empty", "amount": 0, "should_update_status": False}}
    return {"ok": True, "item": item, "ui": item["ui"]}


@router.get("/answer/events")
def answer_events(limit: int = 50):
    return {"ok": True, "items": list_answers(limit)}


# old names kept so existing frontend code does not break
@router.post("/payment-result")
async def payment_result(request: Request):
    return await answer(request)


@router.get("/payment-result/latest")
def latest_payment_result():
    return latest_answer()


@router.get("/payment-result/events")
def payment_result_events(limit: int = 50):
    return answer_events(limit)


def build_answer(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    status = _status(raw.get("status") or raw.get("code") or "received")
    amount = _money(raw.get("amount") or raw.get("paid_amount") or raw.get("received_amount") or 0)
    code, http_status, ok, message = _map_status(status)
    return _make_result(ok=ok, code=code, http_status=http_status, message=message, status=status, amount=amount, raw=raw)


def record_answer(result: dict[str, Any]) -> int:
    _ensure_tables()
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ui_answer_events (ts, source, status, amount, code, http_status, message, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            int(time.time()),
            str(raw.get("source") or "backend")[:120],
            str(result.get("status") or "received")[:80],
            _money(result.get("amount")),
            str(result.get("code") or "")[:80],
            int(result.get("http_status") or 200),
            str(result.get("message") or "")[:500],
            _json(raw),
        ),
    )
    event_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return event_id


def get_latest_answer() -> dict[str, Any] | None:
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ui_answer_events ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return _row(row) if row else None


def list_answers(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_tables()
    safe_limit = max(1, min(int(limit or 50), 200))
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ui_answer_events ORDER BY id DESC LIMIT ?", (safe_limit,))
    rows = cur.fetchall()
    conn.close()
    return [_row(row) for row in rows]


def _make_result(*, ok: bool, code: str, http_status: int, message: str, status: str, amount: float, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": ok,
        "http_status": http_status,
        "code": code,
        "status": status,
        "amount": amount,
        "message": message,
        "ui": {"status": status, "amount": amount, "should_update_status": True},
        "admin": {"status": status, "amount": amount, "title": message, "badge": code, "http_status": http_status},
        "data": {"status": status, "amount": amount},
        "raw": raw,
    }


def _map_status(status: str) -> tuple[str, int, bool, str]:
    if status in {"success", "paid", "accepted", "complete", "completed", "ok"}:
        return "SUCCESS", 200, True, "received amount"
    if status in {"used", "voucher_used", "already_used"}:
        return "USED", 409, False, "used"
    if status in {"not_found", "notfound", "missing"}:
        return "NOT_FOUND", 404, False, "not found"
    if status in {"invalid", "invalid_link", "bad_link"}:
        return "INVALID_LINK", 400, False, "invalid link"
    if status in {"server_error", "api_error", "error_500"}:
        return "SERVER_ERROR", 500, False, "server error"
    if status in {"forbidden", "error_403"}:
        return "FORBIDDEN", 403, False, "forbidden"
    if status in {"rate_limited", "rate_limit", "error_429"}:
        return "RATE_LIMITED", 429, False, "rate limited"
    if status in {"unauthorized", "error_401"}:
        return "UNAUTHORIZED", 401, False, "unauthorized"
    return "RECEIVED", 200, True, "received"


def _row(row: sqlite3.Row) -> dict[str, Any]:
    status = str(row["status"] or "")
    amount = _money(row["amount"])
    return {
        "id": int(row["id"]),
        "ts": int(row["ts"] or 0),
        "source": str(row["source"] or ""),
        "status": status,
        "amount": amount,
        "code": str(row["code"] or ""),
        "http_status": int(row["http_status"] or 200),
        "message": str(row["message"] or ""),
        "ui": {"event_id": int(row["id"]), "status": status, "amount": amount, "should_update_status": True},
        "admin": {"status": status, "amount": amount, "title": str(row["message"] or ""), "badge": str(row["code"] or ""), "http_status": int(row["http_status"] or 200)},
        "raw": _loads(row["raw_payload"]),
    }


def _ensure_tables() -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ui_answer_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, source TEXT, status TEXT NOT NULL DEFAULT 'received', amount REAL NOT NULL DEFAULT 0.0, code TEXT, http_status INTEGER NOT NULL DEFAULT 200, message TEXT, raw_payload TEXT)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ui_answer_events_ts ON ui_answer_events(ts DESC)")
    conn.commit()
    conn.close()


def _conn() -> sqlite3.Connection:
    db_path = Path(UI_DECISION_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def _status(value: Any) -> str:
    return str(value or "received").strip().lower().replace("-", "_").replace(" ", "_")


def _money(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _json(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)[:8000]
    except Exception:
        return "{}"


def _loads(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {"value": data}
    except Exception:
        return {}
