from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from alert_logic import configure_alert_logic, record_payment_alert, send_admin_alert as _send_admin_alert
from db_logic import configure_db_logic
from frontend_status_v import source_flow_status

SAFE_REF_RE = re.compile(r"^[A-Za-z0-9_.:/?&=+\-@%]{1,320}$")
TRUEMONEY_BALANCE_API_URL = "https://apis.truemoneyservices.com/account/v1/balance"
TRUEMONEY_MONEY_RECEIVE_API_URL = os.environ.get("TRUEMONEY_MONEY_RECEIVE_API_URL", "")
TRUEMONEY_BALANCE_TOKEN_ENV = "TRUEMONEY_BALANCE_TOKEN"
TRUEMONEY_VOUCHER_API_URL = os.environ.get("TRUEMONEY_VOUCHER_API_URL", "https://www.planariashop.com/api/truewallet.php")
TRUEMONEY_VOUCHER_API_KEY_ENV = "TRUEMONEY_VOUCHER_API_KEY"
TRUEMONEY_VOUCHER_PHONE_ENV = "TRUEMONEY_VOUCHER_PHONE"
DB_PATH: str | None = None

router = APIRouter(prefix="/decision-api", tags=["decision-api"])


def configure_decision_api(db_path: str | Path) -> None:
    global DB_PATH
    DB_PATH = str(db_path)
    _configure_logic_modules(DB_PATH, source="decision_api")


def _configure_logic_modules(db_path: str | Path, *, source: str) -> None:
    configure_db_logic(db_path=db_path, source=source)
    configure_alert_logic(db_path=db_path, source=source)


def _conn() -> sqlite3.Connection:
    if not DB_PATH:
        raise HTTPException(status_code=500, detail="decision_api_db_not_configured")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row is not None else {}


def _has_table(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table_name,))
    return cur.fetchone() is not None


def _columns(cur: sqlite3.Cursor, table_name: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cur.fetchall()}


