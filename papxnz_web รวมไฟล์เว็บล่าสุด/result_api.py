from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

SAFE_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
ResultSourceProvider = Callable[[str], dict[str, Any]]
ResultFeedProvider = Callable[[str, int], dict[str, Any]]
_result_source_provider: ResultSourceProvider | None = None
_result_feed_provider: ResultFeedProvider | None = None

router = APIRouter(prefix="/result-api", tags=["result-api"])


def _json(data: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)


def _clean_ref(value: str | None) -> str:
    ref = (value or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="missing session_id or payment_ref")
    if not SAFE_REF_RE.match(ref):
        raise HTTPException(status_code=400, detail="invalid payment_ref")
    return ref


def _waiting_response(payment_ref: str, message: str = "payment is not approved yet") -> dict[str, Any]:
    return {
        "ok": True,
        "ready": False,
        "status": "pending",
        "message": message,
        "payment_ref": payment_ref,
    }


def register_result_source_provider(provider: ResultSourceProvider | None) -> None:
    # webapp.py registers its central raw-data reader here. result_api.py stays the
    # frontend-facing result emitter and never reads the database by itself.
    global _result_source_provider
    _result_source_provider = provider


def register_result_feed_provider(provider: ResultFeedProvider | None) -> None:
    # Optional raw-feed provider from webapp.py for page widgets such as recent payments.
    global _result_feed_provider
    _result_feed_provider = provider


def _read_webapp_source(ref: str) -> dict[str, Any] | None:
    if _result_source_provider is None:
        return None
    try:
        data = _result_source_provider(ref)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_webapp_feed(feed_name: str, limit: int) -> dict[str, Any] | None:
    if _result_feed_provider is None:
        return None
    try:
        data = _result_feed_provider(feed_name, limit)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _status_view(raw: dict[str, Any]) -> dict[str, str]:
    status = str(raw.get("source_status") or raw.get("status") or "pending").lower()
    link_status = str(raw.get("link_status") or "").lower()
    join_status = str(raw.get("join_status") or "").lower()
    if join_status == "joined":
        return {"text": "joined", "kind": "good"}
    if link_status == "used":
        return {"text": "link used", "kind": "used"}
    if status in ("success", "approved"):
        return {"text": "approved", "kind": "good"}
    if status in ("api_error", "amount_mismatch", "duplicate", "failed", "insufficient", "invalid", "rejected", "used_voucher", "voucher_used"):
        return {"text": "pending review", "kind": "wait"}
    return {"text": "pending", "kind": "wait"}


def _feed_item(raw: dict[str, Any]) -> dict[str, Any]:
    ref = str(raw.get("payment_ref") or raw.get("id") or "")
    amount = raw.get("amount")
    if amount in (None, ""):
        amount = raw.get("expected_amount") or raw.get("paid_amount") or ""
    status_view = _status_view(raw)
    return {
        "payment_ref": ref,
        "time": raw.get("created_at") or raw.get("first_seen_at") or raw.get("time") or "",
        "amount": amount,
        "package_id": str(raw.get("package_id") or ""),
        "status": status_view["text"],
        "status_kind": status_view["kind"],
        "source": str(raw.get("source") or ""),
    }


def get_result_feed(feed_name: str = "recent_payments", limit: int = 12) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 12), 80))
    source = _read_webapp_feed(feed_name, safe_limit)
    if not source:
        return {
            "ok": True,
            "feed": feed_name,
            "items": [],
            "source": "webapp_feed_not_registered",
        }
    raw_items = source.get("items") if isinstance(source.get("items"), list) else []
    return {
        "ok": True,
        "feed": feed_name,
        "items": [_feed_item(item) for item in raw_items if isinstance(item, dict)],
        "source": "webapp",
    }


def _approved_from_payment(payment: dict[str, Any], ref: str) -> dict[str, Any]:
    result_url = str(payment.get("result_url") or f"/result/{ref}")
    payload: dict[str, Any] = {
        "payment_ref": ref,
        "result_url": result_url,
    }
    if payment.get("package_id"):
        payload["package_id"] = str(payment.get("package_id") or "")
    if payment.get("review_id"):
        payload["review_id"] = payment.get("review_id")
    if payment.get("voucher_ref"):
        payload["voucher_ref"] = str(payment.get("voucher_ref") or "")
    if payment.get("invite_link"):
        payload["invite_link"] = str(payment.get("invite_link") or "")
    return {
        "ok": True,
        "ready": True,
        "status": "approved",
        "message": "payment approved",
        "payment_ref": ref,
        "result_url": result_url,
        "payload": payload,
    }


def _attach_webapp_context(result: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    matcher = source.get("matcher") if isinstance(source.get("matcher"), dict) else {}
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    if matcher.get("matched"):
        result["matcher"] = {
            "matched": True,
            "event": matcher.get("event"),
            "config": {
                "user_check_event_type": str(config.get("user_check_event_type") or ""),
                "web_source": str(config.get("web_source") or ""),
            },
        }
        if isinstance(result.get("payload"), dict):
            result["payload"]["matched_event"] = matcher.get("event")
    result["source"] = "webapp"
    return result


def _result_from_webapp_source(ref: str, source: dict[str, Any]) -> dict[str, Any]:
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    pending_message = str(config.get("pending_message") or "payment is not approved yet")
    payment = source.get("payment") if isinstance(source.get("payment"), dict) else None
    if not payment:
        return _attach_webapp_context(_waiting_response(ref, pending_message), source)

    if bool(payment.get("approved")):
        return _attach_webapp_context(_approved_from_payment(payment, ref), source)

    status = str(payment.get("source_status") or "pending").lower()
    waiting = _waiting_response(ref, pending_message)
    if status:
        waiting["source_status"] = status
    if bool(payment.get("failed")):
        waiting["status"] = "pending"
        waiting["message"] = pending_message
    return _attach_webapp_context(waiting, source)


def get_verified_result(payment_ref: str) -> dict[str, Any]:
    ref = _clean_ref(payment_ref)
    source = _read_webapp_source(ref)
    if not source:
        result = _waiting_response(ref, "webapp result source is not registered")
        result["source"] = "webapp_source_not_registered"
        return result
    return _result_from_webapp_source(ref, source)


def _pick_frontend_ref(session_id: str | None, payment_ref: str | None) -> str:
    # Only identity fields are accepted from the frontend. Client amount/status flags are ignored.
    return _clean_ref(payment_ref or session_id)


@router.get("")
def result_query(
    session_id: str | None = Query(default=None),
    payment_ref: str | None = Query(default=None),
):
    ref = _pick_frontend_ref(session_id, payment_ref)
    return _json(get_verified_result(ref))


@router.get("/{payment_ref}")
def result_by_ref(payment_ref: str):
    return _json(get_verified_result(payment_ref))


@router.get("/feed/{feed_name}")
def result_feed(feed_name: str, limit: int = Query(default=12, ge=1, le=80)):
    return _json(get_result_feed(feed_name, limit))


@router.post("")
async def result_request(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    ref = _pick_frontend_ref(body.get("session_id"), body.get("payment_ref"))
    return _json(get_verified_result(ref))


app = FastAPI(title="PAPXNZ Result API")
app.include_router(router)


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
