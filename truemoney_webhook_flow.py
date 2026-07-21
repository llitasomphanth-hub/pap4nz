from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Callable

from .flow_variables import TRUEMONEY_WEBHOOK_CONFIG

TRUEMONEY_WEBHOOK_VARIABLE = "TRUEMONEY_WEBHOOK_CONFIG"
TRUEMONEY_WEBHOOK_INPUT = ("raw", "amount")
TRUEMONEY_WEBHOOK_ACTION_CONTRACT = {
    "signer": "admin or provider-action integrator",
    "keyapi_form": {"action": "webhook.keyapi.issue", "button": "ขอคีย์ API", "result": "copy keyapi into action header"},
    "request": {
        "method": "POST",
        "url": "backend setting APIURL (for example https://event.webhook)",
        "header": {"keyapi": "system-issued keyapi"},
        "body": {"gift_link": "TrueMoney gift link", "phone": "configured mobile number"},
    },
    "webhook_result_action": "decision.truemoney_webhook",
    "webhook_receives": ("raw", "amount"),
    "webhook_writes": "webhook_api_events",
    "history_record": {
        "id": "raw.username_customer ถ้ามี; ถ้าไม่มีใช้ event id 6 หลักใน raw.history_id",
        "phone": "raw.phone (เบอร์รับเงิน)",
        "gift_link": "raw.gift_link (ลิงก์ซอง)",
        "sender_detail": "raw.owner_profile (ชื่อผู้ส่ง)",
        "amount": "webhook_api_events.amount (จำนวนเงิน)",
        "time": "webhook_api_events.created_at (เวลาบันทึก)",
    },
    "backend_ui_status": "code",
    "raw_message": "provider message is preserved in raw.message",
}
TRUEMONEY_WEBHOOK_RULE = {
    "accept": "รับ raw และ amount เท่านั้น; db_logic อ่านค่าที่ตั้งไว้แล้วตรวจ raw.keyapi/raw.phone",
    "settings_owner": "system_settings",
    "answer_owner": "backend_port/db_logic",
    "language": "raw_only",
}
TRUEMONEY_WEBHOOK_PLUGIN = {
    "variable": TRUEMONEY_WEBHOOK_VARIABLE,
    "input": TRUEMONEY_WEBHOOK_INPUT,
    "next": "core.db_logic.validate_and_record_truemoney_webhook",
    "role": "webhook_plug_only",
}


