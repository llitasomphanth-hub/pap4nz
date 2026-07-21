"""Google login logic boundary.

This file verifies Google identity on the backend, checks the email against
existing account truth, and records every attempt for admin inspection.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Any, Callable

from .db_logic import (
    ensure_central_db,
    find_auth_account,
    create_auth_session_for_user_id,
    list_auth_provider_events,
    record_auth_otp,
    record_auth_provider_event,
    upsert_auth_identity,
)
from .login_event_filter import normalize_login_event_payload, normalize_login_event_result


GOOGLE_PROVIDER = "google"
GOOGLE_FLOW_ROLE = "auth_provider_identity_flow"
GOOGLE_FLOW_CONTRACT_KEY = "AUTH_IDENTITY_CONFIG"
GOOGLE_FLOW_VARIABLE_PAIR = {
    "incoming": ("email", "google_sub", "id_token", "login", "session_id"),
    "recorded": ("auth_users", "google_login_events"),
    "answer": ("status", "reason", "web_user_id", "auth_session"),
}
GOOGLE_BACKEND_PATH = "/customer/action"
GOOGLE_ACTIONS = {
    "start": "auth.google.start",
    "login": "auth.google.login",
    "forgot_password": "auth.google.forgot_password",
}
GOOGLE_UI_IDS = {
    "start": "ui.auth.google_button",
    "login": "ui.auth.google_button",
    "forgot_password": "ui.auth.forgot_password_submit",
}
GOOGLE_OTP_TTL = 60 * 5
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"


class GoogleAuthError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = int(http_status)


def ensure_google_login_tables() -> None:
    ensure_central_db()


def _ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    return None


def receive_google_login(
    payload: dict[str, Any] | None = None,
    *,
    verify_id_token: Callable[[str, str], dict[str, Any]] | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    data = dict(payload or {})
    token = str(data.get("token") or data.get("id_token") or "").strip()
    expected_email = _email(data.get("expectedEmail") or data.get("expected_email") or data.get("session_expected_email"))
    source = str(data.get("source") or "google_login")
    session_id = str(data.get("session_id") or "")

    try:
        google_payload = _verify_google_token(token, verify_id_token=verify_id_token, client_id=client_id)
        google_email = _email(google_payload.get("email"))
        if not google_email:
            raise GoogleAuthError("GOOGLE_EMAIL_MISSING", "ไม่พบอีเมลจาก Google", http_status=401)
        if expected_email and google_email != expected_email:
            raise GoogleAuthError("ACCOUNT_MISMATCH", "บัญชีนี้ไม่ตรงกับข้อมูลในระบบ", http_status=400)
        user = _find_user_by_email(google_email)
        if not user:
            raise GoogleAuthError("ACCOUNT_NOT_FOUND", "ไม่พบบัญชีนี้ในระบบ กรุณาสมัครสมาชิกใหม่", http_status=404)
        account = _mark_google_login(user, google_payload)
        session = create_auth_session_for_user_id(account["auth_user_id"], data)
        if not session.get("ok"):
            raise GoogleAuthError("AUTH_SESSION_CREATE_FAILED", "สร้าง session ของระบบไม่สำเร็จ", http_status=500)
        result = {
            "ok": True,
            "success": True,
            "status": "success",
            "code": "google_login_success",
            "http_status": 200,
            "message": "เข้าสู่ระบบด้วย Google สำเร็จ",
            "action": "login_success",
            "provider": GOOGLE_PROVIDER,
            "mode": "login",
            "backend_path": GOOGLE_BACKEND_PATH,
            "google_email": google_email,
            "expected_email": expected_email,
            "email_matched": True,
            "user_found": True,
            "web_user_id": account["web_user_id"],
            "auth_user_id": account["auth_user_id"],
            "token": session["token"],
            "expires_in": session["expires_in"],
            "auth_session": {"ok": True, "code": session["code"], "cookie": "papxnz_auth"},
            "payload": _build_google_payload(data, "login"),
        }
    except GoogleAuthError as exc:
        result = {
            "ok": False,
            "success": False,
            "status": "failed",
            "code": exc.code,
            "http_status": exc.http_status,
            "message": exc.message,
            "provider": GOOGLE_PROVIDER,
            "mode": "login",
            "backend_path": GOOGLE_BACKEND_PATH,
            "google_email": _email(locals().get("google_email", "")),
            "expected_email": expected_email,
            "email_matched": False,
            "user_found": False,
            "web_user_id": "",
            "payload": _build_google_payload(data, "login"),
        }

    result["source"] = source
    result["session_id"] = session_id
    _copy_navigation_fields(result, data)
    result["effect"] = "record_and_login" if result.get("ok") else "record_only"
    result["does_not_change_ui_state"] = True
    _apply_google_api_shape(result)
    result["db_event"] = record_google_login_event(result)
    return result


def receive_google_start(
    payload: dict[str, Any] | None = None,
    *,
    client_id: str | None = None,
) -> dict[str, Any]:
    data = dict(payload or {})
    source = str(data.get("source") or "google_start")
    session_id = str(data.get("session_id") or "")
    google_client_id = str(client_id or data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    redirect_uri = str(data.get("redirect_uri") or os.getenv("GOOGLE_REDIRECT_URL") or "").strip()

    if not google_client_id:
        result = _google_start_error(data, "GOOGLE_CLIENT_ID_MISSING", "ยังไม่ได้ตั้งค่า Google Client ID")
    elif not redirect_uri:
        result = _google_start_error(data, "GOOGLE_REDIRECT_URI_MISSING", "ยังไม่ได้ส่ง redirect_uri สำหรับ Google login")
    else:
        state = str(data.get("state") or "").strip()
        nonce = str(data.get("nonce") or "").strip()
        redirect_url = GOOGLE_AUTH_ENDPOINT + "?" + _urlencode(
            {
                "client_id": google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "id_token",
                "scope": "openid email profile",
                "state": state,
                "nonce": nonce,
                "prompt": "select_account",
            }
        )
        result = {
            "ok": True,
            "success": True,
            "status": "redirect_required",
            "code": "google_redirect_required",
            "http_status": 200,
            "message": "เปิดหน้าเลือกบัญชี Google",
            "provider": GOOGLE_PROVIDER,
            "mode": "start",
            "backend_path": GOOGLE_BACKEND_PATH,
            "google_email": "",
            "expected_email": "",
            "email_matched": False,
            "user_found": False,
            "web_user_id": "",
            "redirect_url": redirect_url,
            "payload": _build_google_payload(data, "start"),
        }

    result["source"] = source
    result["session_id"] = session_id
    _copy_navigation_fields(result, data)
    result["effect"] = "record_and_redirect" if result.get("ok") else "record_only"
    result["does_not_change_ui_state"] = True
    _apply_google_api_shape(result)
    result["db_event"] = record_google_login_event(result)
    return result


def request_google_forgot_password(
    payload: dict[str, Any] | None = None,
    *,
    send_email: Callable[[str, str, str], Any] | None = None,
) -> dict[str, Any]:
    data = dict(payload or {})
    original_email = _email(data.get("originalEmail") or data.get("original_email") or data.get("email"))
    source = str(data.get("source") or "google_forgot_password")
    session_id = str(data.get("session_id") or "")
    user = _find_user_by_email(original_email) if original_email else None

    if not user:
        result = {
            "ok": False,
            "success": False,
            "status": "failed",
            "code": "EMAIL_NOT_FOUND",
            "http_status": 400,
            "message": "ไม่พบข้อมูลอีเมลนี้ในระบบ กรุณาสมัครสมาชิกใหม่",
            "provider": GOOGLE_PROVIDER,
            "mode": "forgot_password",
            "backend_path": GOOGLE_BACKEND_PATH,
            "google_email": original_email,
            "expected_email": original_email,
            "email_matched": False,
            "user_found": False,
            "otp_sent": False,
            "web_user_id": "",
            "payload": _build_google_payload(data, "forgot_password"),
        }
    else:
        otp = f"{secrets.randbelow(1000000):06d}"
        now = int(time.time())
        _record_email_otp(int(user["id"]), original_email, otp, now=now)
        if send_email:
            send_email(
                original_email,
                "รหัส OTP สำหรับกู้คืนบัญชีของคุณ",
                f"รหัส OTP สำหรับตั้งค่าบัญชีใหม่ของคุณคือ: {otp}",
            )
        result = {
            "ok": True,
            "success": True,
            "status": "otp_sent",
            "code": "google_recovery_otp_sent",
            "http_status": 200,
            "message": "ส่งรหัส OTP ไปยังอีเมลเดิมเรียบร้อยแล้ว",
            "provider": GOOGLE_PROVIDER,
            "mode": "forgot_password",
            "backend_path": GOOGLE_BACKEND_PATH,
            "google_email": original_email,
            "expected_email": original_email,
            "email_matched": True,
            "user_found": True,
            "otp_sent": True,
            "web_user_id": str(user.get("public_user_id") or ""),
            "payload": _build_google_payload(data, "forgot_password"),
        }

    result["source"] = source
    result["session_id"] = session_id
    _copy_navigation_fields(result, data)
    result["effect"] = "record_and_send_otp" if result.get("ok") else "record_only"
    result["does_not_change_ui_state"] = True
    _apply_google_api_shape(result)
    result["db_event"] = record_google_login_event(result)
    return result


def record_google_login_event(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    result["payload"] = normalize_login_event_payload(_safe_payload(payload), domain="google", action=str(payload.get("action") or ""))
    safe_result = normalize_login_event_result(result)
    return record_auth_provider_event("google", safe_result, source="google.login")


def list_google_login_events(limit: int = 50) -> list[dict[str, Any]]:
    return list_auth_provider_events("google", limit=limit)


def describe_google_logic() -> dict[str, Any]:
    return {
        "logic_owner": "Google action adapter",
        "actions": list(GOOGLE_ACTIONS.values()),
        "backend_path": GOOGLE_BACKEND_PATH,
        "effect": "record_and_login",
        "does_not_change_ui_state": True,
        "db_table": "backend_action_history",
        "db_source": "google.login",
        "db_gateway": "core.db_logic",
        "account_tables": ["auth_users", "auth_identities", "auth_password_otps"],
        "rules": [
            "verify_google_id_token_before_any_login",
            "block_ACCOUNT_MISMATCH_when_expected_email_differs",
            "forgot_password_sends_otp_only_to_original_saved_email",
            "missing_original_email_blocks_and_forces_new_registration",
        ],
        "response_shape": {
            "ok": "bool",
            "code": "str",
            "message": "str",
            "account_state": "new|some|finished",
            "display": "dict",
            "frontend": "dict",
        },
    }


def _apply_google_api_shape(result: dict[str, Any]) -> None:
    account_state = _google_account_state(result)
    result["account_state"] = account_state
    result["ui_flow_state"] = account_state
    result["display"] = {
        "title": result.get("message") or "ไม่ทราบสถานะ Google",
        "level": "success" if result.get("ok") else "error",
        "badge": result.get("code") or "",
        "account_state": account_state,
    }
    result["frontend"] = {
        "should_update_status": True,
        "should_update_balance": False,
        "status": "success" if result.get("ok") else "failed",
        "provider": GOOGLE_PROVIDER,
        "account_state": account_state,
        "google_email": result.get("google_email") or "",
        "web_user_id": result.get("web_user_id") or "",
        "next": result.get("redirect_url") or result.get("success_url") or ("login_success" if result.get("ok") and result.get("mode") == "login" else ""),
        "success_url": result.get("success_url") or "",
        "packages_url": result.get("packages_url") or "",
    }
    result["admin"] = _admin_answer_status(
        ok=bool(result.get("ok")),
        http_status=int(result.get("http_status") or 200),
    )


def _admin_answer_status(*, ok: bool, http_status: int) -> dict[str, Any]:
    if int(http_status or 0) >= 500 or int(http_status or 0) == 429:
        status = "retry"
        label = "ลองใหม่"
    elif ok:
        status = "success"
        label = "สำเร็จ"
    else:
        status = "failed"
        label = "ไม่รับคำขอ"
    return {
        "status": status,
        "label": label,
        "http_status": int(http_status or 0),
    }


def _google_account_state(result: dict[str, Any]) -> str:
    code = str(result.get("code") or "").strip()
    if code == "google_redirect_required":
        return ""
    if code in {"google_login_success", "google_recovery_otp_sent"}:
        return "some"
    if code in {"ACCOUNT_NOT_FOUND", "EMAIL_NOT_FOUND"}:
        return "finished"
    if code in {"ACCOUNT_MISMATCH"}:
        return "finished"
    return ""


def _google_start_error(data: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "success": False,
        "status": "failed",
        "code": code,
        "http_status": 400,
        "message": message,
        "provider": GOOGLE_PROVIDER,
        "mode": "start",
        "backend_path": GOOGLE_BACKEND_PATH,
        "google_email": "",
        "expected_email": "",
        "email_matched": False,
        "user_found": False,
        "web_user_id": "",
        "payload": _build_google_payload(data, "start"),
    }


def _copy_navigation_fields(result: dict[str, Any], data: dict[str, Any]) -> None:
    for key in ("success_url", "packages_url"):
        value = str(data.get(key) or "").strip()
        if value:
            result[key] = value


def _verify_google_token(
    token: str,
    *,
    verify_id_token: Callable[[str, str], dict[str, Any]] | None,
    client_id: str | None,
) -> dict[str, Any]:
    if not token:
        raise GoogleAuthError("GOOGLE_TOKEN_MISSING", "Token ไม่ถูกต้อง", http_status=401)
    audience = client_id or os.getenv("GOOGLE_CLIENT_ID") or ""
    if verify_id_token:
        payload = verify_id_token(token, audience)
    else:
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except Exception as exc:
            raise GoogleAuthError("GOOGLE_VERIFIER_NOT_CONFIGURED", "ยังไม่ได้ตั้งค่าตัวตรวจ Google Token", http_status=500) from exc
        payload = google_id_token.verify_oauth2_token(token, google_requests.Request(), audience)
    if not isinstance(payload, dict):
        raise GoogleAuthError("GOOGLE_TOKEN_INVALID", "Token ไม่ถูกต้อง", http_status=401)
    return payload


def _urlencode(params: dict[str, Any]) -> str:
    from urllib.parse import urlencode

    return urlencode({key: str(value) for key, value in params.items() if str(value or "").strip()})


def _find_user_by_email(email: str) -> dict[str, Any] | None:
    if not email:
        return None
    account = find_auth_account(provider=GOOGLE_PROVIDER, email=email)
    if not account:
        return None
    user = account.get("user") if isinstance(account.get("user"), dict) else account
    return dict(user) if isinstance(user, dict) else None


def _mark_google_login(user: dict[str, Any], google_payload: dict[str, Any]) -> dict[str, Any]:
    email = _email(google_payload.get("email"))
    google_sub = str(google_payload.get("sub") or email).strip()
    name = str(google_payload.get("name") or user.get("username") or email).strip()
    existing_web_user_id = str(user.get("public_user_id") or "")
    account = upsert_auth_identity(
        provider=GOOGLE_PROVIDER,
        provider_user_id=google_sub,
        provider_username=email,
        display_name=name,
        email=email,
        raw_payload=google_payload,
        web_user_prefix=f"web_google_{hashlib.sha256(email.encode('utf-8')).hexdigest()[:16]}",
        existing_user_id=user.get("id") or "",
    )
    if existing_web_user_id:
        account["web_user_id"] = existing_web_user_id
    return {"auth_user_id": int(account.get("auth_user_id") or user["id"]), "web_user_id": account.get("web_user_id") or existing_web_user_id, "google_email": email}


def _record_email_otp(user_id: int, email: str, otp: str, *, now: int) -> None:
    record_auth_otp(user_id=user_id, channel="google_email_recovery", destination=email, otp_hash=_otp_hash(otp), ttl_seconds=GOOGLE_OTP_TTL)


def _otp_hash(otp: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.sha256(f"{salt}:{otp}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def _build_google_payload(data: dict[str, Any], mode: str) -> dict[str, Any]:
    action = GOOGLE_ACTIONS[mode]
    return {
        **data,
        "action": action,
        "action_key": action,
        "event_type": action,
        "provider": GOOGLE_PROVIDER,
        "mode": mode,
        "ui_id": data.get("ui_id") or GOOGLE_UI_IDS[mode],
        "backend_path": GOOGLE_BACKEND_PATH,
    }


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    for key in ("token", "id_token", "otp", "password"):
        if key in safe:
            safe[key] = "[redacted]"
    return safe


def _email(value: Any) -> str:
    return str(value or "").strip().lower()


__all__ = [
    "GOOGLE_ACTIONS",
    "GOOGLE_BACKEND_PATH",
    "GOOGLE_PROVIDER",
    "GOOGLE_UI_IDS",
    "describe_google_logic",
    "ensure_google_login_tables",
    "list_google_login_events",
    "receive_google_start",
    "receive_google_login",
    "record_google_login_event",
    "request_google_forgot_password",
]

