import asyncio
import random
import sqlite3
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

DB_NAME = "random_game.db"
IMAGE_ROOT = Path("images")

def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ensure_schema() -> None:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS random_usage (
            user_id INTEGER PRIMARY KEY,
            day_key TEXT,
            used INTEGER DEFAULT 0,
            secret_got_count INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS random_used_images (
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            filename TEXT NOT NULL,
            PRIMARY KEY (user_id, category, filename)
        )
    """)

    cur.execute("PRAGMA table_info(random_usage)")
    cols = {row[1] for row in cur.fetchall()}
    if "day_key" not in cols:
        cur.execute("ALTER TABLE random_usage ADD COLUMN day_key TEXT")
    if "used" not in cols:
        cur.execute("ALTER TABLE random_usage ADD COLUMN used INTEGER DEFAULT 0")
    if "secret_got_count" not in cols:
        cur.execute("ALTER TABLE random_usage ADD COLUMN secret_got_count INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


def init_random_game_db() -> None:
    _ensure_schema()


def _ensure_user_row(cur: sqlite3.Cursor, user_id: int) -> tuple[int, int]:
    today = _today_key()
    cur.execute(
        "SELECT day_key, used, secret_got_count FROM random_usage WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        cur.execute(
            "INSERT INTO random_usage (user_id, day_key, used, secret_got_count) VALUES (?, ?, 0, 0)",
            (user_id, today),
        )
        return 0, 0

    day_key, used, secret_got_count = row

    if day_key != today:
        cur.execute(
            "UPDATE random_usage SET day_key=?, used=0 WHERE user_id=?",
            (today, user_id),
        )
        used = 0

    return int(used or 0), int(secret_got_count or 0)


def get_random_menu_label(chat_id, user_id) -> str:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    used, _secret_got_count = _ensure_user_row(cur, int(user_id))
    conn.commit()
    conn.close()
    return f"🎲สุ่มภาพลับ ({used}/3)"


def _build_random_menu_markup(chat_id, user_id):
    """คืนเมนูหลักรูปแบบเดียวกับ v23/v25 โดยแก้เฉพาะปุ่ม ไม่ส่งข้อความใหม่"""
    random_label = get_random_menu_label(chat_id, user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳  วิธีชำระเงิน", callback_data="menu:payment")],
        [InlineKeyboardButton("🛎️ โปรโมชั่นล่าสุด", callback_data="menu:promo")],
        [InlineKeyboardButton("📝  อ่านเครดิต-รีวิว", url="https://t.me/reviwdelight")],
        [InlineKeyboardButton("🎫  สอบถาม/แจ้งปัญหา", callback_data="menu:ticker")],
        [
            InlineKeyboardButton("📊 สถิติระบบ", callback_data="menu:stats"),
            InlineKeyboardButton(random_label, callback_data="menu:random_image"),
        ],
    ])


def _secret_rate_for_count(secret_got_count: int) -> int:
    if secret_got_count >= 3:
        return 10
    if secret_got_count >= 1:
        return 15
    return 20


def _list_images(category: str) -> list[str]:
    folder = IMAGE_ROOT / category
    if not folder.exists():
        return []
    valid_ext = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted([p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in valid_ext])


def _get_used_images(cur: sqlite3.Cursor, user_id: int, category: str) -> set[str]:
    cur.execute(
        "SELECT filename FROM random_used_images WHERE user_id=? AND category=?",
        (user_id, category),
    )
    return {row[0] for row in cur.fetchall()}


def _clear_used_category(cur: sqlite3.Cursor, user_id: int, category: str) -> None:
    cur.execute(
        "DELETE FROM random_used_images WHERE user_id=? AND category=?",
        (user_id, category),
    )


def _mark_used_image(cur: sqlite3.Cursor, user_id: int, category: str, filename: str) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO random_used_images (user_id, category, filename) VALUES (?, ?, ?)",
        (user_id, category, filename),
    )


def _pick_non_duplicate_image(cur: sqlite3.Cursor, user_id: int, category: str) -> str | None:
    all_images = _list_images(category)
    if not all_images:
        return None

    used_images = _get_used_images(cur, user_id, category)
    available = [name for name in all_images if name not in used_images]

    # เหลือ 5 รูปค่อยรีเซ็ตให้ซ้ำได้อีก (ต่อคน ต่อหมวด)
    if len(available) <= 5:
        _clear_used_category(cur, user_id, category)
        available = all_images[:]

    return random.choice(available) if available else None


async def _delete_message_silent(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def handle_random_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return False

    data = query.data or ""

    if data not in {"menu:random_image", "close_random"}:
        return False

    user_id = int(update.effective_user.id)
    chat_id = int(query.message.chat_id)

    if data == "close_random":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data.pop("last_random_msg", None)
        old_loading = context.user_data.pop("loading_msg", None)
        await _delete_message_silent(context, chat_id, old_loading)
        try:
            await query.answer()
        except Exception:
            pass
        return True

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    used, secret_got_count = _ensure_user_row(cur, user_id)

    if used >= 3:
        conn.commit()
        conn.close()
        try:
            await query.answer("❌ ใช้ครบแล้ว\nเริ่มใหม่ 07:00", show_alert=True)
        except Exception:
            pass
        return True

    old_photo = context.user_data.get("last_random_msg")
    await _delete_message_silent(context, chat_id, old_photo)
    context.user_data.pop("last_random_msg", None)

    old_loading = context.user_data.get("loading_msg")
    await _delete_message_silent(context, chat_id, old_loading)
    context.user_data.pop("loading_msg", None)

    loading_msg = await query.message.reply_text("⏳ กำลังสุ่มภาพ...")
    context.user_data["loading_msg"] = loading_msg.message_id

    await asyncio.sleep(2)

    secret_all = _list_images("secret")
    if secret_all:
        secret_used = _get_used_images(cur, user_id, "secret")
        secret_available = [x for x in secret_all if x not in secret_used]
        if len(secret_available) <= 5:
            _clear_used_category(cur, user_id, "secret")
            secret_got_count = 0

    secret_rate = _secret_rate_for_count(secret_got_count)
    remain = 100 - secret_rate
    normal_rate = remain // 2
    rare_rate = remain - normal_rate

    stars = random.choices([1, 2, 3], weights=[normal_rate, rare_rate, secret_rate])[0]
    star_text = "⭐️" * stars

    if stars == 1:
        category = "normal"
    elif stars == 2:
        category = "rare"
    else:
        category = "secret"

    filename = _pick_non_duplicate_image(cur, user_id, category)
    if not filename:
        conn.commit()
        conn.close()
        await _delete_message_silent(context, chat_id, loading_msg.message_id)
        context.user_data.pop("loading_msg", None)
        try:
            await query.answer(f"ยังไม่มีรูปในหมวด {category}", show_alert=True)
        except Exception:
            pass
        return True

    image_path = IMAGE_ROOT / category / filename

    await _delete_message_silent(context, chat_id, loading_msg.message_id)
    context.user_data.pop("loading_msg", None)

    if used == 0:
        await query.message.reply_text(
            "🎲 คะแนนสุ่ม:\n\n"
            "⭐️ ภาพธรรมดา\n"
            "⭐️⭐️ ภาพหายาก\n"
            "⭐️⭐️⭐️ ภาพสุดลับบ !"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ปิด", callback_data="close_random")]
    ])

    with open(image_path, "rb") as f:
        sent = await query.message.reply_photo(
            photo=f,
            caption=star_text,
            reply_markup=keyboard,
        )

    context.user_data["last_random_msg"] = sent.message_id

    _mark_used_image(cur, user_id, category, filename)

    if stars == 3:
        secret_got_count += 1

    cur.execute(
        "UPDATE random_usage SET day_key=?, used=?, secret_got_count=? WHERE user_id=?",
        (_today_key(), used + 1, secret_got_count, user_id),
    )

    conn.commit()
    conn.close()

    try:
        await query.edit_message_reply_markup(
            reply_markup=_build_random_menu_markup(chat_id, user_id)
        )
    except Exception:
        pass

    try:
        await query.answer()
    except Exception:
        pass
    return True
