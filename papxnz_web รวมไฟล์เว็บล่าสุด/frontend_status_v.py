from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "")


def _amount(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("1", "true", "yes", "ok", "success", "passed", "joined", "issued")


def _clean_template_values(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[str(key)] = value
    return clean


def _template_sources(section: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    ui = payload.get("frontend_ui") if isinstance(payload.get("frontend_ui"), dict) else {}
    template = payload.get("template") if isinstance(payload.get("template"), dict) else {}
    display = payload.get("display") if isinstance(payload.get("display"), dict) else {}
    sources: list[dict[str, Any]] = []
    for source in (ui, template, display):
        common = source.get("common") if isinstance(source.get("common"), dict) else {}
        by_section = source.get(section) if isinstance(source.get(section), dict) else {}
        sources.extend([common, by_section])
    return sources


def _format_baht(value: Any) -> str:
    amount = _amount(value)
    return f"฿{amount:,.2f}"


# Account page UI fields consumed by payment_confirm_v.history().
# page_title: breadcrumb/current page title at the top bar.
# home_parent_label: breadcrumb parent label before the separator.
# menu_label: text next to the hamburger menu icon.
# side_menu_title: large title inside the slide-out menu.
# side_menu_subtitle: small subtitle inside the slide-out menu.
# side_topup_label: slide-out menu label for the top-up link.
# side_group_label: slide-out menu label for the VIP group link.
# side_admin_label: slide-out menu label for the admin contact link.
# side_help_label: slide-out menu label for the help/how-to link.
# side_note: small hint at the bottom of the slide-out menu.
# account_prefix: fixed label before the account username.
# username: display username shown in the profile header.
# tier: small membership tier pill under the username.
# logout_label: logout/back-to-home button text.
# join_label: left label for the account join date row.
# join_date: date shown in the join date row.
# status_label: left label for the account status row.
# status: account status value, for example normal, banned, waiting.
# package_label: chip label for the current package name.
# package: chip value for the current package name.
# role_label: chip label for user role.
# role: chip value for user role.
# member_id_label: chip label for member identifier.
# member_id: chip value for member identifier.
# expire_label: chip label for package expiration.
# expire: chip value for package expiration.
# payment_label: chip label for payment state.
# payment: chip value for payment state.
# access_label: chip label for access/unlock state.
# access: chip value for access/unlock state.
# balance_label: label before balance amount.
# balance: formatted balance text, normally "฿0.00".
# topup_label: top-up button text in the wallet row.
# purchase_history_title: title above package purchase history.
# purchase_history_empty: empty text when no package purchase history exists.
# ledger_history_title: title above all transaction history.
# ledger_empty: empty text when no transaction history exists.
# ledger_attempt_header: table header and mobile data-label for attempt/ref.
# ledger_time_header: table header and mobile data-label for time.
# ledger_package_header: table header and mobile data-label for package.
# ledger_amount_header: table header and mobile data-label for amount.
# ledger_status_header: table header and mobile data-label for status.
# shortcuts_title: title above shortcut buttons.
# shortcut_home: shortcut label for home.
# shortcut_packages: shortcut label for package list.
# shortcut_group: shortcut label for VIP group.
# shortcut_admin: shortcut label for admin.
# shortcuts_aria_label: accessibility label for shortcut navigation.
# copyright: footer copyright text.
ACCOUNT_TEMPLATE_DEFAULTS: dict[str, Any] = {
    "page_title": "จัดการบัญชี",
    "home_parent_label": "หน้าหลัก",
    "menu_label": "เมนู",
    "side_menu_title": "PAPXNZ BOT",
    "side_menu_subtitle": "Premium VIP Menu",
    "side_topup_label": "เติมเงิน VIP",
    "side_group_label": "กลุ่ม VIP",
    "side_admin_label": "ติดต่อแอดมิน",
    "side_help_label": "วิธีใช้งาน",
    "side_note": "แตะพื้นที่มืดด้านซ้ายเพื่อปิดเมนู",
    "account_prefix": "ACCOUNT:",
    "username": "username",
    "tier": "Member",
    "logout_label": "ออกจากระบบ",
    "join_label": "Join:",
    "join_date": "03/06/2026",
    "status_label": "Status:",
    "status": "normal",
    "package_label": "Package",
    "package": "ยังไม่เป็นสมาชิก",
    "role_label": "Role",
    "role": "Member",
    "member_id_label": "Member ID",
    "member_id": "#PAP-0001",
    "expire_label": "Expire",
    "expire": "-",
    "payment_label": "Payment",
    "payment": "รอตรวจสอบ",
    "access_label": "Access",
    "access": "ยังไม่ปลดล็อก",
    "balance_label": "Balance:",
    "balance": "฿0.00",
    "topup_label": "เติมเงิน",
    "purchase_history_title": "ประวัติซื้อแพกเกจ",
    "purchase_history_empty": "ยังไม่มีประวัติซื้อแพกเกจ",
    "ledger_history_title": "ประวัติทำรายการทั้งหมด",
    "ledger_empty": "ยังไม่มีประวัติทำรายการ",
    "ledger_attempt_header": "Attempt",
    "ledger_time_header": "Time",
    "ledger_package_header": "Package",
    "ledger_amount_header": "Amount",
    "ledger_status_header": "Status",
    "shortcuts_title": "ทางลัด",
    "shortcut_home": "หน้าหลัก",
    "shortcut_packages": "แพ็กเกจ",
    "shortcut_group": "กลุ่มหลัก",
    "shortcut_admin": "แอดมิน",
    "shortcuts_aria_label": "ทางลัดบัญชี",
    "copyright": "© 2026 papxnzvip.com All rights reserved.",
}


SECTION_TEMPLATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "account": ACCOUNT_TEMPLATE_DEFAULTS,
}


def frontend_template_context(section: str, payload: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return UI text/data for payment_confirm_v while keeping template fallback safe."""
    data = payload if isinstance(payload, dict) else {}
    context = _clean_template_values(defaults or {})
    context.update(_clean_template_values(SECTION_TEMPLATE_DEFAULTS.get(section, {})))

    for source in _template_sources(section, data):
        context.update(_clean_template_values(source))

    if section == "home":
        selected_amount = data.get("selected_amount")
        selected_package_name = data.get("selected_package_name") or data.get("package_name")
        if selected_amount not in (None, "") and not context.get("selected_amount_text"):
            context["selected_amount_text"] = _format_baht(selected_amount)
        if selected_package_name and not context.get("selected_package_name"):
            context["selected_package_name"] = selected_package_name

    if section == "result":
        for source_key, target_key in {
            "title": "pending_title",
            "message": "pending_message",
            "status": "default_status",
        }.items():
            value = data.get(source_key)
            if value not in (None, ""):
                context[target_key] = value

    if section == "account":
        for source_key, target_key in {
            "username": "username",
            "tier": "tier",
            "role": "role",
            "member_id": "member_id",
            "package_name": "package",
            "package": "package",
            "expire": "expire",
            "payment_status": "payment",
            "access_status": "access",
            "status": "status",
            "join_date": "join_date",
        }.items():
            value = data.get(source_key)
            if value not in (None, ""):
                context[target_key] = value
        if data.get("balance") not in (None, ""):
            context["balance"] = _format_baht(data.get("balance"))

    return context


def home_template_context(payload: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    return frontend_template_context("home", payload, defaults)


def result_template_context(payload: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    return frontend_template_context("result", payload, defaults)


def account_template_context(payload: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    return frontend_template_context("account", payload, defaults)


def source_flow_status(row: dict[str, Any]) -> dict[str, Any]:
    """Translate central state into the small contract a source site can consume."""
    status = _text(row, "status").lower()
    purchase_status = _text(row, "purchase_status").lower() or _text(row, "purchase_state").lower()
    balance_state = _text(row, "balance_state").lower()
    balance_status = _text(row, "balance_status").lower()
    link_status = _text(row, "link_status").lower()
    send_link_state = _text(row, "send_link_state").lower()
    reason = _text(row, "reason") or _text(row, "message") or _text(row, "detail")
    mode = _text(row, "mode")
    package_id = _text(row, "package_id")
    group_id = _text(row, "group_id") or _text(row, "route_group_id")
    request_id = _text(row, "request_id") or _text(row, "purchase_request_id")
    payment_ref = _text(row, "payment_ref") or _text(row, "attempt_id")
    user_id = _text(row, "user_id") or _text(row, "buyer_user_id") or _text(row, "telegram_id") or _text(row, "chat_id")
    username = _text(row, "username") or _text(row, "login")
    owner_user_id = _text(row, "owner_user_id")
    joined_user_id = _text(row, "joined_user_id") or _text(row, "actor_user_id")
    actor_username = _text(row, "actor_username") or _text(row, "joined_username")
    group_status = _text(row, "group_status").lower() or _text(row, "join_status").lower()
    login_found = _bool(row.get("login_found"))
    event_found = _bool(row.get("event_found"))
    group_button_found = _bool(row.get("group_button_found"))
    group_member_found = _bool(row.get("group_member_found"))
    group_identity = row.get("group_identity") if isinstance(row.get("group_identity"), dict) else {}
    ip_context = row.get("ip_context") if isinstance(row.get("ip_context"), dict) else {}
    same_as_owner = _bool(group_identity.get("same_as_owner_user")) or bool(user_id and owner_user_id and user_id == owner_user_id)
    same_as_joined = _bool(group_identity.get("same_as_joined_user")) or bool(user_id and joined_user_id and user_id == joined_user_id)
    balance_before = _amount(row.get("balance_before"))
    balance_after = _amount(row.get("balance_after") if row.get("balance_after") not in (None, "") else row.get("balance"))
    expected_amount = _amount(row.get("expected_amount") if row.get("expected_amount") not in (None, "") else row.get("amount"))
    balance_passed = _bool(row.get("balance_passed")) or _bool(row.get("can_send_link")) or _bool(row.get("can_deduct"))
    api_ok = _bool(row.get("ok"))
    ready = _bool(row.get("ready"))

    login_state = "found" if login_found or user_id or username else "missing"
    event_state = "found" if event_found else "missing"
    identity_state = "unknown"
    if same_as_owner:
        identity_state = "same_owner"
    elif same_as_joined:
        identity_state = "same_joined_user"
    elif user_id and (owner_user_id or joined_user_id):
        identity_state = "mismatch"

    if group_member_found or group_status in ("joined", "member_joined", "success", "approved"):
        group_state = "joined"
    elif group_button_found:
        group_state = "clicked_waiting_member"
    elif group_status in ("left", "kicked", "banned", "failed", "error"):
        group_state = group_status
    else:
        group_state = "unknown"

    retryable = False
    source_status = "pending"
    source_action = "wait"
    balance_action = "keep_pending"
    purchase_action = "wait_balance"
    link_action = "not_checked"
    message = reason or "waiting for central state"

    if status in ("already_passed", "duplicate", "already_confirmed") or reason == "already_marked":
        source_status = "success"
        source_action = "stop_duplicate_check"
        balance_action = "stop_balance_polling"
        purchase_action = "already_processed"
        link_action = "already_processed"
        message = reason or "this round is already processed"
    elif link_status == "success" or send_link_state == "success":
        source_status = "success"
        source_action = "mark_purchase_done"
        balance_action = "stop_balance_polling"
        purchase_action = "purchase_done"
        link_action = "link_success"
        message = reason or "link issued"
    elif balance_passed or ready or balance_state == "balance_confirmed" or purchase_status == "success":
        source_status = "success"
        source_action = "update_balance_then_send_link"
        balance_action = "update_balance"
        purchase_action = "may_send_link"
        link_action = "pending_link_result"
        message = reason or "balance is enough for package"
    elif balance_state in ("balance_zero", "balance_waiting") or reason == "insufficient_balance":
        source_status = "pending"
        source_action = "keep_waiting_balance"
        balance_action = "keep_polling_balance"
        purchase_action = "wait_balance"
        retryable = True
        message = reason or "balance is not enough yet"
    elif status in ("api_error", "system_error") or balance_state == "api_error":
        source_status = "pending"
        source_action = "retry_source_api"
        balance_action = "retry_balance_check"
        purchase_action = "wait_api"
        retryable = True
        message = reason or "source API is not ready"
    elif balance_state in ("route_missing", "balance_confirmed_no_user") or reason in ("group_config_missing", "login_required"):
        source_status = "failed"
        source_action = "show_admin_error"
        balance_action = "hold_for_admin"
        purchase_action = "blocked"
        message = reason or "central setup is missing"
    elif link_status == "error":
        source_status = "failed"
        source_action = "show_link_error"
        balance_action = "do_not_change_balance"
        purchase_action = "link_failed"
        link_action = "link_error"
        message = reason or "link create failed"
    elif not api_ok and status == "error":
        source_status = "pending"
        source_action = "retry_source_api"
        balance_action = "retry_balance_check"
        purchase_action = "wait_api"
        retryable = True
        message = reason or "central is waiting for a usable source response"

    return {
        "source_status": source_status,
        "source_action": source_action,
        "central_status": status,
        "login_state": login_state,
        "event_state": event_state,
        "identity_state": identity_state,
        "group_state": group_state,
        "balance_state": balance_state,
        "balance_status": balance_status,
        "purchase_state": purchase_status,
        "link_state": link_status or send_link_state or "not_checked",
        "duplicate_state": "duplicate" if source_action == "stop_duplicate_check" else "none",
        "retry_state": "retryable" if retryable else "final_or_waiting",
        "balance_action": balance_action,
        "purchase_action": purchase_action,
        "link_action": link_action,
        "reason": reason or message,
        "message": message,
        "retryable": retryable,
        "should_update_balance": balance_action == "update_balance",
        "should_stop_balance_check": balance_action in ("stop_balance_polling", "hold_for_admin"),
        "should_send_link": purchase_action == "may_send_link",
        "should_mark_purchase_done": source_action == "mark_purchase_done",
        "same_as_owner": same_as_owner,
        "same_as_joined_user": same_as_joined,
        "request_id": request_id,
        "payment_ref": payment_ref,
        "user_id": user_id,
        "username": username,
        "owner_user_id": owner_user_id,
        "joined_user_id": joined_user_id,
        "actor_username": actor_username,
        "package_id": package_id,
        "group_id": group_id,
        "expected_amount": expected_amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "ip_context": ip_context,
        "mode": mode,
    }


def summarize_central_answer(answer: dict[str, Any]) -> dict[str, Any]:
    central = answer if isinstance(answer, dict) else {}
    contract = central.get("source_contract") if isinstance(central.get("source_contract"), dict) else {}
    if not contract:
        contract = source_flow_status(central)
    central_ok = _bool(central.get("central_ok", central.get("ok")))
    need_admin = _bool(central.get("need_admin"))
    need_fields = central.get("need_fields") if isinstance(central.get("need_fields"), list) else []
    central_problem = _bool(central.get("central_problem"))
    status = _text(central, "status").lower() or contract.get("source_status") or "pending"
    if central_problem or need_admin:
        status = "need_admin_confirm" if need_admin else "central_problem"
    elif need_fields:
        status = "need_more_data"
    elif contract.get("should_send_link"):
        status = "ready_to_create_link"
    return {
        **contract,
        "central_ok": central_ok,
        "central_problem": central_problem,
        "source_answer_valid": _bool(central.get("source_answer_valid", central_ok and not need_fields and not need_admin)),
        "need_admin": need_admin,
        "need_fields": need_fields,
        "verify_status": status,
        "verify_reason": _text(central, "reason") or contract.get("reason") or "waiting for central answer",
        "central_raw": central,
    }


def ask_central_status(payload: dict[str, Any], central_base_url: str = "http://127.0.0.1:8025", timeout: float = 6.0) -> dict[str, Any]:
    body = json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False).encode("utf-8")
    url = central_base_url.rstrip("/") + "/decision-api/source/verify"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        data = {
            "ok": False,
            "central_ok": False,
            "central_problem": True,
            "source_answer_valid": False,
            "status": "central_unreachable",
            "reason": f"central verify request failed: {exc}",
            "need_admin": False,
            "need_fields": [],
        }
    return summarize_central_answer(data)


def payment_display_status(row: dict[str, Any], central_answer: dict[str, Any] | None = None) -> dict[str, Any]:
    flow = payment_flow_status(row)
    central = central_answer if isinstance(central_answer, dict) else {}
    if not central:
        return flow

    status = str(central.get("verify_status") or central.get("status") or "").lower()
    reason = str(central.get("verify_reason") or central.get("reason") or central.get("message") or "").strip()
    if reason.lower() in ("record needs review or failed", "needs review or failed"):
        reason = "ระบบกลางรับรายการไว้แล้ว กำลังรอตรวจสอบสถานะจริง"
    source_action = str(central.get("source_action") or "").lower()
    need_fields = central.get("need_fields") if isinstance(central.get("need_fields"), list) else []
    merged = {
        **flow,
        "central": central,
        "central_status": status,
        "central_action": source_action,
        "need_fields": need_fields,
    }

    if status in ("need_admin_confirm", "central_problem") or source_action == "show_admin_error":
        merged.update({
            "balance": flow.get("balance", "checking"),
            "status": "รอแอดมินตรวจสอบ",
            "latest_status": "ระบบกลางต้องตรวจสอบ",
            "title": "รอแอดมินตรวจสอบ",
            "message": reason or "ระบบกลางพบข้อมูลตั้งค่าหรือคำตอบที่ต้องให้แอดมินตรวจสอบ",
            "kind": "system_error",
        })
    elif status == "need_more_data":
        missing = ", ".join(str(item) for item in need_fields) if need_fields else "ข้อมูลจากต้นทาง"
        merged.update({
            "balance": "checking",
            "status": "กำลังตรวจสอบ",
            "latest_status": "รอข้อมูลจากต้นทาง",
            "title": "รอข้อมูลจากต้นทาง",
            "message": reason or f"ระบบกลางยังต้องการ {missing}",
            "kind": "checking",
        })
    elif status == "ready_to_create_link" or source_action == "update_balance_then_send_link":
        merged.update({
            "status": "สำเร็จ",
            "latest_status": "พร้อมสร้างลิงก์",
            "title": "ชำระเงินสำเร็จ",
            "message": reason or "ระบบกลางตรวจสอบแล้วว่ายอดพร้อมสำหรับแพ็กเกจนี้",
            "kind": "success",
        })
    elif status == "central_unreachable":
        merged.update({
            "balance": "checking",
            "status": "ระบบกลางติดต่อไม่ได้",
            "latest_status": "ระบบกลางติดต่อไม่ได้",
            "title": "ระบบกลางติดต่อไม่ได้",
            "message": reason or "ยังติดต่อระบบกลางไม่ได้ กรุณาลองใหม่อีกครั้ง",
            "kind": "system_error",
        })
    return merged


def payment_flow_status(row: dict[str, Any]) -> dict[str, Any]:
    status = _text(row, "status").lower()
    link_status = _text(row, "link_status").lower()
    join_status = _text(row, "join_status").lower()
    package_id = _text(row, "package_id")
    detail_text = _text(row, "detail")
    paid_amount = _amount(row.get("paid_amount") if row.get("paid_amount") not in (None, "") else row.get("amount"))
    expected_amount = _amount(row.get("expected_amount"))

    if status in ("checking", "pending"):
        return {
            "balance": "checking",
            "status": "กำลังตรวจสอบ",
            "latest_status": "กำลังตรวจสอบซอง",
            "title": "กำลังตรวจสอบรายการ",
            "message": "ระบบกำลังตรวจสอบซองของขวัญ อย่าเพิ่งปิดหน้านี้",
            "kind": "checking",
            "package_id": package_id,
        }

    if status in ("duplicate", "already_confirmed"):
        return {
            "balance": paid_amount,
            "status": "ซองซ้ำ",
            "latest_status": "ซองนี้เคยตรวจหรืออนุมัติไปแล้ว",
            "title": "ซองนี้เคยตรวจหรืออนุมัติไปแล้ว",
            "message": "เช็คประวัติทำรายการ หรือส่งซองใหม่อีกครั้ง",
            "kind": "duplicate",
            "package_id": package_id,
        }

    if status == "api_error" or link_status == "api_error":
        return {
            "balance": "checking",
            "status": "ดำเนินการไม่สำเร็จเนื่องจากระบบขัดข้อง",
            "latest_status": "ดำเนินการไม่สำเร็จเนื่องจากระบบขัดข้อง",
            "title": "ดำเนินการไม่สำเร็จเนื่องจากระบบขัดข้อง",
            "message": "ระบบตรวจซองหรือ API ชำระเงินขัดข้อง กรุณาลองใหม่ภายหลัง หรือติดต่อแอดมินให้ช่วยตรวจสอบ",
            "kind": "system_error",
            "package_id": package_id,
        }

    if status in ("voucher_used", "used_voucher") or link_status == "voucher_used":
        return {
            "balance": paid_amount,
            "status": "ซองถูกใช้แล้ว",
            "latest_status": "จ่ายไม่สำเร็จ",
            "title": "จ่ายไม่สำเร็จ",
            "message": "ซองนี้ถูกใช้ไปแล้วนะคะ",
            "kind": "used_voucher",
            "package_id": package_id,
        }

    if status in ("invalid", "failed", "amount_mismatch", "insufficient") or link_status in ("failed", "paid_mismatch", "insufficient"):
        if status in ("amount_mismatch", "insufficient") or link_status in ("paid_mismatch", "insufficient"):
            if paid_amount and expected_amount and paid_amount < expected_amount:
                detail = "ลองเลือกรายการอื่น หรือเติมเงินให้ครบสำหรับแพ็กเกจ"
                title = "ยอดคงเหลือไม่เพียงพอต่อค่าบริการนี้ค่ะ"
                kind = "insufficient"
            else:
                detail = f"ยอดที่จ่าย {paid_amount:g} บาท ไม่ตรงกับแพ็กเกจ {expected_amount:g} บาท"
                title = "จ่ายไม่สำเร็จ"
                kind = "failed"
        elif "used" in detail_text.lower() or "redeemed" in detail_text.lower() or "ถูกใช้" in detail_text:
            detail = "ซองนี้ถูกใช้ไปแล้วนะคะ"
            title = "จ่ายไม่สำเร็จ"
            kind = "used_voucher"
        else:
            detail = "ตรวจไม่พบหมายเลขซองนี้ค่ะ"
            title = "จ่ายไม่สำเร็จ"
            kind = "failed"
        return {
            "balance": paid_amount,
            "status": "ไม่พบรายการ",
            "latest_status": "จ่ายไม่สำเร็จ",
            "title": title,
            "message": detail,
            "kind": kind,
            "package_id": package_id,
        }

    if status == "success":
        return {
            "balance": max(paid_amount, expected_amount),
            "status": "สำเร็จ",
            "latest_status": "ชำระเงินสำเร็จ",
            "title": "ชำระเงินสำเร็จ",
            "message": "ระบบตรวจพบการชำระเงินเรียบร้อยแล้ว",
            "kind": "success",
            "package_id": package_id,
        }

    return {
        "balance": 0,
        "status": "ไม่พบรายการ",
        "latest_status": "",
        "title": "ไม่พบรายการ",
        "message": "ยังไม่พบสถานะรายการนี้ในระบบ",
        "kind": "missing",
        "package_id": package_id,
    }
