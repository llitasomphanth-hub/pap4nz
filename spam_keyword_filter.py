"""
spam_keyword_filter.py
ตัวช่วยกรอง/แบนข้อความสแปมแนวโปรโมตพนัน สำหรับใช้ร่วมกับ bot.py

วิธีใช้แบบสั้น:
1) วางไฟล์นี้ไว้โฟลเดอร์เดียวกับ bot.py
2) ใน bot.py:
    from spam_keyword_filter import should_ban_text, ban_message_if_needed

3) ใน handler ข้อความ:
    async def on_text(update, context):
        if await ban_message_if_needed(update, context):
            return
        # ... โค้ดเดิมของคุณต่อจากนี้

หมายเหตุ:
- รองรับ python-telegram-bot แบบ async
- ถ้าเจอคำต้องห้ามในข้อความหรือ caption จะ:
    1) ลบข้อความ
    2) แบนผู้ใช้
    3) ส่งข้อความแจ้งในกลุ่ม (ถ้าส่งได้)
- ข้ามแอดมิน/เจ้าของกลุ่มอัตโนมัติ
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

DEFAULT_BAN_KEYWORDS = [
    "เครดิตฟรี",
    "สล๊อต",
    "สล็อต",
    "แตก",
    "โบนัส",
    "แจกฟรี",
    "ฝาก",
    "ถอน",
    "จิ้ม",
    "คลิก",
    "คลิ๊ก",
    "สมาชิก",
    "ค่าย",
    "ทุนฟรี",
]


@dataclass
class BanMatchResult:
    matched: bool
    keyword: Optional[str] = None
    source_text: str = ""


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.lower().replace("\n", " ").strip()


def should_ban_text(
    text: str,
    keywords: Optional[Iterable[str]] = None,
) -> BanMatchResult:
    keywords = list(keywords or DEFAULT_BAN_KEYWORDS)
    clean = normalize_text(text)

    if not clean:
        return BanMatchResult(matched=False, source_text="")

    for kw in keywords:
        kw_clean = normalize_text(str(kw))
        if kw_clean and kw_clean in clean:
            return BanMatchResult(
                matched=True,
                keyword=kw,
                source_text=clean,
            )

    return BanMatchResult(matched=False, source_text=clean)


async def _is_admin_or_owner(update, context) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def ban_message_if_needed(
    update,
    context,
    keywords: Optional[Iterable[str]] = None,
    notify_chat: bool = True,
) -> bool:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not msg or not chat or not user:
        return False

    if str(chat.type).lower() == "private":
        return False

    if await _is_admin_or_owner(update, context):
        return False

    content = msg.text or msg.caption or ""
    result = should_ban_text(content, keywords=keywords)

    if not result.matched:
        return False

    try:
        await msg.delete()
    except Exception:
        pass

    try:
        await context.bot.ban_chat_member(chat.id, user.id)
    except Exception:
        pass

    if notify_chat:
        try:
            name = user.full_name or f"user:{user.id}"
            await context.bot.send_message(
                chat.id,
                (
                    f"🚫 แบนอัตโนมัติ\n"
                    f"ผู้ใช้: {name}\n"
                    f"เหตุผล: พบคำต้องห้าม '{result.keyword}'"
                ),
            )
        except Exception:
            pass

    return True
