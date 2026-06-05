import os
import re
import time
import json
import sqlite3
import asyncio
import logging
from urllib.parse import urlparse, parse_qs

import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# ตั้งค่า
# =========================
TOKEN = os.environ.get("BOT_TOKEN")

ADMIN_ID = 6682802546
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1003320213852"))
TICKET_FORWARD_GROUP_ID = int(os.environ.get("TICKET_FORWARD_GROUP_ID", "-1003779176416"))

API_KEY = "b2f844f9782b0e48b0d820c8605ab396"
PHONE_NUMBER = "0937919184"
API_URL = "https://www.planariashop.com/api/truewallet.php"

VIP_MIN_AMOUNT = 699
VIP_LINK = "https://t.me/+dcRrL46iACs0MTQ1"

DB_PATH = "used_v.sqlite3"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# =========================
# DB กันซ้ำ
# =========================
def init_used_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS used_v (
            v TEXT PRIMARY KEY,
            amount REAL,
            raw_result TEXT,
            created_at INTEGER,
            used_at TEXT,
            user_id INTEGER
        )
    """)
    try:
        cur.execute("ALTER TABLE used_v ADD COLUMN used_at TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE used_v ADD COLUMN user_id INTEGER")
    except Exception:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_balance (
            user_id INTEGER PRIMARY KEY,
            total_paid REAL NOT NULL DEFAULT 0,
            updated_at INTEGER
        )
    """)
    conn.commit()
    conn.close()

def is_v_used(v: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM used_v WHERE v = ? LIMIT 1", (v,))
    row = cur.fetchone()
    conn.close()
    return row is not None

def get_v_info(v: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT v, amount, raw_result, created_at, used_at, user_id FROM used_v WHERE v = ? LIMIT 1",
        (v,)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    raw_result = None
    try:
        raw_result = json.loads(row[2]) if row[2] else None
    except Exception:
        raw_result = row[2]

    return {
        "v": row[0],
        "amount": float(row[1] or 0),
        "raw_result": raw_result,
        "created_at": row[3],
        "used_at": row[4],
        "user_id": row[5],
    }

def mark_v_used(v: str, amount: float, raw_result: dict, user_id: int, used_at: str | None = None) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO used_v (v, amount, raw_result, created_at, used_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (v, amount, json.dumps(raw_result, ensure_ascii=False), int(time.time()), used_at, int(user_id))
    )
    conn.commit()
    conn.close()

def get_user_total(user_id: int) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_paid FROM user_balance WHERE user_id = ? LIMIT 1", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    try:
        return float(row[0] or 0) if row else 0.0
    except Exception:
        return 0.0

def add_user_total(user_id: int, amount: float) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    current = get_user_total(int(user_id))
    new_total = float(current) + float(amount or 0)
    cur.execute(
        "INSERT OR REPLACE INTO user_balance (user_id, total_paid, updated_at) VALUES (?, ?, ?)",
        (int(user_id), new_total, int(time.time()))
    )
    conn.commit()
    conn.close()
    return new_total

def balance_text(total: float) -> str:
    if total >= VIP_MIN_AMOUNT:
        return (
            "💎 JOIN GROUP VIP\n"
            f"💰 Balance: {int(total)} บาท\n"
            "━━━━━━━━━━━━━━"
        )
    return (
        "⚠️ ตรวจพบยอดเงินไม่พอค่ะ\n"
        f"💰 Balance: {int(total)}/{VIP_MIN_AMOUNT}"
    )

def basic_verify_truemoney_link(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and parsed.netloc in ("gift.truemoney.com", "gift.truemoney.com:443")
            and parsed.path.startswith("/campaign/")
        )
    except Exception:
        return False

def extract_truemoney_v(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        v = qs.get("v", [None])[0]
        return v
    except Exception:
        return None

def is_valid_truemoney_v(v: str | None) -> bool:
    if not v:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]+", v))

# =========================
# API
# =========================
def check_wallet(link: str) -> dict:
    data = {
        "keyapi": API_KEY,
        "phone": PHONE_NUMBER,
        "gift_link": link,
    }
    try:
        res = requests.post(API_URL, data=data, timeout=20)
        return res.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def wallet_amount(result: dict) -> float:
    try:
        return float(result.get("amount") or 0)
    except Exception:
        return 0.0

def wallet_is_success(result: dict) -> bool:
    return str(result.get("status", "")).lower() == "success"

def wallet_fail_text(result: dict) -> str:
    msg = str(result.get("message", "") or "").lower()
    raw = str(result).lower()

    opened_words = [
        "opened", "already redeemed", "used", "redeemed",
        "ใช้ไปแล้ว", "ถูกใช้ไปแล้ว", "เปิดแล้ว", "ซองถูกเปิด"
    ]

    if any(w in msg for w in opened_words) or any(w in raw for w in opened_words):
        return "❌ ลิ้งนี้เคยถูกใช้แล้ว แต่ยังไม่มีข้อมูลเก่าพอให้ยืนยันยอด"

    return "❌ ไม่พบข้อมูลลิ้งนี้ กรุณาส่งใหม่"

# =========================
# ข้อความหลังบ้าน
# =========================
async def notify_admin_result(
    context: ContextTypes.DEFAULT_TYPE,
    sender: str,
    sender_id: int,
    url: str,
    result: dict,
) -> None:
    try:
        amount = wallet_amount(result)
        status = str(result.get("status", "")).lower()
        msg = str(result.get("message", "") or "-")
        owner = result.get("owner_profile", "-")
        redeemer = result.get("redeemer_profile", "-")
        when = result.get("time", "-")

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "📩 ผลตรวจลิ้งล่าสุด\n"
                f"ผู้ส่ง: {sender}\n"
                f"User ID: {sender_id}\n"
                f"สถานะ: {status}\n"
                f"ยอด: {amount}\n"
                f"เจ้าของซอง: {owner}\n"
                f"ผู้รับ: {redeemer}\n"
                f"เวลา: {when}\n"
                f"message: {msg}\n"
            )
        )
    except Exception as e:
        logging.warning("notify admin failed: %s", e)

