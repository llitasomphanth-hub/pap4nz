from __future__ import annotations

import os
import sqlite3
import json
import time
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .flow_variables import WEB_USER_KEY

DB_PATH = os.getenv("PAPXNZ_WEB_DB") or str(Path(__file__).resolve().parent.parent / "papxnz_web.sqlite3")
DB_TRUTH_CONTRACT = {
    "role": "database reader and decision writer",
    "reads": "saved settings and recorded SQLite facts",
    "writes": "accepted raw records and derived amount summaries",
    "rule": "The port routes. db_logic compares saved conditions, records accepted raw facts, and calculates amount summaries.",
}


def configure_db_logic(*, db_path: str | Path | None = None, source: str = "") -> dict[str, Any]:
    global DB_PATH
    if db_path is not None:
        DB_PATH = str(db_path)
        os.environ["PAPXNZ_WEB_DB"] = DB_PATH
    return {"ok": True, "db_path": DB_PATH, "source": source, "contract": DB_TRUTH_CONTRACT}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(sql, tuple(params)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def execute(sql: str, params: Iterable[Any] = ()) -> dict[str, Any]:
    conn = get_conn()
    try:
        cursor = conn.execute(sql, tuple(params))
        conn.commit()
        return {"ok": True, "lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}
    finally:
        conn.close()


def ensure_central_db() -> dict[str, Any]:
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, public_user_id TEXT NOT NULL DEFAULT '',
            username_customer TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', telegram TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0, last_login_at INTEGER NOT NULL DEFAULT 0,
            password_hash TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS auth_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL, provider_username TEXT NOT NULL DEFAULT '', verified_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0, raw_payload TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, token TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0, expires_at INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS auth_password_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, channel TEXT NOT NULL DEFAULT '',
            destination TEXT NOT NULL DEFAULT '', otp_hash TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER NOT NULL DEFAULT 0, used_at INTEGER, ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS auth_provider_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL, provider TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS package_runtime_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, package_id TEXT NOT NULL DEFAULT '', price REAL NOT NULL DEFAULT 0,
            exp_mode TEXT NOT NULL DEFAULT '', exp_value TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
            display_name TEXT NOT NULL DEFAULT '', button_label TEXT NOT NULL DEFAULT '', card_index TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS web_user_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT NOT NULL DEFAULT '', balance REAL NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0, state_key TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS web_wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL DEFAULT 0, user_key TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0, balance_before REAL NOT NULL DEFAULT 0, balance_after REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '', txn_type TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', raw_payload TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS webhook_api_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT '', code TEXT NOT NULL DEFAULT '',
            http_status INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT '', raw_payload TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS package_access_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL DEFAULT 0, state_key TEXT NOT NULL DEFAULT '',
            package_id TEXT NOT NULL DEFAULT '', access_token TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',
            expires_at INTEGER, raw_payload TEXT NOT NULL DEFAULT '{}');
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
        if "username_customer" not in columns:
            conn.execute("ALTER TABLE auth_users ADD COLUMN username_customer TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE auth_users SET username_customer=public_user_id WHERE username_customer='' AND public_user_id<>''")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "db_path": DB_PATH, "source_of_truth": "papxnz_web.sqlite3"}


def find_auth_account(*, provider: str = "", provider_user_id: str = "", email: str = "", auth_user_id: str = "", web_user_id: str = "") -> dict[str, Any] | None:
    ensure_central_db()
    conditions, params = [], []
    if auth_user_id:
        conditions.append("u.id=?"); params.append(str(auth_user_id))
    elif web_user_id:
        conditions.append("u.public_user_id=?"); params.append(str(web_user_id))
    elif email:
        conditions.append("u.email=?"); params.append(str(email).strip().lower())
    elif provider_user_id:
        conditions.append("i.provider_user_id=?"); params.append(str(provider_user_id))
    else:
        return None
    if provider:
        conditions.append("i.provider=?"); params.append(str(provider))
    row = fetch_one(
        "SELECT u.*, i.provider, i.provider_user_id, i.provider_username FROM auth_users u "
        "LEFT JOIN auth_identities i ON i.user_id=u.id WHERE " + " AND ".join(conditions) + " ORDER BY i.id DESC LIMIT 1", params)
    if not row:
        return None
    user = {key: row.get(key) for key in ("id", "public_user_id", "username", "email", "telegram", "status", "created_at", "updated_at", "last_login_at")}
    identity = {key: row.get(key) for key in ("provider", "provider_user_id", "provider_username")}
    return {"ok": True, "user": user, "identity": identity, "blocked": str(user.get("status") or "").lower() == "blocked"}


