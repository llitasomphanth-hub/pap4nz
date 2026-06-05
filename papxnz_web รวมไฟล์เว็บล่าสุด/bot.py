from __future__ import annotations

import requests
from package_config import get_package_plan

API_KEY = "b2f844f9782b0e48b0d820c8605ab396"
PHONE_NUMBER = "0650430096"  # เปลี่ยนเป็นเบอร์พะแพน
_DEFAULT_PLAN = get_package_plan("p3")
VIP_MIN_AMOUNT = float(_DEFAULT_PLAN.amount if _DEFAULT_PLAN else 899)
VIP_LINK = ""

def format_money(value):
    try:
        if str(value).strip().lower() == "error":
            return "error"
        return f"฿ {float(value):,.2f}"
    except Exception:
        return "฿ 0.00"


async def _notify_admin_payment_result(context: ContextTypes.DEFAULT_TYPE, sender: str, sender_id: str, url: str, result: dict, reply_markup=None):
    try:
        amount = _wallet_amount(result)
        status = str(result.get("status", "")).lower()
        api_message = str(result.get("message", "") or "-")
        owner = result.get("owner_profile", "-")
        redeemer = result.get("redeemer_profile", "-")
        when = result.get("time", "-")
        debug_key = "yes" if (os.environ.get("API_KEY") or API_KEY) else "no"
        debug_phone = (os.environ.get("PHONE_NUMBER") or PHONE_NUMBER or "-")
        sent = await context.bot.send_message(
            chat_id=get_admin_notify_chat_id(),
            text=(
                "📩 ผลตรวจลิ้งล่าสุด\n\n"
                "🤖 ข้อมูลจากบอท\n"
                f"ผู้ส่ง: {sender}\n"
                f"User ID: {sender_id}\n"
                f"ลิงก์: {url}\n\n"
                "🌐 ข้อมูลจาก API\n"
                f"status: {status}\n"
                f"amount: {amount}\n"
                f"owner_profile: {owner}\n"
                f"redeemer_profile: {redeemer}\n"
                f"time: {when}\n"
                f"message: {api_message}\n\n"
                "🛠 debug\n"
                f"api_key_ready: {debug_key}\n"
                f"phone: {debug_phone}"
            ),
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        # เคส API ล่ม/รอแอดกด yes-no: เปิดเฉพาะฝั่งแอดมินให้ reply กลับลูกค้าได้
        # แต่ไม่ใส่ TICKET_OPEN เพื่อไม่ให้ข้อความลูกค้าถูกส่งเข้าหลังบ้านเอง
        if reply_markup is not None and status == "error":
            try:
                _ticket_note_admin_side(int(sender_id), sent.message_id)
            except Exception:
                pass
    except Exception:
        pass


API_KEY = "b2f844f9782b0e48b0d820c8605ab396"

def generate_key():
    url = "https://api.cybervilla.xyz/api/keys/generate"
    headers = {"X-Authorization": API_KEY}
    data = {"key_type": "online", "amount": 2, "duration": 1}
    res = requests.post(url, headers=headers, json=data)
    return res.json()

import time
import asyncio
import os
import re
import logging
import sqlite3
import json

from send_buttons_module import send_with_buttons
from send_buttons_module import build_send_handlers
from spam_keyword_filter import ban_message_if_needed
from datetime import datetime, timedelta, timezone
from telegram import InputMediaPhoto
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from random_game import (
    init_random_game_db,
    get_random_menu_label,
    handle_random_game_callback,
)

from urllib.parse import urlparse, parse_qs
from spam_keyword_filter import should_ban_text
from package_config import get_package_plan, load_package_plans

# -----------------------
# ตั้งค่า/ข้อความที่ปรับเองได้
# -----------------------
TOKEN = os.environ.get("BOT_TOKEN")  # ใส่ใน env เหมือนเดิม

ADMIN_ID = 8504953353
# กลุ่มปลายทาง (ไพรเวทได้) — ต้องให้บอทเป็นแอดมินและมีสิทธิ์เชิญคนเข้า (Invite Users)
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", (get_package_plan("p3").group_id if get_package_plan("p3") and get_package_plan("p3").group_id.lstrip("-").isdigit() else "-1003320213852")))
TICKET_FORWARD_GROUP_ID = int(os.environ.get("TICKET_FORWARD_GROUP_ID", "-1003779176416"))

# (ออปชัน) ถ้าสร้าง invite ไม่ได้ จะ fallback ไปใช้ลิ้งนี้แทน (เช่นลิ้งถาวรของกลุ่ม)
GROUP_LINK_FALLBACK = os.environ.get("GROUP_LINK", "").strip()

MENU_VERSION = "menu_v14"


# ===== Allow-list for invite joins =====
# เก็บ user_id ที่ "ได้รับลิ้ง" และมีสิทธิ์เข้ากลุ่ม (กันแชร์ลิ้ง)
ALLOWED_JOIN: dict[int, float] = {}  # user_id -> expires_at (unix time)
ALLOWED_JOIN_TTL_SEC = int(os.environ.get("ALLOWED_JOIN_TTL_SEC", "1800"))  # default 30 นาที

def _allow_user_join(user_id: int) -> None:
    """อนุญาต user_id นี้ให้เข้ากลุ่มได้ภายใน TTL"""
    try:
        ALLOWED_JOIN[int(user_id)] = time.time() + ALLOWED_JOIN_TTL_SEC
    except Exception:
        pass

def _is_user_allowed(user_id: int) -> bool:
    exp = ALLOWED_JOIN.get(int(user_id))
    if not exp:
        return False
    if exp < time.time():
        # หมดอายุ
        ALLOWED_JOIN.pop(int(user_id), None)
        return False
    return True

def _consume_user_allow(user_id: int) -> None:
    """ใช้สิทธิ์แล้ว เอาออกจาก allow-list"""
    ALLOWED_JOIN.pop(int(user_id), None)

def _purge_expired_allows() -> None:
    now = time.time()
    for uid, exp in list(ALLOWED_JOIN.items()):
        if exp < now:
            ALLOWED_JOIN.pop(uid, None)

# ===== Ticket / Support mode =====
# ลูกค้าต้องพิมพ์ /ticker ก่อน ถึงจะเริ่มส่งข้อความเข้าหาแอดมิน
LAST_START_MEDIA_IDS: dict[int, list[int]] = {}
TICKET_OPEN: set[int] = set()          # user_chat_id ที่เปิด ticket อยู่
ADMIN_SIDE_TICKET: set[int] = set()     # user_chat_id ที่เปิดเฉพาะฝั่งแอดมินจากเคส API ล่ม
TICKET_MAP: dict[int, int] = {}        # admin_msg_id -> user_chat_id (ไว้ให้แอด Reply แล้วส่งกลับ)

TICKET_CONFIRMED: set[int] = set()   # chat_id ที่เคยส่งสถานะ 'รอตรวจสอบ' แล้ว (ส่งแค่ครั้งแรกหลัง /ticker)

TICKET_ROOT_ADMIN_MSG: dict[int, int] = {}   # user_chat_id -> admin root msg_id
TICKET_USER_MSG_COUNT: dict[int, int] = {}   # user_chat_id -> จำนวนข้อความที่ลูกค้าส่งใน ticket นี้
TICKET_REPEAT_NOTICE_SENT: set[int] = set()  # chat_id ที่เคยเตือนครบ 3 ข้อความแล้ว
TICKET_MENU_WARN_SUPPRESSED: set[int] = set()  # chat_id ที่กด ❌ อยู่ต่อจาก start=menu แล้ว ไม่ต้องเด้งเตือนซ้ำ
TICKET_REPEAT_NOTICE_TEXT = (
    "เราได้รับข้อความของคุณแล้วนะ\n"
    "เดี๋ยวแอดมินจะเข้ามาตรวจสอบให้เร็วที่สุด"
)

# ===== Admin ban (ตอบครั้งเดียว แล้วเงียบ) =====
BANNED_NOTICE_SENT: set[int] = set()
BAN_REPLY_TEXT = "🚫 อุ๊ปส์! คุณถูกแบนแล้วนะ…โอ๋ๆ ^^"

BANNED_USERS: set[int] = set()

def add_banned_user(uid: int) -> None:
    try:
        BANNED_USERS.add(int(uid))
    except Exception:
        pass

def is_banned_user(uid: int) -> bool:
    try:
        return int(uid) in BANNED_USERS
    except Exception:
        return False

async def handle_banned_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return False

    if not is_banned_user(user.id):
        return False

    if user.id not in BANNED_NOTICE_SENT:
        try:
            await msg.reply_text(BAN_REPLY_TEXT)
        except Exception:
            pass
        BANNED_NOTICE_SENT.add(user.id)
    return True

ADMIN_TICKET_MSGS: dict[int, list[int]] = {}  # user_chat_id -> [admin message ids] (ไว้ลบฝั่งแอดมินตอนปิด)
# ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====
TICKET_ACK_TEXT = (
     "━━━━━━ TICKER ━━━━━━\n\n"
    "🕹️ เปิดโหมดคุยแชทกับแอดมินแล้ว\n"
    "สามารถส่งแจ้งปัญหาผ่านแชทนี้ได้เลย\n\n"
    "หากต้องการทำรายการอื่นกรุณากลับไปที่หน้าเมนู“ /menu “"
)

def _record_admin_msg(user_chat_id: int, admin_msg_id: int) -> None:
    try:
        ADMIN_TICKET_MSGS.setdefault(user_chat_id, []).append(int(admin_msg_id))
    except Exception:
        pass


def _ticket_note_open(user_chat_id: int, root_admin_msg_id: int) -> None:
    uid = int(user_chat_id)
    TICKET_ROOT_ADMIN_MSG[uid] = int(root_admin_msg_id)
    TICKET_USER_MSG_COUNT[uid] = 0
    TICKET_REPEAT_NOTICE_SENT.discard(uid)

def _ticket_note_admin_side(user_chat_id: int, admin_msg_id: int) -> None:
    """ผูกข้อความหลังบ้านให้แอดตอบกลับลูกค้าได้ โดยไม่เปิดโหมด ticket ฝั่งลูกค้า"""
    uid = int(user_chat_id)
    ADMIN_SIDE_TICKET.add(uid)
    TICKET_MAP[int(admin_msg_id)] = uid
    _record_admin_msg(uid, int(admin_msg_id))

def _ticket_note_message(user_chat_id: int) -> int:
    uid = int(user_chat_id)
    TICKET_USER_MSG_COUNT[uid] = TICKET_USER_MSG_COUNT.get(uid, 0) + 1
    return TICKET_USER_MSG_COUNT[uid]


async def _ticket_forward_to_group(context: ContextTypes.DEFAULT_TYPE, msg, open_notice: bool = False):
    """ฟอร์เวิร์ดข้อความลูกค้าในโหมด ticket เข้ากลุ่มหลังบ้าน โดยไม่พาลูกค้าเข้ากลุ่ม"""
    try:
        chat = getattr(msg, "chat", None)
        user = getattr(msg, "from_user", None)
        user_chat_id = int(chat.id) if chat else 0

        if open_notice:
            who = f"@{user.username}" if user and user.username else (user.full_name if user else "unknown")
            sent_open = await context.bot.send_message(
                chat_id=get_ticket_forward_chat_id(),
                text=(
                    "📩 มีลูกค้าเปิด Ticket\n"
                    f"ChatID: {user_chat_id}\n"
                    f"User: {who}"
                ),
            )
            try:
                TICKET_MAP[sent_open.message_id] = user_chat_id
                _record_admin_msg(user_chat_id, sent_open.message_id)
            except Exception:
                pass

        fwd = await context.bot.forward_message(
            chat_id=get_ticket_forward_chat_id(),
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        try:
            TICKET_MAP[fwd.message_id] = user_chat_id
            _record_admin_msg(user_chat_id, fwd.message_id)
        except Exception:
            pass
    except Exception:
        pass

def _ticket_note_close(user_chat_id: int) -> None:
    uid = int(user_chat_id)
    ADMIN_SIDE_TICKET.discard(uid)
    TICKET_ROOT_ADMIN_MSG.pop(uid, None)
    TICKET_USER_MSG_COUNT.pop(uid, None)
    TICKET_REPEAT_NOTICE_SENT.discard(uid)
    TICKET_OPEN_ACK_MSG.pop(uid, None)

async def _clear_admin_ticket_messages(context: ContextTypes.DEFAULT_TYPE, user_chat_id: int) -> None:
    msg_ids = ADMIN_TICKET_MSGS.pop(user_chat_id, [])
    if not msg_ids:
        return
    for mid in msg_ids:
        try:
            await context.bot.delete_message(chat_id=get_admin_notify_chat_id(), message_id=mid)
        except Exception:
            # ถ้าลบไม่ได้ก็ข้าม (กันหลุด)
            pass

# ปิด ticket อัตโนมัติถ้าไม่มีความเคลื่อนไหว 12 ชั่วโมง
TICKET_AUTO_CLOSE_SEC = 90
TICKET_LAST_ACTIVITY: dict[int, float] = {}   # chat_id -> last_activity_epoch
TICKET_CLOSE_JOBS: dict[int, object] = {}     # chat_id -> job (จาก job_queue)
TICKET_HAS_USER_MESSAGE: set[int] = set()  # chat_id ที่ลูกค้าพิมพ์/ส่งรูปแล้ว -> ไม่ auto close แล้ว
TICKET_OPEN_ACK_MSG: dict[int, int] = {}  # user_chat_id -> ข้อความเปิด ticket ฝั่งลูกค้า
WARNING_MSG: dict[int, int] = {}  # user_chat_id -> ข้อความเตือนก่อนปิด ticket

def _cancel_ticket_job(chat_id: int):
    job = TICKET_CLOSE_JOBS.pop(chat_id, None)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass

def touch_ticket(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """อัปเดตเวลา activity และตั้ง timer ปิดอัตโนมัติใหม่"""
    TICKET_LAST_ACTIVITY[chat_id] = time.time()
    _cancel_ticket_job(chat_id)
    # ตั้ง job ปิดอัตโนมัติใหม่
    try:
        job = context.application.job_queue.run_once(
            auto_close_ticket_job,
            when=TICKET_AUTO_CLOSE_SEC,
            data={"chat_id": chat_id},
            name=f"autoclose_{chat_id}",
        )
        TICKET_CLOSE_JOBS[chat_id] = job
    except Exception:
        # ถ้า job_queue ใช้ไม่ได้ ก็ยังให้ระบบ ticket ทำงานต่อได้
        pass


def disable_ticket_autoclose(chat_id: int):
    """เมื่อลูกค้าพิมพ์/ส่งรูปแล้ว ให้ปิด auto close และเปิดค้างจนกว่าแอดจะปิด"""
    TICKET_HAS_USER_MESSAGE.add(int(chat_id))
    _cancel_ticket_job(int(chat_id))
    TICKET_LAST_ACTIVITY.pop(int(chat_id), None)


# ===== Latest-only processing (ลิ้ง/QR เอาแค่อันล่าสุดของคนเดิม) =====
# ใช้เพื่อกันเคสลูกค้าส่งลิ้งแล้วส่ง QR ซ้ำ: ให้ยกเลิกงานเก่า และลบผลลัพธ์เก่าออก
USER_REQ_SEQ: dict[int, int] = {}           # chat_id -> seq
USER_PENDING_TASK: dict[int, asyncio.Task] = {}   # chat_id -> task
USER_PENDING_MSG_ID: dict[int, int] = {}    # chat_id -> bot "กำลังตรวจ" message_id (ลบได้)
USER_RESULT_MSG_IDS: dict[int, list[int]] = {}    # chat_id -> bot result message_ids (ลบได้)
LAST_GROUP_LINK_RESULT_MSG: dict[int, int] = {}   # chat_id -> last invite/group-link message_id (ค้างไว้ 1 อัน)

async def _delete_bot_msg_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

def _remember_result_msg(chat_id: int, message_id: int):
    try:
        USER_RESULT_MSG_IDS.setdefault(int(chat_id), []).append(int(message_id))
    except Exception:
        pass

def _remember_group_link_msg(chat_id: int, message_id: int):
    try:
        LAST_GROUP_LINK_RESULT_MSG[int(chat_id)] = int(message_id)
    except Exception:
        pass

async def _replace_group_link_msg(context: ContextTypes.DEFAULT_TYPE, chat_id: int, new_message_id: int):
    old_mid = LAST_GROUP_LINK_RESULT_MSG.get(int(chat_id))
    if old_mid and int(old_mid) != int(new_message_id):
        await _delete_bot_msg_safe(context, int(chat_id), int(old_mid))
    _remember_group_link_msg(int(chat_id), int(new_message_id))

async def _clear_non_link_result_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """ลบผลลัพธ์เก่าที่ไม่ใช่ลิ้งกลุ่มสำเร็จ"""
    chat_id = int(chat_id)

    old_pending = USER_PENDING_MSG_ID.pop(chat_id, None)
    if old_pending:
        await _delete_bot_msg_safe(context, chat_id, old_pending)

    olds = USER_RESULT_MSG_IDS.pop(chat_id, [])
    for mid in olds:
        await _delete_bot_msg_safe(context, chat_id, mid)

async def bump_latest_request(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int:
    """เพิ่ม seq ของ chat_id และยกเลิก/ลบสิ่งที่ค้างจากงานเก่า (ยกเว้นลิ้งกลุ่มสำเร็จ)"""
    chat_id = int(chat_id)
    USER_REQ_SEQ[chat_id] = USER_REQ_SEQ.get(chat_id, 0) + 1
    seq = USER_REQ_SEQ[chat_id]

    # cancel task เก่า
    t = USER_PENDING_TASK.pop(chat_id, None)
    if t and not t.done():
        try:
            t.cancel()
        except Exception:
            pass

    await _clear_non_link_result_messages(context, chat_id)

    return seq

def is_latest(chat_id: int, seq: int) -> bool:
    return USER_REQ_SEQ.get(int(chat_id), 0) == int(seq)

async def close_ticket_internal(context: ContextTypes.DEFAULT_TYPE, chat_id: int, reason: str = "manual"):
    """ปิด ticket + ล้าง map + แจ้งทั้งลูกค้า/แอดมิน"""
    if chat_id in TICKET_OPEN:
        TICKET_OPEN.discard(chat_id)
    _cancel_ticket_job(chat_id)
    TICKET_LAST_ACTIVITY.pop(chat_id, None)
    TICKET_HAS_USER_MESSAGE.discard(int(chat_id))
    TICKET_CONFIRMED.discard(int(chat_id))
    _ticket_note_close(int(chat_id))

    # ล้าง map ของ chat_id นี้ออก
    for k, v in list(TICKET_MAP.items()):
        if v == chat_id:
            del TICKET_MAP[k]

    # ลบข้อความ ticket ฝั่งแอดมินให้โล่ง (รวมข้อความที่แอด reply ด้วย ถ้าลบได้)
    try:
        await _clear_admin_ticket_messages(context, chat_id)
    except Exception:
        pass

    # แจ้งลูกค้า
    try:
        if reason == "auto":
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏱️ Ticket นี้ถูกปิดอัตโนมัติ"
                    "สามารถทำรายการต่อได้ตามปกติ"
                    "เมนูด้านล่างพร้อมใช้งานแล้ว"
                ),
                reply_markup=_menu_root_keyboard(chat_id, chat_id),
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "✅ ปิด Ticket ให้แล้วค่ะ\n"
                    "สามารถทำรายการต่อได้ตามปกติ"
                ),
                reply_markup=_menu_root_keyboard(chat_id, chat_id),
            )
    except Exception:
        pass
    # (ไม่ส่งแจ้งแอดมินซ้ำ เพื่อให้แชทแอดมินโล่ง)

async def auto_close_ticket_job(context: ContextTypes.DEFAULT_TYPE):
    data = getattr(context, "job", None).data if getattr(context, "job", None) else None
    if not data:
        return
    chat_id = int(data.get("chat_id"))
    # ถ้ายังเปิดอยู่ และลูกค้ายังไม่เคยพิมพ์/ส่งรูป ค่อยปิด
    if chat_id in TICKET_OPEN and chat_id not in TICKET_HAS_USER_MESSAGE:
        await close_ticket_internal(context, chat_id, reason="auto")


PENDING_LINKS: dict[str, float] = {}
PENDING_TTL_SEC = 2 * 24 * 60 * 60


# -----------------------
# Hint /ticker (กันสแปม)
# -----------------------
LAST_HINT: dict[int, float] = {}


# -----------------------
# โฟล “แชททั่วไป” (ตอบ 3 ข้อความ เฉพาะรอบแรก แล้วคูลดาวน์ 10 นาที)
# -----------------------

# -----------------------
# โฟลตอบกลับแชททั่วไป (กันสแปม/กันไหล)
# พฤติกรรมที่ต้องการ:
# - ลูกค้าพิมพ์อะไรก็ได้ -> ส่ง 3 ข้อความแบบหน่วงเวลา (5 วิ, 10 วิ)
# - ระหว่างโฟลกำลังรัน (ช่วง 5 วิ/10 วิ) ถ้าลูกค้าพิมพ์ซ้ำ -> "ไม่ตอบ" และยกเลิกโฟลที่ค้างทันที
# - หลังจบโฟล -> คูลดาวน์ 10 นาที (ช่วงนี้พิมพ์อะไรก็ไม่ตอบ)
# - พอคูลดาวน์หมด -> จะตอบก็ต่อเมื่อลูกค้าทักใหม่ (ไม่ส่งเองอัตโนมัติ)
# -----------------------
# -----------------------
# โฟลตอบกลับแชททั่วไป (คูลดาวน์ตอบแบบ “ต้องทักใหม่หลังครบเวลา”)
# พฤติกรรม:
# - ลูกค้าพิมพ์อะไรก็ได้ -> บอทตอบ “ข้อความที่ 1” แล้วเข้า cooldown 5 วิ
# - ระหว่าง 5 วิ ถ้าทักซ้ำ -> เงียบ
# - ครบ 5 วิ จะ “ยังไม่ส่งเอง” ต้องให้ลูกค้าทักใหม่ ถึงจะได้ “ข้อความที่ 2” แล้วเข้า cooldown 10 วิ
# - ระหว่าง 10 วิ ถ้าทักซ้ำ -> เงียบ
# - ครบ 10 วิ ต้องทักใหม่ ถึงจะได้ “ข้อความที่ 3” แล้วเข้า cooldown 10 นาที
# - ระหว่าง 10 นาที ถ้าทักซ้ำ -> เงียบ
# - ครบ 10 นาที ต้องทักใหม่ ถึงจะเริ่มรอบใหม่ได้
# -----------------------
NORMAL_FLOW_STEP: dict[int, int] = {}         # chat_id -> 0/1/2  (0=พร้อมส่งข้อ1, 1=รอส่งข้อ2, 2=รอส่งข้อ3)
NORMAL_FLOW_NEXT_AT: dict[int, float] = {}   # chat_id -> ts ที่เริ่มตอบได้ใน step ถัดไป
NORMAL_FLOW_COOLDOWN_UNTIL: dict[int, float] = {}  # chat_id -> ts (คูลดาวน์ 10 นาทีหลังจบ)

NORMAL_FLOW_COOLDOWN_SEC = 600  # 10 นาที

def _normal_flow_in_cooldown(chat_id: int) -> bool:
    return time.time() < float(NORMAL_FLOW_COOLDOWN_UNTIL.get(int(chat_id), 0.0))

def _normal_flow_reset(chat_id: int):
    chat_id = int(chat_id)
    NORMAL_FLOW_STEP.pop(chat_id, None)
    NORMAL_FLOW_NEXT_AT.pop(chat_id, None)

def _normal_flow_set_long_cooldown(chat_id: int, seconds: int = NORMAL_FLOW_COOLDOWN_SEC):
    NORMAL_FLOW_COOLDOWN_UNTIL[int(chat_id)] = time.time() + float(seconds)

async def handle_normal_flow_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ตอบแชททั่วไปแบบคูลดาวน์ตอบ (ต้องทักใหม่หลังครบเวลา)"""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg:
        return
    if chat.type != "private":
        return

    chat_id = int(chat.id)
    now = time.time()

    # ถ้าอยู่คูลดาวน์ 10 นาที -> เงียบ
    if _normal_flow_in_cooldown(chat_id):
        return

    step = int(NORMAL_FLOW_STEP.get(chat_id, 0))
    next_at = float(NORMAL_FLOW_NEXT_AT.get(chat_id, 0.0))

    # ถ้ายังไม่ครบเวลาของ step ถัดไป -> เงียบ
    if step in (1, 2) and now < next_at:
        return

    if step == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🤖 อุ้ย...บอทไม่สามารถตอบแชททั่วไปได้ค่ะ\nแจ้งปัญหาการใช้งานกด • /ticker",
        )
        NORMAL_FLOW_STEP[chat_id] = 1
        NORMAL_FLOW_NEXT_AT[chat_id] = now + 5.0
        return

    if step == 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text="หากต้องการสอบถามเพิ่มเติม ติดต่อ📲 @dok_thongg",
        )
        NORMAL_FLOW_STEP[chat_id] = 2
        NORMAL_FLOW_NEXT_AT[chat_id] = now + 10.0
        return

    # step == 2
    await context.bot.send_message(
        chat_id=chat_id,
        text="งดทักซ้ำค่ะ 🤐",
    )
    # จบโฟล -> รีเซ็ต step และเข้าคูลดาวน์ 10 นาที
    _normal_flow_reset(chat_id)
    _normal_flow_set_long_cooldown(chat_id, NORMAL_FLOW_COOLDOWN_SEC)
SHORT_CD = 10
LONG_CD = 10 * 6


DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")
ADMIN_NOTIFY_SETTING_KEY = "admin_notify_chat_id"
TICKET_ADMIN_SETTING_KEY = "ticket_forward_chat_id"

def init_admin_notify_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def get_admin_notify_chat_id() -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key=?", (ADMIN_NOTIFY_SETTING_KEY,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return int(ADMIN_ID)

def set_admin_notify_chat_id(chat_id: int) -> None:
    init_admin_notify_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (ADMIN_NOTIFY_SETTING_KEY, str(int(chat_id))),
    )
    conn.commit()
    conn.close()

def get_ticket_forward_chat_id() -> int:
    try:
        init_admin_notify_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key=?", (TICKET_ADMIN_SETTING_KEY,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return int(TICKET_FORWARD_GROUP_ID)


def set_ticket_forward_chat_id(chat_id: int) -> None:
    init_admin_notify_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (TICKET_ADMIN_SETTING_KEY, str(int(chat_id))),
    )
    conn.commit()
    conn.close()


async def setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    if not user or not chat or not msg:
        return
    if int(user.id) not in {int(ADMIN_ID), int(globals().get("RECOVERY_ADMIN_USER_ID", ADMIN_ID))}:
        await msg.reply_text("⛔ คำสั่งนี้สำหรับแอดมินเท่านั้น")
        return
    set_admin_notify_chat_id(int(chat.id))
    await msg.reply_text(
        "✅ ตั้งค่าหลังบ้านรับแจ้งเตือนเป็นแชทนี้แล้ว\n"
        f"chat_id: {chat.id}"
    )

async def adminstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    if int(user.id) not in {int(ADMIN_ID), int(globals().get("RECOVERY_ADMIN_USER_ID", ADMIN_ID))}:
        await msg.reply_text("⛔ คำสั่งนี้สำหรับแอดมินเท่านั้น")
        return
    await msg.reply_text(f"📌 หลังบ้านรับแจ้งเตือนตอนนี้: {get_admin_notify_chat_id()}")

async def ticketadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    if not user or not chat or not msg:
        return
    if int(user.id) not in {int(ADMIN_ID), int(globals().get("RECOVERY_ADMIN_USER_ID", ADMIN_ID))}:
        await msg.reply_text("⛔ คำสั่งนี้สำหรับแอดมินเท่านั้น")
        return
    set_ticket_forward_chat_id(int(chat.id))
    await msg.reply_text(
        "✅ ตั้งค่าที่รับข้อความ Ticket เป็นแชทนี้แล้ว\n"
        f"chat_id: {chat.id}"
    )

def init_used_v_db():
    init_unique_submitters_db()
    bootstrap_unique_submitters_from_existing_state()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS used_v (
            v TEXT PRIMARY KEY,
            first_seen_at INTEGER,
            amount REAL,
            raw_result TEXT,
            used_at TEXT,
            owner_user_id INTEGER
        )
    """)
    for stmt in [
        "ALTER TABLE used_v ADD COLUMN amount REAL",
        "ALTER TABLE used_v ADD COLUMN raw_result TEXT",
        "ALTER TABLE used_v ADD COLUMN used_at TEXT",
        "ALTER TABLE used_v ADD COLUMN owner_user_id INTEGER",
    ]:
        try:
            cur.execute(stmt)
        except Exception:
            pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_balance (
            user_id INTEGER PRIMARY KEY,
            total REAL NOT NULL DEFAULT 0
        )
    """)

    # ยอดหลังเข้า: แยกจาก user_balance เดิม เพื่อไม่ให้โฟลวก่อนเข้าแตก

    # จำลิงก์ทุกใบที่บอทส่งไว้ ลิงก์ไหนถูกใช้ค่อยหักยอดเจ้าของลิงก์
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_invites (
            invite_link TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            balance_bucket TEXT NOT NULL DEFAULT 'pre',
            used INTEGER NOT NULL DEFAULT 0,
            used_by_user_id INTEGER,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            used_at INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_member_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            event_type TEXT NOT NULL,
            group_id TEXT,
            invite_link TEXT,
            owner_user_id INTEGER,
            actor_user_id INTEGER,
            actor_username TEXT,
            actor_full_name TEXT,
            amount REAL,
            balance_before REAL,
            balance_after REAL,
            source TEXT,
            attempt_id TEXT,
            note TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_group_member_events_ts ON group_member_events(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_group_member_events_actor ON group_member_events(actor_user_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_payment_state (
            user_id INTEGER PRIMARY KEY,
            last_v TEXT,
            payment_sent INTEGER NOT NULL DEFAULT 0,
            joined INTEGER NOT NULL DEFAULT 0,
            invalidated INTEGER NOT NULL DEFAULT 0,
            active_invite TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)
    try:
        cur.execute("ALTER TABLE user_payment_state ADD COLUMN invalidated INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE user_payment_state ADD COLUMN active_invite TEXT")
    except Exception:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS latest_check_state (
            user_id INTEGER PRIMARY KEY,
            latest_kind TEXT,
            latest_text TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_error_payment_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender TEXT,
            url TEXT NOT NULL,
            v TEXT NOT NULL,
            amount REAL,
            raw_result TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            reviewed_at INTEGER
        )
    """)

    conn.commit()
    conn.close()


