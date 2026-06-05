from __future__ import annotations

import asyncio
import re
from typing import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ChatJoinRequestHandler, CommandHandler, ContextTypes

# =========================
# ตั้งค่าได้ตรงนี้
# =========================
# ถ้าใส่ chat id ตรงนี้ /send จะส่งไปแชทนี้เสมอ
# แต่ถ้าพิมพ์ /send -100xxxx ในแชทกับบอท จะใช้ chat id ที่พิมพ์มาก่อน
# ถ้าเว้นว่างไว้ และไม่ได้พิมพ์ chat id ในคำสั่ง จะส่งกลับเข้าแชทเดิม
SEND_TARGET_CHAT_ID_RAW = ""

# ปุ่ม default จะใช้ก็ต่อเมื่อใน /send ไม่ได้ระบุปุ่มมาเอง
SEND_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🌟 สมัครเข้ากลุ่ม VIP คลิก 🌟", url="https://t.me/doktongggggg_bot?start=menu")],
    [InlineKeyboardButton("ช่องอัปเดทลิงก์กลุ่ม", url="https://t.me/+p6xffHdw3FNkNzI1")],
]

# ใครใช้ /send ได้บ้าง
SEND_ALLOWED_USER_IDS = {
    8511802086,
}

# รับรีเควสเข้าแชนแนลนี้อัตโนมัติ
AUTO_APPROVE_CHANNEL_ID = -1003231328344
AUTO_APPROVE_DELAY_SEC = 5

_COMMAND_RE = re.compile(r"^/send(?:@[A-Za-z0-9_]+)?\s*", re.IGNORECASE)
_CHAT_ID_PREFIX_RE = re.compile(r"^(?P<chat_id>-100\d+)(?:\s+|$)")
_BUTTON_BLOCK_RE = re.compile(r"\[(.*?)\]")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _build_default_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(SEND_BUTTONS)


def _is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and int(user.id) in SEND_ALLOWED_USER_IDS)


def _extract_send_payload(msg) -> str:
    raw = msg.text or msg.caption or ""
    return _COMMAND_RE.sub("", raw, count=1).strip()


def _extract_target_and_payload(update: Update, payload: str) -> tuple[int, str]:
    payload = (payload or "").strip()
    match = _CHAT_ID_PREFIX_RE.match(payload)
    if match:
        return int(match.group("chat_id")), payload[match.end():].strip()

    if SEND_TARGET_CHAT_ID_RAW:
        return int(SEND_TARGET_CHAT_ID_RAW), payload

    if not update.effective_chat:
        raise RuntimeError("ไม่พบ chat ปลายทาง")

    return int(update.effective_chat.id), payload


def _parse_button_block(block: str) -> InlineKeyboardButton:
    parts = [p.strip() for p in block.split(",", 1)]
    if len(parts) != 2:
        raise ValueError(f"ปุ่มรูปแบบไม่ถูกต้อง: [{block}]")

    label, url = parts
    if not label:
        raise ValueError("ชื่อปุ่มห้ามว่าง")
    if not url or not _URL_RE.match(url):
        raise ValueError(f"ลิงก์ปุ่มไม่ถูกต้อง: {url}")

    return InlineKeyboardButton(label, url=url)


def _parse_text_and_buttons(payload: str) -> tuple[str, InlineKeyboardMarkup | None]:
    if not payload:
        return "", None

    text_lines: list[str] = []
    button_rows: list[list[InlineKeyboardButton]] = []

    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        matches = list(_BUTTON_BLOCK_RE.finditer(line))
        if matches:
            leftovers = _BUTTON_BLOCK_RE.sub("", line).strip()
            if leftovers:
                text_lines.append(line)
                continue

            row: list[InlineKeyboardButton] = []
            for match in matches:
                row.append(_parse_button_block(match.group(1)))
            if row:
                button_rows.append(row)
            continue

        text_lines.append(line)

    text = "\n".join(text_lines).strip()
    markup = InlineKeyboardMarkup(button_rows) if button_rows else None
    return text, markup


