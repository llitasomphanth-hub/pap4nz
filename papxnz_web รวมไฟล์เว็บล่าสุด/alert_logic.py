from __future__ import annotations

# แจ้งเตือนแอดมิน / error / emergency
# ศูนย์กลางบันทึกปัญหา API / DB / route / payment / auth / setup ก่อนต่อ Telegram/email จริง

import json
import os
from pathlib import Path
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request

from db_logic import execute, fetch_all, fetch_one

ADMIN_ALERT_BOT_TOKEN_ENV = "ADMIN_ALERT_BOT_TOKEN"
ADMIN_ALERT_CHAT_ID_ENV = "ADMIN_ALERT_CHAT_ID"
_CONTEXT: dict[str, Any] = {}


def configure_alert_logic(*, db_path: str | Path | None = None, source: str = "") -> dict[str, Any]:
    """Wire alert/admin notification logic to the central DB context."""
    if db_path is not None:
        _CONTEXT["db_path"] = str(db_path)
    if source:
        _CONTEXT["source"] = source
    return dict(_CONTEXT)


def get_alert_context() -> dict[str, Any]:
    return dict(_CONTEXT)


def _clean(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _detail_text(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return _clean(detail, 4000)
    try:
        return json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str)[:4000]
    except Exception:
        return _clean(detail, 4000)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except Exception:
        return default


def _money_value(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _add_alert_column(column_name: str, column_sql: str) -> None:
    try:
        execute(f"ALTER TABLE alert_events ADD COLUMN {column_sql}")
    except Exception as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def ensure_alert_tables() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            level TEXT NOT NULL,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            detail TEXT,
            status TEXT NOT NULL DEFAULT 'open'
        )
        """
    )
    for column_name, column_sql in {
        "ref_key": "ref_key TEXT",
        "payment_ref": "payment_ref TEXT",
        "voucher_ref": "voucher_ref TEXT",
        "transaction_id": "transaction_id TEXT",
        "amount": "amount REAL DEFAULT 0.0",
        "reason": "reason TEXT",
        "failure_count": "failure_count INTEGER NOT NULL DEFAULT 1",
        "attempt_count": "attempt_count INTEGER NOT NULL DEFAULT 1",
        "retry_count": "retry_count INTEGER NOT NULL DEFAULT 0",
        "current_status": "current_status TEXT",
        "source_table": "source_table TEXT",
        "source_id": "source_id TEXT",
        "route": "route TEXT",
        "context": "context TEXT",
    }.items():
        _add_alert_column(column_name, column_sql)
    execute("CREATE INDEX IF NOT EXISTS idx_alert_events_created ON alert_events(created_at DESC)")
    execute("CREATE INDEX IF NOT EXISTS idx_alert_events_status ON alert_events(status, created_at DESC)")
    execute("CREATE INDEX IF NOT EXISTS idx_alert_events_type ON alert_events(event_type, created_at DESC)")
    execute("CREATE INDEX IF NOT EXISTS idx_alert_events_ref ON alert_events(ref_key, event_type, created_at DESC)")


def notify_admin(alert: dict[str, Any]) -> dict[str, Any]:
    """Placeholder for Telegram/email/admin push. DB recording is the active channel for now."""
    return {"ok": False, "status": "not_configured", "alert_id": alert.get("id", 0)}


def send_admin_alert(text: str) -> dict[str, Any]:
    token = os.environ.get(ADMIN_ALERT_BOT_TOKEN_ENV, "").strip()
    chat_id = os.environ.get(ADMIN_ALERT_CHAT_ID_ENV, "").strip()
    if not token or not chat_id:
        return {"ok": False, "status": "disabled", "message": "admin alert env not configured"}
    form = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": _clean(text, 3500),
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "papxnz-alert-logic/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", "replace")
            data = json.loads(raw) if raw else {}
            return {"ok": bool(data.get("ok")), "status": "sent" if data.get("ok") else "failed", "response": data}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = str(exc)
        return {"ok": False, "status": "failed", "message": body[:500] or f"telegram_http_{getattr(exc, 'code', '')}"}
    except Exception as exc:
        return {"ok": False, "status": "failed", "message": str(exc)[:500]}


def record_alert(
    level: str,
    source: str,
    event_type: str,
    message: str,
    detail: Any = None,
    *,
    ref_key: str = "",
    payment_ref: str = "",
    voucher_ref: str = "",
    transaction_id: str = "",
    amount: Any = 0,
    reason: str = "",
    failure_count: Any = 1,
    attempt_count: Any = 1,
    retry_count: Any = 0,
    current_status: str = "",
    source_table: str = "",
    source_id: str = "",
    route: str = "",
    context: Any = None,
) -> dict[str, Any]:
    ensure_alert_tables()
    result = execute(
        """
        INSERT INTO alert_events (
            level, source, event_type, message, detail, status,
            ref_key, payment_ref, voucher_ref, transaction_id, amount, reason,
            failure_count, attempt_count, retry_count, current_status,
            source_table, source_id, route, context
        )
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _clean(level, 40) or "error",
            _clean(source, 80) or _clean(_CONTEXT.get("source"), 80) or "unknown",
            _clean(event_type, 80) or "unknown",
            _clean(message, 1000) or "alert",
            _detail_text(detail),
            _clean(ref_key, 180),
            _clean(payment_ref, 180),
            _clean(voucher_ref, 180),
            _clean(transaction_id, 180),
            _money_value(amount),
            _clean(reason, 1000),
            max(1, _int_value(failure_count, 1)),
            max(1, _int_value(attempt_count, 1)),
            max(0, _int_value(retry_count, 0)),
            _clean(current_status, 80),
            _clean(source_table, 80),
            _clean(source_id, 180),
            _clean(route, 180),
            _detail_text(context),
        ),
    )
    alert = {
        "id": result["lastrowid"],
        "level": _clean(level, 40) or "error",
        "source": _clean(source, 80) or _clean(_CONTEXT.get("source"), 80) or "unknown",
        "event_type": _clean(event_type, 80) or "unknown",
        "message": _clean(message, 1000) or "alert",
        "ref_key": _clean(ref_key, 180),
        "failure_count": max(1, _int_value(failure_count, 1)),
        "current_status": _clean(current_status, 80),
    }
    notify_admin(alert)
    return alert