def init_unique_submitters_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS unique_payment_submitters (
            user_id INTEGER PRIMARY KEY,
            first_seen_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS unique_submitter_counter_meta (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def bootstrap_unique_submitters_from_existing_state():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM unique_submitter_counter_meta WHERE key='base_count'")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO unique_submitter_counter_meta (key,value) VALUES ('base_count',320)")

    cur.execute("SELECT COUNT(*) FROM unique_submitter_counter_meta WHERE key='seed_seen_count'")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT COUNT(*) FROM unique_payment_submitters")
        existing = cur.fetchone()[0]
        cur.execute("INSERT INTO unique_submitter_counter_meta (key,value) VALUES ('seed_seen_count',?)",(existing,))

    conn.commit()
    conn.close()


def register_unique_submitter(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO unique_payment_submitters (user_id, first_seen_at) VALUES (?, strftime('%s','now'))",(user_id,))
    conn.commit()

    cur.execute("SELECT value FROM unique_submitter_counter_meta WHERE key='base_count'")
    base = cur.fetchone()
    base = base[0] if base else 320

    cur.execute("SELECT value FROM unique_submitter_counter_meta WHERE key='seed_seen_count'")
    seed = cur.fetchone()
    seed = seed[0] if seed else 0

    cur.execute("SELECT COUNT(*) FROM unique_payment_submitters")
    total_seen = cur.fetchone()[0]

    added = max(0, total_seen - seed)
    total = base + added

    conn.close()
    return total, added

PENDING_INVITE_OWNER: dict[str, int] = {}


def get_user_payment_state(user_id: int) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT last_v, payment_sent, joined, invalidated, active_invite FROM user_payment_state WHERE user_id = ? LIMIT 1",
            (int(user_id),),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"last_v": None, "payment_sent": False, "joined": False, "invalidated": False, "active_invite": None}
        return {
            "last_v": row[0],
            "payment_sent": bool(row[1]),
            "joined": bool(row[2]),
            "invalidated": bool(row[3]),
            "active_invite": row[4],
        }
    except Exception:
        return {"last_v": None, "payment_sent": False, "joined": False, "invalidated": False, "active_invite": None}


def upsert_user_payment_state(user_id: int, *, last_v: str | None = None, payment_sent: bool | None = None, joined: bool | None = None, invalidated: bool | None = None, active_invite: str | None = None):
    try:
        current = get_user_payment_state(int(user_id))
        new_last_v = current.get("last_v")
        new_payment_sent = bool(current.get("payment_sent"))
        new_joined = bool(current.get("joined"))
        new_invalidated = bool(current.get("invalidated"))
        new_active_invite = current.get("active_invite")

        if last_v is not None:
            new_last_v = str(last_v)
        if payment_sent is not None:
            new_payment_sent = bool(payment_sent)
        if joined is not None:
            new_joined = bool(joined)
        if invalidated is not None:
            new_invalidated = bool(invalidated)
        if active_invite is not None:
            new_active_invite = str(active_invite) if active_invite else None

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_payment_state (user_id, last_v, payment_sent, joined, invalidated, active_invite, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(user_id) DO UPDATE SET
                last_v = excluded.last_v,
                payment_sent = excluded.payment_sent,
                joined = excluded.joined,
                invalidated = excluded.invalidated,
                active_invite = excluded.active_invite,
                updated_at = excluded.updated_at
            """,
            (int(user_id), new_last_v, int(new_payment_sent), int(new_joined), int(new_invalidated), new_active_invite),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def mark_link_invalid_for_user(user_id: int):
    try:
        USER_PAYMENT_SENT.discard(int(user_id))
        USER_JOINED.discard(int(user_id))
        state = get_user_payment_state(int(user_id))
        invite_link = state.get("active_invite")
        if invite_link:
            PENDING_INVITE_OWNER.pop(str(invite_link), None)
            # ลิงก์รอบนี้ถูกตัดสิทธิ์แล้ว ห้าม load กลับมาเป็น pending ตอนรีสตาร์ท
            try:
                mark_pending_invite_used(str(invite_link), None)
            except Exception:
                pass
        upsert_user_payment_state(
            int(user_id),
            payment_sent=False,
            joined=False,
            invalidated=True,
            active_invite="",
        )
    except Exception:
        pass



def load_persisted_payment_state():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT user_id, payment_sent, joined, invalidated, active_invite FROM user_payment_state")
        rows = cur.fetchall()
        conn.close()
        USER_PAYMENT_SENT.clear()
        USER_JOINED.clear()
        PENDING_INVITE_OWNER.clear()
        for uid, payment_sent, joined, invalidated, active_invite in rows:
            if int(payment_sent):
                USER_PAYMENT_SENT.add(int(uid))
            if int(joined):
                USER_JOINED.add(int(uid))
            if int(payment_sent) and not int(joined) and not int(invalidated) and active_invite:
                PENDING_INVITE_OWNER[str(active_invite)] = int(uid)
        # เพิ่มเฉพาะ memory ของลิงก์ทุกใบที่ยังไม่ถูกใช้จาก ledger
        load_pending_invites_to_memory()
    except Exception:
        pass


def init_chatlog_db():
    """Create table for chat history viewer."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            direction TEXT NOT NULL,  -- 'in' or 'out'
            msg_id INTEGER,
            msg_type TEXT,
            text TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_ts ON chat_messages(chat_id, ts)")
    conn.commit()
    conn.close()

def init_menu_state_db():
    """Create table for remembering which menu version each user has received."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_menu_state (
            user_id INTEGER PRIMARY KEY,
            last_menu_version TEXT,
            updated_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


def get_user_menu_version(user_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT last_menu_version FROM user_menu_state WHERE user_id = ?",
        (int(user_id),)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_user_menu_version(user_id: int, version: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_menu_state (user_id, last_menu_version, updated_at)
        VALUES (?, ?, strftime('%s','now'))
        ON CONFLICT(user_id) DO UPDATE SET
            last_menu_version = excluded.last_menu_version,
            updated_at = excluded.updated_at
    """, (int(user_id), version))
    conn.commit()
    conn.close()


def should_send_start_menu(user_id: int) -> bool:
    last_version = get_user_menu_version(user_id)
    return last_version != MENU_VERSION


def log_chat_message(
    direction: str,
    chat_id: int,
    *,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
    msg_id: int | None = None,
    msg_type: str = "text",
    text: str | None = None,
):
    """Append one message to chat_messages (best-effort)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO chat_messages
               (ts, chat_id, user_id, username, full_name, direction, msg_id, msg_type, text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(time.time()),
                int(chat_id),
                user_id,
                username,
                full_name,
                direction,
                msg_id,
                msg_type,
                text,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        # never break the bot because logging failed
        pass


def _humanize_callback_label(data: str) -> str:
    raw = str(data or "").strip()
    mapping = {
        "menu:check_balance": "เช็คเงิน",
        "menu:root": "กลับเมนู",
        "menu:promo": "โปรโมชัน",
        "menu:payment": "ชำระเงิน",
        "menu:stats": "สถิติระบบ",
        "menu:ticker": "ติดต่อแอดมิน",
        "menu:random_image": "สุ่มรูป",
    }
    if raw in mapping:
        return mapping[raw]
    if raw.startswith("menu:"):
        return raw.split(":", 1)[1]
    return raw or "unknown"


def log_callback_press(
    chat_id: int,
    *,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
    msg_id: int | None = None,
    callback_data: str | None = None,
):
    """Append one callback/button press to chat_messages (best-effort)."""
    try:
        label = _humanize_callback_label(str(callback_data or ""))
        text = f"BUTTON: {label}"
        if callback_data:
            text += f" [{callback_data}]"
        log_chat_message(
            "in",
            int(chat_id),
            user_id=user_id,
            username=username,
            full_name=full_name,
            msg_id=msg_id,
            msg_type="callback",
            text=text,
        )
    except Exception:
        pass

def extract_truemoney_v(url: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        return qs.get("v", [None])[0]
    except Exception:
        return None

def is_valid_truemoney_v(v: str) -> bool:
    """ตรวจความยาวและรูปแบบรหัส v ของซองทรู"""
    if not v:
        return False

    # อนุญาตเฉพาะ a-z A-Z 0-9
    if not re.fullmatch(r"[A-Za-z0-9]+", v):
        return False

    # กำหนดความยาว 34-39 ตัว
    if not (34 <= len(v) <= 39):
        return False

    return True


def extract_truemoney_v_strict(url: str) -> str | None:
    """รับเฉพาะลิงก์ซองทรูจริง: https://gift.truemoney.com/campaign/?v=..."""
    try:
        url = (url or "").strip().rstrip(').,;:\'"}]> \n\t')
        p = urlparse(url)

        if p.scheme != "https":
            return None

        host = (p.netloc or "").lower().split(":")[0]
        if host != "gift.truemoney.com":
            return None

        if p.path != "/campaign/":
            return None

        qs = parse_qs(p.query)
        v = qs.get("v", [None])[0]
        if not v or not is_valid_truemoney_v(v):
            return None

        return v
    except Exception:
        return None


def is_v_used(v: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM used_v WHERE v = ? LIMIT 1", (v,))
    row = cur.fetchone()
    conn.close()
    return row is not None

def mark_v_used(v: str, amount=None, raw_result=None, used_at=None, owner_user_id=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO used_v (v, first_seen_at, amount, raw_result, used_at, owner_user_id)
        VALUES (?, strftime('%s','now'), ?, ?, ?, ?)
        ON CONFLICT(v) DO UPDATE SET
            amount=COALESCE(excluded.amount, used_v.amount),
            raw_result=COALESCE(excluded.raw_result, used_v.raw_result),
            used_at=COALESCE(excluded.used_at, used_v.used_at),
            owner_user_id=COALESCE(excluded.owner_user_id, used_v.owner_user_id)
        """,
        (
            v,
            amount,
            json.dumps(raw_result, ensure_ascii=False) if raw_result is not None else None,
            used_at,
            owner_user_id,
        )
    )
    conn.commit()
    conn.close()

def get_v_used_info(v: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT v, first_seen_at, amount, raw_result, used_at, owner_user_id FROM used_v WHERE v = ? LIMIT 1",
        (v,)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    try:
        raw_result = json.loads(row[3]) if row[3] else None
    except Exception:
        raw_result = row[3]

    try:
        amount = float(row[2] or 0)
    except Exception:
        amount = 0.0

    return {
        "v": row[0],
        "first_seen_at": row[1],
        "amount": amount,
        "raw_result": raw_result,
        "used_at": row[4],
        "owner_user_id": row[5],
    }

def get_user_total(user_id: int) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total FROM user_balance WHERE user_id = ? LIMIT 1", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    try:
        return float(row[0] or 0) if row else 0.0
    except Exception:
        return 0.0

def add_user_total(user_id: int, amount: float) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_balance (user_id, total)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET total = user_balance.total + excluded.total
        """,
        (int(user_id), float(amount)),
    )
    conn.commit()
    cur.execute("SELECT total FROM user_balance WHERE user_id = ? LIMIT 1", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    try:
        return float(row[0] or 0)
    except Exception:
        return 0.0

def subtract_user_total(user_id: int, amount: float) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_balance (user_id, total)
        VALUES (?, 0)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (int(user_id),),
    )
    cur.execute(
        """
        UPDATE user_balance
        SET total = CASE
            WHEN total - ? < 0 THEN 0
            ELSE total - ?
        END
        WHERE user_id = ?
        """,
        (float(amount), float(amount), int(user_id)),
    )
    conn.commit()
    cur.execute("SELECT total FROM user_balance WHERE user_id = ? LIMIT 1", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    try:
        return float(row[0] or 0)
    except Exception:
        return 0.0

def delete_v_used(v: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM used_v WHERE v = ?", (v,))
    conn.commit()
    conn.close()


def unmark_link_pending(url: str):
    PENDING_LINKS.pop(url, None)

PAY_IMAGE_PATH = "bottele.jpg"        # รูปตัวอย่างชำระเงิน (อยู่โฟลเดอร์เดียวกับ bot.py)
PRICE_TEXT = "💸 <b>ราคาเข้ากลุ่ม: 899 บาท</B>"         # แก้เป็นราคาจริง
CONTACT_TEXT = "ช่องทางติดต่อแอดมิน: @dok_thongg"

PAY_HELP_TEXT = (
    f"{PRICE_TEXT}\n\n"
    "💳 <b>วิธีส่งซอง</b>\n"
    "1. คลิกโอนเงิน\n"
    "2. เลือกแถบ “ส่งซองทรูมันนี่”\n"
    "3. เลือกใส่จำนวนเงิน (1 คน)\n"
    "4. กดคัดลอกลิงก์ หรือบันทึกรูปภาพ QR\n\n"
    "🚀 ส่งมาที่แชทนี้\n"
    "รอรับลิงก์กลุ่มอัตโนมัติทันที!"
)

SUCCESS_TEXT = "รับข้อมูลเรียบร้อยค่ะ ✅\nแอดมินกำลังตรวจสอบให้นะคะ 🙂"
FAIL_TEXT = "ตรวจสอบไม่พบค่ะ ❌\nกรุณาส่งใหม่อีกครั้ง (ลิงก์ซองทรูมันนี่ หรือรูป QR เท่านั้นนะคะ)"

# -----------------------
# Inline menu
# -----------------------
MENU_ROOT_TEXT = (
    "<b>ระบบชำระเงินเข้ากลุ่มอัตโนมัติ</b>\n\n"
    "💖เลือกเมนูด้านล่างได้เลย💖\n"
    "━━━━━━━━━━━━━━\nลิ้งค์กลุ่มตัวอย่างใหม่ 🔗 https://t.me/+w6AUm84427c2Yzk1"
)

LAST_BALANCE_MSG = {}
LAST_BALANCE_STATE = {}
LAST_BALANCE_SOURCE = {}
LAST_MENU_MSG: dict[int, int] = {}
LAST_MENU_MEDIA_MSG: dict[int, int] = {}
LAST_PAYMENT_MEDIA_MSG: dict[int, int] = {}
LAST_PAYMENT_TEXT_MSG: dict[int, int] = {}
USER_PAYMENT_SENT: set[int] = set()
USER_JOINED: set[int] = set()
MENU_IMAGE_PATH = "menu.jpg"

## ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====
def _menu_root_keyboard(chat_id: int | None = None, user_id: int | None = None) -> InlineKeyboardMarkup:
    random_label = "🎲 สุ่มภาพ (0/3)"
    if chat_id is not None and user_id is not None:
        random_label = get_random_menu_label(chat_id, user_id)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳  วิธีชำระเงิน", callback_data="menu:payment")],
        [InlineKeyboardButton("🛎️ โปรโมชั่นล่าสุด", callback_data="menu:promo")],
        [InlineKeyboardButton("📝  อ่านเครดิต-รีวิว", url="https://t.me/reviwdelight")],
        [InlineKeyboardButton("🎫  สอบถาม/แจ้งปัญหา", callback_data="menu:ticker")],
        [
            InlineKeyboardButton("📊 สถิติระบบ", callback_data="menu:stats"),

            InlineKeyboardButton(random_label, callback_data="menu:random_image"),
        ]
    ])


# ===== POST-JOIN BALANCE + INVITE LEDGER (ต่อยอดโฟลวเดิมแบบไม่สร้าง flow รับเงินใหม่) =====



def record_pending_invite(invite_link: str, owner_user_id: int, balance_bucket: str = "pre") -> None:
    if not invite_link:
        return
    bucket = "post" if str(balance_bucket) == "post" else "pre"
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO pending_invites (invite_link, owner_user_id, balance_bucket, used, created_at)
            VALUES (?, ?, ?, 0, strftime('%s','now'))
            """,
            (str(invite_link), int(owner_user_id), bucket),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_pending_invite(invite_link: str) -> dict | None:
    if not invite_link:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT invite_link, owner_user_id, balance_bucket, used
            FROM pending_invites
            WHERE invite_link = ? LIMIT 1
            """,
            (str(invite_link),),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "invite_link": row[0],
            "owner_user_id": int(row[1]),
            "balance_bucket": str(row[2] or "pre"),
            "used": bool(row[3]),
        }
    except Exception:
        return None


def mark_pending_invite_used(invite_link: str, used_by_user_id: int | None = None) -> None:
    if not invite_link:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE pending_invites
            SET used = 1,
                used_by_user_id = ?,
                used_at = strftime('%s','now')
            WHERE invite_link = ?
            """,
            (int(used_by_user_id) if used_by_user_id is not None else None, str(invite_link)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def mark_web_payment_invite_joined(invite_link: str, joined_user_id: int | None = None) -> None:
    if not invite_link:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE payment_attempts
            SET join_status='joined',
                link_status=CASE WHEN link_status='issued' THEN 'used' ELSE link_status END,
                link_used_at=COALESCE(link_used_at, strftime('%s','now')),
                joined_user_id=?,
                joined_at=COALESCE(joined_at, strftime('%s','now')),
                join_match_status=CASE
                    WHEN buyer_user_id IS NOT NULL AND buyer_user_id = ? THEN 'matched'
                    WHEN buyer_user_id IS NOT NULL AND buyer_user_id != ? THEN 'mismatch'
                    ELSE join_match_status
                END
            WHERE invite_link = ?
            """,
            (
                int(joined_user_id) if joined_user_id is not None else None,
                int(joined_user_id) if joined_user_id is not None else None,
                int(joined_user_id) if joined_user_id is not None else None,
                str(invite_link),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def mark_web_payment_member_left(user_id: int) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE payment_attempts
            SET join_status='left',
                join_match_status=CASE
                    WHEN join_match_status IN ('matched', 'mismatch') THEN join_match_status
                    ELSE 'left'
                END
            WHERE joined_user_id = ?
            """,
            (int(user_id),),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def find_payment_attempt_id_by_invite(invite_link: str | None) -> str:
    if not invite_link:
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM payment_attempts WHERE invite_link=? LIMIT 1", (str(invite_link),))
        row = cur.fetchone()
        conn.close()
        return str(row[0] or "") if row else ""
    except Exception:
        return ""


def record_group_member_event(
    *,
    event_type: str,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_full_name: str | None = None,
    owner_user_id: int | None = None,
    invite_link: str | None = None,
    amount: float | None = None,
    balance_before: float | None = None,
    balance_after: float | None = None,
    note: str = "",
) -> None:
    try:
        init_used_v_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        attempt_id = find_payment_attempt_id_by_invite(invite_link)
        cur.execute(
            """
            INSERT INTO group_member_events (
                event_type, group_id, invite_link, owner_user_id, actor_user_id,
                actor_username, actor_full_name, amount, balance_before,
                balance_after, source, attempt_id, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event_type or ""),
                str(GROUP_CHAT_ID),
                str(invite_link or ""),
                int(owner_user_id) if owner_user_id is not None else None,
                int(actor_user_id) if actor_user_id is not None else None,
                str(actor_username or ""),
                str(actor_full_name or ""),
                float(amount) if amount is not None else None,
                float(balance_before) if balance_before is not None else None,
                float(balance_after) if balance_after is not None else None,
                "bot.py",
                attempt_id,
                str(note or ""),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_pending_invites_to_memory() -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT invite_link, owner_user_id FROM pending_invites WHERE used = 0")
        rows = cur.fetchall()
        conn.close()
        for invite_link, owner_user_id in rows:
            if invite_link:
                PENDING_INVITE_OWNER[str(invite_link)] = int(owner_user_id)
    except Exception:
        pass


def set_latest_check_state(user_id: int, latest_kind: str, latest_text: str) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO latest_check_state (user_id, latest_kind, latest_text, updated_at)
            VALUES (?, ?, ?, strftime('%s','now'))
            ON CONFLICT(user_id) DO UPDATE SET
                latest_kind = excluded.latest_kind,
                latest_text = excluded.latest_text,
                updated_at = excluded.updated_at
            """,
            (int(user_id), str(latest_kind or ""), str(latest_text or "")),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_latest_check_state(user_id: int) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT latest_kind, latest_text, updated_at FROM latest_check_state WHERE user_id = ? LIMIT 1",
            (int(user_id),),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"latest_kind": "", "latest_text": "", "updated_at": None}
        return {
            "latest_kind": str(row[0] or ""),
            "latest_text": str(row[1] or ""),
            "updated_at": row[2],
        }
    except Exception:
        return {"latest_kind": "", "latest_text": "", "updated_at": None}

LATEST_EXPIRE_SEC = 6 * 60 * 60  #6 ชั่วโมง

# ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====
async def _build_balance_snapshot(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """คืนค่า balance, status, latest_status, update_time โดยแยกสถานะหลักกับ latest ออกจากกัน"""
    try:
        total_paid = float(get_user_total(int(chat_id)) or 0)
    except Exception:
        total_paid = 0.0
    state = get_user_payment_state(chat_id)
    joined_state = (chat_id in USER_JOINED) or bool(state.get("joined"))
    payment_sent_state = (chat_id in USER_PAYMENT_SENT) or bool(state.get("payment_sent"))

    try:
        member = await context.bot.get_chat_member(GROUP_CHAT_ID, chat_id)
        current_status = getattr(member, "status", "")
    except Exception:
        current_status = ""

    if current_status in ("member", "administrator", "creator"):
        # snapshot อ่านสถานะจาก Telegram เพื่อแสดงผลเท่านั้น
        joined_state = True
    elif current_status in ("left", "kicked"):
        # ออกจากกลุ่มแล้วให้แสดงผลตามสถานะจริง แต่ไม่เขียน DB ใน snapshot
        joined_state = False

    latest = get_latest_check_state(int(chat_id))
    latest_kind = str(latest.get("latest_kind", "") or "").lower()
    latest_updated_at = latest.get("updated_at")

    latest_is_fresh = False
    try:
        if latest_updated_at:
            latest_is_fresh = (int(time.time()) - int(latest_updated_at)) < LATEST_EXPIRE_SEC
    except Exception:
        latest_is_fresh = False

    # เคสพิเศษ: API พัง / ยังไม่รู้ผลซองจริง
    # ตอนกดเช็คต้องขึ้น BALANCE: error และคงสถานะเดิมไว้ถ้ามี
    if latest_kind == "check_error" and latest_is_fresh:
        if bool(state.get("invalidated")) and not joined_state:
            status = "ไม่พบรายการ"
        elif joined_state:
            status = "เข้ากลุ่มสำเร็จ"
        elif total_paid > 0 or payment_sent_state:
            status = "รอการเข้ากลุ่ม"
        else:
            status = ""
        update_time = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
        return "error", status, "↻ ตรวจไม่พบข้อมูล", update_time

    # แยกยอดออกจากสถานะ
    # ยอดคือยอด สิทธิ์คือสิทธิ์
    if bool(state.get("invalidated")) and not joined_state:
        # invalidated = สิทธิ์รอบนี้จบแล้ว
        # ถ้ามีเศษเงินจริงหลังหักค่อยแสดงยอดสะสม แต่ไม่ปลุกสิทธิ์เก่ากลับมา
        balance = max(float(total_paid), 0.0)
        status = "รอการเข้ากลุ่ม" if 0 < balance < float(VIP_MIN_AMOUNT) else "ไม่พบรายการ"

    elif joined_state:
        # คนจ่ายยังอยู่ในกลุ่ม = เข้าสำเร็จ
        # BALANCE อ่านยอดหลักหลังหัก 789 เท่านั้น
        try:
            balance = max(float(get_user_total(int(chat_id)) or 0.0), 0.0)
        except Exception:
            balance = max(float(total_paid), 0.0)
        status = "เข้ากลุ่มสำเร็จ"

    elif payment_sent_state:
        # มีลิงก์รอใช้จริงเท่านั้นถึงเป็นรอเข้า
        balance = max(float(total_paid), 0.0)
        status = "รอการเข้ากลุ่ม"

    elif float(total_paid) > 0:
        # ยอดสะสมเฉย ๆ แต่ยังไม่มีลิงก์ pending
        balance = max(float(total_paid), 0.0)
        status = "รอการเข้ากลุ่ม" if balance < float(VIP_MIN_AMOUNT) else "ไม่พบรายการ"

    else:
        balance = 0
        status = "ไม่พบรายการ"

    latest_status = ""
    if latest_is_fresh:
        if latest_kind == "failed_after_join" and joined_state:
            latest_status = "❌ จ่ายไม่สำเร็จ"
        elif latest_kind == "failed" and not joined_state:
            latest_status = "❌ จ่ายไม่สำเร็จ"
        elif latest_kind == "invite_used" and not joined_state:
            latest_status = "ลิงก์นี้ถูกใช้งานไปแล้ว"

    update_time = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
    return balance, status, latest_status, update_time

def _menu_back_keyboard(extra_rows: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    rows = extra_rows[:] if extra_rows else []
    rows.append([InlineKeyboardButton("⬅️ กลับเมนู", callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)

async def _delete_message_safe(msg) -> None:
    try:
        await msg.delete()
    except Exception:
        pass

async def _clear_payment_ui(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, keep_ids: set[int] | None = None):
    if chat_id is None:
        return

    keep_ids = keep_ids or set()

    media_id = LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
    if media_id:
        if int(media_id) in keep_ids:
            LAST_PAYMENT_MEDIA_MSG[int(chat_id)] = int(media_id)
        else:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=media_id)
            except Exception:
                pass

    text_id = LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
    if text_id:
        if int(text_id) in keep_ids:
            LAST_PAYMENT_TEXT_MSG[int(chat_id)] = int(text_id)
        else:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=text_id)
            except Exception:
                pass

async def _edit_or_send_payment_page(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    source_message=None,
):
    """หน้า payment ใช้รูป + caption ใน bubble เดียวกัน เพื่อให้รูปติดกับข้อความ"""
    keyboard = _menu_back_keyboard([[InlineKeyboardButton("🔎 ดูยอดเงิน", callback_data="menu:check_balance")]])
    caption = PAY_HELP_TEXT
    source_mid = int(source_message.message_id) if source_message and getattr(source_message, "message_id", None) else None

    if source_mid and os.path.exists(PAY_IMAGE_PATH):
        try:
            with open(PAY_IMAGE_PATH, "rb") as f:
                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=source_mid,
                    media=InputMediaPhoto(media=f, caption=caption, parse_mode="HTML"),
                    reply_markup=keyboard,
                )
            LAST_PAYMENT_MEDIA_MSG[int(chat_id)] = source_mid
            LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
            LAST_MENU_MSG.pop(int(chat_id), None)
            LAST_MENU_MEDIA_MSG.pop(int(chat_id), None)
            return source_mid
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                LAST_PAYMENT_MEDIA_MSG[int(chat_id)] = source_mid
                LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
                LAST_MENU_MSG.pop(int(chat_id), None)
                LAST_MENU_MEDIA_MSG.pop(int(chat_id), None)
                return source_mid
        except Exception:
            pass

    if source_mid:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=source_mid,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            LAST_PAYMENT_TEXT_MSG[int(chat_id)] = source_mid
            LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
            LAST_MENU_MSG.pop(int(chat_id), None)
            LAST_MENU_MEDIA_MSG.pop(int(chat_id), None)
            return source_mid
        except Exception:
            pass

    if os.path.exists(PAY_IMAGE_PATH):
        with open(PAY_IMAGE_PATH, "rb") as f:
            media_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        LAST_PAYMENT_MEDIA_MSG[int(chat_id)] = media_msg.message_id
        LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
        return media_msg.message_id

    text_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    LAST_PAYMENT_TEXT_MSG[int(chat_id)] = text_msg.message_id
    LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
    return text_msg.message_id


async def _edit_or_send_root_menu_page(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    source_message=None,
):
    """กลับหน้าเมนูหลักจากหน้า payment ด้วยการ edit ข้อความเดิมก่อน"""
    keyboard = _menu_root_keyboard(chat_id, chat_id)
    source_mid = int(source_message.message_id) if source_message and getattr(source_message, "message_id", None) else None

    if source_mid and os.path.exists(MENU_IMAGE_PATH):
        try:
            with open(MENU_IMAGE_PATH, "rb") as f:
                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=source_mid,
                    media=InputMediaPhoto(media=f, caption=MENU_ROOT_TEXT, parse_mode="HTML"),
                    reply_markup=keyboard,
                )
            LAST_MENU_MEDIA_MSG[int(chat_id)] = source_mid
            LAST_MENU_MSG.pop(int(chat_id), None)
            LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
            LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
            return source_mid
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                LAST_MENU_MEDIA_MSG[int(chat_id)] = source_mid
                LAST_MENU_MSG.pop(int(chat_id), None)
                LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
                LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
                return source_mid
        except Exception:
            pass

    if source_mid:
        try:
            if getattr(source_message, "photo", None):
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=source_mid,
                    caption=MENU_ROOT_TEXT,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                LAST_MENU_MEDIA_MSG[int(chat_id)] = source_mid
                LAST_MENU_MSG.pop(int(chat_id), None)
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=source_mid,
                    text=MENU_ROOT_TEXT,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                LAST_MENU_MSG[int(chat_id)] = source_mid
                LAST_MENU_MEDIA_MSG.pop(int(chat_id), None)
            LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
            LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
            return source_mid
        except Exception:
            pass

    return await send_root_menu(chat_id, context)


async def send_root_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    old = LAST_MENU_MSG.pop(int(chat_id), None)
    if old:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old)
        except Exception:
            pass
    old_media = LAST_MENU_MEDIA_MSG.pop(int(chat_id), None)
    if old_media:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_media)
        except Exception:
            pass
    if os.path.exists(MENU_IMAGE_PATH):
        with open(MENU_IMAGE_PATH, "rb") as f:
            media_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=MENU_ROOT_TEXT,
                reply_markup=_menu_root_keyboard(chat_id, chat_id),
                parse_mode="HTML",
            )
        LAST_MENU_MEDIA_MSG[int(chat_id)] = media_msg.message_id
        return media_msg
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=MENU_ROOT_TEXT,
        reply_markup=_menu_root_keyboard(chat_id, chat_id),
        parse_mode="HTML",
    )
    LAST_MENU_MSG[int(chat_id)] = msg.message_id
    return msg


async def build_stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        member_count = await context.bot.get_chat_member_count(GROUP_CHAT_ID)
    except Exception:
        member_count = 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM used_v")
    total_envelopes = int(cur.fetchone()[0] or 0)
    conn.close()

    thai_time = datetime.utcnow() + timedelta(hours=7)

    return (
        "📊 SYSTEM STATUS\n\n"
        f"👥 คนเข้ากลุ่ม: {member_count}\n"
        "📈 อัตราคนเข้ากลุ่มสำเร็จ: 98%\n"
        f"💰 จำนวนซองที่ได้รับ: {total_envelopes}\n"
        "🟢 ระบบออนไลน์\n\n"
        f"⏱ อัปเดตล่าสุด: {thai_time.strftime('%H:%M:%S')} น."
    )


async def _ticket_close_silent(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if chat_id in TICKET_OPEN:
        TICKET_OPEN.discard(chat_id)
    _cancel_ticket_job(chat_id)
    TICKET_LAST_ACTIVITY.pop(chat_id, None)
    TICKET_CONFIRMED.discard(int(chat_id))
    _ticket_note_close(int(chat_id))
    for k, v in list(TICKET_MAP.items()):
        if v == chat_id:
            del TICKET_MAP[k]


async def _ticket_close_with_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if chat_id in TICKET_OPEN:
        # ======= 🔺จุดแก้ ticket flow🔻 =========
        # ปิดเมื่อไร ลบข้อความเปิด ticket และข้อความเตือนเก่าทิ้งเสมอ
        ack_mid = TICKET_OPEN_ACK_MSG.get(int(chat_id))
        if ack_mid:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=ack_mid)
            except Exception:
                pass
        TICKET_OPEN_ACK_MSG.pop(int(chat_id), None)

        warn_mid = WARNING_MSG.get(int(chat_id))
        if warn_mid:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=warn_mid)
            except Exception:
                pass
        WARNING_MSG.pop(int(chat_id), None)

        await _ticket_close_silent(context, chat_id)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔒 ปิดห้องแจ้งปัญหาเรียบร้อย"
            )
        except Exception:
            pass

async def _notify_admin_ticket_closed_by_user(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    user,
    action_text: str,
):
    try:
        who = f"@{user.username}" if user and getattr(user, "username", None) else (user.full_name if user else "unknown")
        await context.bot.send_message(
            chat_id=get_admin_notify_chat_id(),
            text=(
                "📴 ลูกค้าปิด Ticket แล้ว\n"
                f"ChatID: {chat_id}\n"
                f"User: {who}\n"
                f"สาเหตุ: {action_text}"
            ),
        )
    except Exception:
        pass

### ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====
def build_balance_text(balance, status, latest_status="", update_time=None):
    if update_time is None:
        update_time = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")

    raw_status = str(status).strip()

    # สถานะล่าสุดจริง = เด่นที่สุด และใส่อิโมจิได้
    if raw_status == "เข้ากลุ่มสำเร็จ":
        current_status_line = "✅ เข้ากลุ่มสำเร็จ"
        plain_status_line = "เข้ากลุ่มสำเร็จ"
    elif raw_status == "รอการเข้ากลุ่ม":
        current_status_line = "⚠️ รอการเข้ากลุ่ม"
        plain_status_line = "รอการเข้ากลุ่ม"
    elif raw_status == "ไม่พบรายการ":
        current_status_line = "ไม่พบรายการ"
        plain_status_line = "ไม่พบรายการ"
    else:
        current_status_line = raw_status
        plain_status_line = raw_status

    failed_line = str(latest_status)
    if str(balance) == "error" and latest_status:
        failed_line = "↻ ตรวจไม่พบข้อมูล"

    # ถ้ามี failed และ status ว่าง/ไม่พบรายการ -> failed เด่นที่สุด
    if latest_status and (not raw_status or raw_status == "ไม่พบรายการ"):
        return (
            "💰 𝗕𝗔𝗟𝗔𝗡𝗖𝗘: " + format_money(balance) + "\n"
            "⭕ 𝗙𝗔𝗜𝗟𝗘𝗗: " + failed_line + "\n\n"
            "⏱︎ 𝗧𝗜𝗠   𝗡𝗢𝗪: " + str(update_time)
        )

    # ถ้ามี failed และมี status จริง -> failed คือสถานะล่าสุด
    # status กลายเป็นสถานะเก่า ห้ามใส่อิโมจิ
    if latest_status and raw_status in ("เข้ากลุ่มสำเร็จ", "รอการเข้ากลุ่ม"):
        return (
            "💰 𝗕𝗔𝗟𝗔𝗡𝗖𝗘: " + format_money(balance) + "\n"
            "💳 𝗦𝗧𝗔𝗧𝗨𝗦: " + plain_status_line + "\n"
            "⭕ 𝗙𝗔𝗜𝗟𝗘𝗗: " + failed_line + "\n\n"
            "⏱︎ 𝗧𝗜𝗠𝗘 𝗡𝗢𝗪: " + str(update_time)
        )

    return (
        "💰 𝗕𝗔𝗟𝗔𝗡𝗖𝗘: " + format_money(balance) + "\n"
        "💳 𝗦𝗧𝗔𝗧𝗨𝗦: " + current_status_line + "\n\n"
        "⏱︎ 𝗧𝗜𝗠𝗘 𝗡𝗢𝗪: " + str(update_time)
    )

# ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====
async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not update.effective_chat:
        return

    data = query.data or ""

    if data == "menu:promo":
        await query.answer(
            text="‼️ โปรพิเศษรอบสุดท้าย\n\nเหลือเพียง 💸 7️⃣8️⃣9️⃣ บาท\n(จาก 1̶0̶0̶0̶)\n\n🔔 ถึงวันที่ 16/04/26",
            show_alert=True
        )
        return

    if data.startswith("apierr:"):
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        review_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        review = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM api_error_payment_reviews WHERE id = ? LIMIT 1", (review_id,))
            row = cur.fetchone()
            if row:
                review = dict(row)
            conn.close()
        except Exception:
            review = None

        if not review or str(review.get("status") or "") != "pending":
            await query.answer("เคสนี้ถูกตรวจไปแล้ว", show_alert=True)
            return

        user_id = int(review.get("user_id") or 0)
        if action == "no":
            url = str(review.get("url") or "")
            v = str(review.get("v") or extract_truemoney_v(url) or "")
            try:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE api_error_payment_reviews SET status='rejected', reviewed_at=strftime('%s','now') WHERE id=?", (review_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass

            # ปิดเคส API msg err เป็นตรวจจบแล้วแบบ fail
            # ให้ตอนกดเช็คยอดเงินเข้า logic เดียวกับซองถูกใช้/ไม่พบซอง
            # และถ้าส่งซองเดิมซ้ำ ให้ตอบว่าเคยตรวจแล้ว ไม่วนกลับไปเช็ค API ใหม่
            set_latest_check_state(user_id, "failed", "admin_rejected_api_error")
            if v:
                mark_v_used(
                    v,
                    amount=0,
                    raw_result={
                        "status": "error",
                        "message": "admin_rejected_api_error",
                        "admin_review": "admin_review_rejected",
                    },
                    used_at=None,
                    owner_user_id=user_id,
                )
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ แอดมินตรวจสอบแล้ว ไม่พบยอดเงินในรายการนี้ค่ะ")
            except Exception:
                pass
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await query.answer("ปฏิเสธแล้ว")
            return

        if action == "yes":
            try:
                result = json.loads(review.get("raw_result") or "{}")
            except Exception:
                result = {}
            url = str(review.get("url") or "")
            v = str(review.get("v") or extract_truemoney_v(url) or "")

            async def _admin_send_result(text: str, **kwargs):
                sent = await context.bot.send_message(chat_id=user_id, text=text, **kwargs)
                try:
                    _remember_result_msg(user_id, sent.message_id)
                except Exception:
                    pass
                return sent

            async def _admin_send_group_link_result(text: str, **kwargs):
                sent = await context.bot.send_message(chat_id=user_id, text=text, **kwargs)
                try:
                    await _replace_group_link_msg(context, user_id, sent.message_id)
                except Exception:
                    pass
                return sent

            async def _admin_close_processing_msg():
                USER_PENDING_MSG_ID.pop(user_id, None)

            await _run_wallet_success_flow(
                context,
                user_id,
                v,
                result,
                _admin_send_result,
                _admin_send_group_link_result,
                _admin_close_processing_msg,
            )
            try:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE api_error_payment_reviews SET status='approved', reviewed_at=strftime('%s','now') WHERE id=?", (review_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await query.answer("ยืนยันแล้ว")
            return

    if update.effective_chat.type != ChatType.PRIVATE:
        try:
            await query.answer()
        except Exception:
            pass
        return

    chat_id = int(update.effective_chat.id)

    try:
        u = update.effective_user
        log_callback_press(
            chat_id,
            user_id=int(u.id) if u else None,
            username=getattr(u, "username", None) if u else None,
            full_name=getattr(u, "full_name", None) if u else None,
            msg_id=getattr(query.message, "message_id", None),
            callback_data=data,
        )
    except Exception:
        pass

    if await handle_random_game_callback(update, context):
        return

    try:
        await query.answer()
    except Exception:
        pass

    # ======= 🔺จุดแก้ ticket flow🔻 =========
    if chat_id in TICKET_OPEN and data in {"menu:root", "menu:payment", "menu:stats"}:
        old_warn = WARNING_MSG.get(chat_id)
        if old_warn:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
            except Exception:
                pass
        sent_warn = await context.bot.send_message(
            chat_id=chat_id,
            text="ตอนนี้คุณอยู่ในโหมดแจ้งปัญหา ต้องการปิดเพื่อทำรายการอื่นใช่หรือไม่?\n⚠️ คำเตือน: หากยืนยันปิดแอดมินจะไม่สามารถตอบข้อความได้",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("✅", callback_data="menu:ticket_confirm"),
                InlineKeyboardButton("❌", callback_data="menu:ticket_cancel"),
            ]]),
        )
        WARNING_MSG[chat_id] = sent_warn.message_id
        return

    if data == "menu:ticket_confirm":
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        WARNING_MSG.pop(chat_id, None)
        TICKET_MENU_WARN_SUPPRESSED.discard(chat_id)
        if chat_id in TICKET_OPEN:
            await _notify_admin_ticket_closed_by_user(
                context,
                chat_id=chat_id,
                user=update.effective_user,
                action_text="กดยืนยันปิดเพื่อทำรายการอื่น",
            )
            await _ticket_close_with_notice(context, chat_id)
        await send_root_menu(chat_id, context)
        return
        try:
            if msg and msg.message_id:
                asyncio.create_task(_delete_user_msg_delay(context, msg.chat_id, msg.message_id))
        except:
            pass

    if data == "menu:ticket_cancel":
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        WARNING_MSG.pop(chat_id, None)
        TICKET_MENU_WARN_SUPPRESSED.add(chat_id)
        return

    if data == "menu:root":
        current_mid = int(query.message.message_id) if query.message and getattr(query.message, "message_id", None) else None
        await _clear_payment_ui(context, chat_id, keep_ids={current_mid} if current_mid else None)
        await _edit_or_send_root_menu_page(context, chat_id, source_message=query.message)
        return

    if data == "menu:payment":
        current_mid = int(query.message.message_id) if query.message and getattr(query.message, "message_id", None) else None
        await _clear_payment_ui(context, chat_id, keep_ids={current_mid} if current_mid else None)
        await _edit_or_send_payment_page(context, chat_id, source_message=query.message)
        return

    if data == "menu:check_balance":
        amount, status, latest_status, update_time = await _build_balance_snapshot(context, int(chat_id))
        text = build_balance_text(amount, status, latest_status, update_time)

        current_key = f"{amount}|{status}|{latest_status}"
        old_msg_id = LAST_BALANCE_MSG.get(chat_id)
        last_key = LAST_BALANCE_STATE.get(chat_id)
        current_source = LAST_PAYMENT_TEXT_MSG.get(chat_id) or LAST_PAYMENT_MEDIA_MSG.get(chat_id) or 0
        last_source = LAST_BALANCE_SOURCE.get(chat_id)

        same_payment_page = bool(old_msg_id and last_source == current_source)
        same_status = bool(last_key == current_key)

        # หน้าเดิม + สถานะเดิม -> edit ข้อความเดิมตาม flow เดิม
        if old_msg_id and same_payment_page and same_status:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=old_msg_id,
                    text=text,
                )
                LAST_BALANCE_MSG[chat_id] = old_msg_id
                LAST_BALANCE_STATE[chat_id] = current_key
                LAST_BALANCE_SOURCE[chat_id] = current_source
                return
            except Exception as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    LAST_BALANCE_MSG[chat_id] = old_msg_id
                    LAST_BALANCE_STATE[chat_id] = current_key
                    LAST_BALANCE_SOURCE[chat_id] = current_source
                    return
                # ถ้าแก้ไม่ได้จริง ให้ลบของเก่าก่อน แล้วค่อยส่งใหม่
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
                except Exception:
                    pass
                LAST_BALANCE_MSG.pop(chat_id, None)
                LAST_BALANCE_STATE.pop(chat_id, None)
                LAST_BALANCE_SOURCE.pop(chat_id, None)

        # หน้าใหม่ หรือสถานะเปลี่ยน -> ถ้ามีของเก่าค้าง ให้ลบก่อนแล้วค่อยส่งใหม่
        if old_msg_id and (not same_payment_page or not same_status):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except Exception:
                pass
            LAST_BALANCE_MSG.pop(chat_id, None)
            LAST_BALANCE_STATE.pop(chat_id, None)
            LAST_BALANCE_SOURCE.pop(chat_id, None)

        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
        )
        LAST_BALANCE_MSG[chat_id] = sent.message_id
        LAST_BALANCE_STATE[chat_id] = current_key
        LAST_BALANCE_SOURCE[chat_id] = current_source
        return

    if data == "menu:stats":
        await _clear_payment_ui(context, chat_id)
        if chat_id in TICKET_OPEN:
            await _notify_admin_ticket_closed_by_user(
                context,
                chat_id=chat_id,
                user=update.effective_user,
                action_text="กดเมนูสถิติระบบ",
            )
            await _ticket_close_with_notice(context, chat_id)
        stats_text = await build_stats_text(context)
        reply_markup = _menu_back_keyboard([[InlineKeyboardButton("🔄 รีเฟรช", callback_data="menu:stats")]])

        # รีเฟรชให้อยู่ในข้อความเดิม ถ้าแก้ข้อความเดิมไม่ได้จริง ๆ ค่อยส่งข้อความใหม่
        if getattr(query.message, 'photo', None):
            await _delete_message_safe(query.message)
            sent = await context.bot.send_message(chat_id=chat_id, text=stats_text, reply_markup=reply_markup)
            LAST_MENU_MSG[int(chat_id)] = sent.message_id
            return

        try:
            await query.edit_message_text(stats_text, reply_markup=reply_markup)
            if getattr(query.message, 'message_id', None):
                LAST_MENU_MSG[int(chat_id)] = int(query.message.message_id)
        except BadRequest as e:
            err = str(e).lower()
            # ถ้าเนื้อหาเหมือนเดิม/แก้ไม่ได้ชั่วคราว ไม่ต้องเด้งข้อความใหม่ซ้ำ
            if "message is not modified" in err:
                pass
            elif "message to edit not found" in err or "message can't be edited" in err:
                sent = await context.bot.send_message(chat_id=chat_id, text=stats_text, reply_markup=reply_markup)
                LAST_MENU_MSG[int(chat_id)] = sent.message_id
            else:
                raise
        return

    if data == "menu:ticker":
        await _clear_payment_ui(context, chat_id)
        # ======= 🔺จุดแก้ ticket flow🔻 =========
        old_warn = WARNING_MSG.get(chat_id)
        if old_warn:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
            except Exception:
                pass
            WARNING_MSG.pop(chat_id, None)
        # เปิดโหมด ticket แบบเดียวกับ /ticker แต่ใช้จากปุ่ม
        TICKET_MENU_WARN_SUPPRESSED.discard(chat_id)
        if chat_id not in TICKET_OPEN:
            TICKET_OPEN.add(chat_id)
            touch_ticket(context, chat_id)
            u = update.effective_user
            who = f"@{u.username}" if u and u.username else (u.full_name if u else "unknown")
            sent0 = await context.bot.send_message(
                chat_id=get_admin_notify_chat_id(),
                text=(f"📩 มีคนเปิด Ticket\n"
                      f"ChatID: {chat_id}\n"
                      f"User: {who}")
            )
            TICKET_MAP[sent0.message_id] = chat_id
            _record_admin_msg(chat_id, sent0.message_id)
            _ticket_note_open(chat_id, sent0.message_id)
        else:
            touch_ticket(context, chat_id)
        ### MAIN FLOW ticketปุ่ม ใช้จริง ห้ามแก้มั่ว
        ticket_text = (
            "━━━━━━ TICKET ━━━━━━\n\n"
            "🕹️ ตอนนี้คุณอยู่ในโหมดคุยกับแอดมิน\n"
            "ส่งแจ้งรายละเอียดผ่านแชทนี้ได้เลย\n\n"
            "🆘สำหรับติดต่อสอบถามเท่านั้น ( กลับหน้าเมนูทุกครั้งก่อนทำรายการอื่น )\n"
            "🔙 หน้าหลัก = /menu"
        )
        sent_ack = None
        try:
            if getattr(query.message, 'photo', None):
                await _delete_message_safe(query.message)
                sent_ack = await context.bot.send_message(chat_id=chat_id, text=ticket_text)
            else:
                await query.edit_message_text(ticket_text)
                sent_ack = query.message
        except BadRequest:
            sent_ack = await context.bot.send_message(chat_id=chat_id, text=ticket_text)
        if sent_ack and getattr(sent_ack, "message_id", None):
            TICKET_OPEN_ACK_MSG[chat_id] = int(sent_ack.message_id)
        return

# โดเมนที่ “อนุญาต” ให้ผ่านการตรวจแบบพื้นฐาน (ปรับได้)
ALLOWED_DOMAINS = {
    "tmn.app",
    "gift.truemoney.com",
}

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# ฟังก์ชันช่วยเช็ค “แชทส่วนตัวเท่านั้น”
# -----------------------
def is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE

async def private_only_notice(update: Update):
    if update.message:
        await update.message.reply_text("บอทนี้ใช้ในแชทส่วนตัวเท่านั้นนะคะ 🙂")

def sender_label(update: Update) -> tuple[str, str]:
    u = update.effective_user
    if not u:
        return ("unknown", "unknown")
    name = u.first_name or "unknown"
    if u.username:
        name = f"{name} (@{u.username})"
    return (name, str(u.id))

# -----------------------
# ดึง URL
# -----------------------
URL_REGEX = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

def extract_first_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_REGEX.search(text)
    return m.group(1) if m else None

def extract_first_url_from_message(msg) -> str | None:
    """
    ดึง url ตัวแรกจาก message (รองรับทั้ง url ธรรมดา และ text_link)
    """
    if not msg:
        return None

    # entity ก่อน (แม่นกว่า)
    if msg.entities:
        text = msg.text or ""
        for e in msg.entities:
            if e.type == "url":
                return text[e.offset:e.offset + e.length]
            if e.type == "text_link":
                return e.url

    # fallback regex
    text = msg.text or ""
    return extract_first_url(text)

# -----------------------
# ตรวจลิงก์แบบพื้นฐาน (กรองเบื้องต้น)
# -----------------------
def basic_verify_truemoney_link(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False

        host = (p.netloc or "").lower().split(":")[0]
        return host in ALLOWED_DOMAINS
    except Exception:
        return False

# -----------------------
# QR Decode (จากรูป) - OPTIONAL
# ถ้าเครื่องยังไม่มี lib จะอ่านไม่ได้ แต่โค้ดจะไม่พัง
# -----------------------
def try_decode_qr_from_image_bytes(img_bytes: bytes) -> list[str]:
    results: list[str] = []
    try:
        from PIL import Image
        from io import BytesIO
        from pyzbar.pyzbar import decode

        im = Image.open(BytesIO(img_bytes))
        decoded = decode(im)
        for obj in decoded:
            try:
                results.append(obj.data.decode("utf-8", errors="ignore"))
            except Exception:
                pass
    except Exception as e:
        logger.info(f"QR decode not available/failed: {e}")
    return results

# -----------------------
# คำสั่ง /start
# -----------------------


VIP_MIN_AMOUNT = float((get_package_plan("p3").amount if get_package_plan("p3") else VIP_MIN_AMOUNT))
VIP_LINK = GROUP_LINK_FALLBACK if GROUP_LINK_FALLBACK else ""

def _wallet_is_success(result: dict) -> bool:
    return str(result.get("status", "")).lower() == "success"

def _wallet_amount(result: dict) -> float:
    try:
        return float(result.get("amount") or 0)
    except Exception:
        return 0.0

def _wallet_message_used(result: dict) -> bool:
    msg = str(result.get("message", "") or "").lower()
    raw = str(result).lower()
    opened_words = [
        "used", "already redeemed", "redeemed", "ใช้ไปแล้ว",
        "ถูกใช้ไปแล้ว", "เปิดแล้ว", "ซองถูกเปิด", "ซองนี้ถูกใช้งานไปแล้ว"
    ]
    return any(w in msg for w in opened_words) or any(w in raw for w in opened_words)

def _wallet_message_not_found(result: dict) -> bool:
    msg = str(result.get("message", "") or "").lower()
    raw = str(result).lower()
    not_found_words = [
        "not found", "not_found", "no gift", "gift not found",
        "ไม่มีซอง", "ไม่พบซอง", "ซองนี้ไม่พบ", "ไม่พบในระบบ"
    ]
    return any(w in msg for w in not_found_words) or any(w in raw for w in not_found_words)

# ===== ไม่แน่ใจอย่าพึ่งลบ =====
def _wallet_fail_text(result: dict) -> str:
    if _wallet_message_used(result):
        return "❌ ไม่พบยอดเงิน / ซองถูกเปิดใช้แล้ว"
    if _wallet_message_not_found(result):
        return "❌ ตรวจไม่พบซองนี้ค่ะ"
    return "❌ ระบบตรวจสอบไม่สำเร็จ กรุณาลองใหม่"

# ===== MAIN FLOW (ใช้จริง ห้ามแก้มั่ว) =====

def check_wallet(link: str) -> dict:
    api_key = os.environ.get("API_KEY") or API_KEY
    phone_number = os.environ.get("PHONE_NUMBER") or PHONE_NUMBER
    api_url = os.environ.get("API_URL") or "https://www.planariashop.com/api/truewallet.php"
    try:
        import requests
        res = requests.post(
            api_url,
            data={
                "keyapi": api_key,
                "phone": phone_number,
                "gift_link": link,
            },
            timeout=20,
        )
        try:
            return res.json()
        except Exception:
            return {"status": "error", "message": f"invalid json: {res.text[:300]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ===== MAIN FLOW (ฟังชันทั้งหมดนี้ใช้จริง ห้ามแก้มั่ว) =====
async def _run_wallet_success_flow(context: ContextTypes.DEFAULT_TYPE, user_id: int, v: str, result: dict, send_result, send_group_link_result, close_processing_msg):
    amount = _wallet_amount(result)
    mark_v_used(v, amount=amount, raw_result=result, used_at=result.get("time"), owner_user_id=int(user_id))
    set_latest_check_state(int(user_id), "success", str(result.get("message", "") or "success"))

    # สถานะอยู่ในกลุ่มดูจากคนจ่ายเท่านั้น แล้วค่อยเลือกกระเป๋ายอดเงิน
    state_now = get_user_payment_state(int(user_id))
    payer_joined_now = bool(state_now.get("joined")) or (int(user_id) in USER_JOINED)
    try:
        member = await context.bot.get_chat_member(GROUP_CHAT_ID, int(user_id))
        if getattr(member, "status", "") in ("member", "administrator", "creator"):
            payer_joined_now = True
            USER_JOINED.add(int(user_id))
            upsert_user_payment_state(int(user_id), joined=True, invalidated=False)
    except Exception:
        pass

    # เงินทุกยอดต้องเข้ายอดหลัก user_balance เท่านั้น
    # สถานะอยู่ในกลุ่มเป็นเรื่องของ STATUS ไม่ใช่แยกกระเป๋าเงิน
    old_total = get_user_total(int(user_id))
    total_paid = add_user_total(int(user_id), amount)

    if total_paid >= VIP_MIN_AMOUNT:
        invite_link = await create_single_use_invite(context)
        if not invite_link:
            await close_processing_msg()
            await send_result("⚠️ ระบบสร้างลิ้งเข้ากลุ่มไม่ได้ชั่วคราว ติดต่อแอดที่ @dok_thongg นะคะ")
            return

        try:
            _allow_user_join(int(user_id))
            _purge_expired_allows()
            USER_PAYMENT_SENT.add(int(user_id))
            current_joined = bool(get_user_payment_state(int(user_id)).get("joined")) or (int(user_id) in USER_JOINED) or bool(payer_joined_now)
            upsert_user_payment_state(
                int(user_id),
                last_v=v,
                payment_sent=True,
                joined=current_joined,
                invalidated=False,
                active_invite=invite_link,
            )
            set_latest_check_state(int(user_id), "success", "payment_sent")
            PENDING_INVITE_OWNER[str(invite_link)] = int(user_id)
            record_pending_invite(str(invite_link), int(user_id), "pre")
        except Exception:
            pass

        await close_processing_msg()

        if float(old_total) <= 0:
            await send_group_link_result(
                "✅ ชำระเงินสำเร็จ\n"
                "━━━━━━━━━━━━━━\n"
                "💎 JOIN GROUP VIP 💎\n\n"
                + invite_link,
                disable_web_page_preview=True,
            )
        else:
            result_text = (
                "✅ ชำระเงินสำเร็จ\n"
                "──────────\n"
                f"เงินสะสม: {int(total_paid)} / {VIP_MIN_AMOUNT} บาท"
            )
            result_text += "\nคุณสามารถเข้ากลุ่มได้แล้ว"
            await send_result(result_text)
            await send_group_link_result(f"✅ {invite_link}", disable_web_page_preview=True)
    else:
        remaining = max(0.0, float(VIP_MIN_AMOUNT) - float(total_paid))
        await close_processing_msg()
        await send_result(
            "❕ ตรวจพบยอดเงินไม่พอค่ะ\n"
            f"⊕ เงินสะสม: {int(total_paid)} / {VIP_MIN_AMOUNT}\n"
            f"↺ ค้างชำระ: {format_money(remaining)}"
        )

# ===== MAIN FLOW (ฟังชันทั้งหมดนี้ใช้จริง ห้ามแก้มั่ว) =====
async def _process_wallet_link(update: Update, context: ContextTypes.DEFAULT_TYPE, msg, url: str, sender: str, sender_id: str, skip_processing: bool = False, seq: int | None = None, processing_msg=None):
    chat_id = int(update.effective_chat.id) if update.effective_chat else int(msg.chat_id)
    url = (url or "").strip().rstrip(").,;:'\"}]> \n\t")

    async def _send_result(text: str, **kwargs):
        await _clear_non_link_result_messages(context, chat_id)
        sent = await msg.reply_text(text, **kwargs)
        _remember_result_msg(chat_id, sent.message_id)
        return sent

    async def _send_group_link_result(text: str, **kwargs):
        sent = await msg.reply_text(text, **kwargs)
        await _replace_group_link_msg(context, chat_id, sent.message_id)
        return sent

    if not basic_verify_truemoney_link(url):
        set_latest_check_state(int(sender_id), "failed", "invalid_link")
        await _send_result("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
        return

    v = extract_truemoney_v(url)
    if not v or not is_valid_truemoney_v(v):
        set_latest_check_state(int(sender_id), "failed", "invalid_link")
        await _send_result("❌ ลิงก์ซองทรูไม่ถูกต้อง กรุณาส่งใหม่อีกครั้ง")
        return

    used_info = get_v_used_info(v)
    same_owner = bool(used_info and str(used_info.get("owner_user_id") or "") == str(sender_id))
    used_amount = 0.0
    try:
        used_amount = float((used_info or {}).get("amount") or 0)
    except Exception:
        used_amount = 0.0

    # ซองเดิมของ user เดิม
    # - ถ้ารอบก่อนตรวจจบแล้ว (success / used / not found / admin rejected) -> กันซ้ำ
    # - ถ้ายังเป็น pending/check_error จริง ๆ ค่อยปล่อยให้ flow API msg err จัดการต่อ
    if same_owner:
        result_text = str((used_info or {}).get("raw_result") or "").lower()
        resolved_words = [
            "success", "สำเร็จ",
            "used", "redeemed", "ถูกใช้", "เปิดใช้",
            "not found", "not_found", "ไม่พบซอง", "ไม่พบในระบบ",
            "admin_rejected_api_error", "admin_review_rejected",
        ]

        if any(w in result_text for w in resolved_words):
            await _send_result("⚠️ ซองนี้เคยตรวจไปแล้วนะคะ")
            return

    if not skip_processing and processing_msg is None:
        processing_msg = await msg.reply_text("⏳ กำลังตรวจสอบลิ้งค์")
        USER_PENDING_MSG_ID[chat_id] = processing_msg.message_id

    async def _close_processing_msg():
        nonlocal processing_msg
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception:
                pass
            processing_msg = None
        USER_PENDING_MSG_ID.pop(chat_id, None)

    try:
        result = await asyncio.to_thread(check_wallet, url)
    except Exception as e:
        result = {"status": "error", "message": str(e)}

    if seq is not None and not is_latest(chat_id, seq):
        try:
            if processing_msg:
                await processing_msg.delete()
        except Exception:
            pass
        USER_PENDING_MSG_ID.pop(chat_id, None)
        return

    if _wallet_is_success(result):
        await _notify_admin_payment_result(context, sender, sender_id, url, result)
        # ซองเดิมของ user เดิม ที่ตรวจซ้ำแล้ว success อีกครั้ง
        # ให้ตอบว่าเคยตรวจไปแล้ว และห้ามบวกยอดซ้ำ
        if same_owner:
            set_latest_check_state(int(sender_id), "success", str(result.get("message", "") or "success"))
            await _close_processing_msg()
            await _send_result("⚠️ ซองนี้เคยตรวจไปแล้วนะคะ")
            return

        await _run_wallet_success_flow(
            context,
            int(sender_id),
            v,
            result,
            _send_result,
            _send_group_link_result,
            _close_processing_msg,
        )
        return
# ===== MAIN FLOW (โฟลวนี้ใช้จริง ห้ามแก้มั่ว) =====
    # เคส status=error
    # - ถ้า message บอกว่าซองถูกใช้:
    #   * ไม่เคยมีประวัติ -> ตอบตามตรงว่าซองถูกใช้
    #   * เคยมีประวัติลิ้งเดิม -> ตอบว่าไม่พบยอดเงินในซอง
    # - ถ้า message ไม่ใช่ success/used -> ระบบตรวจสอบไม่สำเร็จ
    fail_text = _wallet_fail_text(result)
    if str(result.get("status", "")).lower() == "error":
        if _wallet_message_used(result) or _wallet_message_not_found(result):
            set_latest_check_state(int(sender_id), "failed", str(result.get("message", "") or result))
            # API ยืนยันแล้วว่า fail จริง ให้ถือว่าตรวจจบเหมือนซองถูกใช้/ไม่พบซอง
            # กันส่งซองเดิมซ้ำแล้ววนเช็คใหม่
            try:
                mark_v_used(v, amount=0, raw_result=result, used_at=result.get("time"), owner_user_id=int(sender_id))
            except Exception:
                pass
            await _notify_admin_payment_result(context, sender, sender_id, url, result)
            await _close_processing_msg()
            if _wallet_message_not_found(result):
                await _send_result("❌ ตรวจไม่พบซองนี้ค่ะ")
            elif same_owner:
                await _send_result("🚫 ตรวจไม่พบยอดเงินในซองค่ะ ลองส่งใหม่นะ")
            else:
                await _send_result("❌ ตรวจไม่พบ ซองนี้ถูกใช้ไปแล้วนะคะ")
            return

        latest = get_latest_check_state(int(sender_id))
        latest_kind = str(latest.get("latest_kind", "") or "").lower()
        latest_updated_at = latest.get("updated_at")
        latest_is_fresh = False
        try:
            if latest_updated_at:
                latest_is_fresh = (int(time.time()) - int(latest_updated_at)) < LATEST_EXPIRE_SEC
        except Exception:
            latest_is_fresh = False

        # เคยมี API msg err แล้ว: ห้ามอ่าน error message รอบใหม่ ให้รอแอดมิน/รอ success เท่านั้น
        if latest_kind == "check_error" and latest_is_fresh:
            await _close_processing_msg()
            await _send_result("⚠️ กำลังรอแอดมินตรวจสอบ โปรดรออัพเดทสถานะที่แชทนี้")
            return

        set_latest_check_state(int(sender_id), "check_error", str(result.get("message", "") or result))
        review_id = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO api_error_payment_reviews (user_id, sender, url, v, amount, raw_result, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    int(sender_id),
                    str(sender or ""),
                    str(url or ""),
                    str(v or ""),
                    _wallet_amount(result),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            review_id = int(cur.lastrowid)
            conn.commit()
            conn.close()
        except Exception:
            review_id = None

        reply_markup = None
        if review_id:
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("❎ no", callback_data=f"apierr:no:{review_id}"),
                InlineKeyboardButton("✅ yes", callback_data=f"apierr:yes:{review_id}"),
            ]])
        await _notify_admin_payment_result(context, sender, sender_id, url, result, reply_markup=reply_markup)
        await _close_processing_msg()
        await _send_result("↻ ระบบขัดข้อง กรุณาส่งใหม่อีกครั้งนะ")
        return

    # fail ปกติ: แยกว่าล้มเหลวก่อนหรือหลังเข้ากลุ่ม
    await _notify_admin_payment_result(context, sender, sender_id, url, result)
    current_state = get_user_payment_state(int(sender_id))
    joined_now = bool(current_state.get("joined")) or (int(sender_id) in USER_JOINED)
    try:
        member = await context.bot.get_chat_member(GROUP_CHAT_ID, int(sender_id))
        if getattr(member, "status", "") in ("member", "administrator", "creator"):
            joined_now = True
    except Exception:
        pass

    if joined_now:
        set_latest_check_state(int(sender_id), "failed_after_join", str(result.get("message", "") or result))
    else:
        set_latest_check_state(int(sender_id), "failed", str(result.get("message", "") or result))

    await _close_processing_msg()
    await _send_result(fail_text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    msg = update.effective_message
    user = update.effective_user
    chat_id = int(update.effective_chat.id) if update.effective_chat else None
    payload = " ".join(context.args).strip().lower() if getattr(context, "args", None) else ""

    # ======= 🔺จุดแก้ ticket flow🔻 =========
    if chat_id is not None and chat_id in TICKET_OPEN and payload == "menu":
        if chat_id in TICKET_MENU_WARN_SUPPRESSED:
            try:
                if msg and msg.message_id:
                    asyncio.create_task(
                        _delete_user_msg_delay(context, msg.chat_id, msg.message_id)
                    )
            except Exception:
                pass
            return
        old_warn = WARNING_MSG.get(chat_id)
        if old_warn:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
            except Exception:
                pass
        sent_warn = await context.bot.send_message(
            chat_id=chat_id,
            text="ตอนนี้คุณอยู่ในโหมดแจ้งปัญหา ต้องการปิดเพื่อทำรายการอื่นใช่หรือไม่?\n⚠️ คำเตือน: หากยืนยันปิดแอดมินจะไม่สามารถตอบข้อความได้",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("✅", callback_data="menu:ticket_confirm"),
                InlineKeyboardButton("❌", callback_data="menu:ticket_cancel"),
            ]]),
        )
        WARNING_MSG[chat_id] = sent_warn.message_id
        try:
            if msg and msg.message_id:
                asyncio.create_task(
                    _delete_user_msg_delay(context, msg.chat_id, msg.message_id)
                )
        except Exception:
            pass
        return

    if chat_id is not None and chat_id in TICKET_OPEN:
        await _notify_admin_ticket_closed_by_user(
            context,
            chat_id=chat_id,
            user=update.effective_user,
            action_text="กด /start",
        )
        await _ticket_close_with_notice(context, chat_id)
        try:
            if msg and msg.message_id:
                asyncio.create_task(
                    _delete_user_msg_delay(context, msg.chat_id, msg.message_id)
                )
        except Exception:
            pass
    if chat_id is not None:
        if payload == "menu" and user and msg and not should_send_start_menu(user.id):
            try:
                await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            except Exception:
                pass
            return
        # /start ใช้เปิดเมนู/เคลียร์ UI เท่านั้น ห้าม reset payment/join state
        await _clear_payment_ui(context, chat_id)

        old_media_ids = LAST_START_MEDIA_IDS.get(chat_id, []).copy()
        user_state = get_user_payment_state(chat_id)
        await send_guide_first_time(context, chat_id, user_state)
        await send_root_menu(chat_id, context)
        if payload == "menu" and user:
            set_user_menu_version(user.id, MENU_VERSION)
        for mid in old_media_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except:
                pass
        return
# -----------------------
# คำสั่ง /payment
# -----------------------

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """เปิดหน้าเมนูหลักโดยไม่รีเซ็ตสถานะ เหมาะสำหรับลูกค้าที่มาจาก /ticker"""
    chat = update.effective_chat
    if not chat:
        return
    if chat.type != ChatType.PRIVATE:
        return

    chat_id = int(chat.id)

    if chat_id in TICKET_OPEN:
        await _notify_admin_ticket_closed_by_user(
            context,
            chat_id=chat_id,
            user=update.effective_user,
            action_text="กด /menu",
        )
        await _ticket_close_with_notice(context, chat_id)
        try:
            if update.message and update.message.message_id:
                asyncio.create_task(
                    _delete_user_msg_delay(context, update.message.chat_id, update.message.message_id)
                )
        except Exception:
            pass

    await _clear_payment_ui(context, chat_id)
    await send_root_menu(chat_id, context)

async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    chat_id = int(update.effective_chat.id) if update.effective_chat else None
    if chat_id is not None and chat_id in TICKET_OPEN:
        old_warn = WARNING_MSG.get(chat_id)
        if old_warn:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
            except Exception:
                pass
        sent_warn = await context.bot.send_message(
            chat_id=chat_id,
            text="ตอนนี้คุณอยู่ในโหมดแจ้งปัญหา ต้องการปิดเพื่อทำรายการอื่นใช่หรือไม่?\n⚠️ คำเตือน: หากยืนยันปิดแอดมินจะไม่สามารถตอบข้อความได้",
            reply_markup=InlineKeyboardMarkup([[ 
                InlineKeyboardButton("✅", callback_data="menu:ticket_confirm"),
                InlineKeyboardButton("❌", callback_data="menu:ticket_cancel"),
            ]]),
        )
        WARNING_MSG[chat_id] = sent_warn.message_id
        try:
            if update.message and update.message.message_id:
                asyncio.create_task(
                    _delete_user_msg_delay(context, update.message.chat_id, update.message.message_id)
                )
        except Exception:
            pass
        return

    if update.message:
        await _delete_message_safe(update.message)

    await _clear_payment_ui(context, chat_id)
    try:
        await _edit_or_send_payment_page(context, int(update.effective_chat.id), source_message=None)
    except Exception as e:
        logger.exception(e)
        if chat_id is not None:
            LAST_PAYMENT_MEDIA_MSG.pop(chat_id, None)
            LAST_PAYMENT_TEXT_MSG.pop(chat_id, None)
        text_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=PAY_HELP_TEXT,
            reply_markup=_menu_back_keyboard([[InlineKeyboardButton("🔎 ดูยอดเงิน", callback_data="menu:check_balance")]]),
            parse_mode="HTML",
        )
        if chat_id is not None:
            LAST_PAYMENT_TEXT_MSG[chat_id] = text_msg.message_id
# -----------------------
# รับข้อความ (ลิงก์)
# -----------------------
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    chat = update.effective_chat
    if not user or not msg or not chat:
        return
    if user.id != ADMIN_ID:
        return
    if chat.type != ChatType.PRIVATE or int(chat.id) != int(ADMIN_ID):
        return
    if not context.args:
        await msg.reply_text("ใช้แบบนี้: /ban 1234xxx")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        await msg.reply_text("user id ไม่ถูกต้อง")
        return
    add_banned_user(uid)
    BANNED_NOTICE_SENT.discard(uid)
    await msg.reply_text(f"แบน {uid} เรียบร้อย 😈")


async def create_single_use_invite(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """สร้างลิ้งเชิญเข้ากลุ่มแบบใช้ได้ 1 คน และหมดอายุอัตโนมัติ"""
    try:
        expire_ts = int(time.time()) + 900  # 15 นาที
        invite = await context.bot.create_chat_invite_link(
            chat_id=GROUP_CHAT_ID,
            member_limit=1,
            expire_date=expire_ts,
        )
        return invite.invite_link
    except Exception as e:
        logger.exception("Failed to create invite link: %s", e)
        if GROUP_LINK_FALLBACK:
            return GROUP_LINK_FALLBACK
        return None


async def revoke_invite_if_possible(context: ContextTypes.DEFAULT_TYPE, invite_url: str | None):
    """ปิดลิ้งเชิญทิ้งทันที ถ้าปิดได้"""
    if not invite_url:
        return
    try:
        await context.bot.revoke_chat_invite_link(
            chat_id=GROUP_CHAT_ID,
            invite_link=str(invite_url),
        )
    except Exception:
        pass


async def ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """เริ่มโหมด ticket: หลังจากนี้ข้อความของลูกค้าจะถูกส่งหาแอดมิน"""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return

    if chat.type != ChatType.PRIVATE:
        return

    await _delete_message_safe(msg)
    chat_id = int(chat.id)
    old_warn = WARNING_MSG.get(chat_id)
    if old_warn:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
        except Exception:
            pass
        WARNING_MSG.pop(chat_id, None)
    await _clear_payment_ui(context, chat_id)
    _normal_flow_reset(chat_id)
    TICKET_MENU_WARN_SUPPRESSED.discard(chat_id)

    raw = (msg.text or "").strip()
    parts = raw.split(maxsplit=1)
    initial = parts[1].strip() if len(parts) > 1 else ""

    if chat_id not in TICKET_OPEN:
        TICKET_OPEN.add(chat_id)
        TICKET_HAS_USER_MESSAGE.discard(chat_id)
        touch_ticket(context, chat_id)
        sent_ack = await msg.reply_text(TICKET_ACK_TEXT)
        TICKET_OPEN_ACK_MSG[chat_id] = sent_ack.message_id

        u = update.effective_user
        who = f"@{u.username}" if u and u.username else (u.full_name if u else "unknown")
        sent0 = await context.bot.send_message(
            chat_id=get_admin_notify_chat_id(),
            text=(f"📩 มีคนเปิด Ticket\n"
                  f"ChatID: {chat_id}\n"
                  f"User: {who}")
        )
        TICKET_MAP[sent0.message_id] = chat_id
        _record_admin_msg(chat_id, sent0.message_id)
        _ticket_note_open(chat_id, sent0.message_id)

    if initial:
        disable_ticket_autoclose(chat_id)
        await _ticket_forward_to_group(context, msg)


async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/close (แอดมินเท่านั้น): ใช้แบบ reply ข้อความ ticket ในแชทแอดมิน"""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return

    if user.id != ADMIN_ID:
        return
    allowed_admin_chats = {int(ADMIN_ID), int(get_admin_notify_chat_id()), int(TICKET_FORWARD_GROUP_ID), int(get_ticket_forward_chat_id())}
    if int(chat.id) not in allowed_admin_chats:
        return
    if not msg.reply_to_message:
        return

    replied_id = msg.reply_to_message.message_id
    user_chat_id = TICKET_MAP.get(replied_id)
    if not user_chat_id:
        return

    # เก็บข้อความ /close ของแอดไว้ก่อน เผื่อลบได้ตอนล้าง ticket
    user_chat_id = int(user_chat_id)
    _record_admin_msg(user_chat_id, msg.message_id)
    if user_chat_id in TICKET_OPEN:
        await close_ticket_internal(context, user_chat_id, reason="admin")
    else:
        await _ticket_close_silent(context, user_chat_id)
        try:
            await _clear_admin_ticket_messages(context, user_chat_id)
        except Exception:
            pass

    try:
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except Exception:
        pass


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await ban_message_if_needed(update, context):
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg:
        return

    log_chat_message(
        "in",
        msg.chat_id,
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        full_name=getattr(user, "full_name", None),
        msg_id=getattr(msg, "message_id", None),
        msg_type="text",
        text=(msg.text or msg.caption or ""),
    )

    if msg.chat.type != ChatType.PRIVATE:
        return

    if await handle_banned_user(update, context):
        return

    text_msg = (msg.text or "").strip()
    chat_id = int(update.effective_chat.id) if update.effective_chat else int(msg.chat_id)

    if chat_id in TICKET_OPEN:
        if text_msg.startswith("/"):
            cmd = text_msg.split()[0].lower()
            if cmd not in {"/menu", "/ticker"}:
                old_warn = WARNING_MSG.get(chat_id)
                if old_warn:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=old_warn)
                    except Exception:
                        pass
                sent_warn = await context.bot.send_message(
                    chat_id=chat_id,
                    text="ตอนนี้คุณอยู่ในโหมดแจ้งปัญหา ต้องการปิดเพื่อทำรายการอื่นใช่หรือไม่?\n\n⚠️ คำเตือน: หากยืนยันปิดแอดมินจะไม่สามารถตอบข้อความได้",
                    reply_markup=InlineKeyboardMarkup([[ 
                        InlineKeyboardButton("✅", callback_data="menu:ticket_confirm"),
                        InlineKeyboardButton("❌", callback_data="menu:ticket_cancel"),
                    ]]),
                )
                WARNING_MSG[chat_id] = sent_warn.message_id
            return

        disable_ticket_autoclose(chat_id)
        await _ticket_forward_to_group(context, msg)
        count = _ticket_note_message(chat_id)
        if count >= 3 and chat_id not in TICKET_REPEAT_NOTICE_SENT:
            try:
                await msg.reply_text("📩 ข้อความของคุณถูกส่งถึงแอดมินแล้ว\nสถานะ : รอตรวจสอบ...")
            except Exception:
                pass
            TICKET_REPEAT_NOTICE_SENT.add(chat_id)
        return

    if not text_msg:
        return

    url = extract_first_url_from_message(msg)
    if not url:
        if _normal_flow_in_cooldown(chat_id):
            return
        await handle_normal_flow_step(update, context)
        return

    url = url.strip().rstrip(').,;:\'"}]> \n\t')
    if not basic_verify_truemoney_link(url):
        try:
            await _clear_non_link_result_messages(context, int(msg.chat_id))
        except Exception:
            pass
        sent = await msg.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
        _remember_result_msg(int(msg.chat_id), sent.message_id)
        return

    v = extract_truemoney_v(url)
    if not v or not is_valid_truemoney_v(v):
        try:
            await _clear_non_link_result_messages(context, int(msg.chat_id))
        except Exception:
            pass
        sent = await msg.reply_text("❌ ลิงก์ซองทรูไม่ถูกต้อง กรุณาส่งใหม่อีกครั้ง")
        _remember_result_msg(int(msg.chat_id), sent.message_id)
        return

    sender, sender_id = sender_label(update)
    try:
        unique_total, added_total = register_unique_submitter(int(sender_id))
        admin_head = f"📩 มีคนส่งลิงก์ซองทรูมันนี่ (x{unique_total})+{added_total}"
    except Exception:
        admin_head = "📩 มีคนส่งลิงก์ซองทรูมันนี่"

    await context.bot.send_message(
        chat_id=get_admin_notify_chat_id(),
        text=(
            f"{admin_head}\n"
            f"ผู้ส่ง: {sender}\n"
            f"User ID: {sender_id}\n"
            f"ลิงก์: {url}"
        )
    )

    seq = await bump_latest_request(context, int(chat_id))
    await _process_wallet_link(update, context, msg, url, sender, sender_id, seq=seq)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await ban_message_if_needed(update, context):
        return
    if not is_private(update):
        return

    msg = update.message
    if not msg or not msg.photo:
        return

    chat_id = int(update.effective_chat.id) if update.effective_chat else int(msg.chat_id)
    if chat_id in TICKET_OPEN:
        disable_ticket_autoclose(chat_id)
        await _ticket_forward_to_group(context, msg)

        count = _ticket_note_message(chat_id)

        if count >= 3 and chat_id not in TICKET_REPEAT_NOTICE_SENT:
            try:
                await msg.reply_text("📩 ข้อความของคุณถูกส่งถึงแอดมินแล้ว\n\nสถานะ : รอตรวจสอบ...")
            except Exception:
                pass
            TICKET_REPEAT_NOTICE_SENT.add(chat_id)
        return

    if await handle_banned_user(update, context):
        return

    sender, sender_id = sender_label(update)

    decoded = []
    try:
        file = await msg.photo[-1].get_file()
        img_bytes = await file.download_as_bytearray()
        decoded = try_decode_qr_from_image_bytes(bytes(img_bytes))
    except Exception as e:
        logger.info(f"QR decode step failed: {e}")
        decoded = []

    caption_text = (msg.caption or "").strip()
    caption_url = extract_first_url_from_message(msg)
    caption_url = caption_url.strip().rstrip(").,;:'\"}] ") if caption_url else None
# ===== ไม่มั่นใจ อย่าพึ่งลบ =====
    spam_hit = should_ban_text(caption_text)
    if spam_hit.matched and not decoded and not caption_url:
        try:
            await msg.delete()
        except Exception:
            pass
        await _clear_non_link_result_messages(context, chat_id)
        sent = await context.bot.send_message(
            chat_id=msg.chat_id,
            text=(
                "❌ ไม่พบ QR code รบกวนส่งรูปที่มีคิวอาร์โค้ด/ภาพชัดๆ อีกครั้งนะ"
            )
        )
        _remember_result_msg(chat_id, sent.message_id)
        return

    latest_qr = decoded[-1] if decoded else (caption_url if caption_url else None)
    latest_true = None
    if latest_qr and extract_truemoney_v_strict(latest_qr):
        latest_true = latest_qr

    if not latest_qr:
        try:
            await msg.delete()
        except Exception:
            pass
        await _clear_non_link_result_messages(context, chat_id)
        sent = await context.bot.send_message(
            chat_id=msg.chat_id,
            text=(
                "❌ ไม่พบ QR code รบกวนส่งรูปที่มีคิวอาร์โค้ด/ภาพชัดๆ อีกครั้งนะ"
            )
        )
        _remember_result_msg(chat_id, sent.message_id)
        return

    if latest_true:
        unique_total, added_total = register_unique_submitter(int(sender_id))
        await context.bot.send_message(
            chat_id=get_admin_notify_chat_id(),
            text=(
                f"🧾 มีคนส่งรูปหลักฐาน/QR (x{unique_total})+{added_total}\n"
                f"ผู้ส่ง: {sender}\n"
                f"User ID: {sender_id}\n"
                f"ผลสแกน: ✅ พบลิงก์ทรู"
            )
        )
        await context.bot.forward_message(
            chat_id=get_admin_notify_chat_id(),
            from_chat_id=msg.chat_id,
            message_id=msg.message_id
        )

    seq = await bump_latest_request(context, int(chat_id))

    processing_msg = await msg.reply_text("⏳ กำลังตรวจสอบ รอสักครู่นะคะ…")
    USER_PENDING_MSG_ID[chat_id] = processing_msg.message_id
    await asyncio.sleep(5)

    if not is_latest(chat_id, seq):
        return

    if not latest_true:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        USER_PENDING_MSG_ID.pop(chat_id, None)
        await _clear_non_link_result_messages(context, chat_id)
        sent = await msg.reply_text(
            "❌ ไม่พบลิงก์ซองทรูใน QR กรุณาส่งรูปที่มีคิวอาร์โค้ดซองทรูที่อ่านได้ชัดเจนอีกครั้ง"
        )
        _remember_result_msg(chat_id, sent.message_id)
        return

    await _process_wallet_link(update, context, msg, latest_true, sender, sender_id, skip_processing=True, seq=seq, processing_msg=processing_msg)

TRUE_URL_RE = re.compile(
    r'https?://gift\.truemoney\.com/campaign/\?v=[A-Za-z0-9]{34,39}',
    re.IGNORECASE,
)

def extract_truemoney_url(text: str) -> str | None:
    if not text:
        return None

    compact = re.sub(r'\s+', '', str(text))

    m = TRUE_URL_RE.search(compact)
    if m:
        return m.group(0)

    m = re.search(r'v=([A-Za-z0-9]{34,39})', compact, re.IGNORECASE)
    if m:
        return f"https://gift.truemoney.com/campaign/?v={m.group(1)}"

    return None

async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: Reply ข้อความที่มีลิ้งซองทรู แล้วปลดย้อนทั้ง used_v + pending + ยอดสะสม"""
    user = update.effective_user
    msg = update.effective_message

    if not user or user.id != ADMIN_ID:
        await msg.reply_text("⛔ คำสั่งนี้สำหรับแอดมินเท่านั้น")
        return

    if not msg or not msg.reply_to_message:
        await msg.reply_text("❌ ต้อง Reply ข้อความหลังบ้านที่มีลิงก์ซองทรู แล้วค่อยพิมพ์ /unlock")
        return

    replied = msg.reply_to_message
    replied_text = (replied.text or replied.caption or "").strip()

    url = extract_truemoney_url(replied_text)
    if not url:
        await msg.reply_text("❌ หาไม่เจอลิงก์ซองทรูในข้อความที่ Reply")
        return

    v = extract_truemoney_v_strict(url)
    if not v:
        await msg.reply_text("❌ ลิงก์นี้ไม่ใช่ลิงก์ซองทรูที่ถูกต้อง ปลดไม่ได้")
        return

    info = get_v_used_info(v)

    try:
        delete_v_used(v)
    except Exception as e:
        logger.exception("delete_v_used failed: %s", e)
        await msg.reply_text(f"⚠️ ลบ used_v ไม่สำเร็จ: {e}")
        return

    try:
        unmark_link_pending(url)
    except Exception:
        pass

    rolled_back_text = ""
    try:
        if info and info.get("owner_user_id") and info.get("amount"):
            new_total = subtract_user_total(int(info["owner_user_id"]), float(info["amount"]))
            rolled_back_text = f"\n↩️ ย้อนยอดสะสมแล้ว เหลือ {int(new_total)} บาท"
    except Exception as e:
        logger.exception("subtract_user_total failed: %s", e)
        rolled_back_text = "\n⚠️ ปลด used_v แล้ว แต่ย้อนยอดสะสมไม่สำเร็จ"

    await msg.reply_text("✅ ปลดล็อกแล้ว ส่งใหม่ได้ทันที" + rolled_back_text)


async def on_admin_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    # =========================
    # /latest (admin check)
    # =========================
    raw = (msg.text or "").strip()
    if raw == "/latest" and msg.reply_to_message:
        user_chat_id = None
        target = msg.reply_to_message

        if getattr(target, "forward_from", None):
            user = target.forward_from
            user_chat_id = user.id
            name = user.full_name or "-"
            username = f"@{user.username}" if user.username else "-"
        else:
            try:
                user_chat_id = int((target.text or "").split("User ID: ")[1].split("\n")[0])
            except Exception:
                user_chat_id = None
            name = "-"
            username = "-"

        if not user_chat_id:
            await msg.reply_text("❌ หา user ไม่เจอ")
            return

        state = get_user_payment_state(user_chat_id)
        balance, status_text, latest_status, update_time = await _build_balance_snapshot(context, user_chat_id)

        latest_v = state.get("last_v") if state else None

        text = (
            f"📊 User latest status\n"
            f"Name: {name}\n"
            f"Id: {user_chat_id}\n"
            f"Username: {username}\n\n"
            f"💰 Balance: {format_money(balance)}\n"
            f"💳 Status: {status_text}\n"
        )

        if latest_status:
            text += f"♻️ Latest: {latest_status}\n"
        elif latest_v:
            text += f"♻️ Latest: {latest_v}\n"

        text += f"\n🕒 update: {update_time}"

        await msg.reply_text(text)
        return

    """แอดมิน Reply ข้อความ ticket ในแชทแอดมิน -> ส่งกลับไปหาลูกค้า"""
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return

    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    allowed_admin_chats = {int(ADMIN_ID), int(get_admin_notify_chat_id()), int(TICKET_FORWARD_GROUP_ID), int(get_ticket_forward_chat_id())}
    if int(msg.chat_id) not in allowed_admin_chats:
        return

    replied_id = msg.reply_to_message.message_id
    user_chat_id = TICKET_MAP.get(replied_id)
    if not user_chat_id:
        return

    user_chat_id = int(user_chat_id)

    # เก็บข้อความที่แอดตอบไว้ เพื่อลบตอนปิด ticket
    _record_admin_msg(user_chat_id, msg.message_id)

    raw = (msg.text or "").strip()
    if raw == "/close":
        if user_chat_id in TICKET_OPEN:
            await close_ticket_internal(context, user_chat_id, reason="admin")
        else:
            await _ticket_close_silent(context, user_chat_id)
            try:
                await _clear_admin_ticket_messages(context, user_chat_id)
            except Exception:
                pass
        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except Exception:
            pass
        return

    if user_chat_id in TICKET_OPEN:
        touch_ticket(context, user_chat_id)

    # 1) ถ้าแอดตอบเป็นข้อความธรรมดา/มี caption
    reply_text = msg.text or msg.caption
    if reply_text:
        sent = await context.bot.send_message(chat_id=user_chat_id, text=reply_text)
        log_chat_message("out", user_chat_id, user_id=0, username="bot", full_name="bot", msg_id=sent.message_id, msg_type="text", text=reply_text)
        return

    # 2) ถ้าแอด reply เป็นรูป/ไฟล์/สื่อ ให้ copy กลับไปหาลูกค้า
    try:
        copied = await context.bot.copy_message(
            chat_id=user_chat_id,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        log_chat_message("out", user_chat_id, user_id=0, username="bot", full_name="bot", msg_id=getattr(copied, "message_id", None), msg_type="copy", text="(copied admin reply)")
    except Exception:
        pass


async def check_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ตรวจคนเข้ากลุ่มจากลิงก์ที่บอทส่งไว้: ลิงก์ไหนมีคนเข้า = หักยอดเจ้าของลิงก์ 899"""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.id != GROUP_CHAT_ID:
        return

    new_members = getattr(msg, "new_chat_members", None) or []
    if not new_members:
        return

    await asyncio.sleep(2)
    _purge_expired_allows()

    inv = getattr(msg, "invite_link", None)
    invite_url = None
    try:
        invite_url = getattr(inv, "invite_link", None)
    except Exception:
        invite_url = None

    def _owner_from_invite() -> tuple[int | None, str | None, str]:
        # หลักจริง: Telegram ส่ง invite_url มา ให้เทียบกับ ledger ลิงก์ทุกใบก่อน
        if invite_url:
            pending = get_pending_invite(str(invite_url))
            if pending and not pending.get("used"):
                return int(pending["owner_user_id"]), str(invite_url), str(pending.get("balance_bucket") or "pre")
            owner = PENDING_INVITE_OWNER.get(str(invite_url))
            if owner:
                return int(owner), str(invite_url), "pre"

        # fallback เดิม: ถ้า Telegram ไม่ส่ง invite_url และมี pending ค้างแค่อันเดียว ค่อยใช้ใบนั้น
        if len(PENDING_INVITE_OWNER) == 1:
            try:
                only_invite, only_owner = next(iter(PENDING_INVITE_OWNER.items()))
                pending = get_pending_invite(str(only_invite))
                bucket = str((pending or {}).get("balance_bucket") or "pre")
                return int(only_owner), str(only_invite), bucket
            except Exception:
                return None, None, "pre"
        return None, None, "pre"

    async def _owner_is_member(owner_id: int) -> bool:
        try:
            member = await context.bot.get_chat_member(GROUP_CHAT_ID, int(owner_id))
            return getattr(member, "status", "") in ("member", "administrator", "creator")
        except Exception:
            state = get_user_payment_state(int(owner_id))
            return bool(state.get("joined")) or (int(owner_id) in USER_JOINED)

    async def _finalize_invite_used(owner_id: int, used_invite: str | None, joined_user_id: int, balance_bucket: str = "pre"):
        # มีคนเข้าจากลิงก์ที่บอทส่งให้แล้ว = หักยอดเจ้าของลิงก์ 899 หนึ่งรอบ
        try:
            # ใช้สิทธิ์ลิงก์เมื่อไหร่ หักจากยอดหลักของเจ้าของลิงก์เสมอ
            subtract_user_total(int(owner_id), float(VIP_MIN_AMOUNT))
        except Exception:
            pass

        owner_joined = await _owner_is_member(int(owner_id))
        if owner_joined:
            USER_JOINED.add(int(owner_id))
        else:
            USER_JOINED.discard(int(owner_id))

        # payment_sent เป็นสถานะของ "รอบลิงก์ค้าง" พอมีคนใช้ลิงก์แล้วให้ปิดรอบนั้น
        USER_PAYMENT_SENT.discard(int(owner_id))
        if int(joined_user_id) == int(owner_id):
            _consume_user_allow(int(owner_id))

        upsert_user_payment_state(
            int(owner_id),
            payment_sent=False,
            joined=owner_joined,
            # ถ้าเจ้าของลิงก์ไม่ได้อยู่ในกลุ่ม แต่มีคนใช้ลิงก์ไปแล้ว
            # ให้ล้างไพ่รอบนี้เป็น "ไม่พบรายการ" ไม่ใช่ "รอการเข้ากลุ่ม"
            invalidated=(not owner_joined),
            active_invite="",
        )
        set_latest_check_state(
            int(owner_id),
            "success" if owner_joined else "invite_used",
            "joined" if owner_joined else "used",
        )

        if used_invite:
            PENDING_INVITE_OWNER.pop(str(used_invite), None)
            mark_pending_invite_used(str(used_invite), int(joined_user_id))
            mark_web_payment_invite_joined(str(used_invite), int(joined_user_id))
            await revoke_invite_if_possible(context, used_invite)

    for u in new_members:
        if not u:
            continue
        if int(u.id) == int(ADMIN_ID):
            continue

        owner_user_id, used_invite, balance_bucket = _owner_from_invite()

        # เคสหลัก: ลิงก์ที่บอทส่งไว้มีคนเข้าแล้ว หักยอดเจ้าของลิงก์ ไม่เอาสถานะเข้าออกของคนเข้ามาแทนสถานะคนซื้อ
        if owner_user_id:
            record_group_member_event(
                event_type="join",
                actor_user_id=int(u.id),
                actor_username=getattr(u, "username", "") or "",
                actor_full_name=getattr(u, "full_name", "") or "",
                owner_user_id=int(owner_user_id),
                invite_link=str(used_invite or ""),
                amount=float(VIP_MIN_AMOUNT),
                balance_before=float(get_user_total(int(owner_user_id)) or 0.0),
                note=f"balance_bucket={balance_bucket}",
            )
            await _finalize_invite_used(int(owner_user_id), used_invite, int(u.id), balance_bucket)
            continue
        if invite_url:
            record_group_member_event(
                event_type="join",
                actor_user_id=int(u.id),
                actor_username=getattr(u, "username", "") or "",
                actor_full_name=getattr(u, "full_name", "") or "",
                invite_link=str(invite_url),
                note="invite_url without owner match",
            )
            mark_web_payment_invite_joined(str(invite_url), int(u.id))
            await revoke_invite_if_possible(context, str(invite_url))
            continue

        # fallback เดิม: ไม่มี invite_url ให้จับ แต่ user คนนี้ยังอยู่ allow-list และมี active_invite ของตัวเอง
        if _is_user_allowed(u.id):
            state = get_user_payment_state(int(u.id))
            active_invite = state.get("active_invite")
            if active_invite:
                record_group_member_event(
                    event_type="join",
                    actor_user_id=int(u.id),
                    actor_username=getattr(u, "username", "") or "",
                    actor_full_name=getattr(u, "full_name", "") or "",
                    owner_user_id=int(u.id),
                    invite_link=str(active_invite),
                    amount=float(VIP_MIN_AMOUNT),
                    balance_before=float(get_user_total(int(u.id)) or 0.0),
                    note="active_invite fallback",
                )
                await _finalize_invite_used(int(u.id), str(active_invite), int(u.id), "pre")
                continue

        await asyncio.sleep(1)
        owner_user_id, used_invite, balance_bucket = _owner_from_invite()
        if owner_user_id:
            record_group_member_event(
                event_type="join",
                actor_user_id=int(u.id),
                actor_username=getattr(u, "username", "") or "",
                actor_full_name=getattr(u, "full_name", "") or "",
                owner_user_id=int(owner_user_id),
                invite_link=str(used_invite or ""),
                amount=float(VIP_MIN_AMOUNT),
                balance_before=float(get_user_total(int(owner_user_id)) or 0.0),
                note=f"delayed balance_bucket={balance_bucket}",
            )
            await _finalize_invite_used(int(owner_user_id), used_invite, int(u.id), balance_bucket)
            continue
        if invite_url:
            record_group_member_event(
                event_type="join",
                actor_user_id=int(u.id),
                actor_username=getattr(u, "username", "") or "",
                actor_full_name=getattr(u, "full_name", "") or "",
                invite_link=str(invite_url),
                note="delayed invite_url without owner match",
            )
            mark_web_payment_invite_joined(str(invite_url), int(u.id))
            await revoke_invite_if_possible(context, str(invite_url))
            continue

        if _is_user_allowed(u.id):
            state = get_user_payment_state(int(u.id))
            active_invite = state.get("active_invite")
            if active_invite:
                record_group_member_event(
                    event_type="join",
                    actor_user_id=int(u.id),
                    actor_username=getattr(u, "username", "") or "",
                    actor_full_name=getattr(u, "full_name", "") or "",
                    owner_user_id=int(u.id),
                    invite_link=str(active_invite),
                    amount=float(VIP_MIN_AMOUNT),
                    balance_before=float(get_user_total(int(u.id)) or 0.0),
                    note="delayed active_invite fallback",
                )
                await _finalize_invite_used(int(u.id), str(active_invite), int(u.id), "pre")
                continue

        # ไม่มี pending ของบอทจริง ๆ ถึงค่อยเตะออก ไม่ไปยุ่งสถานะของคนซื้อคนอื่น
        try:
            record_group_member_event(
                event_type="rejected_join",
                actor_user_id=int(u.id),
                actor_username=getattr(u, "username", "") or "",
                actor_full_name=getattr(u, "full_name", "") or "",
                invite_link=str(invite_url or ""),
                note="no pending invite or active allow",
            )
            await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=u.id)
            await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=u.id)
        except Exception:
            pass


