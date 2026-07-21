"""Finance flow declaration. DB access belongs only to db_logic."""
from __future__ import annotations
from typing import Any
from .flow_variables import WEB_USER_KEY, FINANCE_BALANCE
from .any_flow import read_any

LOGIC_KEYS = (WEB_USER_KEY, FINANCE_BALANCE)
FINANCE_FLOW_ROLE = "finance_flow_declaration"
FINANCE_VARIABLE = FINANCE_BALANCE
FINANCE_USED_VARIABLES = LOGIC_KEYS
FINANCE_RECORD_KEY = "FINANCE_RECORD_KEY"
DB_FINANCE_BALANCE_REQUEST = {"variable": FINANCE_BALANCE, "read_from": (FINANCE_BALANCE,), "returns": (FINANCE_BALANCE,)}

def read_finance_money_summary(identity: dict[str, Any] | None) -> dict[str, Any]:
    raw = identity if isinstance(identity, dict) else {}
    user_key = str(raw.get("owner_key") or raw.get("user_key") or raw.get("permanent_user_key") or raw.get("user_id") or "").strip()
    result = read_any(variable=FINANCE_BALANCE, user_key=user_key)
    result.update({"action": "finance.summary", "request": DB_FINANCE_BALANCE_REQUEST, "raw": raw})
    return result

__all__ = ["LOGIC_KEYS", "FINANCE_FLOW_ROLE", "FINANCE_VARIABLE", "FINANCE_USED_VARIABLES", "FINANCE_RECORD_KEY", "DB_FINANCE_BALANCE_REQUEST", "read_finance_money_summary"]
