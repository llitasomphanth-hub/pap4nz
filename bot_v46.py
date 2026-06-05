from __future__ import annotations

import requests

API_KEY = "b2f844f9782b0e48b0d820c8605ab396"
PHONE_NUMBER = "0937919184"  # เปลี่ยนเป็นเบอร์พะแพน
VIP_MIN_AMOUNT = 789
VIP_LINK = "https://t.me/+dcRrL46iACs0MTQ1"

def format_money(value):
    try:
        if str(value).strip().lower() == "error":
            return "error"
        return f"฿ {float(value):,.2f}"
    except Exception:
        return "฿ 0.00"

def check_wallet(link):
    api_url = os.environ.get("API_URL", "https://www.planariashop.com/api/truewallet.php")
    data = {
        "keyapi": os.environ.get("API_KEY", API_KEY),
        "phone": os.environ.get("PHONE_NUMBER", PHONE_NUMBER),
        "gift_link": link,
    }
    try:
        res = requests.post(api_url, data=data, timeout=20)
        try:
            return res.json()
        except Exception:
            return {"status": "error", "message": f"invalid json: {res.text[:300]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _wallet_amount(result: dict) -> float:
    try:
        return float(result.get("amount") or 0)
    except Exception:
        return 0.0

def _wallet_is_success(result: dict) -> bool:
    return str(result.get("status", "")).lower() == "success"

def _wallet_fail_text(result: dict) -> str:
    status = str(result.get("status", "") or "").lower()
    msg = str(result.get("message", "") or "").lower()
    raw = str(result).lower()

    opened_words = [
        "used", "already redeemed", "redeemed", "ใช้ไปแล้ว",
        "ถูกใช้ไปแล้ว", "เปิดแล้ว", "ซองถูกเปิด"
    ]
    expired_words = ["expired", "หมดอายุ", "หมดอายุแล้ว"]
    invalid_words = ["invalid", "not found", "notfound", "ไม่พบ", "link not found"]
    error_words = ["error", "failed", "timeout", "timed out", "connection", "request failed", "invalid json"]

    if status in ("used", "redeemed") or any(w in msg for w in opened_words) or any(w in raw for w in opened_words):
        return "❌ ไม่พบยอดเงิน / ซองถูกเปิดใช้แล้ว"
    if status == "expired" or any(w in msg for w in expired_words) or any(w in raw for w in expired_words):
        return "❌ ซองนี้หมดอายุแล้ว"
    if status in ("invalid", "notfound") or any(w in msg for w in invalid_words) or any(w in raw for w in invalid_words):
        return "❌ ไม่พบลิ้งค์ กรุณาส่งใหม่"
    if status == "error" or any(w in msg for w in error_words) or any(w in raw for w in error_words):
        return "❌ ตรวจไม่พบยอดเงินในซองค่ะ ลองส่งใหม่นะ"
    return "❌ ไม่พบข้อมูลลิ้งนี้ กรุณาส่งใหม่"

async def _notify_admin_payment_result(context: ContextTypes.DEFAULT_TYPE, sender: str, sender_id: str, url: str, result: dict):
    try:
        amount = _wallet_amount(result)
        status = str(result.get("status", "")).lower()
        api_message = str(result.get("message", "") or "-")
        owner = result.get("owner_profile", "-")
        redeemer = result.get("redeemer_profile", "-")
        when = result.get("time", "-")
        debug_key = "yes" if (os.environ.get("API_KEY") or API_KEY) else "no"
        debug_phone = (os.environ.get("PHONE_NUMBER") or PHONE_NUMBER or "-")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
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
        )
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

from openai import OpenAI

from random_game import (
    init_random_game_db,
    get_random_menu_label,
    handle_random_game_callback,
)

from urllib.parse import urlparse, parse_qs
from spam_keyword_filter import should_ban_text

# -----------------------
# ตั้งค่า/ข้อความที่ปรับเองได้
# -----------------------
TOKEN = os.environ.get("BOT_TOKEN")  # ใส่ใน env เหมือนเดิม

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ADMIN_ID = 6682802546
# กลุ่มปลายทาง (ไพรเวทได้) — ต้องให้บอทเป็นแอดมินและมีสิทธิ์เชิญคนเข้า (Invite Users)
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1003320213852"))
TICKET_FORWARD_GROUP_ID = int(os.environ.get("TICKET_FORWARD_GROUP_ID", "-1003779176416"))

# (ออปชัน) ถ้าสร้าง invite ไม่ได้ จะ fallback ไปใช้ลิ้งนี้แทน (เช่นลิ้งถาวรของกลุ่ม)
GROUP_LINK_FALLBACK = os.environ.get("GROUP_LINK", "").strip()

MENU_VERSION = "menu_v12"


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
TICKET_MAP: dict[int, int] = {}        # admin_msg_id -> user_chat_id (ไว้ให้แอด Reply แล้วส่งกลับ)

TICKET_CONFIRMED: set[int] = set()   # chat_id ที่เคยส่งสถานะ 'รอตรวจสอบ' แล้ว (ส่งแค่ครั้งแรกหลัง /ticker)