async def check_group_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.id != GROUP_CHAT_ID:
        return

    left_user = getattr(msg, "left_chat_member", None)
    if not left_user:
        return
    if int(left_user.id) == int(ADMIN_ID):
        return

    state = get_user_payment_state(int(left_user.id))
    try:
        left_total_paid = float(get_user_total(int(left_user.id)) or 0)
    except Exception:
        left_total_paid = 0.0
    record_group_member_event(
        event_type="left",
        actor_user_id=int(left_user.id),
        actor_username=getattr(left_user, "username", "") or "",
        actor_full_name=getattr(left_user, "full_name", "") or "",
        owner_user_id=int(left_user.id),
        amount=0.0,
        balance_before=left_total_paid,
        balance_after=left_total_paid,
        note="left_chat_member",
    )
    mark_web_payment_member_left(int(left_user.id))
    if state.get("joined") or state.get("payment_sent") or state.get("active_invite"):
        mark_link_invalid_for_user(int(left_user.id))
        upsert_user_payment_state(
            int(left_user.id),
            joined=False,
            payment_sent=False,
            invalidated=True,
        )
        USER_JOINED.discard(int(left_user.id))
        USER_PAYMENT_SENT.discard(int(left_user.id))
        try:
            await context.bot.send_message(
                chat_id=int(left_user.id),
                text="🚫 ลิ้งค์เสีย กดปุ่มแจ้งปัญหา เพื่อติดต่อแอดมิน",
            )
        except Exception:
            pass


