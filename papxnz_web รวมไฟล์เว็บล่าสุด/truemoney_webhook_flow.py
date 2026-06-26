from __future__ import annotations

from typing import Any


TRUEMONEY_LINK_KEYWORD = "gift.truemoney.com"

TRUEMONEY_EVENT_TYPES = {
    "MONEY_LINK",
    "DIRECT_TOPUP",
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
    "NOT_TRUEMONEY_EVENT": 400,
    "MISSING_PAYLOAD": 400,
}


def receive_truemoney_webhook_event(
    payload: dict[str, Any] | str | None,
    caller: str = "unknown",
) -> dict[str, Any]:
    """
    ตัวกลางรับข้อมูล TrueMoney

    หน้าที่:
    - รู้ว่าไฟล์ไหนเรียก ผ่าน caller
    - เช็กว่า payload เป็น TrueMoney ไหม
    - คืน result กลางให้หลังบ้านเอาไปโชว์
    - คืน action flags ให้ไฟล์ที่เรียกไปแตกโฟลวต่อเอง
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

    if not is_truemoney:
        return _make_result(
            code=status_code or "NOT_TRUEMONEY_EVENT",
            ok=False,
            caller=caller,
            raw=payload,
        )

    if status_code and status_code != "ACCEPTED":
        return _make_result(
            code=status_code,
            ok=False,
            caller=caller,
            raw=payload,
            data=_extract_data(payload),
        )

    return _make_result(
        code="ACCEPTED",
        ok=True,
        caller=caller,
        raw=payload,
        data=_extract_data(payload),
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

    return {
        "ok": ok,
        "code": code,
        "http_status": http_status,
        "status_text": status_text,
        "message": status_text,
        "caller": caller,

        # สถานะจริง เอาไว้ให้หลังบ้านโชว์
        "display": {
            "title": status_text,
            "level": "success" if ok else "error",
            "badge": code,
            "http_status": http_status,
        },

        # ข้อมูลที่แตกออกมาให้ไฟล์อื่นเอาไปใช้
        "data": {
            "source": "truemoney",
            "event_type": clean_data.get("event_type", ""),
            "amount": clean_data.get("amount", 0),
            "sender_mobile": clean_data.get("sender_mobile", ""),
            "received_time": clean_data.get("received_time", ""),
            "channel": clean_data.get("channel", ""),
            "message": clean_data.get("message", ""),
            "link": clean_data.get("link", ""),
        },

        # ให้ตัวที่เรียกไปแตกโฟลวเอง
        "action": {
            "ready": ok,
            "called_from": caller,
            "can_retry": code in {"SERVER_ERROR", "RATE_LIMITED"},
            "can_replay": code in {"SERVER_ERROR", "RATE_LIMITED"},
            "can_edit": True,
            "next": "",
        },

        # เก็บของดิบไว้ให้หลังบ้านตรวจ
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

    if "invalid" in raw_text or "ลิงก์ไม่ถูก" in raw_text:
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
        "received_time": payload.get("received_time", ""),
        "channel": payload.get("channel", ""),
        "message": payload.get("message", ""),
        "link": raw_link,
    }