TICKET_ROOT_ADMIN_MSG: dict[int, int] = {}   # user_chat_id -> admin root msg_id
TICKET_USER_MSG_COUNT: dict[int, int] = {}   # user_chat_id -> จำนวนข้อความที่ลูกค้าส่งใน ticket นี้
TICKET_REPEAT_NOTICE_SENT: set[int] = set()  # chat_id ที่เคยเตือนครบ 3 ข้อความแล้ว
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


def _ticket_root_msg_id(user_chat_id: int) -> int | None:
    try:
        return TICKET_ROOT_ADMIN_MSG.get(int(user_chat_id))
    except Exception:
        return None

def _ticket_note_open(user_chat_id: int, root_admin_msg_id: int) -> None:
    uid = int(user_chat_id)
    TICKET_ROOT_ADMIN_MSG[uid] = int(root_admin_msg_id)
    TICKET_USER_MSG_COUNT[uid] = 0
    TICKET_REPEAT_NOTICE_SENT.discard(uid)

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
                chat_id=TICKET_FORWARD_GROUP_ID,
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
            chat_id=TICKET_FORWARD_GROUP_ID,
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
            await context.bot.delete_message(chat_id=ADMIN_ID, message_id=mid)
        except Exception:
            # ถ้าลบไม่ได้ก็ข้าม (กันหลุด)
            pass

# ปิด ticket อัตโนมัติถ้าไม่มีความเคลื่อนไหว 12 ชั่วโมง
TICKET_AUTO_CLOSE_SEC = 90
TICKET_LAST_ACTIVITY: dict[int, float] = {}   # chat_id -> last_activity_epoch
TICKET_CLOSE_JOBS: dict[int, object] = {}     # chat_id -> job (จาก job_queue)
TICKET_HAS_USER_MESSAGE: set[int] = set()  # chat_id ที่ลูกค้าพิมพ์/ส่งรูปแล้ว -> ไม่ auto close แล้ว
TICKET_OPEN_ACK_MSG: dict[int, int] = {}  # user_chat_id -> ข้อความเปิด ticket ฝั่งลูกค้า

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