def record_payment_alert(
    *,
    level: str = "error",
    source: str = "decision_api",
    event_type: str = "payment_error",
    message: str,
    reason: str = "",
    payment_ref: str = "",
    voucher_ref: str = "",
    transaction_id: str = "",
    amount: Any = 0,
    current_status: str = "",
    source_table: str = "",
    source_id: str = "",
    route: str = "",
    can_retry: bool | None = None,
    attempt_count: Any = 0,
    retry_count: Any = 0,
    detail: Any = None,
) -> dict[str, Any]:
    ensure_alert_tables()
    ref_key = _clean(payment_ref or voucher_ref or transaction_id or source_id or route, 180)
    previous_count = 0
    if ref_key:
        row = fetch_one(
            """
            SELECT COALESCE(MAX(failure_count), 0) AS failure_count
            FROM alert_events
            WHERE ref_key=? AND event_type=?
            """,
            (ref_key, _clean(event_type, 80) or "payment_error"),
        )
        previous_count = _int_value(row["failure_count"] if row else 0)
    next_failure_count = previous_count + 1
    safe_attempt_count = max(_int_value(attempt_count), next_failure_count)
    safe_retry_count = max(_int_value(retry_count), max(0, next_failure_count - 1 if can_retry else 0))
    context = {
        "can_retry": can_retry,
        "detail": detail,
    }
    return record_alert(
        level,
        source,
        event_type,
        message,
        detail,
        ref_key=ref_key,
        payment_ref=payment_ref,
        voucher_ref=voucher_ref,
        transaction_id=transaction_id,
        amount=amount,
        reason=reason or message,
        failure_count=next_failure_count,
        attempt_count=safe_attempt_count,
        retry_count=safe_retry_count,
        current_status=current_status,
        source_table=source_table,
        source_id=source_id,
        route=route,
        context=context,
    )


def list_recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    ensure_alert_tables()
    safe_limit = max(1, min(int(limit or 50), 200))
    rows: Iterable[Any] = fetch_all(
        """
        SELECT
            id, created_at, level, source, event_type, message, detail, status,
            ref_key, payment_ref, voucher_ref, transaction_id, amount, reason,
            failure_count, attempt_count, retry_count, current_status,
            source_table, source_id, route, context
        FROM alert_events
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    return [dict(row) for row in rows]


def mark_alert_handled(alert_id: int) -> dict[str, int]:
    ensure_alert_tables()
    return execute(
        "UPDATE alert_events SET status='handled' WHERE id=?",
        (int(alert_id),),
    )