def upsert_auth_identity(*, provider: str, provider_user_id: str, provider_username: str = "", display_name: str = "", email: str = "", raw_payload: dict[str, Any] | None = None, web_user_prefix: str = "web", existing_user_id: Any = "") -> dict[str, Any]:
    ensure_central_db()
    now = int(time.time())
    existing = find_auth_account(provider=provider, provider_user_id=provider_user_id) or (find_auth_account(auth_user_id=str(existing_user_id)) if existing_user_id else None)
    if existing:
        user_id = int(existing["user"]["id"])
    else:
        public_id = f"{web_user_prefix}_{secrets.token_urlsafe(10)}"
        saved = execute("INSERT INTO auth_users (public_user_id, username_customer, username, email, telegram, status, created_at, updated_at, last_login_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)", (public_id, public_id, str(display_name or provider_username), str(email).lower(), str(provider_user_id) if provider == "telegram" else "", now, now, now))
        user_id = int(saved["lastrowid"])
    execute("DELETE FROM auth_identities WHERE user_id=? AND provider=?", (user_id, str(provider)))
    execute("INSERT INTO auth_identities (user_id, provider, provider_user_id, provider_username, verified_at, created_at, updated_at, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user_id, str(provider), str(provider_user_id), str(provider_username), now, now, now, json.dumps(raw_payload or {}, ensure_ascii=False, default=str)))
    user = fetch_one("SELECT * FROM auth_users WHERE id=?", (user_id,)) or {}
    return {"ok": True, "auth_user_id": user_id, "web_user_id": user.get("public_user_id") or "", "user": user}


def record_auth_provider_event(provider: str, result: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    ensure_central_db()
    saved = execute("INSERT INTO auth_provider_events (created_at, provider, source, payload_json) VALUES (?, ?, ?, ?)", (int(time.time()), str(provider), str(source), json.dumps(result or {}, ensure_ascii=False, default=str)))
    return {"ok": True, "id": saved.get("lastrowid"), "source": "auth_provider_events"}


def list_auth_provider_events(provider: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_central_db()
    return fetch_all("SELECT * FROM auth_provider_events WHERE provider=? ORDER BY id DESC LIMIT ?", (str(provider), max(1, int(limit))))


def record_auth_otp(*, user_id: int, channel: str, destination: str, otp_hash: str, ttl_seconds: int) -> dict[str, Any]:
    ensure_central_db()
    now = int(time.time())
    saved = execute("INSERT INTO auth_password_otps (user_id, channel, destination, otp_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)", (int(user_id), str(channel), str(destination), str(otp_hash), now, now + int(ttl_seconds)))
    return {"ok": True, "id": saved.get("lastrowid")}


def create_auth_session_for_user_id(user_id: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_central_db()
    user = fetch_one("SELECT * FROM auth_users WHERE id=?", (int(user_id or 0),))
    if not user:
        return {"ok": False, "code": "AUTH_USER_NOT_FOUND"}
    now = int(time.time()); expires_at = now + 60 * 60 * 24 * 30; token = secrets.token_urlsafe(32)
    execute("INSERT INTO auth_sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)", (int(user_id), token, now, expires_at))
    return {"ok": True, "code": "AUTH_SESSION_CREATED", "token": token, "expires_in": expires_at - now, "user": user}


def resolve_auth_session(token: str = "") -> dict[str, Any] | None:
    """Return the authenticated owner for a login-app session token."""
    value = str(token or "").strip()
    if not value:
        return None
    ensure_central_db()
    row = fetch_one(
        "SELECT s.user_id, u.public_user_id, u.username_customer FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id "
        "WHERE s.token=? AND s.expires_at>? ORDER BY s.id DESC LIMIT 1",
        (value, int(time.time())),
    )
    if not row:
        return None
    username_customer = str(row.get("username_customer") or row.get("public_user_id") or f"auth:{row['user_id']}")
    return {"owner_key": username_customer, "username_customer": username_customer, "user_id": int(row["user_id"])}


def read_admin_overview(*, limit: int = 120, bucket: str = "timeline", member_id: str = "") -> dict[str, Any]:
    tables = {"web_users": "auth_users", "webhook": "web_wallet_transactions", "settings": "package_runtime_settings", "backend_settings": "backend_settings", "timeline": "backend_action_history"}
    buckets: dict[str, Any] = {}
    size = max(1, min(int(limit), 200))
    for name, table in tables.items():
        exists = bool(fetch_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)))
        count = fetch_one(f"SELECT COUNT(*) AS count FROM {table}") if exists else {"count": 0}
        items = fetch_all(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (size,)) if exists else []
        buckets[name] = {"count": int((count or {}).get("count") or 0), "items": items}
    return {"ok": True, "page": "overview", "source_of_truth": "papxnz_web.sqlite3", "buckets": buckets, "raw": {"bucket": bucket, "member_id": member_id, "limit": size}}


def read_package_page_config() -> dict[str, Any]:
    """Return the already-recorded display fields for the legacy package page."""
    exists = bool(fetch_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='package_page_config' LIMIT 1"))
    if not exists:
        return {"ok": True, "status": "success", "code": "PACKAGE_PAGE_CONFIG_EMPTY", "http_status": 200, "amount": 0.0, "raw": {"config": {}}}
    config = {str(row["key"]): row["value"] for row in fetch_all("SELECT key, value FROM package_page_config")}
    return {"ok": True, "status": "success", "code": "PACKAGE_PAGE_CONFIG_READ", "http_status": 200, "amount": 0.0, "raw": {"config": config}}


def read_finance_balance(*, user_key: str = "") -> dict[str, Any]:
    """Read the total of accepted ledger amounts; this never trusts an UI total."""
    ensure_central_db()
    key = str(user_key or "").strip()
    if not key:
        return {
            "ok": False, "status": "error", "code": "WEB_USER_KEY_REQUIRED", "http_status": 400,
            "variable": "FINANCE_BALANCE", "amount": 0.0, "raw": {"user_key": key},
        }
    row = fetch_one(
        "SELECT COALESCE(SUM(amount), 0) AS amount, COUNT(*) AS record_count "
        "FROM web_wallet_transactions WHERE user_key=? AND status IN ('accepted', 'success') AND txn_type IN ('topup', 'package_purchase')",
        (key,),
    ) or {}
    amount = float(row.get("amount") or 0)
    return {
        "ok": True, "status": "success", "code": "FINANCE_BALANCE_READ", "http_status": 200,
        "variable": "FINANCE_BALANCE", "amount": amount,
        "raw": {"user_key": key, "record_count": int(row.get("record_count") or 0), "as_of": int(time.time())},
    }


def read_topup_status(*, user_key: str = "") -> dict[str, Any]:
    """Return the final answer of the latest topup equation for one user."""
    ensure_central_db()
    key = str(user_key or "").strip()
    if not key:
        return {"ok": False, "status": "error", "code": "WEB_USER_KEY_REQUIRED", "http_status": 400, "variable": "TOPUP_STATUS", "amount": 0.0, "raw": {"user_key": key}}
    row = fetch_one(
        "SELECT * FROM web_wallet_transactions WHERE user_key=? AND txn_type IN ('topup', 'topup_webhook') ORDER BY id DESC LIMIT 1",
        (key,),
    )
    if not row:
        return {"ok": False, "status": "error", "code": "TOPUP_NOT_FOUND", "http_status": 404, "variable": "TOPUP_STATUS", "amount": 0.0, "raw": {"user_key": key}}
    try:
        raw = json.loads(row.get("raw_payload") or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    return {
        "ok": str(row.get("status") or "").lower() in {"accepted", "success"},
        "status": "success" if str(row.get("status") or "").lower() in {"accepted", "success"} else "error",
        "code": "TOPUP_RECORDED", "http_status": 200, "variable": "TOPUP_STATUS",
        "amount": float(row.get("amount") or 0), "raw": raw,
    }


def _owner_key(raw: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> str:
    """One person identifier, supplied as evidence; never use the app domain as a wallet."""
    for value in (
        (raw or {}).get("username_customer"), (raw or {}).get("owner_key"), (raw or {}).get("user_key"),
        (payload or {}).get("username_customer"), (payload or {}).get("owner_key"), (payload or {}).get("permanent_user_key"),
        (payload or {}).get("public_user_id"), (payload or {}).get("user_id"),
    ):
        key = str(value or "").strip()
        if key:
            return key
    return ""


def record_webhook_api_event(*, raw: dict[str, Any] | None, amount: float, status: str, code: str, http_status: int, source: str = "") -> dict[str, Any]:
    ensure_central_db()
    stored_raw = dict(raw) if isinstance(raw, dict) else {}
    supplied_id = str(stored_raw.get("username_customer") or "").strip()
    event = execute("INSERT INTO webhook_api_events (created_at,amount,status,code,http_status,source,raw_payload) VALUES (?,?,?,?,?,?,?)", (int(time.time()), float(amount or 0), str(status), str(code), int(http_status), str(source), json.dumps(stored_raw, ensure_ascii=False, default=str)))
    history_id = supplied_id or f"{int(event.get('lastrowid') or 0):06d}"
    stored_raw["history_id"] = history_id
    execute("UPDATE webhook_api_events SET raw_payload=? WHERE id=?", (json.dumps(stored_raw, ensure_ascii=False, default=str), int(event.get("lastrowid") or 0)))
    return {**event, "history_id": history_id}


def validate_and_record_truemoney_webhook(*, payload: dict[str, Any] | None = None, amount: float = 0.0, source: str = "", request_meta: dict[str, Any] | None = None, domain: str = "") -> dict[str, Any]:
    """Validate the declared webhook input contract before accepting raw + amount."""
    ensure_central_db()
    data = payload if isinstance(payload, dict) else {}
    meta = request_meta if isinstance(request_meta, dict) else {}
    def finish(ok: bool, code: str, http_status: int, accepted_amount: float = 0.0) -> dict[str, Any]:
        event = record_webhook_api_event(raw=data, amount=accepted_amount, status="success" if ok else "error", code=code, http_status=http_status, source=source)
        return {"ok": ok, "status": "success" if ok else "error", "code": code, "http_status": http_status,
                "variable": "TOPUP_STATUS", "amount": float(accepted_amount), "event_id": event.get("lastrowid"),
                "message": str(data.get("message") or code), "raw": data}
    settings = read_backend_settings("webhook")
    for key in ("keyapi", "phone"):
        expected = str(settings.get(key) or "").strip()
        actual = str(data.get(key) or "").strip()
        if not expected:
            return finish(False, f"{key.upper()}_SETTING_MISSING", 409)
        if not actual:
            return finish(False, f"{key.upper()}_REQUIRED", 400)
        if actual != expected:
            return finish(False, f"{key.upper()}_MISMATCH", 401)

    gift_link = str(data.get("gift_link") or "").strip()
    gift_url = urlparse(gift_link)
    if gift_url.scheme not in {"http", "https"} or not gift_url.netloc:
        return finish(False, "GIFT_LINK_REQUIRED", 400)

    expected_url = str(settings.get("APIURL") or "").strip()
    actual_url = str(meta.get("url") or "").strip()
    if expected_url:
        expected_path = urlparse(expected_url).path or expected_url
        actual_path = urlparse(actual_url).path or actual_url
        if expected_path.rstrip("/") != actual_path.rstrip("/"):
            return finish(False, "WEBHOOK_URL_MISMATCH", 403)

    expected_method = str(settings.get("HTTPMethod") or "").strip().upper()
    if expected_method and expected_method != str(meta.get("method") or "").strip().upper():
        return finish(False, "WEBHOOK_METHOD_MISMATCH", 405)

    allowed_ips = str(settings.get("allowed_ips") or "").strip()
    if allowed_ips:
        try:
            configured_ips = json.loads(allowed_ips)
            allowed = {str(ip).strip() for ip in configured_ips} if isinstance(configured_ips, list) else {str(configured_ips).strip()}
        except json.JSONDecodeError:
            allowed = {ip.strip() for ip in allowed_ips.split(",") if ip.strip()}
        if str(meta.get("ip") or "").strip() not in allowed:
            return finish(False, "WEBHOOK_IP_MISMATCH", 403)

    accepted_amount = float(amount or 0)
    if accepted_amount <= 0:
        return finish(False, "AMOUNT_INVALID", 400)
    # This is API history only. A separate internal action links this event to one owner ledger.
    return finish(True, "WEBHOOK_ACCEPTED", 200, accepted_amount)


def record_topup_for_owner(*, owner_key: str, webhook_event_id: int, source: str = "") -> dict[str, Any]:
    """Append one owner's topup history from an already-accepted webhook event."""
    key = str(owner_key or "").strip()
    if not key:
        return {"ok": False, "status": "error", "code": "OWNER_KEY_REQUIRED", "http_status": 400, "amount": 0.0, "raw": {}}
    event = fetch_one("SELECT * FROM webhook_api_events WHERE id=?", (int(webhook_event_id or 0),))
    if not event or event.get("status") != "success":
        return {"ok": False, "status": "error", "code": "WEBHOOK_EVENT_NOT_ACCEPTED", "http_status": 409, "amount": 0.0, "raw": {"event_id": webhook_event_id}}
    if float(event.get("amount") or 0) <= 0:
        return {"ok": False, "status": "error", "code": "TOPUP_AMOUNT_MUST_BE_POSITIVE", "http_status": 409, "amount": 0.0, "raw": {"event_id": event["id"]}}
    reason = f"webhook_event:{event['id']}"
    if fetch_one("SELECT id FROM web_wallet_transactions WHERE reason=? LIMIT 1", (reason,)):
        return {"ok": False, "status": "error", "code": "TOPUP_ALREADY_LINKED", "http_status": 409, "amount": 0.0, "raw": {"event_id": event["id"]}}
    raw = json.loads(event.get("raw_payload") or "{}")
    saved = execute("INSERT INTO web_wallet_transactions (created_at,user_key,amount,status,txn_type,reason,raw_payload) VALUES (?,?,?,?,?,?,?)", (int(time.time()), key, float(event["amount"]), "accepted", "topup", reason, json.dumps(raw, ensure_ascii=False, default=str)))
    return {"ok": True, "status": "success", "code": "TOPUP_RECORDED", "http_status": 200, "amount": float(event["amount"]), "raw": {"event_id": event["id"], "ledger_id": saved.get("lastrowid"), "username_customer": key}}


def read_package_purchase_inputs(*, user_key: str, package_id: str) -> dict[str, Any]:
    """Read recorded facts only. Package flow owns every purchase decision."""
    ensure_central_db()
    package = fetch_one(
        "SELECT * FROM package_runtime_settings WHERE package_id=? AND enabled=1 AND status='active' LIMIT 1",
        (str(package_id),),
    )
    ledger = fetch_one(
        "SELECT COALESCE(SUM(amount), 0) AS amount, COUNT(*) AS record_count FROM web_wallet_transactions "
        "WHERE user_key=? AND status IN ('accepted','success') AND txn_type IN ('topup','package_purchase')",
        (str(user_key),),
    ) or {}
    return {"package": package, "balance": float(ledger.get("amount") or 0), "record_count": int(ledger.get("record_count") or 0)}


def append_package_purchase_record(*, user_key: str, package_id: str, amount: float, token: str, created_at: int, expires_at: int | None, raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Persist package-flow output only; balance is always calculated on DB read."""
    conn = get_conn()
    try:
        ledger = conn.execute("INSERT INTO web_wallet_transactions (created_at,user_key,amount,status,txn_type,reason,raw_payload) VALUES (?,?,?,?,?,?,?)", (int(created_at), str(user_key), float(amount), "success", "package_purchase", str(package_id), json.dumps(raw_payload, ensure_ascii=False, default=str)))
        cur = conn.execute("INSERT INTO package_access_tokens (created_at,state_key,package_id,access_token,status,expires_at,raw_payload) VALUES (?,?,?,?,?,?,?)", (int(created_at), str(user_key), str(package_id), str(token), "active", expires_at, json.dumps(raw_payload, ensure_ascii=False, default=str)))
        conn.commit()
        return {"ledger_id": ledger.lastrowid, "token_id": cur.lastrowid}
    finally:
        conn.close()


def table_columns(table_name: str) -> set[str]:
    return {str(row.get("name")) for row in fetch_all(f"PRAGMA table_info({table_name})")}


def replace_package_runtime_settings(items: list[dict[str, Any]], *, source: str, updated_at: int) -> list[str]:
    """Raw DB writer for already-validated package setting facts."""
    for column in ("display_name", "button_label", "card_index"):
        if column not in table_columns("package_runtime_settings"):
            execute(f"ALTER TABLE package_runtime_settings ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    saved: list[str] = []
    for item in items:
        package_id = str(item.get("package_id") or "").strip()
        if not package_id:
            continue
        execute("DELETE FROM package_runtime_settings WHERE package_id=?", (package_id,))
        execute("""INSERT INTO package_runtime_settings
            (package_id, price, exp_mode, exp_value, enabled, status, source, updated_at, display_name, button_label, card_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            package_id, item.get("price", 0), str(item.get("exp_mode") or "No"),
            str(item.get("exp_value") or ""), 1 if item.get("enabled") else 0,
            "active" if item.get("enabled") else "disabled", str(source or ""), int(updated_at),
            str(item.get("display_name") or ""), str(item.get("button_label") or ""), str(item.get("card_index") or ""),
        ))
        saved.append(package_id)
    return saved

def save_backend_settings(settings: dict[str, Any], *, provider: str = "webhook", source: str = "") -> dict[str, Any]:
    execute("CREATE TABLE IF NOT EXISTS backend_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, key TEXT, value TEXT, is_secret INTEGER DEFAULT 0, updated_at INTEGER, value_json TEXT, source TEXT)")
    columns = set(table_columns("backend_settings"))
    now = int(time.time())
    saved = []
    for key, value in (settings or {}).items():
        execute("DELETE FROM backend_settings WHERE provider=? AND key=?", (provider, str(key)))
        values = {"provider": provider, "key": str(key), "is_secret": 1 if 'key' in str(key).lower() else 0, "updated_at": now, "source": source}
        if "value" in columns:
            values["value"] = str(value)
        if "value_json" in columns:
            values["value_json"] = json.dumps(value, ensure_ascii=False)
        names = tuple(values)
        execute(f"INSERT INTO backend_settings ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(values[name] for name in names))
        saved.append(str(key))
    return {"ok": True, "saved": saved, "variable": "TRUEMONEY_WEBHOOK_CONFIG"}

def read_backend_settings(provider: str = "webhook") -> dict[str, Any]:
    # Empty settings are a valid contract state.  Callers must receive a
    # precise *_NOT_FOUND result, never a missing-table exception.
    execute("CREATE TABLE IF NOT EXISTS backend_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, key TEXT, value TEXT, is_secret INTEGER DEFAULT 0, updated_at INTEGER, value_json TEXT, source TEXT)")
    columns = set(table_columns("backend_settings"))
    value_column = "value" if "value" in columns else "value_json"
    rows = fetch_all(f"SELECT key,{value_column} AS stored_value FROM backend_settings WHERE provider=? ORDER BY id DESC", (provider,))
    result = {}
    for row in rows:
        value = row.get("stored_value")
        if value_column == "value_json":
            try:
                value = json.loads(str(value))
            except (TypeError, json.JSONDecodeError):
                pass
        result.setdefault(str(row.get("key") or ""), value)
    return result


def record_backend_action(*, action: str, payload: dict[str, Any] | None = None, result: dict[str, Any] | None = None, source: str = "backend_port", variable: str = "") -> dict[str, Any]:
    """Raw history writer. Only backend_port should call this function."""
    data = payload if isinstance(payload, dict) else {}
    answer = result if isinstance(result, dict) else {}
    execute("""CREATE TABLE IF NOT EXISTS backend_action_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        action TEXT NOT NULL, source TEXT NOT NULL, status TEXT, code TEXT,
        payload_json TEXT NOT NULL, result_json TEXT NOT NULL,
        record_scope TEXT NOT NULL DEFAULT 'unscoped', variable TEXT NOT NULL DEFAULT '')""")
    user_key = _owner_key(data.get("raw") if isinstance(data.get("raw"), dict) else {}, data)
    record_scope = "web_user_history" if user_key else "unscoped"
    # This is a readable flow category, not a second DB state store.
    record_variable = str(variable or (WEB_USER_KEY if user_key else "")).strip()
    saved = execute("""INSERT INTO backend_action_history
        (action, source, status, code, payload_json, result_json, record_scope, variable) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
        str(action or "")[:160], str(source or "backend_port")[:160],
        str(answer.get("status") or "")[:80], str(answer.get("code") or "")[:120],
        __import__("json").dumps(data, ensure_ascii=False, default=str)[:12000],
        __import__("json").dumps(answer, ensure_ascii=False, default=str)[:12000], record_scope, record_variable,
    ))
    return {"ok": True, "source_table": "backend_action_history", "id": saved.get("lastrowid"), "action": action, "record_scope": record_scope, "variable": record_variable}



__all__ = ["DB_PATH", "DB_TRUTH_CONTRACT", "configure_db_logic", "get_conn", "fetch_one", "fetch_all", "execute", "ensure_central_db", "read_admin_overview", "read_finance_balance", "read_topup_status", "validate_and_record_truemoney_webhook", "record_topup_for_owner", "read_package_purchase_inputs", "append_package_purchase_record", "table_columns", "replace_package_runtime_settings", "save_backend_settings", "read_backend_settings", "create_auth_session_for_user_id", "resolve_auth_session", "record_backend_action"]