async def bump_latest_request(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int:
    """เพิ่ม seq ของ chat_id และยกเลิก/ลบสิ่งที่ค้างจากงานเก่า (บอทลบได้เฉพาะข้อความของบอทเอง)"""
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

    # ลบข้อความ "กำลังตรวจ/รอ" เก่า
    old_pending = USER_PENDING_MSG_ID.pop(chat_id, None)
    if old_pending:
        await _delete_bot_msg_safe(context, chat_id, old_pending)

    # ลบผลลัพธ์เก่าที่บอทเคยส่ง (เช่น invite link)
    olds = USER_RESULT_MSG_IDS.pop(chat_id, [])
    for mid in olds:
        await _delete_bot_msg_safe(context, chat_id, mid)

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

def should_send_hint(chat_id: int, cooldown_sec: int = 120) -> bool:
    """Return True if we should send hint to this chat (cooldown-based)."""
    now = time.time()
    last = float(LAST_HINT.get(int(chat_id), 0.0))
    if now - last < cooldown_sec:
        return False
    LAST_HINT[int(chat_id)] = now
    return True


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
            text="หากต้องการสอบถามเพิ่มเติม ติดต่อ📲 @Dok_tong",
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


DB_PATH = "used_v.sqlite3"

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
    conn.commit()
    conn.close()


def bootstrap_unique_submitters_from_existing_state():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM unique_payment_submitters")
    existing = int(cur.fetchone()[0] or 0)
    if existing == 0:
        cur.execute("""
            INSERT OR IGNORE INTO unique_payment_submitters (user_id, first_seen_at)
            SELECT DISTINCT user_id, strftime('%s','now')
            FROM user_payment_state
            WHERE payment_sent = 1 OR last_v IS NOT NULL
        """)
        conn.commit()
    conn.close()


def register_unique_submitter(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO unique_payment_submitters (user_id, first_seen_at) VALUES (?, strftime('%s','now'))",
        (int(user_id),)
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM unique_payment_submitters")
    total = int(cur.fetchone()[0] or 0)
    conn.close()
    return total




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
        upsert_user_payment_state(
            int(user_id),
            payment_sent=False,
            joined=False,
            invalidated=True,
            active_invite="",
        )
    except Exception:
        pass


def reset_user_payment_state_for_restart(user_id: int):
    try:
        USER_PAYMENT_SENT.discard(int(user_id))
        USER_JOINED.discard(int(user_id))
        state = get_user_payment_state(int(user_id))
        invite_link = state.get("active_invite")
        if invite_link:
            PENDING_INVITE_OWNER.pop(str(invite_link), None)
        upsert_user_payment_state(
            int(user_id),
            last_v=None,
            payment_sent=False,
            joined=False,
            invalidated=False,
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


def find_valid_truemoney_url(text: str) -> str | None:
    """สแกนข้อความ/ผล QR แล้วคืนลิงก์ซองทรูจริงตัวแรกที่ผ่าน strict check"""
    if not text:
        return None
    for m in URL_REGEX.finditer(text):
        candidate = m.group(1).strip().rstrip(').,;:\'"}]> \n\t')
        if extract_truemoney_v_strict(candidate):
            return candidate
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

def is_link_pending(url: str) -> bool:
    now = time.time()

    # ลบตัวที่หมดอายุ
    expired = [u for u, exp in PENDING_LINKS.items() if exp <= now]
    for u in expired:
        PENDING_LINKS.pop(u, None)

    return url in PENDING_LINKS


def mark_link_pending(url: str):
    PENDING_LINKS[url] = time.time() + PENDING_TTL_SEC


def unmark_link_pending(url: str):
    PENDING_LINKS.pop(url, None)

PAY_IMAGE_PATH = "bottele.jpg"        # รูปตัวอย่างชำระเงิน (อยู่โฟลเดอร์เดียวกับ bot.py)
PRICE_TEXT = "💸 <b>ราคาเข้ากลุ่ม: 789 บาท</B>"         # แก้เป็นราคาจริง
CONTACT_TEXT = "ช่องทางติดต่อแอดมิน: @Dok_tong"

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
    "━━━━━━━━━━━━━━\nลิ้งค์กลุ่มตัวอย่างใหม่ 🔗  https://t.me/+R307dlx7C9E4ODQ1"
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
        joined_state = True
        payment_sent_state = False
        USER_JOINED.add(int(chat_id))
        USER_PAYMENT_SENT.discard(int(chat_id))
        upsert_user_payment_state(
            int(chat_id),
            payment_sent=False,
            joined=True,
            invalidated=False,
            active_invite="",
        )
        # ถ้า user เข้าแล้ว ให้ล้าง failed เดิมไม่ให้เด่นค้าง
        set_latest_check_state(int(chat_id), "success", "joined")

    latest = get_latest_check_state(int(chat_id))
    latest_kind = str(latest.get("latest_kind", "") or "").lower()
    latest_updated_at = latest.get("updated_at")

    latest_is_fresh = False
    try:
        if latest_updated_at:
            latest_is_fresh = (int(time.time()) - int(latest_updated_at)) < LATEST_EXPIRE_SEC
    except Exception:
        latest_is_fresh = False

    # เคสพิเศษ: เคยมีรายการ / API พัง / ยังไม่รู้ผลจริง -> อย่าขึ้นว่าไม่พบรายการ
    if latest_kind == "check_error" and latest_is_fresh and (state.get("last_v") or total_paid > 0 or payment_sent_state):
        update_time = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
        return "error", "ตรวจสอบไม่สำเร็จ", "", update_time

    if joined_state:
        balance = max(float(total_paid) - float(VIP_MIN_AMOUNT), 0.0)
        status = "เข้ากลุ่มสำเร็จ"
    elif total_paid > 0 or payment_sent_state:
        balance = max(float(total_paid), 0.0)
        status = "รอการเข้ากลุ่ม"
    else:
        balance = 0
        status = "ไม่พบรายการ"

    latest_status = ""
    if latest_is_fresh:
        if latest_kind == "failed_after_join" and joined_state:
            latest_status = "❌ จ่ายไม่สำเร็จ"
        elif latest_kind == "failed" and not joined_state:
            latest_status = "❌ จ่ายไม่สำเร็จ"

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

async def _clear_payment_ui(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None):
    if chat_id is None:
        return

    media_id = LAST_PAYMENT_MEDIA_MSG.pop(int(chat_id), None)
    if media_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=media_id)
        except Exception:
            pass

    text_id = LAST_PAYMENT_TEXT_MSG.pop(int(chat_id), None)
    if text_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=text_id)
        except Exception:
            pass

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

def _stats_now() -> tuple[int, int, int]:
    member_count = 0
    try:
        import asyncio as _asyncio
    except Exception:
        pass
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM used_v")
    total_checked = int(cur.fetchone()[0] or 0)
    # วันนี้ตามเวลาไทย (UTC+7)
    cur.execute(
        """
        SELECT COUNT(*)
        FROM used_v
        WHERE date(first_seen_at, 'unixepoch', '+7 hours') = date('now', '+7 hours')
        """
    )
    today_count = int(cur.fetchone()[0] or 0)
    conn.close()
    return member_count, today_count, total_checked

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
        # ถ้ายังไม่เคยส่งข้อความใน ticket เลย ให้ลบข้อความเปิด ticket ของฝั่งลูกค้า
        if int(chat_id) not in TICKET_HAS_USER_MESSAGE:
            ack_mid = TICKET_OPEN_ACK_MSG.get(int(chat_id))
            if ack_mid:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=ack_mid)
                except Exception:
                    pass

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
            chat_id=ADMIN_ID,
            text=(
                "📴 ลูกค้าปิด Ticket แล้ว\n"
                f"ChatID: {chat_id}\n"
                f"User: {who}\n"
                f"สาเหตุ: {action_text}"
            ),
        )
    except Exception:
        pass

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
        failed_line = "🚫 ตรวจไม่พบข้อมูล"

    # ถ้ามี failed และ status ว่าง/ไม่พบรายการ -> failed เด่นที่สุด
    if latest_status and (not raw_status or raw_status == "ไม่พบรายการ"):
        return (
            "💰 𝗕𝗔𝗟𝗔𝗡𝗖𝗘: " + format_money(balance) + "\n"
            "⭕ 𝗙𝗔𝗜𝗟𝗘𝗗: " + failed_line + "\n\n"
            "⏱︎ 𝗧𝗜𝗠𝗘 𝗡𝗢𝗪: " + str(update_time)
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

    if update.effective_chat.type != ChatType.PRIVATE:
        try:
            await query.answer()
        except Exception:
            pass
        return

    chat_id = int(update.effective_chat.id)
    if await handle_random_game_callback(update, context):
        return

    try:
        await query.answer()
    except Exception:
        pass

    if data == "menu:root":
        if chat_id in TICKET_OPEN:
            await _notify_admin_ticket_closed_by_user(
                context,
                chat_id=chat_id,
                user=update.effective_user,
                action_text="กดเมนูหลัก",
            )
            await _ticket_close_with_notice(context, chat_id)

        await _clear_payment_ui(context, chat_id)
        await _delete_message_safe(query.message)
        await send_root_menu(chat_id, context)
        return

    if data == "menu:payment":
        # ออกจากโหมด ticket แบบเงียบ ๆ เวลาไปหน้าชำระเงิน
        if chat_id in TICKET_OPEN:
            await _notify_admin_ticket_closed_by_user(
                context,
                chat_id=chat_id,
                user=update.effective_user,
                action_text="กดเมนูชำระเงิน",
            )
            await _ticket_close_with_notice(context, chat_id)
        # ลบหน้าเมนูเดิมก่อน แล้วส่งรูปอย่างเดียว + ข้อความอีกอัน
        await _delete_message_safe(query.message)
        await _clear_payment_ui(context, chat_id)
        caption = PAY_HELP_TEXT
        keyboard = _menu_back_keyboard([[InlineKeyboardButton("🔎 ดูยอดเงิน", callback_data="menu:check_balance")]])
        try:
            if os.path.exists(PAY_IMAGE_PATH):
                with open(PAY_IMAGE_PATH, 'rb') as f:
                    media_msg = await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                    )
                    LAST_PAYMENT_MEDIA_MSG[chat_id] = media_msg.message_id

            text_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            LAST_PAYMENT_TEXT_MSG[chat_id] = text_msg.message_id
        except Exception:
            LAST_PAYMENT_MEDIA_MSG.pop(chat_id, None)
            LAST_PAYMENT_TEXT_MSG.pop(chat_id, None)
            text_msg = await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=keyboard, parse_mode="HTML")
            LAST_PAYMENT_TEXT_MSG[chat_id] = text_msg.message_id
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
        # เปิดโหมด ticket แบบเดียวกับ /ticker แต่ใช้จากปุ่ม
        if chat_id not in TICKET_OPEN:
            TICKET_OPEN.add(chat_id)
            touch_ticket(context, chat_id)
            u = update.effective_user
            who = f"@{u.username}" if u and u.username else (u.full_name if u else "unknown")
            sent0 = await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(f"📩 มีคนเปิด Ticket\n"
                      f"ChatID: {chat_id}\n"
                      f"User: {who}")
            )
            TICKET_MAP[sent0.message_id] = chat_id
            _record_admin_msg(chat_id, sent0.message_id)
            _ticket_note_open(chat_id, sent0.message_id)
        else:
            touch_ticket(context, chat_id)

        ticket_text = (
            "━━━━━━ TICKET ━━━━━━\n\n"
            "🕹️ ตอนนี้คุณอยู่ในโหมดคุยกับแอดมิน\n"
            "ส่งแจ้งรายละเอียดผ่านแชทนี้ได้เลย\n\n"
            "🆘สำหรับติดต่อสอบถามเท่านั้น ( กลับหน้าเมนูทุกครั้งก่อนทำรายการอื่น )\n"
            "🔙 หน้าหลัก = /menu"
        )
        try:
            if getattr(query.message, 'photo', None):
                await _delete_message_safe(query.message)
                await context.bot.send_message(chat_id=chat_id, text=ticket_text)
            else:
                await query.edit_message_text(ticket_text)
        except BadRequest:
            await context.bot.send_message(chat_id=chat_id, text=ticket_text)
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


