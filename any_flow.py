"""Shared fresh-data doorway for declared PAPXNZ variables.

Callers name the variable they already own.  Any never invents a variable,
does not cache values, and does not decide an equation; it only leads the
caller to the matching db_logic reader.
"""
from __future__ import annotations

from typing import Any

from .flow_variables import FINANCE_BALANCE, PACKAGE_STATUS, TOPUP_STATUS, WEB_USER_KEY

# One literal registry prevents a caller from having to remember where each
# flow lives.  The action owner still decides/writes; this is only the shared
# name-to-flow map used by every internal caller.
ANY_FLOW_REGISTRY = {
    WEB_USER_KEY: {
        "flow": "login",
        "actions": ("account.check", "auth.telegram.openid_confirm", "auth.google.login"),
        "reader": "db_logic.find_auth_account",
        "meaning": "permanent identity of one logged-in web user",
    },
    TOPUP_STATUS: {
        "flow": "topup",
        "actions": ("truemoney.submit", "decision.truemoney_webhook", "topup.record"),
        "reader": "db_logic.read_topup_status",
        "meaning": "result/state of a topup flow",
    },
    PACKAGE_STATUS: {
        "flow": "package",
        "actions": ("package.settings.save", "package_buy", "package.page_config.read"),
        "reader": "db_logic.read_package_purchase_inputs",
        "meaning": "result/state of a package flow",
    },
    FINANCE_BALANCE: {
        "flow": "finance",
        "actions": ("finance.summary",),
        "reader": "db_logic.read_finance_balance",
        "meaning": "current sum of recorded amounts",
    },
}


def get_any_flow(variable: str) -> dict[str, Any]:
    """Return the declared owner map; it does not execute or decide a flow."""
    item = ANY_FLOW_REGISTRY.get(str(variable or ""))
    return dict(item) if item else {}


def read_any(*, variable: str, user_key: str = "", package_id: str = "", provider: str = "", provider_user_id: str = "", email: str = "") -> dict[str, Any]:
    """Read fresh facts from the DB reader declared by ``variable``."""
    from . import db_logic

    key = str(user_key or "").strip()
    if variable == FINANCE_BALANCE:
        return db_logic.read_finance_balance(user_key=key)
    if variable == TOPUP_STATUS:
        return db_logic.read_topup_status(user_key=key)
    if variable == PACKAGE_STATUS:
        return db_logic.read_package_purchase_inputs(user_key=key, package_id=str(package_id or ""))
    if variable == WEB_USER_KEY:
        return db_logic.find_auth_account(
            provider=str(provider or ""),
            provider_user_id=str(provider_user_id or key),
            email=str(email or ""),
            web_user_id=key,
        ) or {"ok": False, "status": "error", "code": "ACCOUNT_NOT_FOUND", "http_status": 404, "raw": {"user_key": key}}
    return {"ok": False, "status": "error", "code": "ANY_VARIABLE_NOT_DECLARED", "http_status": 400, "raw": {"variable": variable}}


__all__ = ["ANY_FLOW_REGISTRY", "get_any_flow", "read_any"]
