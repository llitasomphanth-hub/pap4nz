from __future__ import annotations

from typing import Any


TRUEMONEY_LINK_KEYWORD = "gift.truemoney.com"

TRUEMONEY_EVENT_TYPES = {
    "MONEY_LINK",
    "DIRECT_TOPUP",
}

TRUEMONEY_EMPTY_OK_FIELDS = {"message", "channel"}
TRUEMONEY_REQUIRED_FIELDS = {
    "MONEY_LINK": {"event_type", "received_time", "amount", "sender_mobile"},
    "DIRECT_TOPUP": {"event_type", "received_time", "amount"},
}

TRUEMONEY_STATUS_TEXT = {
    "ACCEPTED": "รับข้อมูลสำเร็จ",
    "USED": "ซองถูกใช้",
    "NOT_FOUND": "ไม่พบซองในระบบ",
    "INVALID_LINK": "ลิงก์ไม่ถูก",
    "SERVER_ERROR": "ระบบปลายทางผิดพลาด",
    "FORBIDDEN": "ไม่มีสิทธิ์เข้าถึง",
    "RATE_LIMITED": "ยิงถี่เกินไป",
    "UNAUTHORIZED": "ยืนยันตัวตนไม่ผ่าน",
    "MISSING_REQUIRED_FIELD": "ข้อมูลสำคัญไม่ครบ",
    "INVALID_AMOUNT": "ยอดเงินไม่ถูกต้อง",
    "NOT_TRUEMONEY_EVENT": "ข้อมูลนี้ไม่ใช่ TrueMoney event",
    "MISSING_PAYLOAD": "ไม่พบ payload",
}

HTTP_STATUS_MAP = {
    "ACCEPTED": 200,
    "USED": 409,
    "NOT_FOUND": 404,
    "INVALID_LINK": 400,
    "SERVER_ERROR": 500,
    "FORBIDDEN": 403,
    "RATE_LIMITED": 429,
    "UNAUTHORIZED": 401,
    "MISSING_REQUIRED_FIELD": 422,
    "INVALID_AMOUNT": 422,
    "NOT_TRUEMONEY_EVENT": 400,
    "MISSING_PAYLOAD": 400,
}


def receive_truemoney_webhook_event(
    payload: dict[str, Any] | str | None,
    caller: str = "unknown",
) -> dict[str, Any]:
    """
    ตัวกลางรับข้อมูล TrueMoney

    กฎกันบั๊ก:
    - missing field = key ไม่มาเลย
    - empty string = key มาแล้วแต่ค่าเป็น ""; บาง field ของ TrueMoney อนุญาต
    - คืน reason/debug ให้หลังบ้าน ไม่ตอบ failed ลอย ๆ
    """

    result = _make_result(
        code="MISSING_PAYLOAD",
        ok=False,
        caller=caller,
        raw=payload,
    )

    if not payload:
        return result

    status_code = _detect_status_code(payload)
    is_truemoney = _is_truemoney_payload(payload)
    clean_data = _extract_data(payload)

    if not is_truemoney:
        return _make_result(
            code=status_code or "NOT_TRUEMONEY_EVENT",
            ok=False,
            caller=caller,
            raw=payload,
            data=clean_data,
        )

    if isinstance(payload, dict):
        event_type = clean_data.get("event_type", "")
        required_fields = TRUEMONEY_REQUIRED_FIELDS.get(event_type, set())
        missing_fields = [field for field in required_fields if field not in payload]
        empty_required_fields = [
            field
            for field in required_fields
            if field in payload and payload.get(field) in (None, "")
        ]
        empty_ok_fields = [
            field
            for field in TRUEMONEY_EMPTY_OK_FIELDS
            if field in payload and payload.get(field) == ""
        ]

        clean_data["missing_fields"] = missing_fields
        clean_data["empty_required_fields"] = empty_required_fields
        clean_data["empty_ok_fields"] = empty_ok_fields
        clean_data["can_validate"] = not missing_fields and not empty_required_fields

        if missing_fields or empty_required_fields:
            return _make_result(
                code="MISSING_REQUIRED_FIELD",
                ok=False,
                caller=caller,
                raw=payload,
                data=clean_data,
            )

        try:
            amount_number = float(clean_data.get("amount", 0))
        except (TypeError, ValueError):
            amount_number = 0

        if event_type in TRUEMONEY_EVENT_TYPES and amount_number <= 0:
            return _make_result(
                code="INVALID_AMOUNT",
                ok=False,
                caller=caller,
                raw=payload,
                data=clean_data,
            )

    if status_code and status_code != "ACCEPTED":
        return _make_result(
            code=status_code,
            ok=False,
            caller=caller,
            raw=payload,
            data=clean_data,
        )

    return _make_result(
        code="ACCEPTED",
        ok=True,
        caller=caller,
        raw=payload,
        data=clean_data,
    )


