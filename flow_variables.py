from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

FLOW_VARIABLE_PATH = ("UI", "PORT", "DB_LOGIC")
PAPXNZ_SYSTEM_CONFIG = {
    "system_key": "PAPXNZ_LOGIN_SYSTEM",
    "app_port": int(os.getenv("LOGIN_APP_PORT") or os.getenv("PORT") or "8030"),
    "main_web_link": os.getenv("MAIN_WEB_LINK", "https://papxnzvip.com/"),
    "host": os.getenv("PAPXNZ_HOST", "papxnzvip.com"),
    # The permanent PAPXNZ identity allowed to operate the emergency/admin UI.
    # Deployment may override this without changing source.
    "admin_login_id": os.getenv("PAPXNZ_ADMIN_LOGIN_ID", "8092b9fc75254dadae364944d103cefa"),
}

WEB_USER_KEY = "WEB_USER_KEY"
FINANCE_BALANCE = "FINANCE_BALANCE"
TOPUP_STATUS = "TOPUP_STATUS"
PACKAGE_STATUS = "PACKAGE_STATUS"
UI_DECISION_DB = "UI_DECISION_DB"
# Backend access contract.  A customer may read only records scoped to their
# own key; UI callers do not grant themselves access by naming a variable.
WEB_USER_ACCESS_REQUIREMENTS = {
    WEB_USER_KEY: {"read": "owner_only", "record": "per_user_history", "fields": ("user_key",), "login_only": True},
    FINANCE_BALANCE: {"read": "owner_only", "record": "amount", "fields": ("amount",)},
    TOPUP_STATUS: {"read": "owner_only", "record": "state", "fields": ()},
    PACKAGE_STATUS: {"read": "owner_only", "record": "state", "fields": ()},
}

# UI answer shape only. It describes the returned slots; it does not judge truth.
UI_STATUS_VARIABLE_GUIDE = {
    "success": {"message": "token"},
    "error": {"message": ("ไม่พบชื่อในระบบ", "not found", "เรียกข้อมูลไม่ตรงกัน", "ระบุข้อมูลให้ครบ!")},
    "unknown": {"raw": True},
}

# These names are query labels for one recorded result stream.  They do not
# own separate state: db_logic evaluates an action, records raw + amount, and
# later reads that same record stream through the requested label.
KEY_DATA_FLOWS = {
    "FINANCE_BALANCE": {"read_from": ("web_wallet_transactions.amount",), "record": ("user_key", "amount", "status", "created_at"), "meaning": "read-only total of recorded amounts"},
    "TOPUP_STATUS": {"origin": "topup only", "actions": ("webhook.settings.read", "webhook.settings.save", "webhook.keyapi.issue", "decision.truemoney_webhook", "topup.record"), "record": ("raw", "amount", "status", "created_at"), "meaning": "every result called as a topup is TOPUP_STATUS"},
    "PACKAGE_STATUS": {"origin": "package only", "actions": ("package.settings.save", "package_buy"), "record": ("package_id", "amount", "token", "status", "created_at"), "meaning": "every result called as a package is PACKAGE_STATUS"},
}

RAW_SYSTEM_FACT_MAP = {
    "เป็นคนที่มีตัวตนอยู่ในเว็บนี้": {"variable": WEB_USER_KEY, "port": "core.backend_port"},
    "บันทึกamontถ้าหักลบได้คือที่เดียวกัน": {"variable": FINANCE_BALANCE, "port": "core.backend_port"},
    "บันทึกเติมเงินเว็บฮุก": {"variable": TOPUP_STATUS, "port": "core.backend_port"},
    "บันทึกรายการซื้อแพกเกจ": {"variable": PACKAGE_STATUS, "port": "core.backend_port"},
}

