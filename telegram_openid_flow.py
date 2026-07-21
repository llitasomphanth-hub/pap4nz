"""One Telegram login flow: OpenID code -> verified identity -> PAPXNZ session."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from typing import Any
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .any_flow import read_any
from .db_logic import create_auth_session_for_user_id, record_auth_provider_event, upsert_auth_identity
from .flow_variables import WEB_USER_KEY

TELEGRAM_PROVIDER = "telegram"
TELEGRAM_OIDC_ISSUER = "https://oauth.telegram.org"
TELEGRAM_OIDC_TOKEN_URL = "https://oauth.telegram.org/token"
TELEGRAM_OIDC_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
TELEGRAM_LOGIN_CLIENT_ID_ENV = "TELEGRAM_LOGIN_CLIENT_ID"
TELEGRAM_LOGIN_CLIENT_SECRET_ENV = "TELEGRAM_LOGIN_CLIENT_SECRET"
_JWKS_CACHE: dict[str, Any] = {"loaded_at": 0, "keys": []}


def receive_telegram_openid_confirm(payload: dict[str, Any] | None = None, *, jwks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify Telegram's callback and create the one server-owned web session."""
    data = dict(payload or {})
    exchange = exchange_telegram_code(data)
    if not exchange["ok"]:
        return _answer(exchange, data)

    verified = verify_telegram_id_token(exchange["id_token"], jwks=jwks)
    if not verified["ok"]:
        return _answer(verified, data)

    user = verified["user"]
    account = upsert_auth_identity(
        provider=TELEGRAM_PROVIDER,
        provider_user_id=user["id"],
        provider_username=user["username"],
        display_name=user["name"] or user["username"] or user["id"],
        raw_payload={"claims": verified["claims"]},
        web_user_prefix="web_tg",
    )
    if not account.get("ok"):
        return _answer({"ok": False, "code": "TELEGRAM_ACCOUNT_WRITE_FAILED", "http_status": 500, "message": "บันทึกบัญชี Telegram ไม่สำเร็จ"}, data)

    # Read the just-written permanent key through the shared fresh-data lane.
    # Any does not decide login; db_logic confirms the identity it stored.
    current_identity = read_any(variable=WEB_USER_KEY, user_key=str(account["web_user_id"]))
    if not current_identity.get("ok"):
        return _answer({"ok": False, "code": "TELEGRAM_ACCOUNT_READ_FAILED", "http_status": 500, "message": "อ่านบัญชี Telegram ไม่สำเร็จ"}, data)
    stored_user = current_identity.get("user") if isinstance(current_identity.get("user"), dict) else {}
    web_user_key = str(stored_user.get("public_user_id") or account["web_user_id"])

    session = create_auth_session_for_user_id(account["auth_user_id"], data)
    if not session.get("ok"):
        return _answer({"ok": False, "code": "AUTH_SESSION_CREATE_FAILED", "http_status": 500, "message": "สร้าง session ไม่สำเร็จ"}, data)

    return _answer({
        "ok": True,
        "code": "TELEGRAM_OPENID_VERIFIED",
        "http_status": 200,
        "message": "เข้าสู่ระบบด้วย Telegram สำเร็จ",
        "WEB_USER_KEY": web_user_key,
        "web_user_id": web_user_key,
        "auth_user_id": account["auth_user_id"],
        "telegram_user_id": user["id"],
        "telegram_username": user["username"],
        "token": session["token"],
        "expires_in": session["expires_in"],
        "auth_session": {"ok": True, "cookie": "papxnz_auth"},
    }, data)


def exchange_telegram_code(payload: dict[str, Any]) -> dict[str, Any]:
    code = str(payload.get("code") or "").strip()
    redirect_uri = str(payload.get("redirect_uri") or "").strip()
    verifier = str(payload.get("code_verifier") or "").strip()
    client_id = str(os.getenv(TELEGRAM_LOGIN_CLIENT_ID_ENV) or payload.get("client_id") or "").strip()
    client_secret = str(os.getenv(TELEGRAM_LOGIN_CLIENT_SECRET_ENV) or "").strip()
    if not code:
        return {"ok": False, "code": "TELEGRAM_AUTHORIZATION_CODE_REQUIRED", "http_status": 400, "message": "ไม่พบ code จาก Telegram"}
    if not redirect_uri:
        return {"ok": False, "code": "TELEGRAM_REDIRECT_URI_REQUIRED", "http_status": 400, "message": "ไม่พบ redirect_uri"}
    if not verifier:
        return {"ok": False, "code": "TELEGRAM_CODE_VERIFIER_REQUIRED", "http_status": 400, "message": "ไม่พบ code_verifier"}
    if not client_id:
        return {"ok": False, "code": "TELEGRAM_CLIENT_ID_MISSING", "http_status": 500, "message": "ยังไม่ได้ตั้งค่า Telegram client id"}
    if not client_secret:
        return {"ok": False, "code": "TELEGRAM_CLIENT_SECRET_MISSING", "http_status": 500, "message": "ยังไม่ได้ตั้งค่า Telegram client secret"}
    body = urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier}).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(TELEGRAM_OIDC_TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "code": "TELEGRAM_TOKEN_EXCHANGE_FAILED", "http_status": 502, "message": "แลก token Telegram ไม่สำเร็จ"}
    id_token = str(token_data.get("id_token") or "").strip()
    if not id_token:
        return {"ok": False, "code": "TELEGRAM_ID_TOKEN_MISSING", "http_status": 401, "message": "Telegram ไม่ส่ง id_token กลับมา"}
    return {"ok": True, "id_token": id_token}


