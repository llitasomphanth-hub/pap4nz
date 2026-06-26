from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# ตัวนี้เป็น DB ใหม่ของโฟลว UI เท่านั้น ไม่ไปยุ่ง DB การเงินเก่า
UI_DECISION_DB = os.environ.get("UI_DECISION_DB", "/root/ui_decision.sqlite3")

router = APIRouter(prefix="/ui-api", tags=["ui-api"])


def configure_ui_decision_api(db_path: str | Path | None = None) -> dict[str, Any]:
    """ให้ webapp หลักเรียกตั้งค่า DB ได้ ถ้าอยากใช้ path เดียวกับระบบเว็บใหม่"""
    global UI_DECISION_DB
    if db_path:
        UI_DECISION_DB = str(db_path)
    _ensure_tables()
    return {"ok": True, "db_path": UI_DECISION_DB}


@router.get("/health")
def ui_decision_health() -> dict[str, Any]:
    _ensure_tables()
    return {
        "ok": True,
        "code": "UI_DECISION_READY",
        "message": "ui decision api พร้อมตอบแล้ว",
        "db_path": UI_DECISION_DB,
    }


@router.post("/payment-result")
async def payment_result(request: Request):
    payload = await request.json()
    result = build_ui_payment_result(payload)
    event_id = record_ui_payment_event(result)
    result["event_id"] = event_id
    result["ui"]["event_id"] = event_id
    return JSONResponse(status_code=result["http_status"], content=result)


@router.get("/payment-result/latest")
def latest_payment_result():
    item = get_latest_ui_payment_event()
    if not item:
        return {
            "ok": True,
            "code": "EMPTY",
            "message": "ยังไม่มีข้อมูล payment-result",
            "item": None,
            "ui": {
                "amount": 0,
                "status": "empty",
                "payment_status": "empty",
                "should_update_balance": False,
                "should_update_status": False,
            },
        }
    return {"ok": True, "item": item, "ui": item.get("ui", {})}


@router.get("/payment-result/events")
def list_payment_result_events(limit: int = 50):
    return {
        "ok": True,
        "items": list_ui_payment_events(limit=limit),
    }


def build_ui_payment_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}

    status = _normalize_status(data.get("status") or data.get("code") or data.get("payment_status") or "")
    amount = _money(data.get("amount") or data.get("paid_amount") or data.get("received_amount") or 0)

    if status in {"success", "paid", "accepted", "complete", "completed", "ok"}:
        return _make_result(
            ok=True,
            code="SUCCESS",
            http_status=200,
            message="ชำระเงินสำเร็จ",
            status="success",
            amount=amount,
            raw=data,
        )

    if status in {"used", "voucher_used", "already_used"}:
        return _make_result(
            ok=False,
            code="USED",
            http_status=409,
            message="ซองถูกใช้แล้ว",
            status="used",
            amount=amount,
            raw=data,
        )

    if status in {"not_found", "notfound", "missing"}:
        return _make_result(
            ok=False,
            code="NOT_FOUND",
            http_status=404,
            message="ไม่พบซองในระบบ",
            status="not_found",
            amount=amount,
            raw=data,
        )

    if status in {"invalid", "invalid_link", "bad_link"}:
        return _make_result(
            ok=False,
            code="INVALID_LINK",
            http_status=400,
            message="ลิงก์ไม่ถูก",
            status="invalid_link",
            amount=amount,
            raw=data,
        )

    if status in {"server_error", "api_error", "error_500"}:
        return _make_result(
            ok=False,
            code="SERVER_ERROR",
            http_status=500,
            message="ระบบปลายทางผิดพลาด",
            status="server_error",
            amount=amount,
            raw=data,
            can_retry=True,
        )

    if status in {"forbidden", "error_403"}:
        return _make_result(
            ok=False,
            code="FORBIDDEN",
            http_status=403,
            message="ไม่มีสิทธิ์เข้าถึง",
            status="forbidden",
            amount=amount,
            raw=data,
        )

    if status in {"rate_limited", "rate_limit", "error_429"}:
        return _make_result(
            ok=False,
            code="RATE_LIMITED",
            http_status=429,
            message="ยิงถี่เกินไป",
            status="rate_limited",
            amount=amount,
            raw=data,
            can_retry=True,
        )

    if status in {"unauthorized", "error_401"}:
        return _make_result(
            ok=False,
            code="UNAUTHORIZED",
            http_status=401,
            message="ยืนยันตัวตนไม่ผ่าน",
            status="unauthorized",
            amount=amount,
            raw=data,
        )

    return _make_result(
        ok=True,
        code="RECEIVED",
        http_status=200,
        message="ตัวกลางรับข้อมูลแล้ว",
        status="received",
        amount=amount,
        raw=data,
    )


