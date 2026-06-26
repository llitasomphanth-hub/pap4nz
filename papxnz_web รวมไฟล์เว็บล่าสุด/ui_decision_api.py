from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/ui-api", tags=["ui-api"])


@router.get("/health")
def ui_decision_health() -> dict[str, Any]:
    return {
        "ok": True,
        "code": "UI_DECISION_READY",
        "message": "ui decision api พร้อมตอบแล้ว",
    }


@router.post("/payment-result")
async def payment_result(request: Request):
    payload = await request.json()
    result = build_ui_payment_result(payload)
    return JSONResponse(status_code=result["http_status"], content=result)


def build_ui_payment_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}

    status = str(data.get("status") or data.get("code") or data.get("payment_status") or "").strip().lower()
    amount = _money(data.get("amount") or data.get("paid_amount") or data.get("received_amount") or 0)

    if status in {"success", "paid", "accepted", "complete", "completed", "ok"}:
        return _make_result(
            ok=True,
            code="SUCCESS",
            http_status=200,
            message="ชำระเงินสำเร็จ",
            payment_status="success",
            amount=amount,
            raw=data,
        )

    if status in {"used", "voucher_used", "already_used"}:
        return _make_result(
            ok=False,
            code="USED",
            http_status=409,
            message="ซองถูกใช้แล้ว",
            payment_status="failed",
            amount=0,
            raw=data,
        )

    if status in {"not_found", "notfound", "missing"}:
        return _make_result(
            ok=False,
            code="NOT_FOUND",
            http_status=404,
            message="ไม่พบซองในระบบ",
            payment_status="failed",
            amount=0,
            raw=data,
        )

    if status in {"invalid", "invalid_link", "bad_link"}:
        return _make_result(
            ok=False,
            code="INVALID_LINK",
            http_status=400,
            message="ลิงก์ไม่ถูก",
            payment_status="failed",
            amount=0,
            raw=data,
        )

    if status in {"server_error", "api_error", "error_500"}:
        return _make_result(
            ok=False,
            code="SERVER_ERROR",
            http_status=500,
            message="ระบบปลายทางผิดพลาด",
            payment_status="error",
            amount=0,
            raw=data,
            can_retry=True,
        )

    if status in {"forbidden", "error_403"}:
        return _make_result(
            ok=False,
            code="FORBIDDEN",
            http_status=403,
            message="ไม่มีสิทธิ์เข้าถึง",
            payment_status="error",
            amount=0,
            raw=data,
        )

    if status in {"rate_limited", "rate_limit", "error_429"}:
        return _make_result(
            ok=False,
            code="RATE_LIMITED",
            http_status=429,
            message="ยิงถี่เกินไป",
            payment_status="error",
            amount=0,
            raw=data,
            can_retry=True,
        )

    if status in {"unauthorized", "error_401"}:
        return _make_result(
            ok=False,
            code="UNAUTHORIZED",
            http_status=401,
            message="ยืนยันตัวตนไม่ผ่าน",
            payment_status="error",
            amount=0,
            raw=data,
        )

    return _make_result(
        ok=True,
        code="RECEIVED",
        http_status=200,
        message="ตัวกลางรับข้อมูลแล้ว",
        payment_status="received",
        amount=0,
        raw=data,
    )


def _make_result(
    *,
    ok: bool,
    code: str,
    http_status: int,
    message: str,
    payment_status: str,
    amount: float,
    raw: dict[str, Any],
    can_retry: bool = False,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "http_status": http_status,
        "code": code,
        "message": message,
        "ui": {
            "should_update_balance": ok and payment_status == "success",
            "should_update_status": True,
            "payment_status": payment_status,
            "amount": amount if ok else 0,
        },
        "action": {
            "can_retry": can_retry,
            "can_replay": can_retry,
            "next": "",
        },
        "raw": raw,
    }


def _money(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0.0
