import os
import random
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

DB_PATH = "random_game.sqlite3"
IMAGE_ROOT = "images"
FOLDER_MAP = {
    "normal": "normal",
    "rare": "rare",
    "secret": "secret",
}
STAR_CAPTION = {
    "normal": "⭐️",
    "rare": "⭐️⭐️",
    "secret": "⭐️⭐️⭐️",
}
MAX_PER_DAY = 3
USER_LOCKS: set[int] = set()


def _conn():
    return sqlite3.connect(DB_PATH)


def init_random_game_db() -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS random_daily (
            user_id INTEGER PRIMARY KEY,
            day_key TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            info_sent INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS random_user_state (
            user_id INTEGER PRIMARY KEY,
            secret_rate INTEGER NOT NULL DEFAULT 20
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS random_used_images (
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            filename TEXT NOT NULL,
            used_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, category, filename)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS random_last_message (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _next_reset_text() -> str:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.strftime("%d/%m %H:%M")


def _ensure_daily_row(user_id: int):
    day_key = _today_key()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT day_key, count, info_sent FROM random_daily WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            "INSERT INTO random_daily (user_id, day_key, count, info_sent) VALUES (?, ?, 0, 0)",
            (user_id, day_key),
        )
        conn.commit()
        conn.close()
        return day_key, 0, 0

    saved_day, count, info_sent = row
    if saved_day != day_key:
        cur.execute(
            "UPDATE random_daily SET day_key=?, count=0, info_sent=0 WHERE user_id=?",
            (day_key, user_id),
        )
        conn.commit()
        conn.close()
        return day_key, 0, 0

    conn.close()
    return saved_day, count, info_sent


def _get_daily_count(user_id: int) -> int:
    _, count, _ = _ensure_daily_row(user_id)
    return int(count)


def _get_info_sent(user_id: int) -> int:
    _, _, info_sent = _ensure_daily_row(user_id)
    return int(info_sent)


def _mark_info_sent(user_id: int) -> None:
    _ensure_daily_row(user_id)
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE random_daily SET info_sent=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def _increase_daily_count(user_id: int) -> int:
    _ensure_daily_row(user_id)
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE random_daily SET count=count+1 WHERE user_id=?", (user_id,))
    conn.commit()
    cur.execute("SELECT count FROM random_daily WHERE user_id=?", (user_id,))
    count = int(cur.fetchone()[0])
    conn.close()
    return count


def get_random_menu_label(chat_id: int, user_id: int) -> str:
    count = _get_daily_count(user_id)
    if count > MAX_PER_DAY:
        count = MAX_PER_DAY
    return f"🎲สุ่มภาพลับ({count}/{MAX_PER_DAY})"


def _get_secret_rate(user_id: int) -> int:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT secret_rate FROM random_user_state WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO random_user_state (user_id, secret_rate) VALUES (?, 20)", (user_id,))
        conn.commit()
        conn.close()
        return 20
    conn.close()
    return int(row[0])


def _set_secret_rate(user_id: int, rate: int) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO random_user_state (user_id, secret_rate)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET secret_rate=excluded.secret_rate
        """,
        (user_id, rate),
    )
    conn.commit()
    conn.close()


def _get_files(category: str) -> list[str]:
    folder = os.path.join(IMAGE_ROOT, FOLDER_MAP[category])
    if not os.path.isdir(folder):
        return []
    return sorted([
        f for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])


def _get_used_files(user_id: int, category: str) -> set[str]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT filename FROM random_used_images WHERE user_id=? AND category=?",
        (user_id, category),
    )
    rows = cur.fetchall()
    conn.close()
    return {r[0] for r in rows}


def _mark_used_file(user_id: int, category: str, filename: str) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO random_used_images (user_id, category, filename, used_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, category, filename, int(time.time())),
    )
    conn.commit()
    conn.close()


def _clear_used_category(user_id: int, category: str) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM random_used_images WHERE user_id=? AND category=?", (user_id, category))
    conn.commit()
    conn.close()


def _remaining_count(user_id: int, category: str) -> int:
    all_files = _get_files(category)
    used = _get_used_files(user_id, category)
    return len([f for f in all_files if f not in used])


def _pick_category(user_id: int) -> str:
    secret_rate = _get_secret_rate(user_id)  # 20 -> 15 -> 10
    remain = 100 - secret_rate
    normal_rate = remain // 2
    rare_rate = remain - normal_rate
    r = random.randint(1, 100)
    if r <= normal_rate:
        return "normal"
    if r <= normal_rate + rare_rate:
        return "rare"
    return "secret"


def _pick_image_for_user(user_id: int, category: str) -> Optional[str]:
    all_files = _get_files(category)
    if not all_files:
        return None
    used = _get_used_files(user_id, category)
    available = [f for f in all_files if f not in used]
    if not available:
        _clear_used_category(user_id, category)
        available = all_files[:]
    chosen = random.choice(available)
    _mark_used_file(user_id, category, chosen)
    return chosen


def _after_secret_win(user_id: int) -> None:
    used_secret_count = len(_get_used_files(user_id, "secret"))
    current = _get_secret_rate(user_id)

    if current == 20 and used_secret_count >= 1:
        _set_secret_rate(user_id, 15)
        current = 15
    if current == 15 and used_secret_count >= 3:
        _set_secret_rate(user_id, 10)
        current = 10

    # ที่ 10% ไปเรื่อย ๆ จนเหลือรูปให้สุ่มอีกแค่ 5 รูป -> รีเซ็ตกลับ
    remaining = _remaining_count(user_id, "secret")
    if current == 10 and remaining <= 5:
        _clear_used_category(user_id, "secret")
        _set_secret_rate(user_id, 20)


async def _delete_last_random_message(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, message_id FROM random_last_message WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return
    chat_id, message_id = int(row[0]), int(row[1])
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def _save_last_random_message(user_id: int, chat_id: int, message_id: int) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO random_last_message (user_id, chat_id, message_id)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, message_id=excluded.message_id
        """,
        (user_id, chat_id, message_id),
    )
    conn.commit()
    conn.close()


def _clear_last_random_message(user_id: int) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM random_last_message WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


async def handle_random_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return False

    data = query.data or ""
    user_id = int(update.effective_user.id)
    chat_id = int(update.effective_chat.id)

    if data == "random:close":
        try:
            _clear_last_random_message(user_id)
            await query.message.delete()
        except Exception:
            pass
        try:
            await query.answer()
        except Exception:
            pass
        return True

    if data != "menu:random_image":
        return False

    try:
        await query.answer()
    except Exception:
        pass

    if user_id in USER_LOCKS:
        try:
            await query.answer("กำลังสุ่มอยู่ รอสักครู่", show_alert=False)
        except Exception:
            pass
        return True

    USER_LOCKS.add(user_id)
    try:
        count = _get_daily_count(user_id)
        if count >= MAX_PER_DAY:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"วันนี้สุ่มครบ {MAX_PER_DAY} ครั้งแล้ว\nเริ่มใหม่ได้ {_next_reset_text()}"
            )
            return True

        if _get_info_sent(user_id) == 0:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⭐ ภาพธรรมดา\n⭐⭐ ภาพหายาก\n⭐⭐⭐ ภาพลับ"
            )
            _mark_info_sent(user_id)

        await _delete_last_random_message(context, user_id)

        category = _pick_category(user_id)
        filename = _pick_image_for_user(user_id, category)
        if not filename:
            await context.bot.send_message(chat_id=chat_id, text="ยังไม่มีรูปในหมวดนี้")
            return True

        if category == "secret":
            _after_secret_win(user_id)

        new_count = _increase_daily_count(user_id)
        image_path = os.path.join(IMAGE_ROOT, FOLDER_MAP[category], filename)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ปิด", callback_data="random:close")]
        ])
        with open(image_path, "rb") as f:
            sent = await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=STAR_CAPTION[category],
                reply_markup=kb,
            )
        _save_last_random_message(user_id, chat_id, sent.message_id)

        # update menu counter on original menu message
        try:
            menu_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 ชำระเงิน", callback_data="menu:payment")],
                [InlineKeyboardButton("📊 สถิติระบบ", callback_data="menu:stats")],
                [InlineKeyboardButton("🎫 แจ้งปัญหา", callback_data="menu:ticker")],
                [InlineKeyboardButton(f"🎲สุ่มภาพลับ({new_count}/{MAX_PER_DAY})", callback_data="menu:random_image")],
            ])
            await query.edit_message_reply_markup(reply_markup=menu_markup)
        except Exception:
            pass

        return True
    finally:
        USER_LOCKS.discard(user_id)