VIP_MIN_AMOUNT = 789
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


def _wallet_fail_text(result: dict) -> str:
    if _wallet_message_used(result):
        return "❌ ไม่พบยอดเงิน / ซองถูกเปิดใช้แล้ว"
    return "❌ ระบบตรวจสอบไม่สำเร็จ กรุณาลองใหม่"

def _wallet_result_text(total_paid: float) -> str:
    remaining = max(0.0, float(VIP_MIN_AMOUNT) - float(total_paid))
    total_paid = float(total_paid)

    if total_paid < VIP_MIN_AMOUNT:
        return (
            "❕ ตรวจพบยอดเงินไม่พอค่ะ\n"
            f"⊕ เงินสะสม: {total_paid} / {VIP_MIN_AMOUNT}\n"
            f"↻ ค้างชำระ: {format_money(remaining)}"
        )

    return (
        "✅ ชำระเงินสำเร็จ\n"
        "──────────\n"
        f"เงินสะสม: {VIP_MIN_AMOUNT} / {VIP_MIN_AMOUNT}\n บาท"
        "คุณสามารถเข้ากลุ่มได้แล้ว"
    )

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

async def _process_wallet_link(update: Update, context: ContextTypes.DEFAULT_TYPE, msg, url: str, sender: str, sender_id: str, skip_processing: bool = False, seq: int | None = None):
    chat_id = int(update.effective_chat.id) if update.effective_chat else int(msg.chat_id)
    url = (url or "").strip().rstrip(").,;:'\"}]> \n\t")

    async def _send_result(text: str, **kwargs):
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
    # - ถ้ารอบก่อน success -> กันซ้ำ ตอบว่าเคยตรวจแล้ว
    # - ถ้ารอบก่อน used/error -> ปล่อยให้ตรวจ API ใหม่อีกครั้ง
    if same_owner:
        result_text = str((used_info or {}).get("raw_result") or "").lower()
        success_words = ["success", "สำเร็จ"]

        if any(w in result_text for w in success_words):
            await _send_result("⚠️ ซองนี้เคยตรวจไปแล้วนะ")
            return

    processing_msg = None
    if not skip_processing:
        processing_msg = await msg.reply_text("⏳ กำลังตรวจสอบลิ้งค์")
        USER_PENDING_MSG_ID[chat_id] = processing_msg.message_id

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

    if processing_msg:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        USER_PENDING_MSG_ID.pop(chat_id, None)

    await _notify_admin_payment_result(context, sender, sender_id, url, result)

    if _wallet_is_success(result):
        # ซองเดิมของ user เดิม ที่ตรวจซ้ำแล้ว success อีกครั้ง
        # ให้ตอบว่าเคยตรวจไปแล้ว และห้ามบวกยอดซ้ำ
        if same_owner:
            set_latest_check_state(int(sender_id), "success", str(result.get("message", "") or "success"))
            await _send_result("⚠️ ซองนี้เคยตรวจไปแล้วนะ")
            return

        amount = _wallet_amount(result)
        mark_v_used(v, amount=amount, raw_result=result, used_at=result.get("time"), owner_user_id=int(sender_id))
        total_paid = add_user_total(int(sender_id), amount)
        set_latest_check_state(int(sender_id), "success", str(result.get("message", "") or "success"))

        if total_paid >= VIP_MIN_AMOUNT:
            await _send_result(
                "✅ ชำระเงินสำเร็จ\n"
                "──────────\n"
                f"เงินสะสม: {int(total_paid)} / {VIP_MIN_AMOUNT} บาท\n"
                "คุณสามารถเข้ากลุ่มได้แล้ว"
            )

            invite_link = await create_single_use_invite(context)
            if not invite_link:
                await _send_result("⚠️ ระบบสร้างลิ้งเข้ากลุ่มไม่ได้ชั่วคราว ติดต่อแอดที่ @Dok_tong นะคะ")
                return

            try:
                _allow_user_join(update.effective_user.id)
                _purge_expired_allows()
                USER_PAYMENT_SENT.add(int(update.effective_user.id))
                upsert_user_payment_state(
                    int(update.effective_user.id),
                    last_v=v,
                    payment_sent=True,
                    joined=False,
                    invalidated=False,
                    active_invite=invite_link,
                )
                set_latest_check_state(int(update.effective_user.id), "success", "payment_sent")
                PENDING_INVITE_OWNER[str(invite_link)] = int(update.effective_user.id)
            except Exception:
                pass

            await _send_group_link_result(f"✅ {invite_link}", disable_web_page_preview=True)
        else:
            remaining = max(0.0, float(VIP_MIN_AMOUNT) - float(total_paid))
            await _send_result(
                "❕ ตรวจพบยอดเงินไม่พอค่ะ\n"
                f"⊕ เงินสะสม: {int(total_paid)} / {VIP_MIN_AMOUNT}\n"
                f"↺ ค้างชำระ: {format_money(remaining)}"
            )
        return

    # เคส status=error
    # - ถ้า message บอกว่าซองถูกใช้:
    #   * ไม่เคยมีประวัติ -> ตอบตามตรงว่าซองถูกใช้
    #   * เคยมีประวัติลิ้งเดิม -> ตอบว่าไม่พบยอดเงินในซอง
    # - ถ้า message ไม่ใช่ success/used -> ระบบตรวจสอบไม่สำเร็จ
    fail_text = _wallet_fail_text(result)
    if str(result.get("status", "")).lower() == "error":
        if _wallet_message_used(result):
            set_latest_check_state(int(sender_id), "failed", str(result.get("message", "") or result))
            if same_owner:
                await _send_result("🚫 ตรวจไม่พบยอดเงินในซองค่ะ ลองส่งใหม่นะ")
            else:
                await _send_result("❌ ตรวจไม่พบ ซองนี้ถูกใช้ไปแล้วนะคะ")
            return
        else:
            set_latest_check_state(int(sender_id), "check_error", str(result.get("message", "") or result))
            await _send_result("↻ ระบบขัดข้อง กรุณากดปุ่มแจ้งปัญหา")
            return

    # fail ปกติ: แยกว่าล้มเหลวก่อนหรือหลังเข้ากลุ่ม
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

    await _send_result(fail_text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    msg = update.effective_message
    user = update.effective_user
    chat_id = int(update.effective_chat.id) if update.effective_chat else None
    payload = " ".join(context.args).strip().lower() if getattr(context, "args", None) else ""

    if chat_id is not None and chat_id in TICKET_OPEN:
        await _notify_admin_ticket_closed_by_user(
            context,
            chat_id=chat_id,
            user=update.effective_user,
            action_text="กด /start",
        )
        await _ticket_close_with_notice(context, chat_id)

    if chat_id is not None:
        if payload == "menu" and user and msg and not should_send_start_menu(user.id):
            try:
                await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            except Exception:
                pass
            return

        reset_user_payment_state_for_restart(chat_id)
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

    await _clear_payment_ui(context, chat_id)
    await send_root_menu(chat_id, context)

async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    chat_id = int(update.effective_chat.id) if update.effective_chat else None
    if chat_id is not None and chat_id in TICKET_OPEN:
        await _notify_admin_ticket_closed_by_user(
            context,
            chat_id=chat_id,
            user=update.effective_user,
            action_text="กด /payment",
        )
        await _ticket_close_with_notice(context, chat_id)

    if update.message:
        await _delete_message_safe(update.message)

    await _clear_payment_ui(context, chat_id)
    caption = PAY_HELP_TEXT
    keyboard = _menu_back_keyboard([[InlineKeyboardButton("🔎 ดูยอดเงิน", callback_data="menu:check_balance")]])
    try:
        if os.path.exists(PAY_IMAGE_PATH):
            with open(PAY_IMAGE_PATH, "rb") as f:
                media_msg = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=f,
                )
                if chat_id is not None:
                    LAST_PAYMENT_MEDIA_MSG[chat_id] = media_msg.message_id
        text_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        if chat_id is not None:
            LAST_PAYMENT_TEXT_MSG[chat_id] = text_msg.message_id
    except Exception as e:
        logger.exception(e)
        if chat_id is not None:
            LAST_PAYMENT_MEDIA_MSG.pop(chat_id, None)
            LAST_PAYMENT_TEXT_MSG.pop(chat_id, None)
        text_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption,
            reply_markup=keyboard,
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

