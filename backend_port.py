from __future__ import annotations

import secrets
from typing import Any

from .db_logic import find_auth_account, record_backend_action, read_admin_overview, read_backend_settings, validate_and_record_truemoney_webhook
from .flow_variables import TOPUP_STATUS

BACKEND_PORT_VERSION = "papxnz-backend-port-raw-v1"
BACKEND_PORT_ROLE = "central_action_port"
BACKEND_PORT_RULE = "receive action, ask db_logic, record raw, return raw result"
WEBHOOK_ADMIN_SETTING_FIELDS = ("APIURL", "HTTPMethod", "phone", "allowed_ips", "JWT_SECRET", "JWT_ALGORITHM")

# UI choices for PACKAGE_STATUS.  These do not decide a result: db_logic
# returns the code first, then the port attaches this short display message.
PACKAGE_STATUS_UI_CHOICES = {
    "LOGIN_PACKAGE_BINDING_REQUIRED": "ไม่พบการเข้าสู่ระบบ",
    "USERNAME_CUSTOMER_REQUIRED": "ไม่พบไอดีผู้ใช้",
    "TOPUP_HISTORY_NOT_FOUND": "ไม่พบประวัติเติมเงิน",
    "PACKAGE_ID_NOT_FOUND": "ไม่พบไอดีแพ็กเกจ",
    "AMOUNT_MISMATCH": "ยอดเงินไม่ตรง",
    "INSUFFICIENT_BALANCE": "เงินไม่พอ",
    "PACKAGE_PURCHASED": "ซื้อแพ็กเกจสำเร็จ",
}