def verify_telegram_id_token(id_token: str, *, jwks: dict[str, Any] | None = None) -> dict[str, Any]:
    client_id = str(os.getenv(TELEGRAM_LOGIN_CLIENT_ID_ENV) or "").strip()
    if not client_id:
        return {"ok": False, "code": "TELEGRAM_CLIENT_ID_MISSING", "http_status": 500, "message": "ยังไม่ได้ตั้งค่า Telegram client id"}
    try:
        header_raw, claims_raw, signature_raw = id_token.split(".")
        header, claims = json.loads(_decode(header_raw)), json.loads(_decode(claims_raw))
    except Exception:
        return {"ok": False, "code": "TELEGRAM_ID_TOKEN_MALFORMED", "http_status": 401, "message": "id_token ไม่ถูกต้อง"}
    audience = claims.get("aud")
    audience_ok = client_id in audience if isinstance(audience, list) else str(audience or "") == client_id
    if header.get("alg") != "RS256" or claims.get("iss") != TELEGRAM_OIDC_ISSUER or not audience_ok or int(claims.get("exp") or 0) <= int(time.time()):
        return {"ok": False, "code": "TELEGRAM_ID_TOKEN_INVALID", "http_status": 401, "message": "token Telegram ไม่ถูกต้องหรือหมดอายุ"}
    key = _verification_key(header, jwks)
    if key is None:
        return {"ok": False, "code": "TELEGRAM_JWKS_KEY_MISSING", "http_status": 502, "message": "ไม่พบ public key Telegram"}
    try:
        key.verify(_decode(signature_raw), f"{header_raw}.{claims_raw}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return {"ok": False, "code": "TELEGRAM_ID_TOKEN_SIGNATURE_INVALID", "http_status": 401, "message": "ลายเซ็น Telegram ไม่ถูกต้อง"}
    telegram_id = str(claims.get("sub") or "").strip()
    if not telegram_id:
        return {"ok": False, "code": "TELEGRAM_USER_MISSING", "http_status": 400, "message": "ไม่พบผู้ใช้ Telegram"}
    return {"ok": True, "claims": claims, "user": {"id": telegram_id, "username": str(claims.get("preferred_username") or claims.get("username") or "").strip().lstrip("@"), "name": str(claims.get("name") or "").strip()}}


def _verification_key(header: dict[str, Any], jwks: dict[str, Any] | None):
    keys = (jwks or _load_jwks()).get("keys") or []
    for item in keys:
        if str(item.get("kid") or "") == str(header.get("kid") or "") and item.get("kty") == "RSA":
            return rsa.RSAPublicNumbers(int.from_bytes(_decode(str(item.get("e") or "")), "big"), int.from_bytes(_decode(str(item.get("n") or "")), "big")).public_key()
    return None


def _load_jwks() -> dict[str, Any]:
    now = int(time.time())
    if _JWKS_CACHE["keys"] and now - int(_JWKS_CACHE["loaded_at"]) < 3600:
        return {"keys": _JWKS_CACHE["keys"]}
    with urllib.request.urlopen(TELEGRAM_OIDC_JWKS_URL, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    _JWKS_CACHE.update({"loaded_at": now, "keys": list(data.get("keys") or [])})
    return data


def _decode(value: str) -> bytes:
    raw = str(value).encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _answer(result: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    answer = dict(result)
    answer["status"] = "success" if answer.get("ok") else "error"
    answer.setdefault("amount", 0.0)
    answer["provider"] = TELEGRAM_PROVIDER
    answer["raw"] = {"action": "auth.telegram.openid_confirm", "http_status": answer.get("http_status"), "provider": TELEGRAM_PROVIDER}
    record_auth_provider_event(TELEGRAM_PROVIDER, answer, source="telegram_openid_flow")
    return answer


__all__ = ["receive_telegram_openid_confirm"]