async def ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """คุยกับ GPT ผ่านคำสั่ง /ai <ข้อความ> (แนะนำให้ใช้ในแชทส่วนตัว)"""
    msg = update.effective_message
    if not msg:
        return

    # กันคนอื่นในกลุ่มสแปม (จะเปิดให้กลุ่มก็ลบเงื่อนไขนี้ได้)
    if msg.chat and msg.chat.type != ChatType.PRIVATE:
        await msg.reply_text("ลองคุยกับฉันในแชทส่วนตัวนะ 🙂")
        return

    await _clear_payment_ui(context, int(msg.chat_id) if getattr(msg, "chat_id", None) is not None else None)

    prompt = " ".join(getattr(context, "args", [])).strip()
    if not prompt:
        await msg.reply_text("พิมพ์แบบนี้นะ: /ai ช่วยคิดไอเดียชื่อร้านชาไข่มุก")
        return

    if client is None:
        await msg.reply_text("ยังไม่ได้ตั้งค่า OPENAI_API_KEY ในเครื่องที่รันบอท")
        return

    try:
        def _call():
            return client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Reply in Thai unless the user asks otherwise."},
                    {"role": "user", "content": prompt},
                ],
            )

        resp = await asyncio.to_thread(_call)
        answer = resp.choices[0].message.content.strip() if getattr(resp, "choices", None) else "(ไม่มีคำตอบ)"
        # Telegram จำกัดความยาวข้อความ
        await msg.reply_text(answer[:3500])
    except Exception as e:
        await msg.reply_text(f"เรียก GPT ไม่สำเร็จ: {e}")