PORT_VARIABLE_STATUS_MAP = {
    "AUTH_IDENTITY_CONFIG": {"port": "core.backend_port", "action": "account.check", "next_logic": "core.db_logic", "status_variable": WEB_USER_KEY},
    "FINANCE_LEDGER_CONFIG": {"port": "core.backend_port", "action": "finance.summary", "next_logic": "core.finance_logic", "status_variable": FINANCE_BALANCE},
    "TRUEMONEY_WEBHOOK_CONFIG": {"port": "core.backend_port", "action": "decision.truemoney_webhook", "next_logic": "core.truemoney_webhook_flow", "status_variable": TOPUP_STATUS},
    "PACKAGE_SETTING_TOKEN_CONFIG": {"port": "core.backend_port", "action": "package.settings.save", "next_logic": "core.package_settings_logic", "status_variable": PACKAGE_STATUS},
    "PACKAGE_PURCHASE_CONFIG": {"port": "core.backend_port", "action": "package_buy", "next_logic": "core.db_logic", "status_variable": PACKAGE_STATUS},
}

DATA_KEY_REGISTRY = {
    "PERMANENT_USER_KEY": {"format": "user:{auth_users.public_user_id}", "source_table": "auth_users", "fallback_allowed": False},
    "FINANCE_RECORD_KEY": {"format": "finance:{PERMANENT_USER_KEY}", "source_tables": ("web_user_wallets", "web_wallet_transactions"), "fallback_allowed": False},
    "PACKAGE_SETTING_KEY": {"format": "package:{package_id}", "source_table": "package_runtime_settings", "fallback_allowed": False},
    "PACKAGE_PURCHASE_KEY": {"format": "purchase:{PERMANENT_USER_KEY}:{package_id}", "source_tables": ("package_purchase_requests", "package_access_tokens"), "fallback_allowed": False},
    "ANSWER_PACKET_KEY": {"format": "answer:{PERMANENT_USER_KEY}:{action}:{event_id}", "source_table": "frontend_answer_packets", "fallback_allowed": False},
}

RAW_TRANSACTION_VARIABLES = {
    "WEBHOOK_RAW_AMOUNT": {"input": "webhook.payload.amount", "record": "raw_transaction.amount"},
    "WEBHOOK_RAW_EVENT": {"input": "webhook.payload", "record": "raw_transaction.payload"},
    "EXTERNAL_TRANSACTION_KEY": {"input": "transaction_id|gift_link|source_ref", "record": "raw_transaction.source_ref"},
}