async def check_status_from_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ให้แอด Reply ข้อความไหนก็ได้ในหลังบ้านเพื่อเช็คสถานะจริง; ถ้าอยู่ใน ticket ให้ส่งกลับหาลูกค้าด้วย"""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return

    if int(user.id) != int(ADMIN_ID):
        return

    allowed_chat_ids = {int(ADMIN_ID), int(get_admin_notify_chat_id()), int(TICKET_FORWARD_GROUP_ID), int(get_ticket_forward_chat_id())}
    if int(chat.id) not in allowed_chat_ids:
        return

    if not msg.reply_to_message:
        await msg.reply_text("ใช้ /check โดย Reply ข้อความหลังบ้านที่ต้องการเช็ค")
        return

    # พยายามหา user_chat_id จากข้อความที่ reply อยู่ก่อน
    user_chat_id = TICKET_MAP.get(int(msg.reply_to_message.message_id))
    ticket_found = bool(user_chat_id)

    # ถ้ายังไม่เจอ ให้ไล่จากข้อความที่ reply chain ย้อนขึ้นไป
    cursor = msg.reply_to_message
    guard = 0
    while not user_chat_id and cursor and guard < 30:
        try:
            cursor = getattr(cursor, "reply_to_message", None)
        except Exception:
            cursor = None
        if cursor:
            user_chat_id = TICKET_MAP.get(int(cursor.message_id))
            if user_chat_id:
                ticket_found = True
        guard += 1

    # ถ้ายังไม่เจอจาก chain ให้ลองดึงจากข้อความที่มี "ChatID: ..."
    if not user_chat_id:
        probe_messages = []
        try:
            probe_messages.append(msg.reply_to_message.text or msg.reply_to_message.caption or "")
        except Exception:
            pass
        if cursor:
            try:
                probe_messages.append(cursor.text or cursor.caption or "")
            except Exception:
                pass

        import re as _re
        for probe in probe_messages:
            m = _re.search(r'ChatID\s*:\s*(-?\d+)', probe or "")
            if m:
                try:
                    user_chat_id = int(m.group(1))
                except Exception:
                    user_chat_id = None
                break

    if not user_chat_id:
        await msg.reply_to_message.reply_text(
            "❌ หา ticket / ChatID ของลูกค้าไม่เจอในข้อความนี้",
            disable_web_page_preview=True,
        )
        return

    amount, status, latest_status, update_time = await _build_balance_snapshot(context, int(user_chat_id))

    try:
        member = await context.bot.get_chat_member(GROUP_CHAT_ID, int(user_chat_id))
        in_group = getattr(member, "status", "") in ("member", "administrator", "creator")
    except Exception:
        in_group = False

    admin_text = (
        "📊 สถานะลูกค้า\n\n"
        f"ChatID: {user_chat_id}\n"
        + build_balance_text(amount, status, latest_status, update_time)
        + "\n"
        + f"👥 In group: {'yes' if in_group else 'no'}"
    )

    # ตอบกลับติดกับข้อความที่แอดกำลังกด /check อยู่
    await msg.reply_to_message.reply_text(
        admin_text,
        disable_web_page_preview=True
    )

    # ถ้าเป็นข้อความใน ticket จริง ค่อยส่งกลับไปหาลูกค้าด้วย
    if ticket_found:
        try:
            await context.bot.send_message(
                chat_id=int(user_chat_id),
                text=build_balance_text(amount, status, latest_status, update_time),
                disable_web_page_preview=True,
            )
        except Exception:
            pass

# =================
# 9 รูปภาพ
# ==========
async def send_guide_first_time(context, chat_id, user_state):
    if user_state.get("guide_sent"):
        return

    media = [
        InputMediaPhoto(open("ex1.jpg","rb")),
        InputMediaPhoto(open("ex12.jpg","rb")),
        InputMediaPhoto(open("ex123.jpg","rb")),
        InputMediaPhoto(open("ex1234.jpg","rb")),
        InputMediaPhoto(open("ex12345.jpg","rb")),
        InputMediaPhoto(open("ex123456.jpg","rb")),
        InputMediaPhoto(open("ex1234567.jpg","rb")),
        InputMediaPhoto(open("ex12345678.jpg","rb")),
        InputMediaPhoto(open("ex123456789.jpg","rb")),
    ]
    media_msgs = await context.bot.send_media_group(chat_id=chat_id, media=media)
    LAST_START_MEDIA_IDS[chat_id] = [m.message_id for m in media_msgs]
    user_state["guide_sent"] = True


async def gen_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = generate_key()
        await update.message.reply_text(f"ผลลัพธ์:\n{result}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def check_link(update, context):
    try:
        raw_text = (update.message.text or "").strip()
        link = raw_text.replace("/tw ", "", 1).strip()
        if not link:
            try:
                await _clear_non_link_result_messages(context, int(update.effective_chat.id))
            except Exception:
                pass
            sent = await update.message.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
            _remember_result_msg(int(update.effective_chat.id), sent.message_id)
            return

        wait_msg = await update.message.reply_text("⏳ กำลังตรวจสอบลิ้งค์")
        result = await asyncio.to_thread(check_wallet, link)
        try:
            await wait_msg.delete()
        except Exception:
            pass

        if _wallet_is_success(result):
            amount = _wallet_amount(result)
            if amount >= VIP_MIN_AMOUNT:
                await update.message.reply_text(
                    "💎 JOIN GROUP VIP\n"
                    f"💰 Balance: {format_money(amount)}\n"
                    "━━━━━━━━━━━━━━\n"
                    f"✅ {VIP_LINK}"
                )
            else:
                await update.message.reply_text(
                    "⚠️ ตรวจพบยอดเงินไม่พอค่ะ\n"
                    f"💰 Balance: {format_money(amount)}/{VIP_MIN_AMOUNT}"
                )
        else:
            await update.message.reply_text(_wallet_fail_text(result))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def _delete_user_msg_delay(context, chat_id: int, message_id: int):
    try:
        await asyncio.sleep(2)
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
    except:
        pass

# -----------------------
# Recovery promote admin
# ใช้กรณีแอคหลักบิน แต่บอทยังเป็นแอดมินอยู่ในแชนแนล
# เงื่อนไข: บอทต้องมีสิทธิ์ Add New Admins / can_promote_members
# -----------------------
RECOVERY_ADMIN_USER_ID = 8679564018
RECOVERY_PROMOTE_CHAT_IDS = [-1003974593385, -1003745031284]


async def promote_recovery_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message

    if not user:
        return

    # ให้เฉพาะแอดเดิม หรือไอดีใหม่ที่ต้องการกู้สิทธิ์ สั่งได้
    if int(user.id) not in {int(ADMIN_ID), int(RECOVERY_ADMIN_USER_ID)}:
        return

    lines = ["🔧 เริ่มกู้สิทธิ์แอดมิน..."]

    for chat_id in RECOVERY_PROMOTE_CHAT_IDS:
        try:
            # เช็คสิทธิ์บอทก่อน จะได้รู้ว่าติดตรงไหน
            bot_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
            can_promote = bool(getattr(bot_member, "can_promote_members", False))

            if not can_promote:
                lines.append(f"❌ {chat_id}: บอทไม่มีสิทธิ์ Add New Admins / can_promote_members")
                continue

            await context.bot.promote_chat_member(
                chat_id=chat_id,
                user_id=RECOVERY_ADMIN_USER_ID,

                # สิทธิ์หลัก
                can_manage_chat=True,
                can_change_info=True,
                can_invite_users=True,
                can_promote_members=True,

                # สิทธิ์สำหรับ channel
                can_post_messages=True,
                can_edit_messages=True,
                can_delete_messages=True,

                # สิทธิ์สำหรับ group/supergroup ถ้าแชนแนลนั้นเป็นกลุ่ม
                can_restrict_members=True,
                can_pin_messages=True,
                can_manage_topics=True,

                # สิทธิ์อื่น ๆ
                can_manage_video_chats=True,
            )

            try:
                await context.bot.set_chat_administrator_custom_title(
                    chat_id=chat_id,
                    user_id=RECOVERY_ADMIN_USER_ID,
                    custom_title="OWNER",
                )
            except Exception:
                # ตั้งฉายาไม่ได้ไม่เป็นไร สิทธิ์หลัก promote สำคัญกว่า
                pass

            lines.append(f"✅ {chat_id}: เพิ่มแอดมินให้ {RECOVERY_ADMIN_USER_ID} แล้ว")

        except BadRequest as e:
            err = str(e)
            if "USER_NOT_PARTICIPANT" in err or "user not found" in err.lower():
                lines.append(f"⚠️ {chat_id}: ไอดีนี้ยังไม่ได้อยู่ในแชนแนล/บอทหา user ไม่เจอ")
            elif "not enough rights" in err.lower() or "have no rights" in err.lower():
                lines.append(f"❌ {chat_id}: สิทธิ์บอทไม่พอสำหรับเพิ่มแอดมิน")
            else:
                lines.append(f"❌ {chat_id}: {err}")
        except Exception as e:
            lines.append(f"❌ {chat_id}: {type(e).__name__}: {e}")

    if msg:
        try:
            await msg.reply_text("\n".join(lines))
        except Exception:
            pass


def main():
    if not TOKEN:
        raise RuntimeError("ไม่พบ BOT_TOKEN ใน environment (export BOT_TOKEN ก่อนรัน)")

    init_used_v_db()
    init_unique_submitters_db()
    bootstrap_unique_submitters_from_existing_state()
    init_chatlog_db()
    init_menu_state_db()
    init_random_game_db()
    init_admin_notify_db()
    load_persisted_payment_state()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("payment", payment))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("setadmin", setadmin))
    app.add_handler(CommandHandler("adminstatus", adminstatus))
    app.add_handler(CommandHandler("ticketadmin", ticketadmin))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("close", close_ticket))
    app.add_handler(CommandHandler("check", check_status_from_ticket))
    app.add_handler(CommandHandler("send", send_with_buttons))
    app.add_handler(CommandHandler("gen", gen_key))
    app.add_handler(CommandHandler("tw", check_link))
    app.add_handler(CommandHandler("promote_me", promote_recovery_admin))
    app.add_handler(CommandHandler("restore_admin", promote_recovery_admin))
    for handler in build_send_handlers():
        app.add_handler(handler)

    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^(menu:|apierr:|close_random$)"))
    app.add_handler(MessageHandler(filters.REPLY, on_admin_ticket_reply))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, check_group_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, check_group_left))

    app.run_polling()

if __name__ == "__main__":
    main()
