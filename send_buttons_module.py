from __future__ import annotations

from typing import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes

# =========================
# ตั้งค่าได้ตรงนี้
# =========================
# ถ้าใส่ chat id ตรงนี้ /send จะส่งไปแชทนี้เสมอ
# ถ้าเว้นว่างไว้ จะส่งกลับเข้าแชทเดิมที่พิมพ์ /send
SEND_TARGET_CHAT_ID_RAW = "-1003603359307"

# ปุ่มที่ต้องการให้แสดงใต้ข้อความ
SEND_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🌟 สมัครเข้ากลุ่ม VIP คลิก 🌟", url="https://t.me/doktongggggg_bot?start=menu")],
    [InlineKeyboardButton("🔗 กลุ่มสำรองกันบิน", url="https://t.me/+R307dlx7C9E4ODQ1")],
    [InlineKeyboardButton("📝 อ่านเครดิต/รีวิว", url="https://t.me/+RnzPkQZh5Eg5Yzg1")],
]

# ใครใช้ /send ได้บ้าง
SEND_ALLOWED_USER_IDS = {
    6682802546,
}


def _resolve_target_chat_id(update: Update) -> int:
    if SEND_TARGET_CHAT_ID_RAW:
        return int(SEND_TARGET_CHAT_ID_RAW)

    if not update.effective_chat:
        raise RuntimeError("ไม่พบ chat ปลายทาง")

    return int(update.effective_chat.id)


def _build_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(SEND_BUTTONS)


def _is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and int(user.id) in SEND_ALLOWED_USER_IDS)


async def _send_success_reply(msg, target_chat_id: int) -> None:
    try:
        await msg.reply_text(f"ส่งแล้ว ✅\nปลายทาง: {target_chat_id}")
    except Exception:
        pass


async def send_with_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ใช้งานได้ 3 แบบ

    1) /send ข้อความที่ต้องการส่ง
    2) Reply ข้อความ/รูป/วิดีโอ/ไฟล์ แล้วพิมพ์ /send
    3) Reply ข้อความ/รูป/วิดีโอ/ไฟล์ แล้วพิมพ์ /send ข้อความใหม่
       -> จะใช้ข้อความใหม่แทน text/caption เดิม
    """
    msg = update.effective_message
    if not msg:
        return

    if not _is_allowed(update):
        return

    try:
        target_chat_id = _resolve_target_chat_id(update)
        reply_markup = _build_markup()
        typed_text = " ".join(context.args).strip()
        replied = msg.reply_to_message

        # -------------------------
        # กรณี reply ข้อความ/สื่อเดิม
        # -------------------------
        if replied:
            override_text = typed_text or None

            if replied.photo:
                await context.bot.send_photo(
                    chat_id=target_chat_id,
                    photo=replied.photo[-1].file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            if replied.video:
                await context.bot.send_video(
                    chat_id=target_chat_id,
                    video=replied.video.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            if replied.document:
                await context.bot.send_document(
                    chat_id=target_chat_id,
                    document=replied.document.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            if replied.animation:
                await context.bot.send_animation(
                    chat_id=target_chat_id,
                    animation=replied.animation.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            if replied.voice:
                await context.bot.send_voice(
                    chat_id=target_chat_id,
                    voice=replied.voice.file_id,
                    caption=override_text if override_text is not None else (replied.caption or ""),
                    reply_markup=reply_markup,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            base_text = override_text if override_text is not None else (replied.text or replied.caption or "")
            if base_text:
                await context.bot.send_message(
                    chat_id=target_chat_id,
                    text=base_text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                await _send_success_reply(msg, target_chat_id)
                return

            await msg.reply_text("ข้อความที่ reply ยังไม่รองรับนะ")
            return

        # -------------------------
        # กรณีพิมพ์ /send ข้อความตรงๆ
        # -------------------------
        if typed_text:
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=typed_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            await _send_success_reply(msg, target_chat_id)
            return

        await msg.reply_text(
            "ใช้แบบนี้นะ:\n"
            "• /send ข้อความที่ต้องการส่ง\n"
            "• หรือ reply ข้อความ/รูป แล้วพิมพ์ /send\n"
            "• หรือ reply ข้อความ/รูป แล้วพิมพ์ /send ข้อความใหม่"
        )
    except Exception as e:
        try:
            await msg.reply_text(f"ส่งไม่สำเร็จ ❌\n{e}")
        except Exception:
            pass


def build_send_handlers() -> Sequence[CommandHandler]:
    return [CommandHandler("send", send_with_buttons)]