PACKAGE_SETTING_TOKEN_CONFIG = {
    "variable": "PACKAGE_SETTING_TOKEN_CONFIG", "action": "package.settings.save",
    "admin_caller": "login_app:/ui-api/package-settings",
    "ui_variables": (WEB_USER_KEY,),
    "requires": ("package_id", "price", "exp_mode", "exp_value"),
    "package_fields": ("package_id", "price", "exp_mode", "exp_value"),
    "returns": (PACKAGE_STATUS,), "allowed_exp_modes": ("days", "months", "years", "No"),
    "button_contract": {
        "package_id": "settings logic สร้าง/บันทึก แล้วปุ่มส่ง ID เดิมนี้เท่านั้น",
        "ui_sends": ("package_id",),
        "login_app_injects": ("username_customer",),
        "purchase_action": "package_buy",
    },
    # Documentation for the action that uses one saved package.  DB logic
    # reads the accumulated blocks; login_event_filter only supplies identity.
    "purchase_check": {
        "when": ("package_id_present", "request_customer_history", "balance_available"),
        "db_reads": ("login_identity", "web_wallet_transactions", "package_runtime_settings"),
        "success_returns": ("amount", "token"),
    },
    "raw_outcomes": {
        "variable_mismatch": "VARIABLE_ACTION_MISMATCH",
        "admin_binding_missing": "PACKAGE_SETTING_ADMIN_BINDING_REQUIRED",
        "payload_incomplete": "PACKAGE_SETTING_PAYLOAD_INCOMPLETE",
        "condition_failed": "PACKAGE_SETTING_PAYLOAD_INVALID",
        "saved": "PACKAGE_SETTING_SAVED",
        "save_failed": "PACKAGE_SETTING_SAVE_FAILED",
    },
}
PACKAGE_SETTING_CONDITIONS = {
    "record_variables": ("package_id", "price", "exp_mode", "exp_value", "enabled", "status", "source", "updated_at"),
    "record_table": "package_runtime_settings",
    "pass_when": ("package_id_present", "price_positive", "expiry_mode_allowed", "expiry_value_valid", "enabled_declared"),
    "returns": (PACKAGE_STATUS,),
}
PACKAGE_SETTING_DB_FLOW = {
    "input": "Variable Settings",
    "read": ("package_id", "price", "exp_mode", "exp_value"),
    "transform": {"price": "package_price"},
    "check": ("package_id_present", "price_positive", "expiry_mode_allowed", "expiry_value_valid", "enabled_declared"),
    "debit_from": (),
    "write_to": ("package_runtime_settings",),
    "returns": ("http_status", "raw"),
}
PACKAGE_PURCHASE_CONFIG = {
    "variable": "PACKAGE_PURCHASE_CONFIG", "action": "package_buy",
    "ui_variables": (WEB_USER_KEY,), "requires": ("package_id", "username_customer"),
    "ui_sends": ("package_id",), "login_app_injects": ("username_customer",),
    "feedback_field": "package_id", "feedback_matches": "package_runtime_settings.package_id",
    "returns": (PACKAGE_STATUS, FINANCE_BALANCE), "success_raw": ("amount", "token"),
    "pass_when": ("username_customer_present", "topup_history_exists", "package_exists", "balance_sufficient"),
    "action_raw": ("username_customer", "package_id"),
    # This is documentation of the action shape only. db_logic decides code;
    # backend_port supplies its complete UI choice for that exact code.
    "known_result_contract": {
        "status": ("success", "error"),
        "message": "declared backend-port UI choice",
        "code": "actual system code",
    },
}
FINANCE_LEDGER_CONFIG = {
    "variable": "FINANCE_LEDGER_CONFIG", "action": "finance.summary",
    "ui_variables": (WEB_USER_KEY,), "requires": ("WEB_USER_KEY",),
    "returns": (FINANCE_BALANCE,), "pass_when": ("user_exists", "finance_record_exists"),
}
TRUEMONEY_WEBHOOK_CONFIG = {
    "variable": "TRUEMONEY_WEBHOOK_CONFIG", "action": "decision.truemoney_webhook",
    "plugin": "core.truemoney_webhook_flow",
    "ui_variables": (),
    "requires": ("raw", "amount"),
    "settings_keys": ("APIURL", "HTTPMethod", "keyapi", "phone", "allowed_ips", "JWT_SECRET", "JWT_ALGORITHM"),
    "action_contract": {
        "ui_input": ("gift_link",),
        "configuration_action": {
            "action": "webhook.settings.save",
            "caller": "login_app:/ui-api/backend-settings",
            "writes": ("keyapi", "phone", "APIURL", "HTTPMethod", "JWT_SECRET", "JWT_ALGORITHM"),
            "rule": "การตั้งค่า action เขียนทับ phone ได้; การส่งซองอ่านค่าล่าสุด",
        },
        "action_reads_from_settings": ("keyapi", "phone", "APIURL", "HTTPMethod"),
        "action_outbound": ("Authorization:keyapi", "phone", "gift_link"),
        "provider_response_checks": ("raw.phone == action.phone",),
    },
    "record_variable": TOPUP_STATUS,
    "returns": ("raw", "http_status", "amount", TOPUP_STATUS),
    "pass_when": ("raw_is_object", "keyapi_matches_setting", "phone_matches_setting", "gift_link_is_url", "url_matches_setting_when_present", "method_matches_setting_when_present", "ip_matches_setting_when_present", "amount_positive"),
    # This is the provider-result contract, owned by backend settings/logic.
    # UI receives the declared state; it never compares raw.message itself.
    "provider_result_contract": {
        "success": {
            "state": "TRUEMONEY_SUCCESS",
            "when": {"status": "success", "message": "สำเร็จ"},
            "required_raw": ("amount", "phone", "owner_profile", "redeemer_profile", "gift_link", "time"),
        },
        # Error message is intentionally not fixed.  Provider owns it; UI may
        # later choose its own wording from raw.message or an UI-side rule.
        "error": {"state": "TRUEMONEY_ERROR", "when": {"status": "error"}, "required_raw": ("message",)},
        "fallback_state": "SYSTEM_ERROR",
    },
}
TRUEMONEY_WEBHOOK_SETTING_RULE = {
    "variable": "TRUEMONEY_WEBHOOK_CONFIG",
    "record_table": "backend_settings",
    "fields": ("APIURL", "HTTPMethod", "keyapi", "phone", "allowed_ips"),
    "request_fields": ("raw", "amount"),
    "when_present": {
        "APIURL": "ยอมรับเฉพาะคำขอจาก URL นี้",
        "HTTPMethod": "ยอมรับเฉพาะ method นี้",
        "keyapi": "ตรวจ keyapi กับค่าที่บันทึก",
        "phone": "ตรวจเบอร์กับค่าที่บันทึก",
        "allowed_ips": "ตรวจ IP ถ้ามีค่า",
        "JWT_SECRET": "Secret สำหรับตรวจ JWT signature",
        "JWT_ALGORITHM": "ต้องเป็น HS256 ตามสัญญา",
        "gift_link": "รับ raw ซอง TrueMoney",
    },
    "returns": {"match": "raw", "missing": "error", "mismatch": "error"},
    "record_result": TOPUP_STATUS,
}