def record_ui_payment_event(result: dict[str, Any]) -> int:
    """บันทึก event ใหม่ให้หลังบ้านดึงไปโชว์ได้ทันที"""
    _ensure_tables()
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    ui = result.get("ui") if isinstance(result.get("ui"), dict) else {}
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ui_payment_events (
            ts, source, status, amount, code, http_status, message,
            should_update_balance, should_update_status, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(time.time()),
            _text(raw.get("source") or raw.get("caller") or "frontend", 120),
            _text(ui.get("status") or result.get("status"), 80),
            _money(ui.get("amount") or data.get("amount") or 0),
            _text(result.get("code"), 80),
            int(result.get("http_status") or 200),
            _text(result.get("message"), 500),
            1 if ui.get("should_update_balance") else 0,
            1 if ui.get("should_update_status") else 0,
            _json(raw),
        ),
    )
    event_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return event_id


def get_latest_ui_payment_event() -> dict[str, Any] | None:
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ui_payment_events ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return _event_row(row) if row else None


def list_ui_payment_events(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_tables()
    safe_limit = max(1, min(int(limit or 50), 200))
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ui_payment_events ORDER BY id DESC LIMIT ?", (safe_limit,))
    rows = cur.fetchall()
    conn.close()
    return [_event_row(row) for row in rows]


def _make_result(
    *,
    ok: bool,
    code: str,
    http_status: int,
    message: str,
    status: str,
    amount: float,
    raw: dict[str, Any],
    can_retry: bool = False,
) -> dict[str, Any]:
    # amount/status คือข้อมูลเดียวกันที่เว็บหลักใช้
    # display/admin แยกไว้เพื่อหลังบ้านโชว์คนละแบบได้
    return {
        "ok": ok,
        "http_status": http_status,
        "code": code,
        "status": status,
        "amount": amount,
        "message": message,
        "ui": {
            "status": status,
            "amount": amount,
            "payment_status": status,
            "should_update_balance": ok and status == "success",
            "should_update_status": True,
        },
        "admin": {
            "title": message,
            "badge": code,
            "level": "success" if ok and status == "success" else ("warning" if status == "received" else "error"),
            "status": status,
            "amount": amount,
            "http_status": http_status,
        },
        "data": {
            "status": status,
            "amount": amount,
        },
        "action": {
            "can_retry": can_retry,
            "can_replay": can_retry,
            "next": "",
        },
        "raw": raw,
    }


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    status = str(row["status"] or "")
    amount = _money(row["amount"])
    code = str(row["code"] or "")
    http_status = int(row["http_status"] or 200)
    message = str(row["message"] or "")
    raw_payload = _loads(row["raw_payload"])
    return {
        "id": int(row["id"]),
        "ts": int(row["ts"] or 0),
        "source": str(row["source"] or ""),
        "status": status,
        "amount": amount,
        "code": code,
        "http_status": http_status,
        "message": message,
        "ui": {
            "event_id": int(row["id"]),
            "status": status,
            "amount": amount,
            "payment_status": status,
            "should_update_balance": bool(row["should_update_balance"]),
            "should_update_status": bool(row["should_update_status"]),
        },
        "admin": {
            "title": message,
            "badge": code,
            "level": "success" if status == "success" else ("warning" if status == "received" else "error"),
            "status": status,
            "amount": amount,
            "http_status": http_status,
        },
        "raw": raw_payload,
    }


def _ensure_tables() -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_payment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            source TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            amount REAL NOT NULL DEFAULT 0.0,
            code TEXT,
            http_status INTEGER NOT NULL DEFAULT 200,
            message TEXT,
            should_update_balance INTEGER NOT NULL DEFAULT 0,
            should_update_status INTEGER NOT NULL DEFAULT 1,
            raw_payload TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ui_payment_events_ts ON ui_payment_events(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ui_payment_events_status ON ui_payment_events(status)")
    conn.commit()
    conn.close()


def _conn() -> sqlite3.Connection:
    db_path = Path(UI_DECISION_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _money(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


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