# =========================
# Bot handlers
# =========================

async def send_vip_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    await msg.reply_text(f"✅ {VIP_LINK}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ส่งลิ้งซองทรูมาได้เลย ระบบจะตรวจให้อัตโนมัติ")

async def tw_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    raw_text = (msg.text or "").strip()

    if raw_text.startswith("/tw "):
        url = raw_text.replace("/tw ", "", 1).strip()
    else:
        url = raw_text

    url = url.strip().rstrip(').,;:\'" }]> 
	')

    if not basic_verify_truemoney_link(url):
        await msg.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
        return

    v = extract_truemoney_v(url)
    if not is_valid_truemoney_v(v):
        await msg.reply_text("❌ ไม่พบลิ้งค์ กรุณาส่งใหม่")
        return

    sender = update.effective_user.full_name if update.effective_user else "Unknown"
    sender_id = update.effective_user.id if update.effective_user else 0

    # 1) ถ้าเคยมีข้อมูลเก่าแล้ว ให้ใช้ข้อมูลเก่าตัดสินทันที
    remembered = get_v_info(v)
    if remembered:
        remembered_owner = int(remembered.get("user_id") or sender_id or 0)
        total_paid = get_user_total(remembered_owner)
        await notify_admin_result(
            context,
            sender,
            sender_id,
            url,
            remembered.get("raw_result") if isinstance(remembered.get("raw_result"), dict) else {
                "status": "remembered",
                "message": "used remembered result",
                "amount": remembered.get("amount", 0),
                "time": remembered.get("used_at", "-"),
            },
        )
        await msg.reply_text(balance_text(total_paid))
        if total_paid >= VIP_MIN_AMOUNT:
            await send_vip_link(update, context)
        return

    # 2) ยังไม่เคยมีข้อมูลเก่า -> ค่อยยิง API ครั้งแรก
    wait_msg = await msg.reply_text("⏳ กำลังตรวจสอบลิ้งค์")

    try:
        result = await asyncio.to_thread(check_wallet, url)

        await notify_admin_result(context, sender, sender_id, url, result)

        try:
            await wait_msg.delete()
        except Exception:
            pass

        if wallet_is_success(result):
            amount = wallet_amount(result)
            mark_v_used(v, amount, result, sender_id, result.get("time"))
            total_paid = add_user_total(sender_id, amount)

            await msg.reply_text(balance_text(total_paid))
            if total_paid >= VIP_MIN_AMOUNT:
                await send_vip_link(update, context)
        else:
            await msg.reply_text(wallet_fail_text(result))

    except Exception as e:
        try:
            await wait_msg.delete()
        except Exception:
            pass
        await msg.reply_text(f"❌ เกิดข้อผิดพลาด: {e}")

def should_check_text(text: str) -> bool:
    text = (text or "").strip()
    return (
        text.startswith("/tw ")
        or "https://gift.truemoney.com/campaign/?v=" in text
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    text = (msg.text or "").strip()
    if should_check_text(text):
        await tw_check(update, context)

def main():
    if not TOKEN:
        raise RuntimeError("กรุณาตั้งค่า BOT_TOKEN ใน environment ก่อน")

    init_used_db()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tw", tw_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("VIP wallet bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