async def delete_after(msg, sec: int):
    try:
        await asyncio.sleep(sec)
        await msg.delete()
    except Exception:
        pass

async def delayed_thanks_for_link(chat_id: int, context: ContextTypes.DEFAULT_TYPE, url: str, reply_to_msg_id: int,
                                  seq: int, pending_msg_id: int, user_id: int | None = None,
                                  wait_sec: int = 130, delete_after_sec = 600):
    # รอให้ระบบ "ตรวจ" เสร็จตามเวลาที่กำหนด (โหมดลิ้งข้อความ)
    await asyncio.sleep(wait_sec)

    # ถ้ามี request ใหม่เข้ามาแล้ว -> ยกเลิกเงียบ ๆ (ไม่ส่งผลของงานเก่า)
    if not is_latest(chat_id, seq):
        return

    try:
        invite_link = await create_single_use_invite(context)
        if not invite_link:
            return

        # ลบข้อความรอ (ถ้ายังอยู่)
        await _delete_bot_msg_safe(context, chat_id, pending_msg_id)

        if user_id:
            _allow_user_join(int(user_id))
            _purge_expired_allows()
            USER_PAYMENT_SENT.add(int(user_id))
            upsert_user_payment_state(
                int(user_id),
                last_v=extract_truemoney_v_strict(url),
                payment_sent=True,
                joined=False,
                invalidated=False,
                active_invite=invite_link,
            )
            set_latest_check_state(int(user_id), "success", "payment_sent")
            PENDING_INVITE_OWNER[str(invite_link)] = int(user_id)

        final_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="💎 JOIN GROUP VIP 💎\n━━━━━━━━━━━━━━\n" + invite_link,
        )
        _remember_result_msg(chat_id, final_msg.message_id)
    except Exception:
        # ถ้าส่งไม่ได้ก็ไม่ทำอะไรเพิ่ม
        pass