def _build_message_link(sent_message) -> str | None:
    try:
        chat = sent_message.chat
        message_id = int(sent_message.message_id)

        username = getattr(chat, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"

        chat_id = int(chat.id)
        if str(chat_id).startswith("-100"):
            internal_id = str(chat_id)[4:]
            return f"https://t.me/c/{internal_id}/{message_id}"
    except Exception:
        return None

    return None


async def _send_success_reply(msg, link: str | None) -> None:
    try:
        if link:
            await msg.reply_text(f"✅ สำเร็จ\n{link}", disable_web_page_preview=True)
        else:
            await msg.reply_text("✅ สำเร็จ")
    except Exception:
        pass


async def _delete_command_message(msg) -> None:
    try:
        await msg.delete()
    except Exception:
        pass


async def send_with_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ใช้งานได้หลายแบบ

    1) /send ข้อความที่ต้องการส่ง
    2) /send -100xxxx ข้อความที่ต้องการส่ง
    3) /send ข้อความ\n[ ปุ่ม1, https://... ]\n[ ปุ่ม2, https://... ]
    4) แนบรูป/วิดีโอ/ไฟล์มากับ /send ในข้อความเดียวกัน
    5) Reply ข้อความ/รูป/วิดีโอ/ไฟล์ แล้วพิมพ์ /send
    6) Reply ข้อความ/สื่อ แล้วพิมพ์ /send ข้อความใหม่ + ปุ่มใหม่
    """
    msg = update.effective_message
    if not msg:
        return

    if not _is_allowed(update):
        return

    try:
        raw_payload = _extract_send_payload(msg)
        target_chat_id, payload = _extract_target_and_payload(update, raw_payload)
        typed_text, typed_markup = _parse_text_and_buttons(payload)
        reply_markup = typed_markup or _build_default_markup()
        replied = msg.reply_to_message
        sent_message = None

        # -------------------------
        # กรณีส่งสื่อมากับ /send ในข้อความเดียวกัน
        # -------------------------
        if msg.photo:
            sent_message = await context.bot.send_photo(
                chat_id=target_chat_id,
                photo=msg.photo[-1].file_id,
                caption=typed_text or "",
                reply_markup=reply_markup,
            )
        elif msg.video:
            sent_message = await context.bot.send_video(
                chat_id=target_chat_id,
                video=msg.video.file_id,
                caption=typed_text or "",
                reply_markup=reply_markup,
            )
        elif msg.document:
            sent_message = await context.bot.send_document(
                chat_id=target_chat_id,
                document=msg.document.file_id,
                caption=typed_text or "",
                reply_markup=reply_markup,
            )
        elif msg.animation:
            sent_message = await context.bot.send_animation(
                chat_id=target_chat_id,
                animation=msg.animation.file_id,
                caption=typed_text or "",
                reply_markup=reply_markup,
            )
        elif msg.voice:
            sent_message = await context.bot.send_voice(
                chat_id=target_chat_id,
                voice=msg.voice.file_id,
                caption=typed_text or "",
                reply_markup=reply_markup,
            )

        if sent_message is not None:
            link = _build_message_link(sent_message)
            await _send_success_reply(msg, link)
            await _delete_command_message(msg)
            return

        # -------------------------
        # กรณี reply ข้อความ/สื่อเดิม
        # -------------------------
        if replied:
            override_text = typed_text or None

            if replied.photo:
                sent_message = await context.bot.send_photo(
                    chat_id=target_chat_id,
                    photo=replied.photo[-1].file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
            elif replied.video:
                sent_message = await context.bot.send_video(
                    chat_id=target_chat_id,
                    video=replied.video.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
            elif replied.document:
                sent_message = await context.bot.send_document(
                    chat_id=target_chat_id,
                    document=replied.document.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
            elif replied.animation:
                sent_message = await context.bot.send_animation(
                    chat_id=target_chat_id,
                    animation=replied.animation.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
            elif replied.voice:
                sent_message = await context.bot.send_voice(
                    chat_id=target_chat_id,
                    voice=replied.voice.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
            else:
                base_text = override_text if override_text is not None else (replied.text or replied.caption or "")
                if base_text:
                    sent_message = await context.bot.send_message(
                        chat_id=target_chat_id,
                        text=base_text,
                        reply_markup=reply_markup,
                        disable_web_page_preview=True,
                    )
                else:
                    await msg.reply_text("ข้อความที่ reply ยังไม่รองรับนะ")
                    return

            link = _build_message_link(sent_message)
            await _send_success_reply(msg, link)
            await _delete_command_message(msg)
            return

        # -------------------------
        # กรณีพิมพ์ /send ข้อความตรงๆ
        # -------------------------
        if typed_text:
            sent_message = await context.bot.send_message(
                chat_id=target_chat_id,
                text=typed_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            link = _build_message_link(sent_message)
            await _send_success_reply(msg, link)
            await _delete_command_message(msg)
            return

        if typed_markup:
            sent_message = await context.bot.send_message(
                chat_id=target_chat_id,
                text="เลือกจากปุ่มด้านล่างได้เลย",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            link = _build_message_link(sent_message)
            await _send_success_reply(msg, link)
            await _delete_command_message(msg)
            return

        await msg.reply_text(
            "ใช้แบบนี้นะ:\n"
            "• /send ข้อความที่ต้องการส่ง\n"
            "• /send -1001234567890 ข้อความที่ต้องการส่ง\n"
            "• /send ข้อความ\n[ กลุ่ม1, https://t.me/xxxxx ]\n[ กลุ่ม2, https://t.me/yyyyy ]\n"
            "• หรือแนบรูป/วิดีโอ/ไฟล์มากับ /send ในข้อความเดียวกัน\n"
            "• หรือ reply ข้อความ/รูป แล้วพิมพ์ /send"
        )
    except Exception as e:
        try:
            await msg.reply_text(f"ส่งไม่สำเร็จ ❌\n{e}")
        except Exception:
            pass


async def auto_approve_channel_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    req = update.chat_join_request
    if not req or not req.chat or not req.from_user:
        return

    if int(req.chat.id) != int(AUTO_APPROVE_CHANNEL_ID):
        return

    try:
        await asyncio.sleep(AUTO_APPROVE_DELAY_SEC)
        await context.bot.approve_chat_join_request(
            chat_id=int(req.chat.id),
            user_id=int(req.from_user.id),
        )
    except Exception:
        pass


def build_send_handlers() -> Sequence[object]:
    return [
        CommandHandler("send", send_with_buttons),
        ChatJoinRequestHandler(auto_approve_channel_join_request),
    ]