def _b64url_json(segment: str) -> dict[str, Any] | None:
    try:
        padded = str(segment).encode("ascii") + b"=" * (-len(str(segment)) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def verify_webhook_hs256(*, request_meta: dict[str, Any] | None, secret: str) -> dict[str, Any]:
    """Verify the documented Authorization JWT before trusting a webhook."""
    meta = request_meta if isinstance(request_meta, dict) else {}
    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    authorization = next((str(value or "") for key, value in headers.items() if str(key).lower() == "authorization"), "").strip()
    if not authorization:
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_REQUIRED", "http_status": 401}
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization
    parts = token.split(".")
    if len(parts) != 3:
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_MALFORMED", "http_status": 401}
    header, payload = _b64url_json(parts[0]), _b64url_json(parts[1])
    if not header or not payload:
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_MALFORMED", "http_status": 401}
    if str(header.get("alg") or "") != "HS256":
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_ALGORITHM_MISMATCH", "http_status": 401}
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(expected, parts[2]):
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_INVALID_SIGNATURE", "http_status": 401}
    now = int(time.time())
    try:
        if "exp" not in payload:
            return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_EXP_REQUIRED", "http_status": 401}
        if now >= int(payload["exp"]):
            return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_EXPIRED", "http_status": 401}
        if "nbf" in payload and now < int(payload["nbf"]):
            return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_NOT_ACTIVE", "http_status": 401}
    except (TypeError, ValueError):
        return {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_CLAIM_INVALID", "http_status": 401}
    return {"ok": True, "status": "success", "state": "JWT_VERIFIED", "code": "JWT_VERIFIED", "http_status": 200, "claims": payload}


def _provider_state(raw: dict[str, Any]) -> tuple[str, bool]:
    """Match an external raw result against the backend-owned contract."""
    contract = TRUEMONEY_WEBHOOK_CONFIG["provider_result_contract"]
    status = str(raw.get("status") or "").strip()
    message = str(raw.get("message") or "").strip()
    success = contract["success"]
    if status == success["when"]["status"] and message == success["when"]["message"]:
        required = success["required_raw"]
        if all(str(raw.get(field) or "").strip() for field in required):
            return str(success["state"]), True
        return str(contract["fallback_state"]), False
    error = contract["error"]
    if status == error["when"]["status"] and all(str(raw.get(field) or "").strip() for field in error["required_raw"]):
        return str(error["state"]), False
    return str(contract["fallback_state"]), False


def receive_truemoney_webhook_event(payload: dict[str, Any] | None, *, caller: str = "") -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    raw = data.get("raw")
    if not isinstance(raw, dict):
        return {
            "ok": False, "status": "error", "code": "TRUEMONEY_RAW_REQUIRED", "http_status": 400,
            "amount": 0.0, "raw": raw if raw is not None else {}, "caller": caller,
        }
    # Provider outcomes live inside raw.  They are never rewritten as local
    # key/phone configuration errors, and an error payload may legitimately
    # have no amount at all.
    try:
        provider_http = int(raw.get("http_status") or 0)
    except (TypeError, ValueError):
        provider_http = 502
    provider_status = str(raw.get("status") or "").lower()
    provider_code = str(raw.get("code") or "").strip()
    provider_message = str(raw.get("message") or "").strip()
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        amount = 0.0
    state, accepted = _provider_state(raw)
    if state == "SYSTEM_ERROR":
        return {
            "ok": False, "status": "error", "state": state,
            "code": "UNEXPECTED_PROVIDER_RESPONSE", "message": provider_message or "UNEXPECTED_PROVIDER_RESPONSE",
            "http_status": provider_http if provider_http >= 400 else 502, "amount": amount, "raw": raw, "caller": caller,
        }
    if state == "TRUEMONEY_ERROR" or provider_http >= 400 or provider_status in {"error", "failed", "failure"}:
        return {
            "ok": False,
            "status": provider_status or "error",
            "state": state,
            "code": state,
            "message": provider_message or provider_code or "TRUEMONEY_PROVIDER_ERROR",
            "http_status": provider_http if provider_http >= 400 else 400,
            "amount": amount,
            "raw": raw,
            "caller": caller,
        }
    if not accepted or amount <= 0:
        return {
            "ok": False, "status": "error", "code": "TRUEMONEY_AMOUNT_REQUIRED", "http_status": 400,
            "state": state, "message": "TRUEMONEY_AMOUNT_REQUIRED", "amount": 0.0, "raw": raw, "caller": caller,
        }
    return {
        "ok": True,
        "status": "success",
        "state": state,
        "code": "TRUEMONEY_RAW_RECEIVED",
        "message": provider_message or "TRUEMONEY_RAW_RECEIVED",
        "http_status": 200,
        "amount": amount,
        "raw": raw,
        "caller": caller,
        "rule": TRUEMONEY_WEBHOOK_RULE,
    }


def dispatch_truemoney_webhook(payload: dict[str, Any] | None, backend_port: Callable[[dict[str, Any]], Any]) -> Any:
    return backend_port({"action": "decision.truemoney_webhook", **(payload if isinstance(payload, dict) else {})})


__all__ = ["TRUEMONEY_WEBHOOK_VARIABLE", "TRUEMONEY_WEBHOOK_INPUT", "TRUEMONEY_WEBHOOK_ACTION_CONTRACT", "TRUEMONEY_WEBHOOK_RULE", "TRUEMONEY_WEBHOOK_PLUGIN", "verify_webhook_hs256", "receive_truemoney_webhook_event", "dispatch_truemoney_webhook"]