FLOW_VARIABLES = {key: value for key, value in {"PACKAGE_SETTING_TOKEN_CONFIG": PACKAGE_SETTING_TOKEN_CONFIG, "PACKAGE_PURCHASE_CONFIG": PACKAGE_PURCHASE_CONFIG, "FINANCE_LEDGER_CONFIG": FINANCE_LEDGER_CONFIG, "TRUEMONEY_WEBHOOK_CONFIG": TRUEMONEY_WEBHOOK_CONFIG}.items()}
FLOW_QUESTION_CONTRACTS = FLOW_VARIABLES

def flow_variable(name: str) -> dict[str, Any]: return deepcopy(FLOW_VARIABLES.get(str(name or "").strip(), {}))
def data_key(name: str) -> dict[str, Any]: return deepcopy(DATA_KEY_REGISTRY.get(str(name or "").strip(), {}))
def system_source_gate(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {"trusted": str(data.get("system_key") or "").strip() == PAPXNZ_SYSTEM_CONFIG["system_key"], "system_key": str(data.get("system_key") or "")}


def resolve_variable_action(variable: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a declared variable/action pair before it reaches a webhook/port."""
    data = payload if isinstance(payload, dict) else {}
    name = str(variable or data.get("variable") or "").strip()
    expected = PORT_VARIABLE_STATUS_MAP.get(name) or next((item for item in PORT_VARIABLE_STATUS_MAP.values() if item.get("status_variable") == name), None)
    action_name = str(action or data.get("action") or "").strip()
    if not name or not expected:
        return {"ok": False, "code": "VARIABLE_NOT_DECLARED", "variable": name, "action": action_name}
    if action_name != str(expected.get("action") or ""):
        return {"ok": False, "code": "VARIABLE_ACTION_MISMATCH", "variable": name, "action": action_name, "expected_action": expected.get("action")}
    return {"ok": True, "variable": name, "action": action_name, "port": expected.get("port"), "next_logic": expected.get("next_logic"), "payload": data}

__all__ = ["FLOW_VARIABLE_PATH", "PAPXNZ_SYSTEM_CONFIG", "RAW_SYSTEM_FACT_MAP", "PORT_VARIABLE_STATUS_MAP", "DATA_KEY_REGISTRY", "RAW_TRANSACTION_VARIABLES", "WEB_USER_KEY", "FINANCE_BALANCE", "TOPUP_STATUS", "PACKAGE_STATUS", "UI_DECISION_DB", "WEB_USER_ACCESS_REQUIREMENTS", "UI_STATUS_VARIABLE_GUIDE", "KEY_DATA_FLOWS", "PACKAGE_SETTING_TOKEN_CONFIG", "PACKAGE_SETTING_CONDITIONS", "PACKAGE_SETTING_DB_FLOW", "PACKAGE_PURCHASE_CONFIG", "FINANCE_LEDGER_CONFIG", "TRUEMONEY_WEBHOOK_CONFIG", "TRUEMONEY_WEBHOOK_SETTING_RULE", "FLOW_VARIABLES", "FLOW_QUESTION_CONTRACTS", "flow_variable", "data_key", "system_source_gate", "resolve_variable_action"]