def _add_column_if_missing(cur: sqlite3.Cursor, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _columns(cur, table_name):
        return
    try:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
    except Exception:
        pass


def _safe_cols(cur: sqlite3.Cursor, table_name: str, cols: list[str]) -> str:
    existing = _columns(cur, table_name)
    return ", ".join(col if col in existing else f"NULL AS {col}" for col in cols)


def _clean(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_ref(value: Any) -> str:
    ref = _clean(value)
    if ref and not SAFE_REF_RE.match(ref):
        raise HTTPException(status_code=400, detail="invalid_ref")
    return ref


def _client_ip(request: Request, payload: dict[str, Any]) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return _clean(payload.get("ip") or forwarded or (request.client.host if request.client else ""), 80)


def _payload_json(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:4000]
    except Exception:
        return "{}"


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(term in key_text for term in ("token", "authorization", "secret", "password", "keyapi", "api_key", "wallet_api_key")):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _decision_logic_payload(status: str, reason: str, api: dict[str, Any] | None = None, system_server: dict[str, Any] | None = None) -> dict[str, Any]:
    case = _clean(status, 40).lower() or "error"
    if case in ("approved", "approve"):
        case = "approved"
    elif case in ("rejected", "reject"):
        case = "rejected"
    elif case == "success":
        case = "success"
    elif case in ("paid", "complete", "completed", "ok"):
        case = "success"
    else:
        case = "error"

    payload: dict[str, Any] = {
        "case": case,
        "reason": _clean(reason or case, 500),
    }
    if case == "success":
        payload["api"] = api or {}
    elif case == "error":
        payload["api"] = api or {}
        payload["system_server"] = system_server or {}
    else:
        payload["system_server"] = system_server or {}
    return payload


def _raw_hash(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()


def _ids_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    slip_raw = payload.get("slip_raw") or payload.get("image_raw") or payload.get("image_base64") or ""
    return {
        "payment_ref": _safe_ref(payload.get("payment_ref") or payload.get("attempt_id") or payload.get("ref_id")),
        "voucher_url": _safe_ref(payload.get("voucher_url") or payload.get("voucher_link") or payload.get("link")),
        "voucher_ref": _safe_ref(payload.get("voucher_ref") or payload.get("voucher") or payload.get("v")),
        "transaction_id": _safe_ref(payload.get("transaction_id") or payload.get("reference_id") or payload.get("trans_id")),
        "session_id": _safe_ref(payload.get("session_id")),
        "username": _clean(payload.get("username") or payload.get("login"), 120),
        "user_id": _clean(payload.get("user_id") or payload.get("chat_id") or payload.get("telegram_id"), 80),
        "package_id": _clean(payload.get("package_id") or payload.get("package"), 40),
        "amount": _clean(payload.get("amount") or payload.get("expected_amount") or payload.get("paid_amount"), 80),
        "invite_link": _safe_ref(payload.get("invite_link") or payload.get("group_link")),
        "slip_hash": _raw_hash(slip_raw),
    }


def _status_from_record(record: dict[str, Any]) -> tuple[str, str, bool]:
    text = " ".join(
        str(record.get(key) or "")
        for key in ("status", "source_status", "detail", "note", "link_status", "join_status", "join_match_status")
    ).lower()
    if any(term in text for term in ("joined", "approved", "success", "paid", "completed", "complete", "issued")):
        return "success", "record is approved/successful", True
    if any(term in text for term in ("rejected", "invalid", "failed", "api_error", "error", "amount_mismatch", "duplicate", "insufficient", "used_voucher", "voucher_used")):
        return "err", "record needs review or failed", False
    return "pending", "waiting for matching payment/group evidence", False


def _ensure_decision_tables(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            mode TEXT,
            payment_ref TEXT,
            voucher_ref TEXT,
            transaction_id TEXT,
            session_id TEXT,
            username TEXT,
            user_id TEXT,
            package_id TEXT,
            invite_link TEXT,
            slip_hash TEXT,
            status TEXT,
            request_ip TEXT,
            raw_payload TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_checks_ts ON decision_checks(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_checks_ref ON decision_checks(payment_ref, voucher_ref, transaction_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_checks_hash ON decision_checks(slip_hash)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_error_payment_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender TEXT,
            url TEXT,
            v TEXT UNIQUE,
            amount REAL DEFAULT 0.0,
            raw_result TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT (strftime('%s','now')),
            reviewed_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_admin_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            source TEXT,
            source_id TEXT,
            review_id INTEGER,
            payment_ref TEXT,
            voucher_ref TEXT,
            truemoney_url TEXT,
            amount REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'pending',
            decision_status TEXT,
            reviewed_at INTEGER,
            raw_payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_review_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            review_id INTEGER,
            bridge_id INTEGER,
            action TEXT,
            actor TEXT,
            amount REAL DEFAULT 0.0,
            status TEXT,
            tier_id INTEGER,
            group_id TEXT,
            invite_link TEXT,
            bot_status TEXT,
            bot_error TEXT,
            send_status TEXT,
            send_error TEXT,
            can_retry INTEGER NOT NULL DEFAULT 1,
            raw_payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS system_error_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            source TEXT,
            source_event TEXT,
            source_id TEXT,
            payment_ref TEXT,
            voucher_ref TEXT,
            voucher_url TEXT,
            transaction_id TEXT,
            amount REAL DEFAULT 0.0,
            reported_ts INTEGER,
            match_status TEXT,
            matched_table TEXT,
            matched_id TEXT,
            matched_status TEXT,
            time_delta INTEGER,
            status TEXT,
            admin_review_id INTEGER,
            raw_payload TEXT,
            match_payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS money_in_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            source TEXT,
            source_event TEXT,
            source_id TEXT,
            payment_ref TEXT,
            voucher_ref TEXT,
            voucher_url TEXT,
            transaction_id TEXT,
            amount REAL DEFAULT 0.0,
            sender TEXT,
            sender_mobile TEXT,
            account_ref TEXT,
            verify_ok INTEGER NOT NULL DEFAULT 0,
            match_status TEXT,
            matched_table TEXT,
            matched_id TEXT,
            time_delta INTEGER DEFAULT 0,
            status TEXT,
            raw_payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_balance_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            api_url TEXT,
            request_ip TEXT,
            http_status INTEGER,
            ok INTEGER NOT NULL DEFAULT 0,
            balance REAL,
            previous_balance REAL,
            balance_delta REAL DEFAULT 0.0,
            status TEXT,
            message TEXT,
            money_log_id INTEGER,
            raw_payload TEXT
        )
        """
    )
    for column_name, column_sql in {
        "expected_amount": "expected_amount REAL DEFAULT 0.0",
        "purchase_state": "purchase_state TEXT",
        "can_send_link": "can_send_link INTEGER NOT NULL DEFAULT 0",
        "route_group_id": "route_group_id TEXT",
    }.items():
        _add_column_if_missing(cur, "api_balance_checks", column_name, column_sql)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_balance (
            user_id INTEGER PRIMARY KEY,
            total REAL NOT NULL DEFAULT 0.0,
            source TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            raw_payload TEXT
        )
        """
    )
    for column_name, column_sql in {
        "total": "total REAL NOT NULL DEFAULT 0.0",
        "source": "source TEXT",
        "updated_at": "updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))",
        "raw_payload": "raw_payload TEXT",
    }.items():
        _add_column_if_missing(cur, "user_balance", column_name, column_sql)
    for column_name, column_sql in {
        "balance_passed": "balance_passed INTEGER NOT NULL DEFAULT 0",
        "send_link_state": "send_link_state TEXT",
    }.items():
        _add_column_if_missing(cur, "api_balance_checks", column_name, column_sql)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_voucher_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            api_url TEXT,
            request_ip TEXT,
            http_status INTEGER,
            ok INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            message TEXT,
            amount REAL DEFAULT 0.0,
            transaction_id TEXT,
            sender TEXT,
            sender_mobile TEXT,
            voucher_ref TEXT,
            voucher_url TEXT,
            money_log_id INTEGER,
            source_payload TEXT,
            raw_payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_money_receive_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            api_url TEXT,
            request_ip TEXT,
            http_status INTEGER,
            ok INTEGER NOT NULL DEFAULT 0,
            event_type TEXT,
            amount REAL DEFAULT 0.0,
            sender_mobile TEXT,
            receiver_mobile TEXT,
            received_time TEXT,
            transaction_id TEXT,
            message TEXT,
            status TEXT,
            money_log_id INTEGER,
            raw_payload TEXT
        )
        """
    )
    _add_column_if_missing(cur, "api_voucher_checks", "source_payload", "source_payload TEXT")
    _add_column_if_missing(cur, "api_money_receive_logs", "money_log_id", "money_log_id INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_admin_reviews_source ON decision_admin_reviews(source, source_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_admin_reviews_status ON decision_admin_reviews(status, ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_review_checks_review ON admin_review_checks(review_id, ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_review_checks_ts ON admin_review_checks(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_system_error_cases_ref ON system_error_cases(payment_ref, voucher_ref, transaction_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_system_error_cases_ts ON system_error_cases(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_money_in_ledger_ref ON money_in_ledger(payment_ref, voucher_ref, transaction_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_money_in_ledger_amount_ts ON money_in_ledger(amount, ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_money_in_ledger_ts ON money_in_ledger(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_balance_checks_ts ON api_balance_checks(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_balance_checks_status ON api_balance_checks(status, ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_voucher_checks_ts ON api_voucher_checks(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_voucher_checks_status ON api_voucher_checks(status, ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_voucher_checks_ref ON api_voucher_checks(voucher_ref, transaction_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_money_receive_logs_ts ON api_money_receive_logs(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_money_receive_logs_tx ON api_money_receive_logs(transaction_id)")
    cur.execute(
        """
        DELETE FROM api_balance_checks
        WHERE COALESCE(money_log_id, 0)=0
          AND (
              lower(COALESCE(api_url, '')) LIKE '%voucher%'
              OR lower(COALESCE(api_url, '')) LIKE '%truewallet%'
          )
        """
    )


def _slip_hash_context(cur: sqlite3.Cursor, ids: dict[str, str]) -> dict[str, Any]:
    slip_hash = ids.get("slip_hash") or ""
    if not slip_hash:
        return {"provided": False, "seen_before": False, "matches": []}
    _ensure_decision_tables(cur)
    cur.execute(
        """
        SELECT id, ts, mode, payment_ref, voucher_ref, transaction_id, status, request_ip
        FROM decision_checks
        WHERE slip_hash=?
        ORDER BY ts DESC
        LIMIT 8
        """,
        (slip_hash,),
    )
    matches = [_row_dict(row) for row in cur.fetchall()]
    return {
        "provided": True,
        "hash": slip_hash,
        "seen_before": bool(matches),
        "match_count": len(matches),
        "matches": matches,
    }


def _voucher_ref_from_url(url: str) -> str:
    match = re.search(r"[?&]v=([^&\s]+)", str(url or ""))
    return _clean(match.group(1) if match else "", 160)


def _review_user_id(value: Any) -> int:
    try:
        return int(str(value or "0").strip() or 0)
    except Exception:
        return 0


def _review_amount(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _extract_balance_value(value: Any) -> float:
    balance_keys = {
        "balance",
        "available_balance",
        "availablebalance",
        "current_balance",
        "currentbalance",
        "wallet_balance",
        "walletbalance",
        "total_balance",
        "totalbalance",
        "amount",
    }

    def walk(item: Any) -> float:
        if isinstance(item, dict):
            for key, nested in item.items():
                if str(key).replace("-", "_").lower() in balance_keys:
                    amount = _review_amount(nested)
                    if amount > 0:
                        return amount
            for nested in item.values():
                amount = walk(nested)
                if amount > 0:
                    return amount
        elif isinstance(item, list):
            for nested in item:
                amount = walk(nested)
                if amount > 0:
                    return amount
        return 0.0

    return walk(value)


def _api_token_from_request(request: Request, payload: dict[str, Any]) -> str:
    header_auth = request.headers.get("authorization", "").strip()
    if header_auth.lower().startswith("bearer "):
        header_auth = header_auth[7:].strip()
    elif header_auth.lower().startswith("token "):
        header_auth = header_auth[6:].strip()
    return _clean(
        payload.get("token")
        or payload.get("api_token")
        or request.headers.get("x-truemoney-token")
        or request.headers.get("token")
        or header_auth
        or os.environ.get(TRUEMONEY_BALANCE_TOKEN_ENV, ""),
        500,
    )


def _voucher_api_credentials(payload: dict[str, Any]) -> tuple[str, str]:
    api_key = str(
        payload.get("keyapi")
        or payload.get("api_key")
        or payload.get("wallet_api_key")
        or os.environ.get(TRUEMONEY_VOUCHER_API_KEY_ENV)
        or os.environ.get("API_KEY")
        or ""
    ).strip()
    phone = str(
        payload.get("phone")
        or payload.get("phone_number")
        or payload.get("wallet_phone")
        or os.environ.get(TRUEMONEY_VOUCHER_PHONE_ENV)
        or os.environ.get("PHONE_NUMBER")
        or ""
    ).strip()
    return api_key, phone


def _deep_find(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).replace("-", "_").lower() in keys and item not in (None, ""):
                return item
        for item in value.values():
            found = _deep_find(item, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find(item, keys)
            if found not in (None, ""):
                return found
    return None


def _voucher_api_amount(raw_response: dict[str, Any]) -> float:
    return _review_amount(_deep_find(raw_response, {"amount", "received_amount", "paid_amount", "transfer_amount", "value"}))


def _voucher_api_transaction_id(raw_response: dict[str, Any], fallback: str = "") -> str:
    return _clean(
        _deep_find(raw_response, {"transaction_id", "transactionid", "reference_id", "referenceid", "trans_id", "transid", "txn_id", "txid"})
        or fallback,
        180,
    )


def _voucher_api_sender(raw_response: dict[str, Any]) -> tuple[str, str]:
    sender = _clean(
        _deep_find(raw_response, {"sender_name", "sender", "payer_name", "owner_profile", "redeemer_profile", "name", "fullname"})
        or "",
        160,
    )
    mobile = _clean(
        _deep_find(raw_response, {"sender_mobile", "payer_mobile", "mobile", "mobile_no", "phone", "phone_number"})
        or "",
        80,
    )
    return sender, mobile


def _call_truemoney_balance_api(token: str) -> dict[str, Any]:
    if not token:
        return {"ok": False, "status": "api_error", "http_status": 0, "message": "truemoney balance token missing"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Token": token,
        "User-Agent": "papxnz-decision-api/1.0",
        "Accept": "application/json",
    }
    request = urllib.request.Request(TRUEMONEY_BALANCE_API_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8", "replace")
            http_status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = str(exc)
        return {
            "ok": False,
            "status": "api_error",
            "http_status": int(getattr(exc, "code", 0) or 0),
            "message": f"truemoney balance api http error {getattr(exc, 'code', '')}".strip(),
            "raw_response": raw[:4000],
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "api_error",
            "http_status": 0,
            "message": f"truemoney balance api network error: {str(exc)[:300]}",
        }
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {"raw": raw[:4000]}
    balance = _extract_balance_value(data)
    ok = 200 <= http_status < 300 and balance > 0
    return {
        "ok": ok,
        "status": "success" if ok else "api_error",
        "http_status": http_status,
        "message": "balance api success" if ok else "balance value not found in api response",
        "balance": balance,
        "raw_response": data,
    }


def _receive_items_from_api_response(raw_response: Any) -> list[dict[str, Any]]:
    if isinstance(raw_response, dict):
        data = raw_response.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("items", "transactions", "records", "list", "receive", "receives"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if any(key in data for key in ("amount", "transaction_id", "received_time", "sender_number", "sender_mobile")):
                return [data]
        for key in ("items", "transactions", "records", "list", "receive", "receives"):
            value = raw_response.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(raw_response, list):
        return [item for item in raw_response if isinstance(item, dict)]
    return []


def _money_receive_event(item: dict[str, Any]) -> dict[str, Any]:
    amount = _review_amount(
        item.get("amount")
        or item.get("received_amount")
        or item.get("money")
        or item.get("value")
        or item.get("transfer_amount")
    )
    transaction_id = _clean(
        item.get("transaction_id")
        or item.get("transactionid")
        or item.get("reference_id")
        or item.get("trans_id")
        or item.get("txn_id"),
        180,
    )
    sender_mobile = _clean(
        item.get("sender_number")
        or item.get("sender_mobile")
        or item.get("sender_phone")
        or item.get("payer_mobile")
        or item.get("mobile"),
        80,
    )
    receiver_mobile = _clean(item.get("receiver_number") or item.get("receiver_mobile") or item.get("receiver"), 80)
    received_time = _clean(item.get("received_time") or item.get("time") or item.get("created_at") or item.get("date"), 80)
    event_type = _clean(item.get("event_type") or item.get("type") or item.get("event") or "money_in", 80)
    message = _clean(item.get("message") or item.get("description") or item.get("note"), 500)
    if not transaction_id:
        transaction_id = _clean(f"{event_type}:{sender_mobile}:{received_time}:{amount:g}", 180)
    return {
        "event_type": event_type,
        "amount": amount,
        "sender_mobile": sender_mobile,
        "receiver_mobile": receiver_mobile,
        "received_time": received_time,
        "transaction_id": transaction_id,
        "message": message,
        "status": "paid" if amount > 0 else "ignored",
    }


def _insert_money_receive_ledger_log(cur: sqlite3.Cursor, event: dict[str, Any], raw_item: dict[str, Any], api_log_id: int) -> int:
    amount = _review_amount(event.get("amount"))
    if amount <= 0:
        return 0
    existing = _successful_money_log(cur, {"transaction_id": event.get("transaction_id")}, amount)
    if existing:
        return int(existing.get("id") or 0)
    cur.execute(
        """
        INSERT INTO money_in_ledger (
            source, source_event, source_id, payment_ref, voucher_ref, voucher_url,
            transaction_id, amount, sender, sender_mobile, account_ref, verify_ok,
            match_status, matched_table, matched_id, time_delta, status, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "truemoney_money_receive_api",
            _clean(event.get("event_type") or "money_in", 120),
            _clean(event.get("transaction_id") or f"api_money_receive:{api_log_id}", 180),
            "",
            "",
            "",
            _clean(event.get("transaction_id"), 180),
            amount,
            _clean(raw_item.get("sender_name") or raw_item.get("payer_name") or raw_item.get("sender"), 160),
            _clean(event.get("sender_mobile"), 80),
            _clean(event.get("receiver_mobile") or "truemoney_receive", 160),
            1,
            "api_money_receive",
            "api_money_receive_logs",
            str(api_log_id),
            0,
            "paid",
            _payload_json(_redact_secrets({"event": event, "raw_item": raw_item})),
        ),
    )
    return int(cur.lastrowid or 0)


def _insert_api_money_receive_log(
    cur: sqlite3.Cursor,
    *,
    request_ip: str,
    api_result: dict[str, Any],
    event: dict[str, Any],
    raw_item: dict[str, Any],
) -> tuple[int, int, bool]:
    transaction_id = _clean(event.get("transaction_id"), 180)
    if transaction_id:
        cur.execute(
            """
            SELECT id, money_log_id
            FROM api_money_receive_logs
            WHERE transaction_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (transaction_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"] or 0), int(row["money_log_id"] or 0), False
    cur.execute(
        """
        INSERT INTO api_money_receive_logs (
            api_url, request_ip, http_status, ok, event_type, amount,
            sender_mobile, receiver_mobile, received_time, transaction_id,
            message, status, money_log_id, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            TRUEMONEY_MONEY_RECEIVE_API_URL,
            request_ip,
            int(api_result.get("http_status") or 0),
            1 if api_result.get("ok") else 0,
            _clean(event.get("event_type"), 80),
            _review_amount(event.get("amount")),
            _clean(event.get("sender_mobile"), 80),
            _clean(event.get("receiver_mobile"), 80),
            _clean(event.get("received_time"), 80),
            transaction_id,
            _clean(event.get("message"), 500),
            _clean(event.get("status") or ("paid" if _review_amount(event.get("amount")) > 0 else "ignored"), 80),
            None,
            _payload_json(_redact_secrets(raw_item)),
        ),
    )
    api_log_id = int(cur.lastrowid or 0)
    money_log_id = _insert_money_receive_ledger_log(cur, event, raw_item, api_log_id)
    if money_log_id:
        cur.execute("UPDATE api_money_receive_logs SET money_log_id=? WHERE id=?", (money_log_id, api_log_id))
    return api_log_id, money_log_id, True


def _call_truemoney_voucher_api(voucher_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key, phone = _voucher_api_credentials(payload)
    if not api_key or not phone:
        return {
            "ok": False,
            "status": "api_error",
            "http_status": 0,
            "message": "truemoney voucher api key or phone missing",
            "raw_response": {"status": "error", "message": "api key or phone missing"},
        }
    form = urllib.parse.urlencode({
        "keyapi": api_key,
        "phone": phone,
        "gift_link": voucher_url,
    }).encode("utf-8")
    request = urllib.request.Request(
        TRUEMONEY_VOUCHER_API_URL,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "papxnz-decision-api/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
            http_status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = str(exc)
        http_status = int(getattr(exc, "code", 0) or 0)
    except Exception as exc:
        return {
            "ok": False,
            "status": "api_error",
            "http_status": 0,
            "message": f"truemoney voucher api network error: {str(exc)[:300]}",
            "raw_response": {"status": "error", "message": str(exc)[:500]},
        }
    try:
        data = json.loads(raw)
    except Exception:
        data = {"status": "error", "message": f"invalid json: {raw[:300]}", "raw": raw[:1000]}
    data = data if isinstance(data, dict) else {"value": data}
    amount = _voucher_api_amount(data)
    transaction_id = _voucher_api_transaction_id(data, _voucher_ref_from_url(voucher_url))
    sender, sender_mobile = _voucher_api_sender(data)
    text = " ".join(str(value or "") for value in (data.get("status"), data.get("message"), data.get("detail"), data.get("error"))).lower()
    is_system_error = http_status >= 500 or any(term in text for term in ("api_error", "server", "timeout", "network"))
    is_used = any(term in text for term in ("used", "redeemed", "เปิดใช้", "ถูกใช้"))
    is_success = 200 <= http_status < 300 and amount > 0 and not is_system_error and not is_used
    status = "success" if is_success else ("system_error" if is_system_error else ("voucher_used" if is_used else "failed"))
    return {
        "ok": is_success,
        "status": status,
        "http_status": http_status,
        "message": _clean(data.get("message") or data.get("detail") or data.get("error") or status, 500),
        "amount": amount,
        "transaction_id": transaction_id,
        "sender_name": sender,
        "sender_mobile": sender_mobile,
        "raw_response": data,
    }


def _previous_api_balance(cur: sqlite3.Cursor) -> float:
    _ensure_decision_tables(cur)
    cur.execute(
        """
        SELECT balance
        FROM api_balance_checks
        WHERE ok=1 AND balance IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return _review_amount(row["balance"] if row else 0)


def _insert_api_balance_check(
    cur: sqlite3.Cursor,
    *,
    request_ip: str,
    api_result: dict[str, Any],
    previous_balance: float,
    delta: float,
    money_log_id: int,
    api_url: str = TRUEMONEY_BALANCE_API_URL,
    expected_amount: float = 0.0,
    purchase_state: str = "",
    can_send_link: bool = False,
    route_group_id: str = "",
) -> int:
    raw_response = api_result.get("raw_response", api_result)
    cur.execute(
        """
        INSERT INTO api_balance_checks (
            api_url, request_ip, http_status, ok, balance, previous_balance,
            balance_delta, status, message, money_log_id, raw_payload,
            expected_amount, purchase_state, can_send_link, route_group_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            api_url,
            request_ip,
            int(api_result.get("http_status") or 0),
            1 if api_result.get("ok") else 0,
            _review_amount(api_result.get("balance")),
            previous_balance,
            delta,
            _clean(api_result.get("status") or "api_error", 80),
            _clean(api_result.get("message"), 500),
            money_log_id or None,
            _payload_json(_redact_secrets(raw_response if isinstance(raw_response, dict) else {"raw": raw_response})),
            expected_amount,
            _clean(purchase_state, 80),
            1 if can_send_link else 0,
            _clean(route_group_id, 120),
        ),
    )
    return int(cur.lastrowid or 0)


def _expected_amount_from_payload(payload: dict[str, Any]) -> float:
    for key in ("expected_amount", "package_price", "price", "amount", "paid_amount", "received_amount"):
        amount = _review_amount(payload.get(key))
        if amount > 0:
            return amount
    return 0.0


def _route_for_amount(cur: sqlite3.Cursor, amount: float, project_id: str = "default") -> dict[str, Any]:
    amount = _review_amount(amount)
    if amount <= 0:
        return {"matched": False, "reason": "missing expected amount"}
    if _has_table(cur, "project_routes"):
        cur.execute(
            """
            SELECT project_id, sort_order, group_id, price
            FROM project_routes
            WHERE project_id=? AND ABS(price - ?) < 0.01
            ORDER BY sort_order, id
            LIMIT 1
            """,
            (project_id or "default", amount),
        )
        row = _row_dict(cur.fetchone())
        if row:
            return {"matched": True, "source": "project_routes", **row}
    if _has_table(cur, "vip_tier_config"):
        tier_cols = _columns(cur, "vip_tier_config")
        price_col = "price" if "price" in tier_cols else "min_amount"
        cur.execute(
            f"""
            SELECT tier_id AS sort_order, group_link AS group_id, {price_col} AS price
            FROM vip_tier_config
            WHERE ABS({price_col} - ?) < 0.01
            ORDER BY tier_id
            LIMIT 1
            """,
            (amount,),
        )
        row = _row_dict(cur.fetchone())
        if row:
            return {"matched": True, "source": "vip_tier_config", "project_id": project_id or "default", **row}
    return {"matched": False, "reason": f"no configured route for {amount:g}"}


def _balance_user_id(cur: sqlite3.Cursor, payload: dict[str, Any]) -> int:
    user_id = _review_user_id(payload.get("user_id") or payload.get("chat_id") or payload.get("telegram_id"))
    if user_id:
        return user_id
    username = _clean(payload.get("username") or payload.get("login") or payload.get("email") or payload.get("telegram"), 160)
    if username and _has_table(cur, "auth_users"):
        cur.execute(
            """
            SELECT id FROM auth_users
            WHERE username=? OR email=? OR telegram=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (username, username, username),
        )
        row = cur.fetchone()
        return _review_user_id(row["id"] if row else 0)
    return 0


def _upsert_user_balance(cur: sqlite3.Cursor, user_id: int, balance: float, source: str, raw_payload: dict[str, Any]) -> None:
    if not user_id:
        return
    _ensure_decision_tables(cur)
    cur.execute(
        """
        INSERT INTO user_balance (user_id, total, source, updated_at, raw_payload)
        VALUES (?, ?, ?, strftime('%s','now'), ?)
        ON CONFLICT(user_id) DO UPDATE SET
            total=excluded.total,
            source=excluded.source,
            updated_at=strftime('%s','now'),
            raw_payload=excluded.raw_payload
        """,
        (user_id, balance, _clean(source, 80), _payload_json(_redact_secrets(raw_payload))),
    )


def _balance_purchase_state(
    cur: sqlite3.Cursor,
    payload: dict[str, Any],
    *,
    api_ok: bool,
    balance: float,
    previous_balance: float,
    delta: float,
    money_log_id: int,
) -> dict[str, Any]:
    project_id = _clean(payload.get("project_id") or "default", 80) or "default"
    expected_amount = _expected_amount_from_payload(payload)
    route_amount = expected_amount or delta
    route_match = _route_for_amount(cur, route_amount, project_id)
    user_id = _balance_user_id(cur, payload)
    balance_passed = False
    can_send_link = False
    send_link_state = "waiting_balance"
    state = "balance_waiting"
    reason = "waiting for API balance to reach package price"
    if not api_ok:
        state = "api_error"
        reason = "balance api did not return a usable balance"
        send_link_state = "blocked_by_api"
    elif balance <= 0:
        state = "balance_zero"
        reason = "balance is still zero in central API log"
        send_link_state = "waiting_balance"
    elif expected_amount > 0 and balance + 0.01 < expected_amount:
        state = "balance_waiting"
        reason = f"balance {balance:g} is still below package price {expected_amount:g}"
        send_link_state = "waiting_balance"
    elif not route_match.get("matched"):
        state = "route_missing"
        reason = str(route_match.get("reason") or "balance amount does not match any setup route")
        send_link_state = "blocked_by_route"
    elif not user_id:
        state = "balance_confirmed_no_user"
        reason = "balance is enough, but user_id/username is missing so central balance cannot be updated"
        send_link_state = "blocked_by_user"
    else:
        state = "balance_confirmed"
        reason = "API balance is enough and matched a configured package route"
        balance_passed = True
        can_send_link = True
        send_link_state = "source_may_send_link"
    return {
        "purchase_state": state,
        "balance_state": state,
        "balance_status": "success" if balance_passed else "error",
        "balance_passed": balance_passed,
        "can_deduct": balance_passed,
        "can_send_link": can_send_link,
        "send_link_state": send_link_state,
        "reason": reason,
        "expected_amount": expected_amount,
        "route_match": route_match,
        "route_group_id": _clean(route_match.get("group_id"), 120) if route_match.get("matched") else "",
        "user_id": user_id,
    }


def _route_for_package_id(cur: sqlite3.Cursor, package_id: Any, project_id: str = "default") -> dict[str, Any]:
    package_text = _clean(package_id, 80).lower()
    match = re.search(r"(\d+)$", package_text)
    if not match:
        return {"matched": False, "reason": "package_id_missing_or_invalid"}
    slot = int(match.group(1))
    if _has_table(cur, "project_routes"):
        cur.execute(
            """
            SELECT project_id, sort_order, group_id, price
            FROM project_routes
            WHERE project_id=? AND sort_order=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (project_id or "default", slot),
        )
        row = cur.fetchone()
        if row and _review_amount(row["price"]) > 0 and _clean(row["group_id"]):
            return {
                "matched": True,
                "source": "project_routes",
                "package_id": package_text,
                "slot": slot,
                "price": _review_amount(row["price"]),
                "group_id": _clean(row["group_id"], 120),
            }
    return {"matched": False, "reason": "group_config_missing", "package_id": package_text, "slot": slot}


def _insert_api_voucher_check(cur: sqlite3.Cursor, *, request_ip: str, api_result: dict[str, Any], voucher_url: str, voucher_ref: str, source_payload: dict[str, Any], money_log_id: int = 0) -> int:
    raw_response = api_result.get("raw_response", api_result)
    cur.execute(
        """
        INSERT INTO api_voucher_checks (
            api_url, request_ip, http_status, ok, status, message, amount,
            transaction_id, sender, sender_mobile, voucher_ref, voucher_url,
            money_log_id, source_payload, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            TRUEMONEY_VOUCHER_API_URL,
            request_ip,
            int(api_result.get("http_status") or 0),
            1 if api_result.get("ok") else 0,
            _clean(api_result.get("status") or "api_error", 80),
            _clean(api_result.get("message"), 500),
            _review_amount(api_result.get("amount")),
            _clean(api_result.get("transaction_id"), 180),
            _clean(api_result.get("sender_name"), 160),
            _clean(api_result.get("sender_mobile"), 80),
            _clean(voucher_ref, 180),
            _clean(voucher_url, 600),
            money_log_id or None,
            _payload_json(_redact_secrets(source_payload if isinstance(source_payload, dict) else {})),
            _payload_json(_redact_secrets(raw_response if isinstance(raw_response, dict) else {"raw": raw_response})),
        ),
    )
    return int(cur.lastrowid or 0)


def _insert_balance_delta_money_log(cur: sqlite3.Cursor, payload: dict[str, Any], api_result: dict[str, Any], request_ip: str, delta: float, check_id: int) -> int:
    if delta <= 0:
        return 0
    raw_payload = _payload_json(_redact_secrets({"payload": payload, "api_result": api_result, "balance_check_id": check_id}))
    cur.execute(
        """
        INSERT INTO money_in_ledger (
            source, source_event, source_id, payment_ref, voucher_ref, voucher_url,
            transaction_id, amount, sender, sender_mobile, account_ref, verify_ok,
            match_status, matched_table, matched_id, time_delta, status, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "truemoney_balance_api",
            "account_balance_delta",
            f"balance_check:{check_id}",
            _clean(payload.get("payment_ref") or payload.get("attempt_id"), 180),
            _clean(payload.get("voucher_ref") or payload.get("v"), 180),
            _clean(payload.get("voucher_url") or payload.get("truemoney_url") or payload.get("url"), 600),
            _clean(payload.get("transaction_id") or payload.get("reference_id") or f"balance_check:{check_id}", 180),
            delta,
            _clean(payload.get("sender_name") or payload.get("payer_name") or payload.get("sender") or payload.get("username"), 160),
            _clean(payload.get("sender_mobile") or payload.get("payer_mobile") or payload.get("mobile"), 80),
            _clean(payload.get("account_ref") or "truemoney_balance", 160),
            1,
            "balance_delta",
            "api_balance_checks",
            str(check_id),
            0,
            "paid",
            raw_payload,
        ),
    )
    return int(cur.lastrowid or 0)


def _webhook_money_amount(payload: dict[str, Any]) -> float:
    for value in (
        payload.get("money_in"),
        payload.get("amount"),
        payload.get("paid_amount"),
        payload.get("received_amount"),
        payload.get("transfer_amount"),
        payload.get("balance_delta"),
        payload.get("delta"),
    ):
        amount = _review_amount(value)
        if amount > 0:
            return amount
    return 0.0


def _successful_money_log(cur: sqlite3.Cursor, payload: dict[str, Any], amount: float = 0.0) -> dict[str, Any]:
    if not _has_table(cur, "money_in_ledger"):
        return {}
    voucher_url = _clean(payload.get("voucher_url") or payload.get("truemoney_url") or payload.get("url"), 600)
    voucher_ref = _clean(payload.get("voucher_ref") or payload.get("v") or _voucher_ref_from_url(voucher_url), 180)
    refs = {
        _clean(payload.get("transaction_id") or payload.get("reference_id") or payload.get("trans_id"), 180),
        _clean(payload.get("source_id") or payload.get("report_id"), 180),
        _clean(payload.get("payment_ref") or payload.get("attempt_id"), 180),
        voucher_ref,
    }
    refs = {ref for ref in refs if ref}
    if not refs:
        return {}
    where = ["lower(COALESCE(status,'')) IN ('paid','success','approved')"]
    params: list[Any] = []
    ref_where = []
    for ref in refs:
        ref_where.extend(["transaction_id=?", "source_id=?", "payment_ref=?", "voucher_ref=?"])
        params.extend([ref, ref, ref, ref])
    if ref_where:
        where.append(f"({' OR '.join(ref_where)})")
    if amount > 0:
        where.append("ABS(amount - ?) < 0.01")
        params.append(amount)
    cur.execute(
        f"""
        SELECT id, ts, source, source_event, amount, transaction_id, payment_ref, voucher_ref, status
        FROM money_in_ledger
        WHERE {' AND '.join(where)}
        ORDER BY id DESC
        LIMIT 1
        """,
        params,
    )
    return _row_dict(cur.fetchone())


def _insert_direct_webhook_money_log(cur: sqlite3.Cursor, payload: dict[str, Any], request_ip: str, amount: float, check_id: int = 0, matched_table: str = "api_balance_checks") -> int:
    if amount <= 0:
        return 0
    if _successful_money_log(cur, payload, amount):
        return 0
    voucher_url = _clean(payload.get("voucher_url") or payload.get("truemoney_url") or payload.get("url"), 600)
    cur.execute(
        """
        INSERT INTO money_in_ledger (
            source, source_event, source_id, payment_ref, voucher_ref, voucher_url,
            transaction_id, amount, sender, sender_mobile, account_ref, verify_ok,
            match_status, matched_table, matched_id, time_delta, status, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _clean(payload.get("source") or "truemoney_webhook", 120),
            _clean(payload.get("event_type") or payload.get("event") or "money_in", 120),
            _clean(payload.get("source_id") or payload.get("report_id") or payload.get("transaction_id") or payload.get("reference_id") or f"balance_webhook:{check_id}", 180),
            _clean(payload.get("payment_ref") or payload.get("attempt_id"), 180),
            _clean(payload.get("voucher_ref") or payload.get("v") or _voucher_ref_from_url(voucher_url), 180),
            voucher_url,
            _clean(payload.get("transaction_id") or payload.get("reference_id") or payload.get("trans_id") or f"balance_webhook:{check_id}", 180),
            amount,
            _clean(payload.get("sender_name") or payload.get("payer_name") or payload.get("sender") or payload.get("username"), 160),
            _clean(payload.get("sender_mobile") or payload.get("payer_mobile") or payload.get("mobile"), 80),
            _clean(payload.get("account_ref") or payload.get("receiver") or request_ip, 160),
            1,
            "webhook_received",
            matched_table if check_id else "",
            str(check_id or ""),
            0,
            "paid",
            _payload_json(_redact_secrets(payload)),
        ),
    )
    return int(cur.lastrowid or 0)


def process_truemoney_voucher(payload: dict[str, Any], request_ip: str = "") -> dict[str, Any]:
    safe_payload = payload if isinstance(payload, dict) else {}
    voucher_url = _clean(
        safe_payload.get("voucher_url") or safe_payload.get("truemoney_url") or safe_payload.get("url") or safe_payload.get("link"),
        600,
    )
    voucher_ref = _clean(safe_payload.get("voucher_ref") or safe_payload.get("v") or _voucher_ref_from_url(voucher_url), 180)
    source_id = _clean(safe_payload.get("source_id") or safe_payload.get("payment_ref") or safe_payload.get("attempt_id") or voucher_ref, 180)
    if not voucher_url or "gift.truemoney.com/campaign/" not in voucher_url:
        return {
            "ok": False,
            "ready": False,
            "status": "invalid",
            "message": "invalid truemoney voucher link",
            "mode": "truemoney_voucher_redeem",
            "api_response": {"status": "invalid", "message": "invalid truemoney voucher link"},
        }

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    passed_log = _successful_money_log(cur, {**safe_payload, "voucher_url": voucher_url, "voucher_ref": voucher_ref})
    if passed_log:
        conn.close()
        return {
            "ok": True,
            "ready": True,
            "status": "already_passed",
            "message": "this voucher already passed; skipped duplicate redeem",
            "mode": "truemoney_voucher_redeem",
            "existing_money_log": passed_log,
            "can_retry": False,
        }
    api_result = _call_truemoney_voucher_api(voucher_url, safe_payload)
    raw_response = api_result.get("raw_response") if isinstance(api_result.get("raw_response"), dict) else {"raw": api_result.get("raw_response")}
    amount = _review_amount(api_result.get("amount"))
    transaction_id = _clean(api_result.get("transaction_id") or voucher_ref or source_id, 180)
    evidence_payload = {
        **safe_payload,
        **raw_response,
        "source": safe_payload.get("source") or "truemoney_voucher_api",
        "event_type": safe_payload.get("event_type") or "truemoney_voucher_redeem",
        "source_id": source_id,
        "payment_ref": safe_payload.get("payment_ref") or safe_payload.get("attempt_id") or source_id,
        "voucher_ref": voucher_ref,
        "voucher_url": voucher_url,
        "transaction_id": transaction_id,
        "amount": amount,
        "sender_name": api_result.get("sender_name") or raw_response.get("sender_name") or raw_response.get("owner_profile") or raw_response.get("redeemer_profile"),
        "sender_mobile": api_result.get("sender_mobile") or raw_response.get("sender_mobile") or raw_response.get("mobile"),
        "status": api_result.get("status"),
    }
    check_id = _insert_api_voucher_check(
        cur,
        request_ip=request_ip,
        api_result={**api_result, "raw_response": raw_response},
        voucher_url=voucher_url,
        voucher_ref=voucher_ref,
        source_payload=safe_payload,
    )
    money_log_id = 0
    if api_result.get("ok") and amount > 0:
        money_log_id = _insert_direct_webhook_money_log(cur, evidence_payload, request_ip, amount, check_id, "api_voucher_checks")
        if money_log_id:
            cur.execute("UPDATE api_voucher_checks SET money_log_id=? WHERE id=?", (money_log_id, check_id))

    decision_status = "success" if api_result.get("ok") else ("system_error" if api_result.get("status") == "system_error" else str(api_result.get("status") or "failed"))
    decision_result = {
        "ok": bool(api_result.get("ok")),
        "ready": bool(api_result.get("ok")),
        "status": decision_status,
        "message": api_result.get("message") or decision_status,
        "mode": "truemoney_voucher_redeem",
        "amount": amount,
        "transaction_id": transaction_id,
        "voucher_ref": voucher_ref,
        "money_log_id": money_log_id,
        "api_check_id": check_id,
        "api_voucher_check_id": check_id,
        "api_response": _redact_secrets(raw_response),
        "can_retry": decision_status == "system_error",
    }
    ids = _ids_from_payload(evidence_payload)
    cur.execute(
        """
        INSERT INTO decision_checks (
            ts, mode, payment_ref, voucher_ref, transaction_id, session_id, username,
            user_id, package_id, invite_link, slip_hash, status, request_ip, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(time.time()),
            "truemoney_voucher_redeem",
            ids["payment_ref"],
            ids["voucher_ref"],
            ids["transaction_id"],
            ids["session_id"],
            ids["username"],
            ids["user_id"],
            ids["package_id"],
            ids["invite_link"],
            ids["slip_hash"],
            decision_status,
            request_ip,
            _payload_json(evidence_payload),
        ),
    )
    admin_visibility = _record_decision_admin_visibility(cur, evidence_payload, decision_result, request_ip)
    decision_result["admin_visibility"] = admin_visibility
    _commit_and_record_finance_alert(conn, evidence_payload, decision_result, request_ip, admin_visibility)
    conn.close()
    return decision_result


def _money_in_amount(payload: dict[str, Any], result: dict[str, Any] | None = None) -> float:
    result = result if isinstance(result, dict) else {}
    payment = result.get("payment") if isinstance(result.get("payment"), dict) else {}
    for value in (
        payload.get("amount"),
        payload.get("paid_amount"),
        payload.get("received_amount"),
        payload.get("transfer_amount"),
        payment.get("amount"),
        payment.get("paid_amount"),
        payment.get("received_amount"),
    ):
        amount = _review_amount(value)
        if amount > 0:
            return amount
    return 0.0


def _looks_like_money_in(payload: dict[str, Any], result: dict[str, Any] | None = None) -> bool:
    result = result if isinstance(result, dict) else {}
    amount = _money_in_amount(payload, result)
    if amount <= 0:
        return False
    payment = result.get("payment") if isinstance(result.get("payment"), dict) else {}
    if payload.get("verify_ok") in (True, 1, "1", "true", "True", "ok", "approved", "verified"):
        return True
    status_text = " ".join(
        str(value or "")
        for value in (
            payload.get("status"),
            payload.get("note"),
            payload.get("verify_ok"),
            result.get("status"),
            result.get("message"),
            payment.get("status"),
            payment.get("source_status"),
        )
    ).lower()
    event_text = " ".join(
        str(value or "")
        for value in (
            payload.get("source"),
            payload.get("event_type"),
            payload.get("mode"),
            payment.get("source"),
            payment.get("event_type"),
        )
    ).lower()
    success_terms = ("success", "approved", "paid", "completed", "complete", "received", "verified", "verify_ok", "true")
    source_terms = ("webhook", "truemoney", "tmn", "topup", "deposit", "transfer", "money_in")
    return any(term in status_text for term in success_terms) or any(term in event_text for term in source_terms)


def _record_money_in_ledger(
    cur: sqlite3.Cursor,
    payload: dict[str, Any],
    result: dict[str, Any],
    request_ip: str,
    *,
    match: dict[str, Any] | None = None,
) -> int:
    _ensure_decision_tables(cur)
    if _clean(result.get("status"), 80).lower() in ("api_error", "system_error"):
        return 0
    if not _looks_like_money_in(payload, result):
        return 0
    ids = _ids_from_payload(payload)
    payment = result.get("payment") if isinstance(result.get("payment"), dict) else {}
    match = match if isinstance(match, dict) else {}
    best = match.get("best") if isinstance(match.get("best"), dict) else {}
    voucher_url = _clean(payload.get("truemoney_url") or payload.get("voucher_url") or payload.get("url") or ids.get("voucher_url") or payment.get("url") or payment.get("voucher_url"), 600)
    voucher_ref = _clean(ids.get("voucher_ref") or payload.get("v") or _voucher_ref_from_url(voucher_url) or payment.get("v") or payment.get("voucher_ref"), 180)
    amount = _money_in_amount(payload, result)
    if _successful_money_log(cur, {**payload, "voucher_ref": voucher_ref, "voucher_url": voucher_url}, amount):
        return 0
    verify_raw = payload.get("verify_ok")
    verify_ok = 1 if verify_raw in (True, 1, "1", "true", "True", "ok", "approved", "verified") or str(result.get("status") or "").lower() in ("success", "approved", "paid") else 0
    cur.execute(
        """
        INSERT INTO money_in_ledger (
            source, source_event, source_id, payment_ref, voucher_ref, voucher_url,
            transaction_id, amount, sender, sender_mobile, account_ref, verify_ok,
            match_status, matched_table, matched_id, time_delta, status, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _clean(payload.get("source") or payment.get("source") or "decision_api", 120),
            _clean(payload.get("event_type") or result.get("mode") or payment.get("event_type"), 120),
            _clean(payload.get("report_id") or payload.get("source_id") or ids.get("payment_ref") or ids.get("transaction_id") or voucher_ref, 180),
            ids.get("payment_ref") or _clean(payment.get("id") or payment.get("payment_ref"), 180),
            voucher_ref,
            voucher_url,
            ids.get("transaction_id") or _clean(payment.get("transaction_id") or payment.get("reference_id"), 180),
            amount,
            _clean(payload.get("sender_name") or payload.get("payer_name") or payload.get("sender") or payload.get("username") or payment.get("sender_name") or payment.get("payer_name") or payment.get("sender") or payment.get("username"), 160),
            _clean(payload.get("sender_mobile") or payload.get("payer_mobile") or payload.get("mobile") or payment.get("sender_mobile") or payment.get("payer_mobile"), 80),
            _clean(payload.get("account_ref") or payload.get("receiver") or request_ip, 160),
            verify_ok,
            _clean(match.get("match_status") or ("matched_self" if best else "unmatched"), 80),
            _clean(best.get("table"), 80),
            _clean(best.get("id"), 80),
            int(best.get("time_delta") or 0),
            _clean(result.get("status") or payment.get("status") or "logged", 80),
            _payload_json({"payload": payload, "result": result, "match": match}),
        ),
    )
    return int(cur.lastrowid or 0)


def _ensure_admin_review_from_payload(cur: sqlite3.Cursor, payload: dict[str, Any], source: str = "decision_api") -> dict[str, Any]:
    _ensure_decision_tables(cur)
    truemoney_url = _clean(payload.get("truemoney_url") or payload.get("voucher_url") or payload.get("url"), 600)
    voucher_ref = _clean(payload.get("voucher_ref") or payload.get("v") or _voucher_ref_from_url(truemoney_url), 180)
    source_id = _clean(payload.get("report_id") or payload.get("source_id") or payload.get("payment_ref") or payload.get("attempt_id"), 180)
    payment_ref = _clean(payload.get("payment_ref") or payload.get("attempt_id"), 180)
    amount = _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("expected_amount"))
    user_id = _review_user_id(payload.get("user_id") or payload.get("chat_id") or payload.get("telegram_id"))
    sender = _clean(payload.get("sender") or payload.get("username") or payload.get("login") or payload.get("source") or source, 160)
    raw_payload = _payload_json(payload)

    review_id = 0
    review_ref = voucher_ref or _clean(payload.get("transaction_id") or payload.get("reference_id") or source_id or payment_ref, 180)
    if not voucher_ref and not truemoney_url and review_ref:
        voucher_ref = review_ref
    if voucher_ref or truemoney_url:
        if voucher_ref:
            cur.execute("SELECT id FROM api_error_payment_reviews WHERE v=? LIMIT 1", (voucher_ref,))
        else:
            cur.execute("SELECT id FROM api_error_payment_reviews WHERE url=? LIMIT 1", (truemoney_url,))
        row = cur.fetchone()
        if row:
            review_id = int(row["id"])
        else:
            cur.execute(
                """
                INSERT INTO api_error_payment_reviews (user_id, sender, url, v, amount, raw_result, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (user_id, sender, truemoney_url, voucher_ref, amount, raw_payload),
            )
            review_id = int(cur.lastrowid)

    existing_bridge = None
    if source_id:
        cur.execute(
            "SELECT * FROM decision_admin_reviews WHERE source=? AND source_id=? LIMIT 1",
            (source, source_id),
        )
        existing_bridge = cur.fetchone()

    if existing_bridge:
        bridge_id = int(existing_bridge["id"])
        cur.execute(
            """
            UPDATE decision_admin_reviews
            SET review_id=?, payment_ref=?, voucher_ref=?, truemoney_url=?, amount=?, raw_payload=?
            WHERE id=?
            """,
            (review_id or None, payment_ref, voucher_ref, truemoney_url, amount, raw_payload, bridge_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO decision_admin_reviews
                (ts, source, source_id, review_id, payment_ref, voucher_ref, truemoney_url, amount, status, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (int(time.time()), source, source_id, review_id or None, payment_ref, voucher_ref, truemoney_url, amount, raw_payload),
        )
        bridge_id = int(cur.lastrowid)

    return {
        "queued": True,
        "bridge_id": bridge_id,
        "review_id": review_id,
        "source": source,
        "source_id": source_id,
        "payment_ref": payment_ref,
        "voucher_ref": voucher_ref,
        "truemoney_url": truemoney_url,
        "amount": amount,
        "status": "pending",
    }


def record_missing_slip_for_admin(payload: dict[str, Any]) -> dict[str, Any]:
    conn = _conn()
    cur = conn.cursor()
    result = _ensure_admin_review_from_payload(cur, payload, "missing_slip_reports")
    conn.commit()
    conn.close()
    return result


def _admin_review_context(cur: sqlite3.Cursor, ids: dict[str, str]) -> dict[str, Any]:
    if not _has_table(cur, "decision_admin_reviews"):
        return {}
    candidates = [
        ("payment_ref", ids["payment_ref"]),
        ("voucher_ref", ids["voucher_ref"]),
        ("truemoney_url", ids["voucher_url"]),
        ("source_id", ids["payment_ref"]),
    ]
    return _query_first(cur, "decision_admin_reviews", candidates, "ts")


def _insert_admin_review_check(cur: sqlite3.Cursor, payload: dict[str, Any]) -> int:
    _ensure_decision_tables(cur)
    raw_payload = _payload_json(payload)
    cur.execute(
        """
        INSERT INTO admin_review_checks (
            review_id, bridge_id, action, actor, amount, status, tier_id, group_id,
            invite_link, bot_status, bot_error, send_status, send_error, can_retry, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("review_id"),
            payload.get("bridge_id"),
            _clean(payload.get("action"), 40),
            _clean(payload.get("actor") or "decision_api", 120),
            _review_amount(payload.get("amount")),
            _clean(payload.get("status"), 40),
            _review_user_id(payload.get("tier_id")),
            _clean(payload.get("group_id"), 120),
            _clean(payload.get("invite_link"), 600),
            _clean(payload.get("bot_status") or "not_run_by_decision_api", 80),
            _clean(payload.get("bot_error"), 500),
            _clean(payload.get("send_status") or "not_run_by_decision_api", 80),
            _clean(payload.get("send_error"), 500),
            1 if payload.get("can_retry", True) else 0,
            raw_payload,
        ),
    )
    return int(cur.lastrowid or 0)


def _decision_needs_admin_review(result: dict[str, Any], mode: str) -> bool:
    status = _clean(result.get("status"), 40).lower()
    message = _clean(result.get("message"), 500).lower()
    payment = result.get("payment") if isinstance(result.get("payment"), dict) else {}
    admin_review = result.get("admin_review") if isinstance(result.get("admin_review"), dict) else {}
    system_terms = (
        "api_error",
        "system_error",
        "server_error",
        "bot_error",
        "bot_failed",
        "invite_error",
        "invite_failed",
        "send_failed",
        "telegram_http",
        "telegram_getme_failed",
        "token",
        "missing/not configured",
        "db_error",
        "database",
        "network",
        "timeout",
    )
    if admin_review and _clean(admin_review.get("status"), 40).lower() in ("pending", "needs_retry", "api_error", "system_error"):
        return True
    if status in ("api_error", "system_error", "needs_retry"):
        return True
    if any(term in message for term in system_terms):
        return True
    if payment:
        text = " ".join(str(payment.get(key) or "") for key in ("status", "detail", "link_status", "invite_error")).lower()
        if any(term in text for term in system_terms):
            return True
    return False


def _admin_payload_from_decision(payload: dict[str, Any], result: dict[str, Any], request_ip: str) -> dict[str, Any]:
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    payment = result.get("payment") if isinstance(result.get("payment"), dict) else {}
    voucher_url = _clean(payload.get("truemoney_url") or payload.get("voucher_url") or payload.get("url") or identity.get("voucher_url") or payment.get("voucher_url"), 600)
    voucher_ref = _clean(payload.get("voucher_ref") or payload.get("v") or identity.get("voucher_ref") or _voucher_ref_from_url(voucher_url), 180)
    payment_ref = _clean(payload.get("payment_ref") or payload.get("attempt_id") or identity.get("payment_ref") or payment.get("id"), 180)
    amount = _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("expected_amount") or payment.get("paid_amount") or payment.get("amount") or payment.get("expected_amount"))
    user_id = _review_user_id(payload.get("user_id") or payload.get("chat_id") or payload.get("telegram_id") or identity.get("user_id") or payment.get("buyer_user_id"))
    return {
        "source_id": payment_ref or voucher_ref or _raw_hash(_payload_json(payload))[:24],
        "payment_ref": payment_ref,
        "truemoney_url": voucher_url,
        "voucher_url": voucher_url,
        "voucher_ref": voucher_ref,
        "amount": amount,
        "user_id": user_id,
        "sender": payload.get("sender") or payload.get("username") or identity.get("username") or f"decision:{request_ip or 'system'}",
        "decision_status": result.get("status"),
        "decision_message": result.get("message"),
    }


def _reported_ts_from_payload(payload: dict[str, Any]) -> int:
    for key in ("reported_ts", "created_at", "ts", "timestamp", "slip_ts"):
        try:
            value = int(float(str(payload.get(key) or "").strip()))
            if value > 0:
                return value
        except Exception:
            pass
    return 0


def _system_error_payload(payload: dict[str, Any], result: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            payload.get("status"),
            payload.get("event_type"),
            payload.get("error_type"),
            payload.get("error"),
            payload.get("reason"),
            payload.get("note"),
            payload.get("detail"),
            result.get("status"),
            result.get("message"),
        )
    ).lower()
    system_terms = (
        "api_error",
        "system_error",
        "server_error",
        "bot_error",
        "bot_failed",
        "invite_error",
        "send_failed",
        "telegram_http",
        "token",
        "missing/not configured",
        "db_error",
        "database",
        "network",
        "timeout",
    )
    return any(term in text for term in system_terms)


def _record_status_for_match(record: dict[str, Any]) -> tuple[str, bool]:
    text = " ".join(
        str(record.get(key) or "")
        for key in ("status", "source_status", "detail", "note", "link_status", "join_status", "verify_ok")
    ).lower()
    if any(term in text for term in ("api_error", "system_error", "server_error", "bot_error", "bot_failed", "invite_error", "send_failed", "timeout", "database", "network")):
        return "system_error", False
    if any(term in text for term in ("success", "approved", "paid", "issued", "joined", "complete", "completed")):
        return "success", True
    if any(term in text for term in ("pending", "checking", "queued")):
        return "pending", False
    return _clean(record.get("status") or record.get("source_status") or "-", 80), False


def _match_row_score(ids: dict[str, str], amount: float, reported_ts: int, row: dict[str, Any]) -> tuple[int, int]:
    score = 0
    if ids["payment_ref"] and ids["payment_ref"] in {str(row.get("id") or ""), str(row.get("payment_ref") or ""), str(row.get("payment_attempt_id") or ""), str(row.get("source_id") or "")}:
        score += 60
    if ids["transaction_id"] and ids["transaction_id"] == str(row.get("transaction_id") or row.get("reference_id") or ""):
        score += 55
    voucher_ref = ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])
    row_voucher = str(row.get("v") or row.get("voucher_ref") or "")
    row_url = str(row.get("voucher_url") or row.get("url") or row.get("truemoney_url") or "")
    if voucher_ref and (voucher_ref == row_voucher or voucher_ref == _voucher_ref_from_url(row_url) or voucher_ref in row_url):
        score += 50
    if ids["voucher_url"] and ids["voucher_url"] == row_url:
        score += 45
    row_amount = _review_amount(row.get("amount") or row.get("paid_amount") or row.get("expected_amount"))
    if amount > 0 and row_amount > 0 and abs(amount - row_amount) < 0.01:
        score += 20
    row_ts = 0
    for key in ("created_at", "ts", "reviewed_at"):
        try:
            row_ts = int(float(str(row.get(key) or "0")))
            if row_ts:
                break
        except Exception:
            pass
    delta = abs(row_ts - reported_ts) if row_ts and reported_ts else 0
    if delta and delta <= 300:
        score += 15
    elif delta and delta <= 3600:
        score += 8
    return score, delta


def _system_error_match_context(cur: sqlite3.Cursor, payload: dict[str, Any]) -> dict[str, Any]:
    ids = _ids_from_payload(payload)
    amount = _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("expected_amount"))
    reported_ts = _reported_ts_from_payload(payload)
    candidates: list[dict[str, Any]] = []

    def add_rows(table: str, rows: list[sqlite3.Row]) -> None:
        for row in rows:
            data = _row_dict(row)
            score, delta = _match_row_score(ids, amount, reported_ts, data)
            if score:
                matched_status, resolved = _record_status_for_match(data)
                candidates.append({
                    "table": table,
                    "id": str(data.get("id") or data.get("rowid") or ""),
                    "score": score,
                    "time_delta": delta,
                    "matched_status": matched_status,
                    "resolved": resolved,
                    "record": data,
                })

    if _has_table(cur, "money_in_ledger"):
        where = []
        params = []
        money_cols = _columns(cur, "money_in_ledger")
        for col, value in (
            ("transaction_id", ids["transaction_id"]),
            ("payment_ref", ids["payment_ref"]),
            ("voucher_ref", ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])),
            ("voucher_url", ids["voucher_url"]),
        ):
            if value and col in money_cols:
                where.append(f"{col}=?")
                params.append(value)
        if amount > 0 and "amount" in money_cols:
            where.append("ABS(amount - ?) < 0.01")
            params.append(amount)
        if reported_ts and "ts" in money_cols:
            where.append("ABS(ts - ?) <= 3600")
            params.append(reported_ts)
        if where:
            cur.execute(f"SELECT * FROM money_in_ledger WHERE {' OR '.join(where)} ORDER BY ts DESC LIMIT 16", params)
            add_rows("money_in_ledger", cur.fetchall())

    if _has_table(cur, "api_balance_checks"):
        where = []
        params = []
        balance_cols = _columns(cur, "api_balance_checks")
        report_ref = _clean(payload.get("report_id") or payload.get("source_id"), 180)
        check_ref = report_ref.split(":", 1)[1] if report_ref.startswith("api_balance_check:") else ids["payment_ref"]
        if check_ref and str(check_ref).isdigit() and "id" in balance_cols:
            where.append("id=?")
            params.append(int(check_ref))
        if where:
            cur.execute(f"SELECT * FROM api_balance_checks WHERE {' OR '.join(where)} ORDER BY ts DESC LIMIT 8", params)
            add_rows("api_balance_checks", cur.fetchall())

    if _has_table(cur, "api_voucher_checks"):
        where = []
        params = []
        voucher_cols = _columns(cur, "api_voucher_checks")
        report_ref = _clean(payload.get("report_id") or payload.get("source_id"), 180)
        check_ref = report_ref.split(":", 1)[1] if report_ref.startswith("api_voucher_check:") else ""
        if check_ref and str(check_ref).isdigit() and "id" in voucher_cols:
            where.append("id=?")
            params.append(int(check_ref))
        for col, value in (
            ("voucher_ref", ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])),
            ("voucher_url", ids["voucher_url"]),
            ("transaction_id", ids["transaction_id"]),
        ):
            if value and col in voucher_cols:
                where.append(f"{col}=?")
                params.append(value)
        if where:
            cur.execute(f"SELECT * FROM api_voucher_checks WHERE {' OR '.join(where)} ORDER BY ts DESC LIMIT 8", params)
            add_rows("api_voucher_checks", cur.fetchall())

    if _has_table(cur, "payment_attempts"):
        where = []
        params: list[Any] = []
        for col, value in (("id", ids["payment_ref"]), ("voucher_url", ids["voucher_url"]), ("invite_link", ids["invite_link"])):
            if value and col in _columns(cur, "payment_attempts"):
                where.append(f"{col}=?")
                params.append(value)
        voucher_ref = ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])
        if voucher_ref and "voucher_url" in _columns(cur, "payment_attempts"):
            where.append("voucher_url LIKE ?")
            params.append(f"%{voucher_ref}%")
        if where:
            cur.execute(f"SELECT * FROM payment_attempts WHERE {' OR '.join(where)} ORDER BY created_at DESC LIMIT 12", params)
            add_rows("payment_attempts", cur.fetchall())

    if _has_table(cur, "missing_slip_reports"):
        where = []
        params = []
        for col, value in (("id", _clean(payload.get("report_id"))), ("payment_attempt_id", ids["payment_ref"]), ("truemoney_url", ids["voucher_url"])):
            if value and col in _columns(cur, "missing_slip_reports"):
                where.append(f"{col}=?")
                params.append(value)
        voucher_ref = ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])
        if voucher_ref and "truemoney_url" in _columns(cur, "missing_slip_reports"):
            where.append("truemoney_url LIKE ?")
            params.append(f"%{voucher_ref}%")
        if where:
            cur.execute(f"SELECT * FROM missing_slip_reports WHERE {' OR '.join(where)} ORDER BY created_at DESC LIMIT 12", params)
            add_rows("missing_slip_reports", cur.fetchall())

    if _has_table(cur, "webhook_events"):
        where = []
        params = []
        if ids["transaction_id"]:
            where.append("transaction_id=?")
            params.append(ids["transaction_id"])
        if amount > 0:
            where.append("amount=?")
            params.append(str(amount))
        if where:
            cur.execute(f"SELECT * FROM webhook_events WHERE {' OR '.join(where)} ORDER BY ts DESC LIMIT 12", params)
            add_rows("webhook_events", cur.fetchall())

    if _has_table(cur, "api_error_payment_reviews"):
        where = []
        params = []
        voucher_ref = ids["voucher_ref"] or _voucher_ref_from_url(ids["voucher_url"])
        for col, value in (("id", ids["payment_ref"]), ("v", voucher_ref), ("url", ids["voucher_url"])):
            if value and col in _columns(cur, "api_error_payment_reviews"):
                where.append(f"{col}=?")
                params.append(value)
        if where:
            cur.execute(f"SELECT * FROM api_error_payment_reviews WHERE {' OR '.join(where)} ORDER BY created_at DESC LIMIT 12", params)
            add_rows("api_error_payment_reviews", cur.fetchall())

    candidates.sort(key=lambda item: (item["score"], -item["time_delta"]), reverse=True)
    best = candidates[0] if candidates else {}
    return {
        "ids": ids,
        "amount": amount,
        "reported_ts": reported_ts,
        "matched": bool(best),
        "match_status": "matched_resolved" if best.get("resolved") else ("matched_unresolved" if best else "unmatched"),
        "best": best,
        "candidates": candidates[:8],
    }


def _insert_system_error_case(cur: sqlite3.Cursor, payload: dict[str, Any], result: dict[str, Any], request_ip: str, match: dict[str, Any], review: dict[str, Any]) -> int:
    ids = match.get("ids") or _ids_from_payload(payload)
    best = match.get("best") if isinstance(match.get("best"), dict) else {}
    raw_payload = _payload_json({"payload": payload, "decision": result, "request_ip": request_ip})
    match_payload = _payload_json(match)
    cur.execute(
        """
        INSERT INTO system_error_cases (
            source, source_event, source_id, payment_ref, voucher_ref, voucher_url, transaction_id,
            amount, reported_ts, match_status, matched_table, matched_id, matched_status,
            time_delta, status, admin_review_id, raw_payload, match_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _clean(payload.get("source") or "decision_api", 120),
            _clean(payload.get("event_type") or payload.get("error_type") or result.get("mode"), 120),
            _clean(payload.get("report_id") or payload.get("source_id") or ids.get("payment_ref") or ids.get("transaction_id") or ids.get("voucher_ref"), 180),
            ids.get("payment_ref"),
            ids.get("voucher_ref") or _voucher_ref_from_url(ids.get("voucher_url")),
            ids.get("voucher_url"),
            ids.get("transaction_id"),
            match.get("amount") or 0.0,
            match.get("reported_ts") or 0,
            match.get("match_status"),
            best.get("table"),
            best.get("id"),
            best.get("matched_status"),
            best.get("time_delta") or 0,
            "logged",
            review.get("review_id") if review else None,
            raw_payload,
            match_payload,
        ),
    )
    return int(cur.lastrowid or 0)


def _record_decision_admin_visibility(cur: sqlite3.Cursor, payload: dict[str, Any], result: dict[str, Any], request_ip: str) -> dict[str, Any]:
    _ensure_decision_tables(cur)
    mode = _clean(result.get("mode"), 80) or "decision_check"
    is_system_error = _system_error_payload(payload, result)
    system_match = _system_error_match_context(cur, payload) if is_system_error else {}
    needs_review = _decision_needs_admin_review(result, mode) and not (system_match.get("match_status") == "matched_resolved")
    review = {}
    if needs_review:
        review_payload = _admin_payload_from_decision(payload, result, request_ip)
        review = _ensure_admin_review_from_payload(cur, review_payload, f"decision_{mode}")
        if review.get("review_id"):
            cur.execute(
                "UPDATE api_error_payment_reviews SET status='api_error' WHERE id=? AND lower(COALESCE(status,'')) IN ('pending','')",
                (review["review_id"],),
            )
        if review.get("bridge_id"):
            cur.execute(
                "UPDATE decision_admin_reviews SET status='api_error', decision_status='api_error' WHERE id=? AND lower(COALESCE(status,'')) IN ('pending','')",
                (review["bridge_id"],),
            )
            review["status"] = "api_error"
        result["admin_review"] = review
    system_case_id = 0
    if is_system_error:
        system_case_id = _insert_system_error_case(cur, payload, result, request_ip, system_match, review)
    status = _clean(result.get("status"), 40).lower() or "pending"
    log_status = "system_error" if is_system_error else ("needs_admin" if needs_review and status not in ("success", "approved") else status)
    log_id = _insert_admin_review_check(cur, {
        "review_id": review.get("review_id") if review else None,
        "bridge_id": review.get("bridge_id") if review else None,
        "action": "auto_check",
        "actor": f"decision_api:{request_ip or 'system'}",
        "amount": review.get("amount") if review else _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("expected_amount")),
        "status": log_status,
        "tier_id": None,
        "group_id": payload.get("group_id") or payload.get("group_link") or "",
        "invite_link": payload.get("invite_link") or "",
        "bot_status": "manual_required" if needs_review else ("system_error_logged" if is_system_error else "auto_checked"),
        "bot_error": str(result.get("message") or "")[:500] if (needs_review or is_system_error) else "",
        "send_status": "waiting_admin" if needs_review else "not_needed",
        "send_error": "",
        "can_retry": needs_review,
        "mode": mode,
        "payload": payload,
        "decision": result,
        "system_error_case_id": system_case_id,
        "system_error_match": system_match,
    })
    return {"log_id": log_id, "needs_review": needs_review, "admin_review": review, "system_error_case_id": system_case_id, "system_error_match": system_match}


def _record_finance_alert(payload: dict[str, Any], result: dict[str, Any], request_ip: str, visibility: dict[str, Any] | None = None) -> None:
    try:
        visibility = visibility if isinstance(visibility, dict) else {}
        mode = _clean(result.get("mode"), 80) or _clean(payload.get("event_type"), 80) or "payment_flow"
        status = _clean(result.get("status"), 80).lower()
        message = _clean(result.get("message") or result.get("reason") or status, 1000)
        needs_review = bool(visibility.get("needs_review"))
        is_problem = status in ("api_error", "system_error", "error", "needs_retry") or needs_review or _system_error_payload(payload, result)
        if not is_problem:
            return
        ids = _ids_from_payload(payload)
        match = visibility.get("system_error_match") if isinstance(visibility.get("system_error_match"), dict) else {}
        best = match.get("best") if isinstance(match.get("best"), dict) else {}
        admin_review = visibility.get("admin_review") if isinstance(visibility.get("admin_review"), dict) else {}
        source_table = _clean(best.get("table") or admin_review.get("source") or payload.get("source") or mode, 80)
        source_id = _clean(
            best.get("id")
            or admin_review.get("source_id")
            or payload.get("source_id")
            or payload.get("report_id")
            or ids.get("payment_ref")
            or ids.get("transaction_id")
            or ids.get("voucher_ref"),
            180,
        )
        amount = _review_amount(
            payload.get("amount")
            or payload.get("paid_amount")
            or payload.get("expected_amount")
            or result.get("amount")
        )
        reason_parts = [message or "finance flow needs attention"]
        if match.get("match_status"):
            reason_parts.append(f"match={match.get('match_status')}")
        if source_table or source_id:
            reason_parts.append(f"from={source_table or '-'}#{source_id or '-'}")
        if visibility.get("system_error_case_id"):
            reason_parts.append(f"system_error_case_id={visibility.get('system_error_case_id')}")
        if visibility.get("log_id"):
            reason_parts.append(f"admin_check_log_id={visibility.get('log_id')}")
        record_payment_alert(
            level="critical" if status == "system_error" else "error",
            source="decision_api",
            event_type=f"finance_{mode}_problem"[:80],
            message=message or f"{mode} problem",
            reason=" | ".join(reason_parts),
            payment_ref=ids.get("payment_ref"),
            voucher_ref=ids.get("voucher_ref") or _voucher_ref_from_url(ids.get("voucher_url")),
            transaction_id=ids.get("transaction_id"),
            amount=amount,
            current_status=status or "error",
            source_table=source_table,
            source_id=source_id,
            route=mode,
            can_retry=bool(result.get("can_retry") or needs_review),
            detail={
                "request_ip": request_ip,
                "payload_source": payload.get("source"),
                "payload_event_type": payload.get("event_type"),
                "result_status": result.get("status"),
                "result_message": result.get("message"),
                "admin_visibility": visibility,
                "api_balance": result.get("api_balance") if isinstance(result.get("api_balance"), dict) else {},
                "source_contract": result.get("source_contract") if isinstance(result.get("source_contract"), dict) else {},
            },
        )
    except Exception:
        pass


def _commit_and_record_finance_alert(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    result: dict[str, Any],
    request_ip: str,
    visibility: dict[str, Any] | None = None,
) -> None:
    conn.commit()
    _record_finance_alert(payload, result, request_ip, visibility)


def _query_first(cur: sqlite3.Cursor, table: str, candidates: list[tuple[str, str]], order_col: str = "rowid") -> dict[str, Any]:
    if not candidates or not _has_table(cur, table):
        return {}
    existing = _columns(cur, table)
    where: list[str] = []
    params: list[str] = []
    for col, value in candidates:
        if col in existing and value:
            where.append(f"{col}=?")
            params.append(value)
    if not where:
        return {}
    order = order_col if order_col in existing else "rowid"
    cur.execute(f"SELECT * FROM {table} WHERE {' OR '.join(where)} ORDER BY {order} DESC LIMIT 1", params)
    return _row_dict(cur.fetchone())


def _find_payment(cur: sqlite3.Cursor, ids: dict[str, str]) -> dict[str, Any]:
    attempt = _query_first(
        cur,
        "payment_attempts",
        [
            ("id", ids["payment_ref"]),
            ("voucher_url", ids["voucher_url"]),
            ("voucher_url", ids["voucher_ref"]),
            ("invite_link", ids["invite_link"]),
            ("package_id", ids["package_id"]),
        ],
        "created_at",
    )
    if attempt:
        return {"source": "payment_attempts", **attempt}

    review = _query_first(
        cur,
        "api_error_payment_reviews",
        [
            ("id", ids["payment_ref"]),
            ("v", ids["voucher_ref"] or ids["payment_ref"]),
            ("url", ids["voucher_url"]),
            ("user_id", ids["user_id"]),
            ("sender", ids["username"]),
        ],
        "created_at",
    )
    if review:
        return {"source": "api_error_payment_reviews", **review}

    webhook = _query_first(
        cur,
        "webhook_events",
        [
            ("transaction_id", ids["transaction_id"]),
            ("sender_mobile", _clean(ids["username"])),
            ("amount", _clean(ids.get("amount"))),
        ],
        "ts",
    )
    if webhook:
        return {"source": "webhook_events", **webhook}
    return {}


def _latest_login(cur: sqlite3.Cursor, ids: dict[str, str], ip: str) -> dict[str, Any]:
    return _query_first(
        cur,
        "package_login_users",
        [
            ("username", ids["username"]),
            ("package_id", ids["package_id"]),
            ("ip", ip),
        ],
        "ts",
    )


def _latest_user_event(cur: sqlite3.Cursor, ids: dict[str, str], ip: str, event_type: str = "") -> dict[str, Any]:
    candidates = [
        ("payment_ref", ids["payment_ref"]),
        ("session_id", ids["session_id"]),
        ("user_id", ids["user_id"]),
        ("username", ids["username"]),
        ("package_id", ids["package_id"]),
        ("invite_link", ids["invite_link"]),
        ("ip", ip),
    ]
    event = _query_first(cur, "package_user_events", candidates, "ts")
    if event_type and event and str(event.get("event_type") or "") != event_type:
        return {}
    return event


def _latest_group_click(cur: sqlite3.Cursor, ids: dict[str, str], ip: str) -> dict[str, Any]:
    return _query_first(
        cur,
        "package_group_button_events",
        [
            ("username", ids["username"]),
            ("package_name", ids["package_id"]),
            ("invite_link", ids["invite_link"]),
            ("ip", ip),
        ],
        "ts",
    )


def _latest_group_member(cur: sqlite3.Cursor, ids: dict[str, str]) -> dict[str, Any]:
    member = _query_first(
        cur,
        "group_member_events",
        [
            ("attempt_id", ids["payment_ref"]),
            ("invite_link", ids["invite_link"]),
            ("actor_user_id", ids["user_id"]),
            ("owner_user_id", ids["user_id"]),
            ("group_id", ids["invite_link"]),
        ],
        "ts",
    )
    if member:
        return {"source": "group_member_events", **member}
    attempt = _query_first(
        cur,
        "payment_attempts",
        [
            ("id", ids["payment_ref"]),
            ("invite_link", ids["invite_link"]),
            ("buyer_user_id", ids["user_id"]),
            ("joined_user_id", ids["user_id"]),
        ],
        "created_at",
    )
    return {"source": "payment_attempts", **attempt} if attempt else {}


def _ip_context(login: dict[str, Any], event: dict[str, Any], group_click: dict[str, Any], request_ip: str) -> dict[str, Any]:
    login_ip = _clean(login.get("ip"), 80)
    event_ip = _clean(event.get("ip"), 80)
    click_ip = _clean(group_click.get("ip"), 80)
    known = [value for value in (login_ip, event_ip, click_ip, request_ip) if value]
    return {
        "request_ip": request_ip,
        "login_ip": login_ip,
        "event_ip": event_ip,
        "group_click_ip": click_ip,
        "same_as_login": bool(request_ip and login_ip and request_ip == login_ip),
        "same_as_event": bool(request_ip and event_ip and request_ip == event_ip),
        "same_as_group_click": bool(request_ip and click_ip and request_ip == click_ip),
        "known_ips": sorted(set(known)),
    }


def _group_identity_context(ids: dict[str, str], group_member: dict[str, Any]) -> dict[str, Any]:
    requested_user_id = ids.get("user_id") or ""
    joined_user_id = _clean(group_member.get("joined_user_id") or group_member.get("actor_user_id"), 80)
    owner_user_id = _clean(group_member.get("owner_user_id") or group_member.get("buyer_user_id"), 80)
    joined_username = _clean(group_member.get("joined_username") or group_member.get("actor_username"), 120)
    return {
        "requested_user_id": requested_user_id,
        "joined_user_id": joined_user_id,
        "owner_user_id": owner_user_id,
        "joined_username": joined_username,
        "same_as_joined_user": bool(requested_user_id and joined_user_id and requested_user_id == joined_user_id),
        "same_as_owner_user": bool(requested_user_id and owner_user_id and requested_user_id == owner_user_id),
        "known": bool(group_member),
    }


def _decision_payload(payload: dict[str, Any], request_ip: str, mode: str) -> dict[str, Any]:
    ids = _ids_from_payload(payload)
    conn = _conn()
    cur = conn.cursor()
    payment = _find_payment(cur, ids)
    login = _latest_login(cur, ids, request_ip)
    event = _latest_user_event(cur, ids, request_ip)
    group_click = _latest_group_click(cur, ids, request_ip)
    group_member = _latest_group_member(cur, ids)
    slip_context = _slip_hash_context(cur, ids)
    admin_review = _admin_review_context(cur, ids)
    conn.close()

    status, reason, ready = _status_from_record(payment) if payment else ("pending", "no matching payment record yet", False)
    if admin_review and not ready:
        status, reason, ready = _status_from_record(admin_review)
        if status == "pending":
            reason = "manual admin review is pending"
    if mode == "group_status":
        current_event_type = _clean(payload.get("event_type"), 80).lower()
        if group_member:
            status, reason, ready = _status_from_record(group_member)
        elif group_click:
            status, reason, ready = "pending", "group button clicked, waiting for bot/member event", False
        elif any(term in current_event_type for term in ("group", "invite", "enter")):
            status, reason, ready = "pending", "group click received, waiting for bot/member event", False
        else:
            status, reason, ready = "pending", "no group button/member evidence yet", False
    elif mode == "recheck" and ids["slip_hash"]:
        if slip_context["seen_before"]:
            reason = f"{reason}; raw image/slip hash matched previous check"
        else:
            reason = f"{reason}; raw image/slip hash stored for future comparison"

    ip = _ip_context(login, event, group_click, request_ip)
    group_identity = _group_identity_context(ids, group_member)
    api_summary = {
        "mode": mode,
        "payment_found": bool(payment),
        "login_found": bool(login),
        "event_found": bool(event),
        "group_button_found": bool(group_click),
        "group_member_found": bool(group_member),
    }
    system_summary = {
        "admin_review": admin_review,
        "raw_image_context": slip_context,
        "ip_context": ip,
        "group_identity": group_identity,
    }
    return {
        "ok": True,
        "ready": ready,
        "status": status,
        "message": reason,
        "reason": reason,
        "decision_logic": _decision_logic_payload(status, reason, api=api_summary, system_server=system_summary),
        "mode": mode,
        "identity": {key: value for key, value in ids.items() if value and key != "slip_hash"},
        "raw_image_hash": ids["slip_hash"],
        "raw_image_context": slip_context,
        "ip_context": ip,
        "group_identity": group_identity,
        "payment": payment,
        "login": login,
        "event": event,
        "group_button": group_click,
        "group_member": group_member,
        "admin_review": admin_review,
    }


def _raw_source_payload(payload: dict[str, Any], request_ip: str) -> dict[str, Any]:
    raw = payload.get("raw")
    raw_payload = raw if isinstance(raw, dict) else {}
    qr_number = _clean(
        payload.get("qr_number")
        or payload.get("qr_ref")
        or payload.get("qr")
        or raw_payload.get("qr_number")
        or raw_payload.get("qr_ref")
        or raw_payload.get("qr"),
        180,
    )
    voucher_url = _clean(
        payload.get("voucher_url")
        or payload.get("truemoney_url")
        or payload.get("link")
        or payload.get("url")
        or raw_payload.get("voucher_url")
        or raw_payload.get("link")
        or raw_payload.get("url"),
        600,
    )
    reference_id = _clean(
        payload.get("reference_id")
        or payload.get("transaction_id")
        or payload.get("trans_id")
        or payload.get("ref")
        or raw_payload.get("reference_id")
        or raw_payload.get("transaction_id")
        or raw_payload.get("trans_id")
        or raw_payload.get("ref"),
        180,
    )
    voucher_ref = _clean(
        payload.get("voucher_ref")
        or payload.get("v")
        or raw_payload.get("voucher_ref")
        or raw_payload.get("v")
        or _voucher_ref_from_url(voucher_url),
        180,
    )
    source_id = _clean(
        payload.get("source_id")
        or payload.get("report_id")
        or payload.get("payment_ref")
        or payload.get("attempt_id")
        or reference_id
        or voucher_ref
        or qr_number
        or _raw_hash(_payload_json({"payload": payload, "request_ip": request_ip}))[:24],
        180,
    )
    return {
        **payload,
        "source": payload.get("source") or "raw_upstream",
        "event_type": payload.get("event_type") or "raw_payment_evidence",
        "source_id": source_id,
        "report_id": payload.get("report_id") or source_id,
        "payment_ref": payload.get("payment_ref") or payload.get("attempt_id") or reference_id or qr_number,
        "reference_id": reference_id,
        "transaction_id": payload.get("transaction_id") or reference_id,
        "voucher_url": voucher_url,
        "truemoney_url": payload.get("truemoney_url") or voucher_url,
        "voucher_ref": voucher_ref,
        "v": payload.get("v") or voucher_ref,
        "qr_number": qr_number,
        "raw_evidence": raw_payload or payload,
    }


def _raw_auto_match(cur: sqlite3.Cursor, payload: dict[str, Any]) -> dict[str, Any]:
    amount = _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("expected_amount") or payload.get("received_amount"))
    money_log = _successful_money_log(cur, payload, amount)
    if money_log:
        return {"matched": True, "table": "money_in_ledger", "record": money_log, "status": "success", "reason": "raw reference matched paid money ledger"}

    ids = _ids_from_payload(payload)
    payment = _find_payment(cur, ids)
    if payment:
        status, reason, ready = _status_from_record(payment)
        return {"matched": True, "table": payment.get("source") or "payment", "record": payment, "status": status, "ready": ready, "reason": reason}

    system_match = _system_error_match_context(cur, payload)
    if system_match.get("match_status") == "matched_resolved":
        return {"matched": True, "table": system_match.get("matched_table") or "system_error_cases", "record": system_match, "status": "success", "ready": True, "reason": "raw reference matched resolved server case"}
    if system_match.get("match_status"):
        return {"matched": False, "table": system_match.get("matched_table") or "", "record": system_match, "status": "pending", "ready": False, "reason": "raw reference has related server evidence but is not resolved"}
    return {"matched": False, "status": "pending", "ready": False, "reason": "no matching raw payment evidence found"}


def decision_snapshot(payload: dict[str, Any], mode: str = "payment_check", request_ip: str = "") -> dict[str, Any]:
    """Public in-process adapter for web pages that need the same decision logic."""
    safe_payload = payload if isinstance(payload, dict) else {}
    return _decision_payload(safe_payload, _clean(request_ip, 80), _clean(mode, 80) or "payment_check")


def _log_decision_event(request: Request, payload: dict[str, Any], result: dict[str, Any], request_ip: str) -> None:
    try:
        admin_visibility: dict[str, Any] = {}
        conn = _conn()
        cur = conn.cursor()
        ids = _ids_from_payload(payload)
        payload_event_type = _clean(payload.get("event_type"), 80)
        decision_event_type = f"decision_{payload_event_type}"[:80] if payload_event_type else "decision_check"
        _ensure_decision_tables(cur)
        cur.execute(
            """
            INSERT INTO decision_checks (
                ts, mode, payment_ref, voucher_ref, transaction_id, session_id, username,
                user_id, package_id, invite_link, slip_hash, status, request_ip, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(time.time()),
                str(result.get("mode") or "")[:80],
                ids["payment_ref"],
                ids["voucher_ref"],
                ids["transaction_id"],
                ids["session_id"],
                ids["username"],
                ids["user_id"],
                ids["package_id"],
                ids["invite_link"],
                ids["slip_hash"],
                str(result.get("status") or "")[:80],
                request_ip,
                _payload_json(payload),
            ),
        )
        admin_visibility = _record_decision_admin_visibility(cur, payload, result, request_ip)
        result["admin_visibility"] = admin_visibility
        money_match = admin_visibility.get("system_error_match") if isinstance(admin_visibility, dict) else {}
        if _looks_like_money_in(payload, result) and not money_match:
            money_match = _system_error_match_context(cur, payload)
        money_log_id = _record_money_in_ledger(cur, payload, result, request_ip, match=money_match)
        if money_log_id:
            result["money_in_log_id"] = money_log_id
        if not _has_table(cur, "package_user_events"):
            _commit_and_record_finance_alert(conn, payload, result, request_ip, admin_visibility)
            conn.close()
            return
        for column_name, column_sql in {
            "balance_before": "balance_before REAL DEFAULT 0.0",
            "balance_after": "balance_after REAL DEFAULT 0.0",
            "balance_delta": "balance_delta REAL DEFAULT 0.0",
            "expected_amount": "expected_amount REAL DEFAULT 0.0",
            "purchase_state": "purchase_state TEXT",
            "can_send_link": "can_send_link INTEGER NOT NULL DEFAULT 0",
            "balance_passed": "balance_passed INTEGER NOT NULL DEFAULT 0",
            "send_link_state": "send_link_state TEXT",
            "api_balance_check_id": "api_balance_check_id INTEGER",
            "money_log_id": "money_log_id INTEGER",
        }.items():
            _add_column_if_missing(cur, "package_user_events", column_name, column_sql)
        api_balance = result.get("api_balance") if isinstance(result.get("api_balance"), dict) else {}
        balance_before = _review_amount(payload.get("balance_before") or api_balance.get("previous_balance"))
        balance_after = _review_amount(payload.get("balance_after") or api_balance.get("balance"))
        balance_delta = _review_amount(payload.get("balance_delta") or api_balance.get("balance_delta") or api_balance.get("direct_amount"))
        expected_amount = _review_amount(payload.get("expected_amount") or api_balance.get("expected_amount") or payload.get("amount"))
        purchase_state = _clean(payload.get("purchase_state") or result.get("purchase_state") or api_balance.get("purchase_state"), 80)
        balance_passed = 1 if (payload.get("balance_passed") is True or result.get("balance_passed") is True or api_balance.get("balance_passed") is True) else 0
        can_send_link = 1 if (payload.get("can_send_link") is True or result.get("can_send_link") is True or api_balance.get("can_send_link") is True) else 0
        send_link_state = _clean(payload.get("send_link_state") or result.get("send_link_state") or api_balance.get("send_link_state"), 80)
        cur.execute(
            """
            INSERT INTO package_user_events (
                event_type, session_id, user_id, username, package_id, package_name, amount,
                payment_ref, status, group_id, invite_link, source, path, ip,
                user_agent, raw_payload, note, balance_before, balance_after, balance_delta,
                expected_amount, purchase_state, can_send_link, balance_passed, send_link_state,
                api_balance_check_id, money_log_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_event_type,
                ids["session_id"],
                ids["user_id"],
                ids["username"],
                ids["package_id"],
                _clean(payload.get("package_name"), 120),
                float(str(payload.get("amount") or "0").replace(",", "") or 0),
                ids["payment_ref"],
                str(result.get("status") or "")[:80],
                _clean(payload.get("group_id"), 80),
                ids["invite_link"],
                "decision_api",
                str(request.url.path)[:180],
                request_ip,
                request.headers.get("user-agent", "")[:240],
                _payload_json(payload),
                str(result.get("message") or "")[:500],
                balance_before,
                balance_after,
                balance_delta,
                expected_amount,
                purchase_state,
                can_send_link,
                balance_passed,
                send_link_state,
                _review_user_id(api_balance.get("check_id") or payload.get("api_balance_check_id")) or None,
                _review_user_id(api_balance.get("money_log_id") or result.get("money_in_log_id") or payload.get("money_log_id")) or None,
            ),
        )
        group_event_type = payload_event_type.lower()
        if _has_table(cur, "package_group_button_events") and any(term in group_event_type for term in ("group", "invite", "enter")):
            cur.execute(
                """
                INSERT INTO package_group_button_events (
                    action, username, package_name, invite_link, source, path, ip, user_agent, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload_event_type or "decision_group_event",
                    ids["username"],
                    _clean(payload.get("package_name") or ids["package_id"], 120),
                    ids["invite_link"],
                    "decision_api",
                    str(request.url.path)[:180],
                    request_ip,
                    request.headers.get("user-agent", "")[:240],
                    str(result.get("message") or "")[:500],
                ),
            )
        _commit_and_record_finance_alert(conn, payload, result, request_ip, admin_visibility)
        conn.close()
    except Exception:
        pass


async def _payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


@router.post("/payment/check")
async def payment_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    result = _decision_payload(payload, request_ip, "payment_check")
    _log_decision_event(request, payload, result, request_ip)
    return JSONResponse(result)


@router.post("/payment/recheck")
async def payment_recheck(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    result = _decision_payload(payload, request_ip, "recheck")
    _log_decision_event(request, payload, result, request_ip)
    return JSONResponse(result)


@router.post("/missing-slip/check")
async def missing_slip_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    conn = _conn()
    cur = conn.cursor()
    admin_review = _ensure_admin_review_from_payload(cur, payload, "missing_slip_reports")
    conn.commit()
    conn.close()

    merged_payload = {
        **payload,
        "payment_ref": payload.get("payment_ref") or payload.get("attempt_id") or admin_review.get("payment_ref") or admin_review.get("source_id"),
        "voucher_ref": payload.get("voucher_ref") or admin_review.get("voucher_ref"),
        "voucher_url": payload.get("voucher_url") or admin_review.get("truemoney_url"),
    }
    result = _decision_payload(merged_payload, request_ip, "missing_slip_check")
    result["admin_review"] = admin_review
    _log_decision_event(request, merged_payload, result, request_ip)
    return JSONResponse(result)


@router.post("/raw/check")
async def raw_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    raw_payload = _raw_source_payload(payload, request_ip)

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    match = _raw_auto_match(cur, raw_payload)
    conn.commit()
    conn.close()

    if match.get("matched") and str(match.get("status") or "") in ("success", "approved", "paid", "already_passed"):
        status = "success"
        ready = True
        reason = str(match.get("reason") or "raw evidence matched automatically")
        api_summary = {
            "status": "auto_matched",
            "message": "raw evidence matched automatically",
            "match_table": match.get("table"),
            "match_status": match.get("status"),
        }
        system_summary = {
            "raw_check": "auto_match",
            "admin_review_required": False,
            "match": match,
        }
    else:
        status = "system_error"
        ready = False
        reason = str(match.get("reason") or "raw evidence was not found in central logs; queued for admin review")
        api_summary = {
            "status": "raw_not_found",
            "message": "raw evidence did not match automatically",
            "match_table": match.get("table") or "",
            "match_status": match.get("status") or "pending",
        }
        system_summary = {
            "raw_check": "manual_review_queued",
            "admin_review_required": True,
            "reason": reason,
            "admin_review": {},
            "match": match,
        }

    result = {
        "ok": True,
        "ready": ready,
        "status": status,
        "message": reason,
        "reason": reason,
        "mode": "raw_check",
        "identity": {key: value for key, value in _ids_from_payload(raw_payload).items() if value and key != "slip_hash"},
        "raw_received": {
            "qr_number": raw_payload.get("qr_number") or "",
            "voucher_url": raw_payload.get("voucher_url") or "",
            "voucher_ref": raw_payload.get("voucher_ref") or "",
            "reference_id": raw_payload.get("reference_id") or raw_payload.get("transaction_id") or "",
            "source_id": raw_payload.get("source_id") or "",
        },
        "match": match,
        "admin_review": {},
        "decision_logic": _decision_logic_payload(
            "success" if ready else "error",
            reason,
            api=api_summary,
            system_server=system_summary,
        ),
    }
    _log_decision_event(request, raw_payload, result, request_ip)
    if not ready:
        visibility = result.get("admin_visibility") if isinstance(result.get("admin_visibility"), dict) else {}
        review = visibility.get("admin_review") if isinstance(visibility.get("admin_review"), dict) else {}
        result["admin_review"] = review
        system_server = result.get("decision_logic", {}).get("system_server") if isinstance(result.get("decision_logic"), dict) else {}
        if isinstance(system_server, dict):
            system_server["admin_review"] = review
            system_server["admin_visibility"] = visibility
    return JSONResponse(result)


@router.post("/system-error/check")
async def system_error_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    passed_log = _successful_money_log(cur, payload, _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("received_amount")))
    conn.close()
    if passed_log:
        return JSONResponse({
            "ok": True,
            "ready": True,
            "status": "already_passed",
            "message": "this reference already passed; skipped duplicate system-error check",
            "mode": "system_error_check",
            "existing_money_log": passed_log,
            "can_retry": False,
        })
    system_payload = {
        **payload,
        "status": payload.get("status") or "system_error",
        "event_type": payload.get("event_type") or payload.get("error_type") or "system_error_report",
    }
    result = _decision_payload(system_payload, request_ip, "system_error_check")
    if result.get("status") == "pending":
        result["status"] = "system_error"
        result["ready"] = False
        result["message"] = result.get("message") or "system error report received from source"
    _log_decision_event(request, system_payload, result, request_ip)
    return JSONResponse(result)


@router.post("/truemoney/voucher/redeem")
async def truemoney_voucher_redeem(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    return JSONResponse(process_truemoney_voucher(payload, request_ip))


@router.post("/truemoney/balance/check")
async def truemoney_balance_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    passed_log = _successful_money_log(cur, payload, _review_amount(payload.get("amount") or payload.get("paid_amount") or payload.get("received_amount")))
    conn.close()
    if passed_log:
        return JSONResponse({
            "ok": True,
            "ready": True,
            "status": "already_passed",
            "message": "this reference already passed; skipped balance api check",
            "mode": "truemoney_balance_check",
            "existing_money_log": passed_log,
            "can_retry": False,
        })
    token = _api_token_from_request(request, payload)
    api_result = _call_truemoney_balance_api(token)

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    previous_balance = _previous_api_balance(cur)
    balance = _review_amount(api_result.get("balance"))
    delta = balance - previous_balance if api_result.get("ok") and previous_balance > 0 and balance > previous_balance else 0.0
    check_id = _insert_api_balance_check(
        cur,
        request_ip=request_ip,
        api_result=api_result,
        previous_balance=previous_balance,
        delta=delta,
        money_log_id=0,
    )
    money_log_id = 0
    purchase_state = _balance_purchase_state(
        cur,
        payload,
        api_ok=bool(api_result.get("ok")),
        balance=balance,
        previous_balance=previous_balance,
        delta=delta,
        money_log_id=money_log_id,
    )
    if api_result.get("ok") and purchase_state["user_id"]:
        _upsert_user_balance(cur, int(purchase_state["user_id"]), balance, "truemoney_balance_check", {
            "payload": payload,
            "api_result": api_result,
            "api_balance_check_id": check_id,
        })
    cur.execute(
        """
        UPDATE api_balance_checks
        SET expected_amount=?, purchase_state=?, can_send_link=?, route_group_id=?,
            balance_passed=?, send_link_state=?
        WHERE id=?
        """,
        (
            purchase_state["expected_amount"],
            purchase_state["purchase_state"],
            1 if purchase_state["can_send_link"] else 0,
            purchase_state["route_group_id"],
            1 if purchase_state["balance_passed"] else 0,
            purchase_state["send_link_state"],
            check_id,
        ),
    )
    conn.commit()
    conn.close()

    status = "success" if purchase_state["can_deduct"] else "error"
    message = _clean(api_result.get("message") or ("balance api success" if api_result.get("ok") else "balance api failed"), 500)
    if api_result.get("ok") and previous_balance <= 0:
        message = "balance baseline stored; waiting for the next real increase"
    elif delta > 0:
        message = f"balance increased by {delta:g}; waiting for source send-link confirmation"
    if not purchase_state["can_send_link"]:
        message = purchase_state["reason"]
    decision_payload = {
        "source": "truemoney_balance_api",
        "event_type": "truemoney_balance_check" if api_result.get("ok") else "truemoney_balance_api_error",
        "source_id": f"api_balance_check:{check_id}",
        "report_id": f"api_balance_check:{check_id}",
        "payment_ref": str(check_id),
        "transaction_id": f"balance_check:{check_id}",
        "status": status,
        "amount": purchase_state["expected_amount"] or delta,
        "group_id": purchase_state["route_group_id"],
        "user_id": purchase_state["user_id"],
        "api_balance_check_id": check_id,
        "request_ip": request_ip,
        "balance_before": previous_balance,
        "balance_after": balance,
        "balance_delta": delta,
        "purchase_state": purchase_state["purchase_state"],
        "balance_state": purchase_state["balance_state"],
        "balance_status": purchase_state["balance_status"],
        "balance_passed": purchase_state["balance_passed"],
        "can_deduct": purchase_state["can_deduct"],
        "can_send_link": purchase_state["can_send_link"],
        "send_link_state": purchase_state["send_link_state"],
    }
    decision_result = {
        "ok": bool(api_result.get("ok")),
        "ready": bool(purchase_state["can_send_link"]),
        "status": status,
        "message": message,
        "reason": message,
        "mode": "truemoney_balance_check",
        "purchase_state": purchase_state["purchase_state"],
        "balance_state": purchase_state["balance_state"],
        "balance_status": purchase_state["balance_status"],
        "balance_passed": purchase_state["balance_passed"],
        "can_deduct": purchase_state["can_deduct"],
        "can_send_link": purchase_state["can_send_link"],
        "send_link_state": purchase_state["send_link_state"],
        "route_match": purchase_state["route_match"],
        "balance_user_id": purchase_state["user_id"],
        "api_balance": {
            "check_id": check_id,
            "api_url": TRUEMONEY_BALANCE_API_URL,
            "http_status": int(api_result.get("http_status") or 0),
            "balance": balance,
            "previous_balance": previous_balance,
            "balance_delta": delta,
            "money_log_id": money_log_id,
            "expected_amount": purchase_state["expected_amount"],
            "purchase_state": purchase_state["purchase_state"],
            "balance_state": purchase_state["balance_state"],
            "balance_status": purchase_state["balance_status"],
            "balance_passed": purchase_state["balance_passed"],
            "can_deduct": purchase_state["can_deduct"],
            "can_send_link": purchase_state["can_send_link"],
            "send_link_state": purchase_state["send_link_state"],
            "route_group_id": purchase_state["route_group_id"],
            "user_id": purchase_state["user_id"],
            "can_retry": True,
            "retry_endpoint": "/decision-api/truemoney/balance/check",
            "baseline_only": bool(api_result.get("ok") and previous_balance <= 0 and not money_log_id),
        },
    }
    decision_result["source_contract"] = source_flow_status({
        **decision_payload,
        **decision_result,
        "reason": decision_result["reason"],
        "balance_before": previous_balance,
        "balance_after": balance,
        "expected_amount": purchase_state["expected_amount"],
        "group_id": purchase_state["route_group_id"],
    })
    _log_decision_event(request, decision_payload, decision_result, request_ip)
    return JSONResponse(decision_result)


@router.post("/truemoney/money/receive/check")
async def truemoney_money_receive_check(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    raw_response = payload.get("api_response") or payload.get("response") or payload.get("payload") or payload
    http_status = int(_review_amount(payload.get("http_status") or payload.get("status_code") or 200))
    status_text = " ".join(
        str(value or "")
        for value in (
            payload.get("status"),
            payload.get("event_type"),
            payload.get("event"),
            payload.get("message"),
            payload.get("error"),
        )
    ).lower()
    is_error = http_status >= 400 or any(term in status_text for term in ("error", "failed", "fail", "timeout", "api_error", "system_error"))
    api_result = {
        "ok": not is_error,
        "status": "api_error" if is_error else "success",
        "http_status": http_status,
        "message": _clean(payload.get("message") or payload.get("note") or ("money receive payload received" if not is_error else "money receive error payload received"), 500),
        "raw_response": raw_response,
    }
    receive_items = _receive_items_from_api_response(raw_response)

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    events = []
    ignored_count = 0
    for raw_item in receive_items:
        event = _money_receive_event(raw_item)
        if _review_amount(event.get("amount")) <= 0:
            ignored_count += 1
            continue
        api_log_id, money_log_id, is_new = _insert_api_money_receive_log(
            cur,
            request_ip=request_ip,
            api_result=api_result,
            event=event,
            raw_item=raw_item,
        )
        events.append({
            **event,
            "api_money_receive_log_id": api_log_id,
            "money_log_id": money_log_id,
            "is_new": is_new,
        })
    malformed_payload = (not receive_items) or (bool(receive_items) and not events)
    status = "system_error" if is_error or malformed_payload else "success"
    message = _clean(api_result.get("message") or "money receive payload logged", 500)
    if malformed_payload and not is_error:
        message = "money receive payload has no valid money-in item"
    admin_visibility: dict[str, Any] = {}
    admin_alert: dict[str, Any] = {"ok": False, "status": "not_needed"}
    if status == "system_error":
        first_event = events[0] if events else {}
        system_payload = {
            "source": "truemoney_money_receive_receiver",
            "event_type": "money_receive_payload_error",
            "source_id": first_event.get("transaction_id") or payload.get("source_id") or payload.get("report_id") or f"money_receive:{int(time.time())}",
            "report_id": first_event.get("transaction_id") or payload.get("report_id") or "",
            "transaction_id": first_event.get("transaction_id") or payload.get("transaction_id") or payload.get("reference_id") or "",
            "amount": first_event.get("amount") or payload.get("amount") or payload.get("received_amount") or 0,
            "status": "system_error",
            "message": message,
            "request_ip": request_ip,
            "raw_payload": _redact_secrets(payload),
        }
        auto_match = _system_error_match_context(cur, system_payload)
        if auto_match.get("match_status") == "matched_resolved":
            status = "success"
            message = "money receive error auto-resolved from money log"
            admin_visibility = {
                "needs_review": False,
                "system_error_match": auto_match,
                "auto_resolved": True,
            }
        else:
            decision_result = {
                "ok": False,
                "ready": False,
                "status": "system_error",
                "message": message,
                "mode": "truemoney_money_receive_receiver",
                "can_retry": True,
            }
            admin_visibility = _record_decision_admin_visibility(cur, system_payload, decision_result, request_ip)
            alert_text = (
                "[PAPAN Money API BUG]\n"
                f"status: {status}\n"
                f"message: {message}\n"
                f"ip: {request_ip or '-'}\n"
                f"items: {len(receive_items)} / valid: {len(events)} / ignored: {ignored_count}\n"
                f"system_error_case_id: {admin_visibility.get('system_error_case_id') or '-'}"
            )
            admin_alert = _send_admin_alert(alert_text)
    if status == "system_error" and isinstance(locals().get("decision_result"), dict):
        _commit_and_record_finance_alert(
            conn,
            {**system_payload, "receive_items": len(receive_items), "valid_events": len(events), "ignored_count": ignored_count},
            decision_result,
            request_ip,
            admin_visibility,
        )
    else:
        conn.commit()
    conn.close()

    new_events = [event for event in events if event["is_new"]]
    api_summary = {
        "endpoint": "/decision-api/truemoney/money/receive/check",
        "api_url": TRUEMONEY_MONEY_RECEIVE_API_URL,
        "http_status": int(api_result.get("http_status") or 0),
        "count": len(events),
        "new_count": len(new_events),
        "duplicate_count": len(events) - len(new_events),
        "ignored_count": ignored_count,
    }
    system_summary = {
        "needs_review": bool(admin_visibility.get("needs_review")) if admin_visibility else False,
        "admin_review": admin_visibility.get("admin_review") if isinstance(admin_visibility, dict) else {},
        "system_error_case_id": admin_visibility.get("system_error_case_id") if isinstance(admin_visibility, dict) else 0,
        "auto_resolved": bool(admin_visibility.get("auto_resolved")) if isinstance(admin_visibility, dict) else False,
        "admin_alert": admin_alert,
    }
    return JSONResponse({
        "ok": status != "system_error",
        "ready": status != "system_error",
        "status": status,
        "message": message,
        "reason": message,
        "decision_logic": _decision_logic_payload(
            "success" if status != "system_error" else "error",
            message,
            api=api_summary,
            system_server=system_summary,
        ),
        "mode": "truemoney_money_receive_receiver",
        "api_url": TRUEMONEY_MONEY_RECEIVE_API_URL,
        "http_status": int(api_result.get("http_status") or 0),
        "count": len(events),
        "new_count": len(new_events),
        "duplicate_count": len(events) - len(new_events),
        "ignored_count": ignored_count,
        "notify": new_events,
        "admin_visibility": admin_visibility,
        "admin_alert": admin_alert,
        "events": events,
    })


@router.get("/truemoney/money/receive/logs")
def truemoney_money_receive_logs(limit: int = 50):
    safe_limit = max(1, min(int(limit or 50), 200))
    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    cur.execute(
        """
        SELECT id, ts, event_type, amount, sender_mobile, receiver_mobile,
               received_time, transaction_id, message, status, money_log_id
        FROM api_money_receive_logs
        ORDER BY ts DESC, id DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    rows = [_row_dict(row) for row in cur.fetchall()]
    conn.close()
    return JSONResponse({"ok": True, "count": len(rows), "logs": rows})


@router.get("/truemoney/money/receive/info")
def truemoney_money_receive_info():
    return JSONResponse({
        "ok": True,
        "endpoint": "/decision-api/truemoney/money/receive/check",
        "method": "POST",
        "purpose": "receive money-in payloads and store API-only logs without user binding",
        "api_url": TRUEMONEY_MONEY_RECEIVE_API_URL,
        "token": "not required; upstream posts the receive payload here",
        "decision_logic": {
            "success": ["reason", "api"],
            "error": ["reason", "api", "system_server"],
            "approved": ["reason", "system_server"],
            "rejected": ["reason", "system_server"],
        },
        "tables": ["api_money_receive_logs", "money_in_ledger"],
        "duplicate_rule": "same transaction_id is treated as duplicate and is not inserted again",
        "bug_alert": {
            "logs": ["system_error_cases", "admin_review_checks"],
            "push": "Telegram admin group when ADMIN_ALERT_BOT_TOKEN and ADMIN_ALERT_CHAT_ID are configured",
            "triggers": ["payload status/error", "http_status >= 400", "no valid money-in item"],
        },
        "example_payload": {
            "status": "ok",
            "data": [{
                "event_type": "P2P",
                "amount": "100.00",
                "sender_number": "0812345678",
                "receiver_number": "0813333444",
                "received_time": "2024-04-01 14:20:34",
                "transaction_id": "202508261015009876",
                "message": "Payment from friend",
            }],
        },
    })


@router.post("/truemoney/balance/webhook")
async def truemoney_balance_webhook(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    api_response = payload.get("api_response") or payload.get("response") or payload.get("data") or payload
    api_response = api_response if isinstance(api_response, dict) else {"value": api_response}
    redacted_api_response = _redact_secrets(api_response)
    evidence_payload = {**api_response, **payload}
    balance = _extract_balance_value(api_response) or _extract_balance_value(payload)
    direct_amount = _webhook_money_amount(evidence_payload)
    http_status = int(_review_amount(payload.get("http_status") or payload.get("status_code") or api_response.get("http_status") or api_response.get("status_code")))
    status_text = " ".join(
        str(value or "")
        for value in (
            payload.get("status"),
            payload.get("event_type"),
            payload.get("event"),
            payload.get("message"),
            payload.get("error"),
            api_response.get("status"),
            api_response.get("message"),
            api_response.get("error"),
            api_response.get("code"),
        )
    ).lower()
    is_error = http_status >= 400 or any(term in status_text for term in ("error", "failed", "fail", "timeout", "network", "server", "api_error", "system_error"))
    api_result = {
        "ok": not is_error,
        "status": "api_error" if is_error else "success",
        "http_status": http_status,
        "message": _clean(payload.get("message") or payload.get("note") or api_response.get("message") or api_response.get("error") or ("webhook error received" if is_error else "webhook received"), 500),
        "balance": balance,
        "raw_response": redacted_api_response,
    }

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    passed_log = _successful_money_log(cur, evidence_payload, direct_amount)
    if passed_log:
        contract = source_flow_status({
            "ok": True,
            "ready": True,
            "status": "already_passed",
            "reason": "already_passed",
            "mode": "truemoney_balance_webhook",
        })
        conn.close()
        return JSONResponse({
            "ok": True,
            "ready": True,
            "status": "already_passed",
            "message": "this money-in reference already passed; skipped duplicate check",
            "mode": "truemoney_balance_webhook",
            "existing_money_log": passed_log,
            "can_retry": False,
            "source_contract": contract,
        })
    previous_balance = _previous_api_balance(cur)
    balance_delta = balance - previous_balance if (not is_error and previous_balance > 0 and balance > previous_balance) else 0.0
    check_id = _insert_api_balance_check(
        cur,
        request_ip=request_ip,
        api_result=api_result,
        previous_balance=previous_balance,
        delta=balance_delta,
        money_log_id=0,
    )
    money_log_id = 0
    purchase_state = _balance_purchase_state(
        cur,
        payload,
        api_ok=not is_error,
        balance=balance,
        previous_balance=previous_balance,
        delta=direct_amount or balance_delta,
        money_log_id=money_log_id,
    )
    if not is_error and purchase_state["user_id"]:
        _upsert_user_balance(cur, int(purchase_state["user_id"]), balance, "truemoney_balance_webhook", {
            "payload": payload,
            "api_response": redacted_api_response,
            "api_balance_check_id": check_id,
        })
    cur.execute(
        """
        UPDATE api_balance_checks
        SET expected_amount=?, purchase_state=?, can_send_link=?, route_group_id=?,
            balance_passed=?, send_link_state=?
        WHERE id=?
        """,
        (
            purchase_state["expected_amount"],
            purchase_state["purchase_state"],
            1 if purchase_state["can_send_link"] else 0,
            purchase_state["route_group_id"],
            1 if purchase_state["balance_passed"] else 0,
            purchase_state["send_link_state"],
            check_id,
        ),
    )
    conn.commit()
    conn.close()

    decision_status = "success" if purchase_state["can_deduct"] else "error"
    decision_payload = {
        **{key: value for key, value in payload.items() if key.lower() not in ("token", "api_token", "authorization", "secret")},
        "source": payload.get("source") or "truemoney_balance_webhook",
        "event_type": payload.get("event_type") or ("truemoney_balance_webhook_error" if is_error else "truemoney_balance_webhook"),
        "source_id": payload.get("source_id") or f"api_balance_check:{check_id}",
        "report_id": payload.get("report_id") or f"api_balance_check:{check_id}",
        "payment_ref": payload.get("payment_ref") or str(check_id),
        "transaction_id": payload.get("transaction_id") or payload.get("reference_id") or f"balance_webhook:{check_id}",
        "status": decision_status,
        "amount": purchase_state["expected_amount"] or direct_amount or balance_delta,
        "group_id": purchase_state["route_group_id"],
        "user_id": purchase_state["user_id"],
        "api_balance_check_id": check_id,
        "request_ip": request_ip,
        "balance_before": previous_balance,
        "balance_after": balance,
        "balance_delta": direct_amount or balance_delta,
        "purchase_state": purchase_state["purchase_state"],
        "balance_state": purchase_state["balance_state"],
        "balance_status": purchase_state["balance_status"],
        "balance_passed": purchase_state["balance_passed"],
        "can_deduct": purchase_state["can_deduct"],
        "can_send_link": purchase_state["can_send_link"],
        "send_link_state": purchase_state["send_link_state"],
    }
    message = api_result["message"] if is_error else purchase_state["reason"]
    decision_result = {
        "ok": not is_error,
        "ready": bool(purchase_state["can_send_link"]),
        "status": decision_status,
        "message": message,
        "reason": message,
        "mode": "truemoney_balance_webhook",
        "purchase_state": purchase_state["purchase_state"],
        "balance_state": purchase_state["balance_state"],
        "balance_status": purchase_state["balance_status"],
        "balance_passed": purchase_state["balance_passed"],
        "can_deduct": purchase_state["can_deduct"],
        "can_send_link": purchase_state["can_send_link"],
        "send_link_state": purchase_state["send_link_state"],
        "route_match": purchase_state["route_match"],
        "balance_user_id": purchase_state["user_id"],
        "api_balance": {
            "check_id": check_id,
            "balance": balance,
            "previous_balance": previous_balance,
            "balance_delta": balance_delta,
            "direct_amount": direct_amount,
            "money_log_id": money_log_id,
            "expected_amount": purchase_state["expected_amount"],
            "purchase_state": purchase_state["purchase_state"],
            "balance_state": purchase_state["balance_state"],
            "balance_status": purchase_state["balance_status"],
            "balance_passed": purchase_state["balance_passed"],
            "can_deduct": purchase_state["can_deduct"],
            "can_send_link": purchase_state["can_send_link"],
            "send_link_state": purchase_state["send_link_state"],
            "route_group_id": purchase_state["route_group_id"],
            "user_id": purchase_state["user_id"],
            "can_retry": True,
            "retry_endpoint": "/decision-api/truemoney/balance/webhook",
            "baseline_only": bool(not is_error and balance > 0 and previous_balance <= 0 and not money_log_id),
        },
        "api_response": redacted_api_response,
    }
    decision_result["source_contract"] = source_flow_status({
        **decision_payload,
        **decision_result,
        "reason": decision_result["reason"],
        "balance_before": previous_balance,
        "balance_after": balance,
        "expected_amount": purchase_state["expected_amount"],
        "group_id": purchase_state["route_group_id"],
    })
    _log_decision_event(request, decision_payload, decision_result, request_ip)
    return JSONResponse(decision_result)


@router.get("/truemoney/balance/webhook/info")
def truemoney_balance_webhook_info():
    return JSONResponse({
        "ok": True,
        "endpoint": "/decision-api/truemoney/balance/webhook",
        "method": "POST",
        "purpose": "รับคำตอบ API ดิบจากต้นทาง แล้วบันทึก workflow/log เงินเข้า/system error",
        "rules": [
            "ส่งคำตอบ API ดิบไว้ใน api_response, response หรือ data",
            "ถ้า api_response มี amount + transaction_id จะลง money_in_ledger",
            "ถ้า api_response มี balance จะเก็บ baseline และดู balance_delta รอบถัดไป",
            "ถ้า status/error/http_status บอกว่าล่ม จะเข้า system_error_cases",
            "ถ้า transaction_id/reference เดิมเคยผ่านแล้ว จะตอบ already_passed และไม่ตรวจซ้ำ",
        ],
        "example_money_in": {
            "event_type": "money_in",
            "api_response": {
                "status": "success",
                "amount": 300,
                "transaction_id": "TX123",
                "sender_name": "น.ส. สุดใจ จิต***",
                "sender_mobile": "0801234567",
                "message": "ok",
            },
        },
        "example_balance": {
            "event_type": "balance_update",
            "api_response": {
                "status": "ok",
                "data": {
                    "balance": "20010",
                    "mobile_no": "0801234567",
                    "updated_at": "2023-10-16 10:18:41",
                },
            },
        },
        "example_error": {
            "event_type": "balance_update",
            "api_response": {
                "status": "err",
                "err": "Missing required parameter",
                "status_code": 500,
            },
        },
        "where_to_view": [
            "/private-fastapi -> Balance API Checks",
            "/private-fastapi -> click row -> API response tab",
            "/private-fastapi -> Money In Ledger",
            "/private-fastapi -> System Error Match Log",
        ],
    })


@router.post("/admin/review/action")
async def admin_review_action(request: Request):
    payload = await _payload(request)
    review_id = _review_user_id(payload.get("review_id"))
    bridge_id = _review_user_id(payload.get("bridge_id"))
    action = _clean(payload.get("action") or payload.get("btn_action"), 20).lower()
    approved = action in ("yes", "approve", "approved", "success")
    status = "approved" if approved else "rejected"
    amount = _review_amount(payload.get("confirm_amount") or payload.get("amount"))
    bot_status = _clean(payload.get("bot_status"), 80)
    send_status = _clean(payload.get("send_status"), 80)
    final_status = status
    if approved and not (bot_status == "invite_created" and send_status == "sent"):
        final_status = "needs_retry"
    if not review_id and not bridge_id:
        raise HTTPException(status_code=400, detail="missing_review_id")

    conn = _conn()
    cur = conn.cursor()
    _ensure_decision_tables(cur)
    actor = _clean(payload.get("actor") or _client_ip(request, payload) or "decision_api", 120)
    if not review_id and bridge_id:
        cur.execute("SELECT review_id FROM decision_admin_reviews WHERE id=? LIMIT 1", (bridge_id,))
        row = cur.fetchone()
        review_id = int(row["review_id"] or 0) if row else 0
    if review_id:
        if approved:
            cur.execute(
                "UPDATE api_error_payment_reviews SET status=?, amount=?, reviewed_at=strftime('%s','now') WHERE id=?",
                (final_status, amount, review_id),
            )
        else:
            cur.execute(
                "UPDATE api_error_payment_reviews SET status='rejected', amount=0.0, reviewed_at=strftime('%s','now') WHERE id=?",
                (review_id,),
            )
    if bridge_id:
        cur.execute(
            """
            UPDATE decision_admin_reviews
            SET status=?, decision_status=?, amount=CASE WHEN ? > 0 THEN ? ELSE amount END, reviewed_at=strftime('%s','now')
            WHERE id=?
            """,
            (final_status, final_status, amount, amount, bridge_id),
        )
    elif review_id:
        cur.execute(
            """
            UPDATE decision_admin_reviews
            SET status=?, decision_status=?, amount=CASE WHEN ? > 0 THEN ? ELSE amount END, reviewed_at=strftime('%s','now')
            WHERE review_id=?
            """,
            (final_status, final_status, amount, amount, review_id),
        )
    log_id = _insert_admin_review_check(cur, {
        **payload,
        "review_id": review_id,
        "bridge_id": bridge_id,
        "action": action,
        "actor": actor,
        "amount": amount,
        "status": final_status,
        "bot_status": bot_status or "not_run_by_decision_api",
        "send_status": send_status or "not_run_by_decision_api",
        "can_retry": final_status != "approved",
    })
    conn.commit()
    conn.close()
    if final_status == "approved":
        reason = "admin approved and system server completed"
    elif final_status == "rejected":
        reason = "admin rejected this request"
    else:
        reason = "admin approved but system server needs retry"
    system_summary = {
        "review_id": review_id,
        "bridge_id": bridge_id,
        "action": action,
        "actor": actor,
        "amount": amount,
        "bot_status": bot_status or "not_run_by_decision_api",
        "send_status": send_status or "not_run_by_decision_api",
        "log_id": log_id,
        "can_retry": final_status != "approved",
    }
    return JSONResponse({
        "ok": True,
        "review_id": review_id,
        "bridge_id": bridge_id,
        "status": final_status,
        "amount": amount,
        "reason": reason,
        "decision_logic": _decision_logic_payload(
            final_status if final_status in ("approved", "rejected") else "error",
            reason,
            api={},
            system_server=system_summary,
        ),
        "log_id": log_id,
        "can_retry": final_status != "approved",
    })


@router.get("/payment/{payment_ref}")
def payment_by_ref(payment_ref: str, request: Request):
    payload = {"payment_ref": payment_ref}
    request_ip = _client_ip(request, payload)
    result = _decision_payload(payload, request_ip, "payment_check")
    return JSONResponse(result)


@router.post("/source/verify")
async def source_verify(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    project_id = _clean(payload.get("project_id") or "default", 80) or "default"
    result = _decision_payload(payload, request_ip, "source_verify")
    api_state = result.get("decision_logic", {}).get("api", {}) if isinstance(result.get("decision_logic"), dict) else {}
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    group_identity = result.get("group_identity") if isinstance(result.get("group_identity"), dict) else {}
    group_member = result.get("group_member") if isinstance(result.get("group_member"), dict) else {}

    conn = _conn()
    cur = conn.cursor()
    route_match = {}
    expected_amount = _review_amount(payload.get("expected_amount") or payload.get("price") or payload.get("amount"))
    if payload.get("package_id") or payload.get("package"):
        route_match = _route_for_package_id(cur, payload.get("package_id") or payload.get("package"), project_id)
    elif expected_amount > 0:
        route_match = _route_for_amount(cur, expected_amount, project_id)
    user_id = _balance_user_id(cur, payload)
    balance_row = None
    if user_id and _has_table(cur, "user_balance"):
        cur.execute("SELECT user_id, total, updated_at, source FROM user_balance WHERE user_id=? LIMIT 1", (user_id,))
        balance_row = cur.fetchone()
    conn.close()

    db_balance = _review_amount(balance_row["total"]) if balance_row else 0.0
    source_balance = _review_amount(payload.get("balance") or payload.get("balance_after"))
    balance = source_balance if source_balance > 0 else db_balance
    central_problem = False
    need_admin = False
    need_fields: list[str] = []
    reason = "source state accepted by central"

    if payload.get("package_id") or payload.get("package") or expected_amount > 0:
        if not route_match.get("matched"):
            central_problem = True
            need_admin = True
            need_fields.extend(["project_routes.group_id", "project_routes.price"])
            reason = str(route_match.get("reason") or "group_config_missing")
        else:
            expected_amount = _review_amount(route_match.get("price") or expected_amount)

    if not user_id:
        need_fields.append("user_id")
        reason = "source must send user_id/chat_id/telegram_id"

    if expected_amount > 0 and balance <= 0:
        need_fields.append("balance")
        reason = "central needs source balance before deciding package state"

    balance_passed = bool(expected_amount > 0 and balance + 0.01 >= expected_amount and route_match.get("matched") and user_id)
    if balance_passed:
        reason = "source balance matches central package config"

    status = "accepted"
    if central_problem:
        status = "need_admin_confirm" if need_admin else "central_problem"
    elif need_fields:
        status = "need_more_data"
    elif balance_passed:
        status = "ready_to_create_link"

    verify_payload = {
        **payload,
        **api_state,
        **identity,
        **group_identity,
        **group_member,
        "ok": not central_problem,
        "ready": balance_passed,
        "status": "success" if balance_passed else ("error" if central_problem else "pending"),
        "reason": reason,
        "mode": "source_verify",
        "balance": balance,
        "balance_after": balance,
        "expected_amount": expected_amount,
        "balance_state": "balance_confirmed" if balance_passed else ("route_missing" if central_problem else "balance_waiting"),
        "balance_status": "success" if balance_passed else "error",
        "balance_passed": balance_passed,
        "can_send_link": balance_passed,
        "send_link_state": "source_may_send_link" if balance_passed else "waiting_balance",
        "group_id": _clean(route_match.get("group_id"), 120) if route_match.get("matched") else _clean(payload.get("group_id"), 120),
        "user_id": user_id or payload.get("user_id") or payload.get("chat_id") or payload.get("telegram_id"),
        "ip_context": result.get("ip_context"),
        "group_identity": group_identity,
    }
    contract = source_flow_status(verify_payload)
    response = {
        "ok": not central_problem,
        "central_ok": not central_problem,
        "central_problem": central_problem,
        "source_answer_valid": not central_problem and not need_fields,
        "status": status,
        "reason": reason,
        "need_admin": need_admin,
        "need_fields": sorted(set(need_fields)),
        "ready": balance_passed,
        "mode": "source_verify",
        "route_match": route_match,
        "db_balance": db_balance,
        "source_balance": source_balance,
        "balance": balance,
        "expected_amount": expected_amount,
        "source_contract": contract,
        "decision_logic": result.get("decision_logic"),
    }
    _log_decision_event(request, payload, response, request_ip)
    return JSONResponse(response)


@router.post("/group/status")
async def group_status(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    result = _decision_payload(payload, request_ip, "group_status")
    api_state = result.get("decision_logic", {}).get("api", {}) if isinstance(result.get("decision_logic"), dict) else {}
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    group_identity = result.get("group_identity") if isinstance(result.get("group_identity"), dict) else {}
    group_member = result.get("group_member") if isinstance(result.get("group_member"), dict) else {}
    result["source_contract"] = source_flow_status({
        **payload,
        **api_state,
        **identity,
        **group_identity,
        **group_member,
        "ok": result.get("ok"),
        "ready": result.get("ready"),
        "status": result.get("status"),
        "reason": result.get("reason"),
        "mode": result.get("mode"),
        "ip_context": result.get("ip_context"),
        "group_identity": group_identity,
    })
    _log_decision_event(request, payload, result, request_ip)
    return JSONResponse(result)


@router.post("/identity/status")
async def identity_status(request: Request):
    payload = await _payload(request)
    request_ip = _client_ip(request, payload)
    result = _decision_payload(payload, request_ip, "identity_status")
    api_state = result.get("decision_logic", {}).get("api", {}) if isinstance(result.get("decision_logic"), dict) else {}
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    group_identity = result.get("group_identity") if isinstance(result.get("group_identity"), dict) else {}
    group_member = result.get("group_member") if isinstance(result.get("group_member"), dict) else {}
    result["source_contract"] = source_flow_status({
        **payload,
        **api_state,
        **identity,
        **group_identity,
        **group_member,
        "ok": result.get("ok"),
        "ready": result.get("ready"),
        "status": result.get("status"),
        "reason": result.get("reason"),
        "mode": result.get("mode"),
        "ip_context": result.get("ip_context"),
        "group_identity": group_identity,
    })
    _log_decision_event(request, payload, result, request_ip)
    return JSONResponse(result)