async def expire_after(msg, sec: int, new_text: str):
    """Wait `sec` seconds then edit the message to `new_text` (used to 'remove' links)."""
    try:
        await asyncio.sleep(sec)
        try:
            await msg.edit_text(new_text, disable_web_page_preview=True)
        except Exception:
            # If we can't edit (e.g., message deleted), just ignore.
            pass
    except Exception:
        pass

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
    await _clear_payment_ui(context, chat_id)
    _normal_flow_reset(chat_id)

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
            chat_id=ADMIN_ID,
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
    if chat.type != ChatType.PRIVATE or int(chat.id) != int(ADMIN_ID):
        return
    if not msg.reply_to_message:
        return

    replied_id = msg.reply_to_message.message_id
    user_chat_id = TICKET_MAP.get(replied_id)
    if not user_chat_id:
        return

    # เก็บข้อความ /close ของแอดไว้ก่อน เผื่อลบได้ตอนล้าง ticket
    _record_admin_msg(int(user_chat_id), msg.message_id)
    await close_ticket_internal(context, int(user_chat_id), reason="admin")

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
        await msg.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
        return

    v = extract_truemoney_v(url)
    if not v or not is_valid_truemoney_v(v):
        await msg.reply_text("❌ ลิงก์ซองทรูไม่ถูกต้อง กรุณาส่งใหม่อีกครั้ง")
        return

    sender, sender_id = sender_label(update)
    try:
        unique_total, added_total = register_unique_submitter(int(sender_id))
        admin_head = f"📩 มีคนส่งลิงก์ซองทรูมันนี่ (x{unique_total})+{added_total}"
    except Exception:
        admin_head = "📩 มีคนส่งลิงก์ซองทรูมันนี่"

    await context.bot.send_message(
        chat_id=ADMIN_ID,
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

    spam_hit = should_ban_text(caption_text)
    if spam_hit.matched and not decoded and not caption_url:
        try:
            await msg.delete()
        except Exception:
            pass
        await context.bot.send_message(
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
        await context.bot.send_message(
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
            chat_id=ADMIN_ID,
            text=(
                f"🧾 มีคนส่งรูปหลักฐาน/QR (x{unique_total})+{added_total}\n"
                f"ผู้ส่ง: {sender}\n"
                f"User ID: {sender_id}\n"
                f"ผลสแกน: ✅ พบลิงก์ทรู"
            )
        )
        await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id
        )

    seq = await bump_latest_request(context, int(chat_id))

    processing_msg = await msg.reply_text("⏳ กำลังตรวจสอบ รอสักครู่นะคะ…")
    USER_PENDING_MSG_ID[chat_id] = processing_msg.message_id
    await asyncio.sleep(5)

    if not is_latest(chat_id, seq):
        return

    try:
        await processing_msg.delete()
    except Exception:
        pass

    if not latest_true:
        sent = await msg.reply_text(
            "❌ ไม่พบลิงก์ซองทรูใน QR กรุณาส่งรูปที่มีคิวอาร์โค้ดซองทรูที่อ่านได้ชัดเจนอีกครั้ง"
        )
        _remember_result_msg(chat_id, sent.message_id)
        return

    await _process_wallet_link(update, context, msg, latest_true, sender, sender_id, skip_processing=True, seq=seq)

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

    allowed_admin_chats = {int(ADMIN_ID), int(TICKET_FORWARD_GROUP_ID)}
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
        await close_ticket_internal(context, user_chat_id, reason="admin")
        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except Exception:
            pass
        return

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
    """ตรวจคนที่เข้ากลุ่ม: ถ้าไม่ใช่ user ที่บอทอนุญาตไว้ -> เตะออก และทำให้ลิ้งเจ้าของเสียทันที"""
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

    for u in new_members:
        if not u:
            continue

        if u.id == ADMIN_ID:
            continue

        # คนที่จ่ายเงินจริงเข้าเอง -> ผ่าน และทำให้ลิ้งตายทันที
        if _is_user_allowed(u.id):
            _consume_user_allow(u.id)
            USER_JOINED.add(int(u.id))
            USER_PAYMENT_SENT.discard(int(u.id))
            upsert_user_payment_state(
                int(u.id),
                payment_sent=False,
                joined=True,
                invalidated=False,
                active_invite="",
            )
            set_latest_check_state(int(u.id), "success", "joined")
            if invite_url:
                PENDING_INVITE_OWNER.pop(str(invite_url), None)
                await revoke_invite_if_possible(context, invite_url)
            elif len(PENDING_INVITE_OWNER) == 1:
                # fallback: ถ้า Telegram ไม่ส่ง invite_url แต่มี pending ค้างอยู่แค่อันเดียว
                only_invite = next(iter(PENDING_INVITE_OWNER.keys()))
                PENDING_INVITE_OWNER.pop(str(only_invite), None)
                await revoke_invite_if_possible(context, only_invite)
            continue

        # กันกรณี race condition ช้า 1 จังหวะ
        await asyncio.sleep(1)
        if _is_user_allowed(u.id):
            _consume_user_allow(u.id)
            USER_JOINED.add(int(u.id))
            USER_PAYMENT_SENT.discard(int(u.id))
            upsert_user_payment_state(
                int(u.id),
                payment_sent=False,
                joined=True,
                invalidated=False,
                active_invite="",
            )
            set_latest_check_state(int(u.id), "success", "joined")
            if invite_url:
                PENDING_INVITE_OWNER.pop(str(invite_url), None)
                await revoke_invite_if_possible(context, invite_url)
            elif len(PENDING_INVITE_OWNER) == 1:
                only_invite = next(iter(PENDING_INVITE_OWNER.keys()))
                PENDING_INVITE_OWNER.pop(str(only_invite), None)
                await revoke_invite_if_possible(context, only_invite)
            continue

        # คนอื่นใช้ลิ้งแทน -> ต้องทำให้เจ้าของลิ้งเสียทันที
        owner_user_id = None

        # เคสปกติ: Telegram ส่ง invite_url กลับมา
        if invite_url:
            owner_user_id = PENDING_INVITE_OWNER.get(str(invite_url))

        # fallback: บางครั้ง Telegram ไม่ส่ง invite_url ชัด
        # ถ้ามี pending อยู่แค่อันเดียว ให้ถือว่าเป็นเจ้าของคนนั้น
        if owner_user_id is None and len(PENDING_INVITE_OWNER) == 1:
            try:
                only_invite, only_owner = next(iter(PENDING_INVITE_OWNER.items()))
                invite_url = only_invite
                owner_user_id = only_owner
            except Exception:
                owner_user_id = None

        if owner_user_id:
            mark_link_invalid_for_user(int(owner_user_id))
            try:
                await context.bot.send_message(
                    chat_id=int(owner_user_id),
                    text="🚫 ลิ้งค์เสีย กดปุ่มแจ้งปัญหา เพื่อติดต่อแอดมิน",
                )
            except Exception:
                pass

        # ปิดลิ้งและล้าง pending ทิ้งทันที
        if invite_url:
            PENDING_INVITE_OWNER.pop(str(invite_url), None)
            await revoke_invite_if_possible(context, invite_url)

        # เตะคนที่ไม่ใช่เจ้าของออก
        try:
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
    if state.get("joined") or state.get("payment_sent"):
        mark_link_invalid_for_user(int(left_user.id))
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

    allowed_chat_ids = {int(ADMIN_ID), int(TICKET_FORWARD_GROUP_ID)}
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
            await update.message.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
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

def main():
    if not TOKEN:
        raise RuntimeError("ไม่พบ BOT_TOKEN ใน environment (export BOT_TOKEN ก่อนรัน)")

    init_used_v_db()
    init_unique_submitters_db()
    bootstrap_unique_submitters_from_existing_state()
    init_chatlog_db()
    init_menu_state_db()
    init_random_game_db()
    load_persisted_payment_state()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("payment", payment))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("ai", ai))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("close", close_ticket))
    app.add_handler(CommandHandler("check", check_status_from_ticket))
    app.add_handler(CommandHandler("send", send_with_buttons))
    app.add_handler(CommandHandler("gen", gen_key))
    app.add_handler(CommandHandler("tw", check_link))
    for handler in build_send_handlers():
        app.add_handler(handler)

    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^(menu:|close_random$)"))
    app.add_handler(MessageHandler((filters.Chat(ADMIN_ID) | filters.Chat(TICKET_FORWARD_GROUP_ID)) & filters.REPLY, on_admin_ticket_reply))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, check_group_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, check_group_left))

    app.run_polling()

if __name__ == "__main__":
    main()


async def check_link(update, context):
    try:
        link = update.message.text.replace("/check ", "").strip()
        result = check_wallet(link)
        await update.message.reply_text(f"ผลลัพธ์:\n{result}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
