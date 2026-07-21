from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "bot_token",
    "client_secret",
    "code_verifier",
    "credential",
    "hash",
    "id_token",
    "init_data",
    "initdata",
    "otp",
    "password",
    "secret",
    "token",
}


def normalize_login_event_payload(
    payload: dict[str, Any] | None,
    *,
    domain: str = "",
    action: str = "",
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    clean_action = _text(action or data.get("action") or data.get("action_key") or data.get("mode"))
    provider = _provider(data, domain)
    identity = _identity(data, provider=provider)
    safe = _redact(data)
    safe.update(
        {
            "event_family": "login",
            "domain": _text(domain or provider or data.get("domain") or "unknown"),
            "provider": provider,
            "action": clean_action,
            "action_key": clean_action,
            "event_type": clean_action,
            "source": _text(data.get("source") or data.get("caller") or ""),
            "ui_id": _text(data.get("ui_id")),
            "session_id": _text(data.get("session_id") or data.get("ui_session_id")),
            "ui_fingerprint_id": _text(data.get("ui_fingerprint_id")),
            "actor_name": _actor_name(data, identity, provider),
            "ip": _first_text(data.get("ip"), data.get("request_ip"), data.get("client_ip"), data.get("remote_addr"), data.get("x_forwarded_for")),
            "user_agent": _first_text(data.get("user_agent"), data.get("ua"), data.get("browser")),
            "identity": identity,
            "filter_version": "login-event-filter-v1",
        }
    )
    return safe


def normalize_login_event_result(result: dict[str, Any] | None) -> dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    safe = {key: value for key, value in data.items() if key not in {"db_event"}}
    return _redact(safe)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                clean[key_text] = "[redacted]"
            else:
                clean[key_text] = _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in SENSITIVE_KEYS or lowered.endswith("_token") or lowered.endswith("_secret")


def _identity(data: dict[str, Any], *, provider: str) -> dict[str, str]:
    username = _first_text(data.get("username"), data.get("login"), data.get("ui_saved_user"), data.get("telegram_username"))
    user_id = _first_text(data.get("user_id"), data.get("web_user_id"), data.get("auth_user_id"))
    provider_user_id = _first_text(
        data.get("provider_user_id"),
        data.get("telegram_id"),
        data.get("telegram_user_id"),
        data.get("google_sub"),
        data.get("id"),
    )
    google_email = _text(data.get("google_email") or data.get("email") or data.get("expected_email") or data.get("expectedEmail")).lower()
    state = "known" if any((username, user_id, provider_user_id, google_email)) else "unknown"
    return {
        "state": state,
        "provider": provider,
        "username": username,
        "user_id": user_id,
        "provider_user_id": provider_user_id,
        "google_email": google_email,
        "ui_fingerprint_id": _text(data.get("ui_fingerprint_id")),
        "session_id": _text(data.get("session_id") or data.get("ui_session_id")),
    }


def _actor_name(data: dict[str, Any], identity: dict[str, str], provider: str) -> str:
    actor = _first_text(
        data.get("actor_name"),
        data.get("full_name"),
        data.get("name"),
        data.get("first_name"),
        data.get("telegram_username"),
        data.get("telegram_identifier"),
        identity.get("username"),
        identity.get("google_email"),
        identity.get("provider_user_id"),
        identity.get("user_id"),
        data.get("ui_fingerprint_id"),
    )
    if provider == "telegram" and actor and not actor.startswith("@") and not actor.isdigit() and "@" not in actor and " " not in actor:
        return f"@{actor}"
    return actor


def _provider(data: dict[str, Any], domain: str) -> str:
    provider = _text(data.get("provider")).lower()
    if provider:
        return provider
    raw = f"{domain} {data}".lower()
    if "telegram" in raw:
        return "telegram"
    if "google" in raw:
        return "google"
    return _text(domain).lower()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["normalize_login_event_payload", "normalize_login_event_result"]