def _backend_slots(answer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return display-ready facts; the browser must not infer a new state."""
    status = str(answer.get("status") or "")
    code = str(answer.get("code") or "")
    text = str(answer.get("message") or code or status)
    slot_state = answer.get("port_state") or answer.get("state") or answer.get("provider_state") or code
    slot_code = answer.get("port_state") or code
    slot = {"text": text, "status": status, "state": slot_state, "code": slot_code, "amount": answer.get("amount", 0.0)}
    slots = {
        "home.topup.answer.message": slot,
        "home.latest_transaction": slot,
        "packages.purchase.answer.message": slot,
    }
    balance = answer.get("balance")
    if balance is None and str(answer.get("variable") or "") == "FINANCE_BALANCE":
        balance = answer.get("amount", 0.0)
    if balance is not None:
        slots["home.balance"] = {
            "text": f"ยอดเงิน ฿{float(balance):,.2f}",
            "status": status,
            "code": code,
            "amount": balance,
        }
    return slots


def _finish(result: dict[str, Any] | None, *, action: str, variable: str, raw: dict[str, Any], caller: str) -> dict[str, Any]:
    """Keep the port answer shape stable; decisions remain in the called logic."""
    answer = dict(result or {})
    ok = bool(answer.get("ok"))
    answer.setdefault("status", "success" if ok else "error")
    answer.setdefault("http_status", 200 if ok else 400)
    answer.setdefault("amount", 0.0)
    answer.setdefault("action", action)
    if variable:
        answer.setdefault("variable", variable)
    answer.setdefault("raw", raw)
    answer.setdefault("caller", caller)
    # A business write is separate from the audit row below.  When a flow
    # rejects before it can create its own record result, make that explicit
    # for the backend log instead of leaving the reader to infer it.
    if "record" not in answer:
        if answer.get("event_id"):
            answer["record"] = {"status": "written", "target": "webhook_api_events", "record_id": answer.get("event_id")}
        elif ok:
            answer["record"] = {"status": "not_applicable", "reason": "READ_OR_DECISION_ONLY"}
        else:
            answer["record"] = {"status": "not_written", "reason": str(answer.get("code") or "ACTION_REJECTED")}
    # The port is the only state-to-slot mapper.  UI receives the completed
    # answer and renders it verbatim; it never turns success/error keywords
    # into a different result.
    answer["slots"] = _backend_slots(answer)
    # Audit history is always separate from the business write.  It is saved
    # before the one terminal port answer is returned.  The browser never
    # receives this internal write trail; admin/history readers get it from
    # backend_action_history later.
    try:
        record_backend_action(action=action, payload=raw, result=answer, source="backend_port", variable=variable)
    except Exception:
        # The terminal answer must not be replaced or expanded with a second
        # state. The failed audit write is only observable from server logs.
        pass
    answer.pop("record", None)
    return answer


def backend_port_contract() -> dict[str, Any]:
    return {"ok": True, "port": "core.backend_port", "rule": BACKEND_PORT_RULE}


def receive_backend_event(payload: dict[str, Any] | None, *, caller: str = "") -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    action = str(data.get("action") or ("package_buy" if data.get("package_id") else "")).strip()
    variable = str(data.get("variable") or data.get("config_variable") or "").strip()
    mode = str(data.get("mode") or "recorded").strip()
    if not action and variable == "PAPXNZ_SYSTEM_CONFIG" and mode in {"read", "recorded", "fresh", "live"}:
        result = read_admin_overview(limit=int(data.get("limit") or 120), bucket=str(data.get("bucket") or "timeline"), member_id=str(data.get("member_id") or ""))
        result.update({"variable": variable, "mode": "read", "raw": data, "caller": caller})
        return _finish(result, action="", variable=variable, raw=data, caller=caller)
    if not action:
        result = {"ok": False, "status": "error", "code": "ACTION_REQUIRED", "raw": data}
        return _finish(result, action="", variable=variable, raw=data, caller=caller)
    if action in {"account.check", "auth.account.check", "auth.identity.check", "login.account.check"}:
        account = find_auth_account(
            provider=str(data.get("provider") or ""), provider_user_id=str(data.get("telegram_id") or data.get("login") or ""),
            email=str(data.get("email") or ""), auth_user_id=str(data.get("auth_user_id") or ""), web_user_id=str(data.get("web_user_id") or data.get("public_user_id") or ""))
        result = {"ok": bool(account), "status": "success" if account else "error", "code": "ACCOUNT_FOUND" if account else "ACCOUNT_NOT_FOUND", "account_exists": bool(account), "account": (account or {}).get("user", {}), "identity": (account or {}).get("identity", {}), "raw": data, "caller": caller}
        return _finish(result, action=action, variable=variable, raw=data, caller=caller)
    if action.startswith("auth.telegram."):
        if action == "auth.telegram.openid_confirm":
            from .telegram_openid_flow import receive_telegram_openid_confirm
            result = receive_telegram_openid_confirm(data)
        else:
            result = {"ok": False, "status": "error", "code": "AUTH_ACTION_UNSUPPORTED", "http_status": 404, "amount": 0.0, "raw": data}
        return _finish(result, action=action, variable=variable, raw=data, caller=caller)
    if action.startswith("auth.google."):
        from . import google_logic
        handlers = {"auth.google.start": google_logic.receive_google_start, "auth.google.login": google_logic.receive_google_login, "auth.google.forgot_password": google_logic.request_google_forgot_password}
        handler = handlers.get(action)
        result = handler(data) if handler else {"ok": False, "status": "error", "code": "AUTH_ACTION_UNSUPPORTED", "raw": data}
        return _finish(result, action=action, variable=variable, raw=data, caller=caller)
    if action == "package.settings.save":
        from .package_settings_logic import save_package_setting_config
        from .flow_variables import PACKAGE_SETTING_TOKEN_CONFIG
        expected_variable = PACKAGE_SETTING_TOKEN_CONFIG["returns"][0]
        if variable != expected_variable:
            result = {"ok": False, "status": "error", "code": "VARIABLE_ACTION_MISMATCH", "raw": {"action": action, "variable": variable, "expected_variable": expected_variable}}
            return _finish(result, action=action, variable=variable, raw=data, caller=caller)
        if caller != PACKAGE_SETTING_TOKEN_CONFIG["admin_caller"]:
            result = {"ok": False, "status": "error", "code": "PACKAGE_SETTING_ADMIN_BINDING_REQUIRED", "raw": {"action": action, "variable": variable, "expected_caller": PACKAGE_SETTING_TOKEN_CONFIG["admin_caller"]}}
            return _finish(result, action=action, variable=variable, raw=data, caller=caller)
        result = save_package_setting_config(data)
        result.update({"mode": "write", "request_raw": data, "caller": caller})
        return _finish(result, action=action, variable=variable, raw=data, caller=caller)
    if action == "webhook.settings.save":
        from .db_logic import save_backend_settings
        if caller != "login_app:/ui-api/backend-settings":
            result = {"ok": False, "status": "error", "code": "WEBHOOK_SETTINGS_ADMIN_BINDING_REQUIRED", "http_status": 403, "amount": 0.0, "raw": data}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        unknown_fields = sorted(set(settings) - set(WEBHOOK_ADMIN_SETTING_FIELDS))
        if unknown_fields:
            result = {
                "ok": False, "status": "error", "code": "WEBHOOK_SETTING_FIELD_NOT_DECLARED",
                "http_status": 400, "amount": 0.0, "raw": {"unknown_fields": unknown_fields},
            }
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
        # The receiving port owns provenance; a client payload must not name
        # or impersonate the source that recorded a setting.
        saved = save_backend_settings(settings, provider=str(data.get("provider") or "webhook"), source=caller)
        result = {"ok": bool(saved.get("ok")), "status": "success" if saved.get("ok") else "error", "code": "WEBHOOK_SETTINGS_SAVED" if saved.get("ok") else "WEBHOOK_SETTINGS_SAVE_FAILED", "http_status": 200 if saved.get("ok") else 400, "amount": 0.0, "raw": {"saved": saved.get("saved", []), "provider": data.get("provider") or "webhook"}}
        return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
    if action == "webhook.settings.read":
        if caller != "login_app:/ui-api/backend-settings":
            result = {"ok": False, "status": "error", "code": "WEBHOOK_SETTINGS_ADMIN_BINDING_REQUIRED", "http_status": 403, "amount": 0.0, "raw": {}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
        stored = read_backend_settings("webhook")
        settings = {field: str(stored.get(field) or "") for field in WEBHOOK_ADMIN_SETTING_FIELDS if field != "JWT_SECRET"}
        settings["JWT_SECRET_SET"] = bool(str(stored.get("JWT_SECRET") or "").strip())
        settings["KEYAPI_SET"] = bool(str(stored.get("keyapi") or "").strip())
        result = {"ok": True, "status": "success", "code": "WEBHOOK_SETTINGS_READ", "http_status": 200, "amount": 0.0, "raw": {"settings": settings}}
        return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
    if action == "webhook.keyapi.issue":
        from .db_logic import save_backend_settings
        if caller != "login_app:/ui-api/backend-settings":
            result = {"ok": False, "status": "error", "code": "WEBHOOK_SETTINGS_ADMIN_BINDING_REQUIRED", "http_status": 403, "amount": 0.0, "raw": {}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
        keyapi = f"papxnz_{secrets.token_urlsafe(24)}"
        saved = save_backend_settings({"keyapi": keyapi}, provider="webhook", source=caller)
        result = {"ok": bool(saved.get("ok")), "status": "success" if saved.get("ok") else "error", "code": "KEYAPI_ISSUED" if saved.get("ok") else "KEYAPI_ISSUE_FAILED", "http_status": 200 if saved.get("ok") else 400, "amount": 0.0, "keyapi": keyapi if saved.get("ok") else "", "raw": {"keyapi": keyapi if saved.get("ok") else ""}}
        return _finish(result, action=action, variable=TOPUP_STATUS, raw=data, caller=caller)
    if action == "decision.truemoney_webhook":
        from .truemoney_webhook_flow import receive_truemoney_webhook_event, verify_webhook_hs256
        def topup_answer(result: dict[str, Any]) -> dict[str, Any]:
            """UI gets the short backend status; provider wording remains raw."""
            answer = dict(result)
            code = str(answer.get("code") or "SYSTEM_ERROR")
            provider_message = str(answer.get("message") or "")
            if provider_message:
                answer["provider_message"] = provider_message
            answer["message"] = code
            return answer
        settings = read_backend_settings("webhook")
        secret = str(settings.get("JWT_SECRET") or "").strip()
        algorithm = str(settings.get("JWT_ALGORITHM") or "HS256").strip()
        if not secret:
            result = {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_SECRET_NOT_FOUND", "http_status": 409, "amount": 0.0, "message": "JWT_SECRET_NOT_FOUND", "raw": {}}
            return _finish(topup_answer(result), action=action, variable=TOPUP_STATUS, raw={}, caller=caller)
        if algorithm != "HS256":
            result = {"ok": False, "status": "error", "state": "SYSTEM_ERROR", "code": "JWT_ALGORITHM_NOT_SUPPORTED", "http_status": 409, "amount": 0.0, "message": "JWT_ALGORITHM_NOT_SUPPORTED", "raw": {}}
            return _finish(topup_answer(result), action=action, variable=TOPUP_STATUS, raw={}, caller=caller)
        jwt_result = verify_webhook_hs256(request_meta=data.get("_request"), secret=secret)
        if not jwt_result.get("ok"):
            jwt_result.update({"amount": 0.0, "message": str(jwt_result.get("code") or "JWT_ERROR"), "raw": {}})
            return _finish(topup_answer(jwt_result), action=action, variable=TOPUP_STATUS, raw={}, caller=caller)
        flow_result = receive_truemoney_webhook_event(data, caller=caller)
        if not flow_result.get("ok"):
            from .db_logic import record_webhook_api_event
            event = record_webhook_api_event(raw=flow_result.get("raw") if isinstance(flow_result.get("raw"), dict) else {}, amount=float(flow_result.get("amount") or 0), status=str(flow_result.get("status") or "error"), code=str(flow_result.get("code") or "TRUEMONEY_PROVIDER_ERROR"), http_status=int(flow_result.get("http_status") or 400), source=caller)
            flow_result["event_id"] = event.get("lastrowid")
            return _finish(topup_answer(flow_result), action=action, variable=TOPUP_STATUS, raw=flow_result.get("raw", {}), caller=caller)
        result = validate_and_record_truemoney_webhook(payload=flow_result["raw"], amount=float(flow_result["amount"]), source=caller or "backend_port", request_meta=data.get("_request"), domain=str(data.get("domain") or ""))
        result["provider_state"] = flow_result.get("state")
        result["provider_message"] = flow_result.get("message")
        return _finish(topup_answer(result), action=action, variable=TOPUP_STATUS, raw=flow_result["raw"], caller=caller)
    if action == "truemoney.submit":
        gift_link = str(data.get("gift_link") or data.get("voucher_url") or "").strip()
        settings = read_backend_settings("webhook")
        expected_keyapi = str(settings.get("keyapi") or "").strip()
        supplied_keyapi = str(data.get("keyapi") or "").strip()
        expected_phone = str(settings.get("phone") or "").strip()
        api_url = str(settings.get("APIURL") or "").strip()
        http_method = str(settings.get("HTTPMethod") or "").strip().upper()

        # The action owns the outbound contract.  It may use the saved key and
        # phone itself; a supplied value is only accepted when it is identical.
        if not expected_keyapi:
            result = {"ok": False, "status": "error", "state": "KEYAPI_NOT_FOUND", "code": "KEYAPI_NOT_FOUND", "http_status": 409, "amount": 0.0, "message": "KEYAPI_NOT_FOUND", "raw": {"gift_link": gift_link, "diagnostic": {"lookup": "backend_settings.webhook.keyapi", "match_count": 0}}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        if supplied_keyapi and supplied_keyapi != expected_keyapi:
            result = {"ok": False, "status": "error", "state": "KEYAPI_MISMATCH", "code": "KEYAPI_MISMATCH", "http_status": 401, "amount": 0.0, "message": "KEYAPI_MISMATCH", "raw": {"gift_link": gift_link}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        if not expected_phone:
            result = {"ok": False, "status": "error", "state": "PHONE_NOT_FOUND", "code": "PHONE_NOT_FOUND", "http_status": 409, "amount": 0.0, "message": "PHONE_NOT_FOUND", "raw": {"gift_link": gift_link, "diagnostic": {"lookup": "backend_settings.webhook.phone", "match_count": 0}}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        if not gift_link:
            result = {"ok": False, "status": "error", "state": "GIFT_LINK_REQUIRED", "code": "GIFT_LINK_REQUIRED", "http_status": 400, "amount": 0.0, "message": "GIFT_LINK_REQUIRED", "raw": {}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        if not api_url:
            result = {"ok": False, "status": "error", "state": "WEBHOOK_URL_NOT_FOUND", "code": "WEBHOOK_URL_NOT_FOUND", "http_status": 409, "amount": 0.0, "message": "WEBHOOK_URL_NOT_FOUND", "raw": {"gift_link": gift_link}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        if not http_method:
            result = {"ok": False, "status": "error", "state": "HTTP_METHOD_NOT_FOUND", "code": "HTTP_METHOD_NOT_FOUND", "http_status": 409, "amount": 0.0, "message": "HTTP_METHOD_NOT_FOUND", "raw": {"gift_link": gift_link}}
            return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
        # No request is claimed as sent until an actual provider caller exists.
        result = {
            "ok": False, "status": "error", "state": "PROVIDER_CALLER_NOT_CONFIGURED",
            "code": "PROVIDER_CALLER_NOT_CONFIGURED", "http_status": 503, "amount": 0.0,
            "message": "PROVIDER_CALLER_NOT_CONFIGURED", "raw": {"gift_link": gift_link, "keyapi": "configured", "phone": "configured", "api_url": api_url, "http_method": http_method},
        }
        return _finish(result, action=action, variable=TOPUP_STATUS, raw=result["raw"], caller=caller)
    if action == "topup.record":
        from .db_logic import record_topup_for_owner
        from .flow_variables import PAPXNZ_SYSTEM_CONFIG
        if caller != "login_app:/customer/action":
            result = {"ok": False, "status": "error", "code": "LOGIN_BINDING_REQUIRED", "http_status": 403, "amount": 0.0, "raw": {}}
            return _finish(result, action=action, variable="TOPUP_STATUS", raw=data, caller=caller)
        if str(data.get("domain") or "").strip().lower() != str(PAPXNZ_SYSTEM_CONFIG["host"]).strip().lower():
            result = {"ok": False, "status": "error", "code": "DOMAIN_NOT_ALLOWED", "http_status": 403, "amount": 0.0, "raw": {"domain": data.get("domain") or ""}}
            return _finish(result, action=action, variable="TOPUP_STATUS", raw=data, caller=caller)
        result = record_topup_for_owner(owner_key=str(data.get("owner_key") or ""), webhook_event_id=int(data.get("webhook_event_id") or 0), source=caller)
        return _finish(result, action=action, variable="TOPUP_STATUS", raw=data, caller=caller)
    if action == "finance.summary":
        from .finance_logic import read_finance_money_summary
        result = read_finance_money_summary(data)
        return _finish(result, action=action, variable="FINANCE_BALANCE", raw=data, caller=caller)
    if action == "package.page_config.read":
        from .db_logic import read_package_page_config
        result = read_package_page_config()
        return _finish(result, action=action, variable="PACKAGE_STATUS", raw=data, caller=caller)
    if action == "package_buy" or mode == "purchase":
        from .flow_variables import PACKAGE_PURCHASE_CONFIG
        def package_answer(result: dict[str, Any], action_raw: dict[str, Any]) -> dict[str, Any]:
            answer = dict(result)
            code = str(answer.get("code") or "")
            # package flow decided the condition. The port supplies the
            # declared UI choice for that exact code; it never changes code.
            answer.setdefault("reason", code)
            answer["message"] = PACKAGE_STATUS_UI_CHOICES[code]
            raw_result = answer.get("raw") if isinstance(answer.get("raw"), dict) else {}
            answer["raw"] = {**raw_result, "action": action_raw, "server_code": code}
            return answer
        # A debit is only a logged-in customer's package purchase.  Admin
        # settings and arbitrary port calls cannot deduct a wallet directly.
        if caller != "login_app:/customer/action":
            result = {"ok": False, "status": "error", "code": "LOGIN_PACKAGE_BINDING_REQUIRED", "http_status": 403, "variable": "PACKAGE_STATUS", "amount": 0.0, "raw": {"status": "error", "message": "LOGIN_PACKAGE_BINDING_REQUIRED", "package_id": data.get("package_id")}}
            return _finish(package_answer(result, {"package_id": data.get("package_id") or ""}), action=action, variable="PACKAGE_STATUS", raw=data, caller=caller)
        username_customer = str(data.get("username_customer") or "").strip()
        if not username_customer:
            result = {"ok": False, "status": "error", "state": "USERNAME_CUSTOMER_REQUIRED", "code": "USERNAME_CUSTOMER_REQUIRED", "http_status": 400, "variable": "PACKAGE_STATUS", "amount": 0.0, "raw": {"status": "error", "message": "USERNAME_CUSTOMER_REQUIRED", "package_id": data.get("package_id")}}
            return _finish(package_answer(result, {"package_id": data.get("package_id") or ""}), action=action, variable="PACKAGE_STATUS", raw=data, caller=caller)
        action_raw = {"username_customer": username_customer, "package_id": str(data.get("package_id") or "")}
        from .package_settings_logic import purchase_configured_package
        result = purchase_configured_package(username_customer=username_customer, package_id=action_raw["package_id"])
        result["username_customer"] = username_customer
        result = package_answer(result, action_raw)
        result.update({"action": action, "mode": "purchase", "request_raw": data, "caller": caller})
        return _finish(result, action=action, variable=variable, raw=data, caller=caller)
    if mode in {"read", "recorded", "fresh", "live"}:
        if variable == "TOPUP_STATUS":
            from .any_flow import read_any
            result = read_any(variable=variable, user_key=str(data.get("key_value") or data.get("user_key") or data.get("permanent_user_key") or data.get("user_id") or ""))
        else:
            result = {"ok": False, "status": "error", "code": "READ_ACTION_NOT_DECLARED", "http_status": 400, "variable": variable, "amount": 0.0, "raw": data}
        result.update({"status": "read", "action": action, "mode": mode, "raw": data, "caller": caller})
    elif mode == "write":
        result = {"ok": False, "status": "error", "code": "DIRECT_VARIABLE_WRITE_FORBIDDEN", "http_status": 403, "variable": variable, "amount": 0.0, "raw": data}
    else:
        result = {"ok": False, "status": "error", "code": "ACTION_NOT_DECLARED", "http_status": 400, "variable": variable, "amount": 0.0, "raw": data, "caller": caller}
    return _finish(result, action=action, variable=variable, raw=data, caller=caller)


def call_backend_port(*, action: str, payload: dict[str, Any] | None = None, caller: str = "") -> dict[str, Any]:
    return receive_backend_event({**(payload if isinstance(payload, dict) else {}), "action": action}, caller=caller or "backend_port.call")


__all__ = ["BACKEND_PORT_VERSION", "BACKEND_PORT_ROLE", "WEBHOOK_ADMIN_SETTING_FIELDS", "backend_port_contract", "receive_backend_event", "call_backend_port"]