def _make_result(
    code: str,
    ok: bool,
    caller: str,
    raw: Any = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    http_status = HTTP_STATUS_MAP.get(code, 400)
    status_text = TRUEMONEY_STATUS_TEXT.get(code, "ไม่ทราบสถานะ")
    clean_data = data or {}
    missing_fields = clean_data.get("missing_fields", [])
    empty_required_fields = clean_data.get("empty_required_fields", [])
    empty_ok_fields = clean_data.get("empty_ok_fields", [])

    return {
        "ok": ok,
        "code": code,
        "reason": code.lower(),
        "http_status": http_status,
        "status_text": status_text,
        "message": status_text,
        "caller": caller,

        "display": {
            "title": status_text,
            "level": "success" if ok else "error",
            "badge": code,
            "http_status": http_status,
        },

        "data": {
            "source": "truemoney",
            "event_type": clean_data.get("event_type", ""),
            "amount": clean_data.get("amount", 0),
            "sender_mobile": clean_data.get("sender_mobile", ""),
            "sender_name": clean_data.get("sender_name", ""),
            "transaction_id": clean_data.get("transaction_id", ""),
            "received_time": clean_data.get("received_time", ""),
            "channel": clean_data.get("channel", ""),
            "message": clean_data.get("message", ""),
            "link": clean_data.get("link", ""),
            "missing_fields": missing_fields,
            "empty_required_fields": empty_required_fields,
            "empty_ok_fields": empty_ok_fields,
            "can_validate": clean_data.get("can_validate", False),
        },

        "action": {
            "ready": ok,
            "called_from": caller,
            "can_retry": code in {"SERVER_ERROR", "RATE_LIMITED"},
            "can_replay": code in {"SERVER_ERROR", "RATE_LIMITED"},
            "can_edit": True,
            "next": "" if ok else "admin_review" if code in {"MISSING_REQUIRED_FIELD", "INVALID_AMOUNT"} else "",
        },

        "debug": {
            "owner": "truemoney_webhook_flow",
            "stage": "accepted" if ok else "validate_payload",
            "reason": code.lower(),
            "missing_fields": missing_fields,
            "empty_required_fields": empty_required_fields,
            "empty_ok_fields": empty_ok_fields,
            "empty_string_is_missing": False,
        },

        "raw": raw,
    }


def _is_truemoney_payload(payload: dict[str, Any] | str) -> bool:
    raw_text = str(payload)

    if TRUEMONEY_LINK_KEYWORD in raw_text:
        return True

    if isinstance(payload, dict):
        event_type = payload.get("event_type", "")
        if event_type in TRUEMONEY_EVENT_TYPES:
            return True

        link = payload.get("link", "") or payload.get("payload", "")
        if TRUEMONEY_LINK_KEYWORD in str(link):
            return True

    return False


def _detect_status_code(payload: dict[str, Any] | str) -> str:
    raw_text = str(payload).lower()

    if "used" in raw_text or "ซองถูกใช้" in raw_text:
        return "USED"

    if "not_found" in raw_text or "not found" in raw_text or "ไม่พบซอง" in raw_text:
        return "NOT_FOUND"

    if "invalid_link" in raw_text or "ลิงก์ไม่ถูก" in raw_text:
        return "INVALID_LINK"

    if "server_error" in raw_text or "500" in raw_text:
        return "SERVER_ERROR"

    if "forbidden" in raw_text or "403" in raw_text:
        return "FORBIDDEN"

    if "rate_limit" in raw_text or "429" in raw_text:
        return "RATE_LIMITED"

    if "unauthorized" in raw_text or "401" in raw_text:
        return "UNAUTHORIZED"

    return ""


def _extract_data(payload: dict[str, Any] | str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "link": str(payload),
            "can_validate": False,
            "missing_fields": [],
            "empty_required_fields": [],
            "empty_ok_fields": [],
        }

    raw_link = (
        payload.get("link")
        or payload.get("payload")
        or payload.get("url")
        or ""
    )

    return {
        "event_type": payload.get("event_type", ""),
        "amount": payload.get("amount", 0),
        "sender_mobile": payload.get("sender_mobile", ""),
        "sender_name": payload.get("sender_name", ""),
        "transaction_id": payload.get("transaction_id", ""),
        "received_time": payload.get("received_time", ""),
        "channel": payload.get("channel", ""),
        "message": payload.get("message", ""),
        "link": raw_link,
    }
