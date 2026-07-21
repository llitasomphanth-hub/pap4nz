from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .any_flow import read_any
from .db_logic import append_package_purchase_record, replace_package_runtime_settings
from .flow_variables import PACKAGE_SETTING_CONDITIONS, PACKAGE_SETTING_TOKEN_CONFIG, PACKAGE_STATUS


def _setting_raw(status: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """The package-settings flow owns this raw result; it is not UI text."""
    return {"status": status, "message": message, **details}


def _setting_error(code: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "code": code,
        "http_status": 400,
        "variable": PACKAGE_STATUS,
        "amount": 0.0,
        "raw": _setting_raw("error", code, raw),
        # The contract remains the short code.  This is the business-write
        # result for the audit log: no debit/token row exists on a rejected
        # package decision.
        "record": {"status": "not_written", "reason": code},
    }


def purchase_configured_package(*, username_customer: str, package_id: str) -> dict[str, Any]:
    """Package flow owns its equation; db_logic only supplies/saves facts."""
    facts = read_any(variable=PACKAGE_STATUS, user_key=username_customer, package_id=package_id)
    package = facts["package"]
    if not package:
        return _setting_error("PACKAGE_ID_NOT_FOUND", {
            "package_id": package_id,
            "diagnostic": {"lookup": "package_runtime_settings", "match_count": 0},
        })
    if facts["record_count"] == 0:
        return _setting_error("TOPUP_HISTORY_NOT_FOUND", {
            "package_id": package_id,
            "username_customer": username_customer,
            "diagnostic": {"lookup": "web_wallet_transactions", "accepted_record_count": 0},
        })
    price = float(package["price"] or 0)
    before = float(facts["balance"])
    if before < price:
        return _setting_error("INSUFFICIENT_BALANCE", {
            "price": price,
            "balance": before,
            "username_customer": username_customer,
            "diagnostic": {"rule": "balance >= package.price", "actual": before, "required": price},
        })
    created_at = int(datetime.now(timezone.utc).timestamp())
    exp_value = int(package["exp_value"] or 0) if str(package["exp_value"] or "").isdigit() else 0
    days = exp_value * ({"months": 30, "years": 365}.get(str(package["exp_mode"]), 1))
    expires_at = int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp()) if days else None
    token = secrets.token_urlsafe(32)
    amount = -price
    raw = _setting_raw("success", "PACKAGE_PURCHASED", {"amount": amount, "token": token, "username_customer": username_customer, "token_created_at": created_at, "token_expires_at": expires_at})
    saved = append_package_purchase_record(user_key=username_customer, package_id=package_id, amount=amount, token=token, created_at=created_at, expires_at=expires_at, raw_payload=raw)
    return {"ok": True, "status": "success", "state": "PACKAGE_PURCHASED", "code": "PACKAGE_PURCHASED", "http_status": 200, "variable": PACKAGE_STATUS, "amount": amount, "token": token, "token_id": saved["token_id"], "created_at": created_at, "expires_at": expires_at, "raw": raw, "record": {"status": "written", "ledger_id": saved["ledger_id"], "token_id": saved["token_id"]}}


def _validate_package(item: object, index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(item, dict):
        return None, _setting_error("PACKAGE_SETTING_PAYLOAD_INCOMPLETE", {"index": index, "missing": list(PACKAGE_SETTING_TOKEN_CONFIG["requires"]) + ["enabled"]})

    required = (*PACKAGE_SETTING_TOKEN_CONFIG["requires"], "enabled")
    unknown_fields = sorted(set(item) - set(required))
    if unknown_fields:
        return None, _setting_error("PACKAGE_SETTING_FIELD_NOT_DECLARED", {"index": index, "unknown_fields": unknown_fields})
    # A new package never receives an ID from the UI.  The central settings
    # logic creates it, then the customer button uses that returned same ID.
    data = dict(item)
    if not str(data.get("package_id") or "").strip():
        data["package_id"] = f"pkg_{secrets.token_urlsafe(9)}"
    missing = [field for field in required if field != "package_id" and (field not in data or data[field] in (None, ""))]
    if missing:
        return None, _setting_error("PACKAGE_SETTING_PAYLOAD_INCOMPLETE", {"index": index, "missing": missing})

    failed: list[str] = []
    package_id = str(data["package_id"]).strip()
    try:
        price = int(data["price"])
    except (TypeError, ValueError):
        price = 0
    exp_mode = str(data["exp_mode"]).strip()
    exp_value = str(data["exp_value"]).strip()
    enabled = data["enabled"]
    if not package_id:
        failed.append("package_id_present")
    if price <= 0:
        failed.append("price_positive")
    if exp_mode not in PACKAGE_SETTING_TOKEN_CONFIG["allowed_exp_modes"]:
        failed.append("expiry_mode_allowed")
    if exp_mode != "No":
        try:
            if int(exp_value) <= 0:
                failed.append("expiry_value_valid")
        except (TypeError, ValueError):
            failed.append("expiry_value_valid")
    if not isinstance(enabled, bool):
        failed.append("enabled_declared")
    if failed:
        return None, _setting_error("PACKAGE_SETTING_PAYLOAD_INVALID", {"index": index, "failed_conditions": failed})

    return {
        "package_id": package_id,
        "price": price,
        "exp_mode": exp_mode,
        "exp_value": exp_value,
        "enabled": enabled,
    }, None


def save_package_setting_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    items = data.get("runtime_packages")
    if not isinstance(items, list) or not items:
        return _setting_error("PACKAGE_SETTING_PAYLOAD_INCOMPLETE", {"missing": ["runtime_packages"]})

    valid_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        valid, error = _validate_package(item, index)
        if error:
            return error
        if valid:
            valid_items.append(valid)
    try:
        saved = replace_package_runtime_settings(valid_items, source="package.settings.save", updated_at=int(time.time()))
    except Exception as exc:
        return _setting_error("PACKAGE_SETTING_SAVE_FAILED", {"reason": str(exc)})
    return {
        "ok": True,
        "status": "success",
        "code": "PACKAGE_SETTING_SAVED",
        "http_status": 200,
        "variable": PACKAGE_STATUS,
        "amount": 0.0,
        "raw": _setting_raw("success", "PACKAGE_SETTING_SAVED", {
            "variable": PACKAGE_STATUS,
            "saved_packages": saved,
            "conditions": PACKAGE_SETTING_CONDITIONS["pass_when"],
            "button_contract": PACKAGE_SETTING_TOKEN_CONFIG["button_contract"],
            "purchase_check": PACKAGE_SETTING_TOKEN_CONFIG["purchase_check"],
            "outbound_actions": [
                {"action": "package_buy", "package_id": package_id,
                 "ui_sends": ("package_id",), "login_app_injects": ("username_customer",)}
                for package_id in saved
            ],
        }),
    }

__all__ = ["save_package_setting_config", "purchase_configured_package"]
