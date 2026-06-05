from __future__ import annotations
from fastapi import UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
import shutil
import os
import re
import sqlite3
import time
from collections import Counter
import json
import base64
from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import urlencode

import jwt

from fastapi import FastAPI, HTTPException, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import packages_v
from result_api import register_result_feed_provider, register_result_source_provider, router as result_api_router

# 🔑 ตั้งค่าฐานข้อมูลร่วมกัน (ดึงค่าเชื่อมต่อฐานข้อมูลตัวเดียวกันกับบอทหลัก)
DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")
TMN_WEBHOOK_SECRET = os.environ.get("TMN_WEBHOOK_SECRET", "").strip()
TMN_WEBHOOK_URL = os.environ.get("TMN_WEBHOOK_URL", "https://papxnzvip.com/webhook/tmn").strip()

# ใช้โฟลเดอร์เดียวกับไฟล์เว็บจริง: /root/papxnz_web/images
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "images")
STATIC_ROOT = os.path.join(BASE_DIR, "static")
OVERLAY_DIR = os.path.join(STATIC_ROOT, "package_overlays")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(OVERLAY_DIR, exist_ok=True)

app = FastAPI(title="Papan VIP CENTRAL Dashboard")
app.include_router(result_api_router)

app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

TG_LINK_RE = re.compile(r'https?://t\.me/[^\s<>\'\"]+')
TM_LINK_RE = re.compile(r"https?://gift\.truemoney\.com/campaign/\S+")


def _clean_group_id(raw: str, field_name: str) -> str:
    value = (raw or "").strip()
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "t.me/", "@", "+")):
        raise HTTPException(status_code=400, detail=f"{field_name} must be Telegram Group ID like -100xxxxxxxxxx, not an invite link")
    if not value.startswith("-100") or not value[1:].isdigit():
        raise HTTPException(status_code=400, detail=f"{field_name} must be Telegram Group ID like -100xxxxxxxxxx")
    return value

ALLOWED_PACKAGE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _safe_image_ext(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in ALLOWED_PACKAGE_IMAGE_EXTS else ".webp"


def _add_column_if_missing(cur: sqlite3.Cursor, table_name: str, column_name: str, column_sql: str) -> None:
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = {str(row[1]) for row in cur.fetchall()}
    if column_name in columns:
        return
    try:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
    except Exception:
        pass



def _save_package_cover_data(data_url: str, slot: str) -> str:
    """รับรูปที่ครอปจากหน้าเว็บแบบ data URL แล้วเซฟเป็น /images/...webp"""
    raw_data = (data_url or "").strip()
    if not raw_data or "," not in raw_data or not raw_data.startswith("data:image/"):
        return ""

    try:
        header, b64 = raw_data.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        return ""

    if not raw:
        return ""

    os.makedirs(IMAGE_DIR, exist_ok=True)
    safe_slot = re.sub(r"[^a-zA-Z0-9_-]", "", slot or "package") or "package"
    filename = f"{safe_slot}_{int(time.time())}.webp"
    abs_path = os.path.join(IMAGE_DIR, filename)

    try:
        from io import BytesIO
        from PIL import Image, ImageOps

        img = Image.open(BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.save(abs_path, "WEBP", quality=86, method=6)
        return f"/images/{filename}"
    except Exception:
        # ถ้าไม่มี Pillow ให้เซฟ raw เป็น .webp ตามที่ browser ส่งมา
        try:
            with open(abs_path, "wb") as f:
                f.write(raw)
            return f"/images/{filename}"
        except Exception:
            return ""

def _conn():
    return sqlite3.connect(DB_PATH)

def _ensure_tables():
    conn = _conn()
    cur = conn.cursor()
    # 1. ตารางบันทึกประวัติข้อความของระบบเดิม
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            direction TEXT NOT NULL,
            msg_id INTEGER,
            msg_type TEXT,
            text TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_ts ON chat_messages(chat_id, ts)")
    
    # 2. ตารางบล็อกผู้ใช้ของระบบเดิม
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            chat_id INTEGER PRIMARY KEY,
            blocked_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    
    # 3. ตารางบันทึกเหตุการณ์ Webhook ของระบบเดิม
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            source TEXT NOT NULL,
            event_type TEXT,
            amount TEXT,
            sender_mobile TEXT,
            transaction_id TEXT UNIQUE,
            raw_payload TEXT,
            verify_ok INTEGER NOT NULL DEFAULT 0,
            note TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events_ts ON webhook_events(ts DESC)")

    # 4. ตารางคุมตั๋วตรวจซองล่มแฮนด์เมดเชื่อมบอทและหน้าเว็บ (Yes/No ตัวแม่)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_error_payment_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender TEXT,
            url TEXT,
            v TEXT UNIQUE,
            amount REAL DEFAULT 0.0,
            raw_result TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT (strftime('%s','now')),
            reviewed_at INTEGER
        )
        """
    )

    # 5. ตารางกลางสำหรับรองรับการเก็บข้อมูลฟอร์มกรอกตั้งค่าราคาแยกกลุ่มของพะแพน
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vip_tier_config (
            tier_id INTEGER PRIMARY KEY,
            tier_name TEXT,
            min_amount REAL,
            group_link TEXT
        )
        """
    )
    # ใส่ค่าระบบเริ่มต้นกันตารางว่างเปล่า
    cur.execute("INSERT OR IGNORE INTO vip_tier_config (tier_id, tier_name, min_amount, group_link) VALUES (3, 'Tier 3 (กลุ่มหลัก)', 899.0, '-1003320213852')")
    cur.execute("INSERT OR IGNORE INTO vip_tier_config (tier_id, tier_name, min_amount, group_link) VALUES (2, 'Tier 2 (กลุ่มกลาง)', 500.0, '-1003320213852')")
    cur.execute("INSERT OR IGNORE INTO vip_tier_config (tier_id, tier_name, min_amount, group_link) VALUES (1, 'Tier 1 (กลุ่มเริ่ม)', 300.0, '-1003320213852')")

    # 6. ตารางตั้งค่าหน้าแพ็กเกจ เชื่อมกับ packages_v.py
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS package_page_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    package_defaults = {
        "page_title": "เลือกแพ็กเกจ VIP",
        "page_subtitle": "ยกระดับบอทส่วนตัวของคุณด้วยฟีเจอร์พรีเมียม",
        "server_text": "SERVER ONLINE 24HR",
        "back_text": "กลับหน้าหลัก",
        "p1_icon": "star", "p1_name": "VIP Starter", "p1_price": "199", "p1_unit": "บาท / 30 วัน",
        "p1_feature1": "ปลดล็อกเข้ากลุ่มลับ VIP Access Link ได้ทันที", "p1_feature2": "ระบบตรวจสอบยอดเติมเงินออโต้ 24 ชั่วโมง",
        "p1_feature3": "", "p1_feature4": "", "p1_feature5": "",
        "p1_btn": "สมัครแพ็กเกจนี้", "p1_sub_btn": "ดูตัวอย่าง", "p1_cover": "",
        "p2_icon": "crown", "p2_name": "VIP Pro Pass", "p2_price": "499", "p2_unit": "บาท / 90 วัน",
        "p2_feature1": "รวมสรรพคุณของระดับ Starter ทั้งหมดไว้ครบ", "p2_feature2": "ความเร็วประมวลผลคิวพิเศษ (Fast Pass VIP)",
        "p2_feature3": "", "p2_feature4": "", "p2_feature5": "",
        "p2_btn": "สมัครแพ็กเกจนี้", "p2_sub_btn": "ดูตัวอย่าง", "p2_badge": "RECOMMENDED", "p2_cover": "",
        "p3_icon": "flame", "p3_name": "VIP Lifetime", "p3_price": "999", "p3_unit": "บาท / ตลอดชีพ",
        "p3_feature1": "จ่ายครั้งเดียวจบ ปลดล็อกทุกฟีเจอร์ถาวร 100%", "p3_feature2": "รับยศพิเศษประดับโปรไฟล์สมาชิกถาวรสุดเท่",
        "p3_feature3": "", "p3_feature4": "", "p3_feature5": "",
        "p3_btn": "สมัครแพ็กเกจนี้", "p3_sub_btn": "ดูตัวอย่าง", "p3_cover": "",
    }
    for key, value in package_defaults.items():
        cur.execute("INSERT OR IGNORE INTO package_page_config (key, value) VALUES (?, ?)", (key, value))

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS package_login_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            username TEXT,
            source TEXT,
            path TEXT,
            package_id TEXT,
            ip TEXT,
            user_agent TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS package_purchase_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            package_id TEXT,
            package_name TEXT,
            amount REAL,
            username TEXT,
            logged_in INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            source TEXT,
            path TEXT,
            ip TEXT,
            user_agent TEXT,
            bot_claimed_at INTEGER,
            bot_result TEXT,
            note TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_package_purchase_requests_ts ON package_purchase_requests(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_package_purchase_requests_status ON package_purchase_requests(status)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS package_group_button_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            action TEXT NOT NULL DEFAULT 'enter_group',
            username TEXT,
            package_name TEXT,
            invite_link TEXT,
            source TEXT,
            path TEXT,
            ip TEXT,
            user_agent TEXT,
            note TEXT
        )
        """
    )
    for column_name, column_sql in {
        "action": "action TEXT NOT NULL DEFAULT 'enter_group'",
        "username": "username TEXT",
        "package_name": "package_name TEXT",
        "invite_link": "invite_link TEXT",
        "source": "source TEXT",
        "path": "path TEXT",
        "ip": "ip TEXT",
        "user_agent": "user_agent TEXT",
        "note": "note TEXT",
    }.items():
        _add_column_if_missing(cur, "package_group_button_events", column_name, column_sql)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_package_group_button_events_ts ON package_group_button_events(ts DESC)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS package_user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            event_type TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            username TEXT,
            package_id TEXT,
            package_name TEXT,
            amount REAL,
            payment_ref TEXT,
            status TEXT,
            group_id TEXT,
            invite_link TEXT,
            source TEXT,
            path TEXT,
            ip TEXT,
            user_agent TEXT,
            raw_payload TEXT,
            note TEXT
        )
        """
    )
    for column_name, column_sql in {
        "event_type": "event_type TEXT NOT NULL DEFAULT 'custom'",
        "session_id": "session_id TEXT",
        "user_id": "user_id TEXT",
        "username": "username TEXT",
        "package_id": "package_id TEXT",
        "package_name": "package_name TEXT",
        "amount": "amount REAL",
        "payment_ref": "payment_ref TEXT",
        "status": "status TEXT",
        "group_id": "group_id TEXT",
        "invite_link": "invite_link TEXT",
        "source": "source TEXT",
        "path": "path TEXT",
        "ip": "ip TEXT",
        "user_agent": "user_agent TEXT",
        "raw_payload": "raw_payload TEXT",
        "note": "note TEXT",
    }.items():
        _add_column_if_missing(cur, "package_user_events", column_name, column_sql)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_package_user_events_ts ON package_user_events(ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_package_user_events_type ON package_user_events(event_type)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_api_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    for key, value in {
        "bot_api_url": "",
        "bot_api_token": "",
        "bot_queue_enabled": "0",
        "bot_queue_note": "webapp queues events in used_v.sqlite3",
        "bot_group_source": "vip_tier_config",
        "bot_link_permission": "administrator:can_invite_users",
        "bot_link_mode": "single_use_invite_after_approved_payment",
    }.items():
        cur.execute("INSERT OR IGNORE INTO bot_api_config (key, value) VALUES (?, ?)", (key, value))
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS result_matcher_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    for key, value in {
        "user_check_event_type": "enter_group_click",
        "purchase_event_type": "package_click",
        "success_event_type": "success_view",
        "web_source": "packages_v",
        "require_username_match": "1",
        "pending_message": "waiting for matching user/payment",
    }.items():
        cur.execute("INSERT OR IGNORE INTO result_matcher_config (key, value) VALUES (?, ?)", (key, value))
    cur.execute(
        """
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
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_group_member_events_ts ON group_member_events(ts DESC)")
    for column_name, column_sql in {
        "event_type": "event_type TEXT NOT NULL DEFAULT 'raw'",
        "group_id": "group_id TEXT",
        "invite_link": "invite_link TEXT",
        "owner_user_id": "owner_user_id INTEGER",
        "actor_user_id": "actor_user_id INTEGER",
        "actor_username": "actor_username TEXT",
        "actor_full_name": "actor_full_name TEXT",
        "amount": "amount REAL",
        "balance_before": "balance_before REAL",
        "balance_after": "balance_after REAL",
        "source": "source TEXT",
        "attempt_id": "attempt_id TEXT",
        "note": "note TEXT",
    }.items():
        _add_column_if_missing(cur, "group_member_events", column_name, column_sql)

    conn.commit()
    conn.close()

@app.on_event("startup")
def _startup():
    _ensure_tables()

def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)

def _preview(text: Optional[str], limit: int = 60) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) > limit:
        return t[:limit] + "…"
    return t or "(ไม่มีข้อความ)"

def _extract_links(text: Optional[str]):
    raw = text or ""
    return TG_LINK_RE.findall(raw), TM_LINK_RE.findall(raw)

# ========================================================
# 🎨 สไตล์ CSS ป้องกันตารางปลิ้นและบีบอัด รองรับโมบายนิ่งถาวร
# ========================================================
def _base_css() -> str:
    return """
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    html, body { margin:0; padding:0; overflow-x:hidden; background:#0f172a; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; }
    a { color:#38bdf8; text-decoration:none; }
    
    .header { padding:16px 20px; border-bottom:1px solid #1e293b; position:sticky; top:0; background:#1e293b; z-index:5; display:flex; gap:12px; align-items:center; }
    .header-copy { min-width:0; }
    .menu-toggle { width:40px; height:40px; border-radius:10px; border:1px solid #334155; background:#0f172a; color:#fff; font-size:20px; cursor:pointer; }
    .menu-toggle:hover { background:#1e293b; }
    .back-link { display:inline-block; margin-bottom:4px; color:#94a3b8; font-size:13px; }
    
    .side-overlay { position:fixed; inset:0; background:rgba(0,0,0,.6); opacity:0; pointer-events:none; transition:.2s ease; z-index:19; }
    .side-overlay.show { opacity:1; pointer-events:auto; }
    .side-menu { position:fixed; left:0; top:0; bottom:0; width:260px; background:#1e2640; border-right:1px solid #2d3748; padding:24px 16px; transform:translateX(-102%); transition:.2s ease; z-index:20; }
    .side-menu.open { transform:translateX(0); }
    .side-title { font-size:18px; font-weight:800; color:#fff; margin-bottom:20px; padding-left:10px; border-left:4px solid #3b82f6; }
    .side-link, .side-close { display:block; width:100%; text-align:left; margin:8px 0; padding:12px; border-radius:8px; border:1px solid #334155; background:#0f172a; color:#cbd5e1; font-weight:500; cursor:pointer; }
    .side-link:hover, .side-close:hover { background:#243049; border-color:#475569; color:#fff; }
    
    .container { width:min(1280px, 100%); margin:0 auto; padding:16px 12px 60px; }
    .small { opacity:.7; font-size:12px; }
    
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
    @media (max-width: 600px) {
        .metrics-grid { grid-template-columns: repeat(2, 1fr); }
        .metrics-grid .metric-card:first-child { grid-column: span 2; }
    }
    .metric-card { background-color: #1e293b; border: 1px solid #334155; padding: 16px; border-radius: 12px; }
    .metric-card .lbl { font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; margin-bottom: 4px; }
    .metric-card .num { font-size: 20px; font-weight: 800; color: #fff; }
    
    .dashboard-section { background-color: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 16px; margin-bottom: 20px; }
    .section-title { font-size: 15px; font-weight: 700; color: #fff; margin-top: 0; margin-bottom: 16px; border-left: 4px solid #3b82f6; padding-left: 8px; }
    
    .split-row { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; margin-bottom: 20px; }
    @media (max-width: 960px) { .split-row { grid-template-columns: 1fr; } }
    
    .table-container { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .responsive-table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; min-width: 500px; }
    .responsive-table th { padding: 10px; color: #94a3b8; border-bottom: 2px solid #334155; font-weight: 600; }
    .responsive-table td { padding: 10px; border-bottom: 1px solid #334155; color: #cbd5e1; }
    
    .review-item { display: grid; grid-template-columns: 1.2fr 1.5fr 2fr 2.5fr; padding: 12px; border-bottom: 1px solid #334155; align-items: center; gap: 8px; }
    @media (max-width: 768px) {
        .review-item { grid-template-columns: 1fr; padding: 16px; gap: 10px; border-bottom: 2px solid #334155; background: rgba(0,0,0,0.1); border-radius: 8px; margin-bottom: 10px; }
        .review-item > div { width: 100%; }
        .review-item form { width: 100%; display: flex; justify-content: space-between; gap: 4px; }
        .review-item .btn { flex: 1; text-align: center; justify-content: center; }
    }
    
    .form-group-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 10px; }
    @media (max-width: 480px) { .form-group-grid { grid-template-columns: 1fr; } }

    .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; display: inline-block; }
    .badge.paid, .badge.success { background: rgba(16,185,129,0.15); color: #10b981; }
    .badge.error, .badge.drop { background: rgba(239,68,68,0.15); color: #ef4444; }
    .badge.pending { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .badge.active { background: rgba(56,189,248,0.15); color: #38bdf8; }
    .badge.idle { background: rgba(148,163,184,0.15); color: #94a3b8; }
    
    .btn { padding: 8px 14px; border-radius: 6px; font-weight: bold; border: none; cursor: pointer; font-size: 12px; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; transition: opacity 0.2s; }
    .btn:hover { opacity: 0.85; }
    .btn.approve { background-color: #10b981; color: #fff; }
    .btn.reject { background-color: #ef4444; color: #fff; }
    
    .input-box { background:#0f172a; border:1px solid #334155; color:#fff; padding:8px 12px; border-radius:8px; font-size:14px; }
    
    /* Legacy Layout */
    .summary { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; }
    .mini { padding:2px 6px; border-radius:4px; font-size:10px; font-weight:bold; }
    .mini.button { background:#3b82f6; color:#fff; }
    .mini.join { background:#10b981; color:#fff; }
    .mini.payment { background:#f59e0b; color:#fff; }
    .mini.ticket { background:#ec4899; color:#fff; }
    .mini.cmd { background:#8b5cf6; color:#fff; }
    .mini.admin { background:#6b7280; color:#fff; }
    .mini.text { background:#4b5563; color:#fff; }
    .chat-card { background:#1e293b; border:1px solid #334155; border-radius:12px; padding:14px; margin-bottom:12px; }
    .chat-card .top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; }
    .chat-card .title { font-weight:bold; font-size:15px; }
    .msg-row { margin:4px 0; padding:8px; border-radius:6px; font-size:13px; word-break:break-all; }
    .msg-row.in { background:rgba(255,255,255,0.03); border-left:3px solid #64748b; }
    .msg-row.out { background:rgba(56,189,248,0.05); border-left:3px solid #38bdf8; text-align:right; }
    .action-row { display:flex; gap:8px; margin-top:10px; }
    """

def _shell_header(title: str, subtitle: str = "", back_href: str | None = None) -> str:
    back_html = f"<a class='back-link' href='{back_href}'>← กลับหน้ารวมแชท</a>" if back_href else ""
    return f"""
    <div class="header">
      <button class="menu-toggle" type="button" onclick="toggleSideMenu()">☰</button>
      <div class="header-copy">
        {back_html}
        <div style="font-weight:800; font-size:15px; color:#fff;">{title}</div>
        {f"<div class='small' style='color:#94a3b8; font-size:11px;'>{subtitle}</div>" if subtitle else ""}
      </div>
    </div>
    <div class="side-overlay" id="sideOverlay" onclick="closeSideMenu()"></div>
    <aside class="side-menu" id="sideMenu">
      <div class="side-title">อาณาจักร VIP คุมระบบ</div>
      <a class="side-link" href="/chats">💬 หน้าส่องประวัติแชท (Chats)</a>
      <a class="side-link" href="/api" style="background:#2a3454; color:#fff; border-color:#3b82f6;">🎫 แผงคุมซองเติมเงิน (API Dashboard)</a>
      <a class="side-link" href="/blocked">🚫 ส่องรายชื่อที่โดนบล็อก</a>
      <a class="side-link" href="/api#package-editor">แก้รูป/การ์ดแพ็กเกจ VIP</a>
      <a class="side-link" href="/packages" target="_blank">💎 เปิดหน้าแพ็กเกจ VIP</a>
      <button class="side-close" type="button" onclick="closeSideMenu()">✖ ปิดแท็บบาร์</button>
    </aside>
    """

def _shell_script() -> str:
    return """
    <script>
    function toggleSideMenu(){
      const menu = document.getElementById('sideMenu');
      const overlay = document.getElementById('sideOverlay');
      if(menu){ menu.classList.toggle('open'); }
      if(overlay){ overlay.classList.toggle('show'); }
    }
    function closeSideMenu(){
      const menu = document.getElementById('sideMenu');
      const overlay = document.getElementById('sideOverlay');
      if(menu){ menu.classList.remove('open'); }
      if(overlay){ overlay.classList.remove('show'); }
    }
    </script>
    """

def _render_page(*, title: str, header_title: str, header_subtitle: str = "", body: str, back_href: str | None = None) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <title>{escape(title)}</title>
            <style>{_base_css()}</style>
        </head>
        <body>
            {_shell_header(header_title, header_subtitle, back_href)}
            <div class="container">
              {body}
            </div>
            {_shell_script()}
        </body>
        </html>"""
    )


@app.get("/packages", response_class=HTMLResponse)
def packages_public_page(request: Request):
    _ensure_tables()
    return packages_v.packages_page(edit=request.query_params.get("edit") == "1")

@app.post("/packages/edit/save")
async def packages_editor_save(request: Request):
    _ensure_tables()
    payload = await request.json()
    return JSONResponse(packages_v.save_package_editor_config(payload))


@app.post("/packages/login-event")
async def packages_login_event(request: Request):
    _ensure_tables()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    username = str(payload.get("username") or "").strip()[:120]
    source = str(payload.get("source") or "packages_v").strip()[:80]
    path = str(payload.get("path") or "").strip()[:180]
    package_id = str(payload.get("package") or payload.get("package_id") or "").strip()[:40]
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:240]
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO package_login_users (username, source, path, package_id, ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (username, source, path, package_id, ip, user_agent),
    )
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})

@app.post("/packages/buy-event")
async def packages_buy_event(request: Request):
    _ensure_tables()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    package_id = str(payload.get("package_id") or payload.get("package") or "").strip()[:40]
    package_name = str(payload.get("package_name") or "").strip()[:120]
    username = str(payload.get("username") or "").strip()[:120]
    source = str(payload.get("source") or "packages_v").strip()[:80]
    path = str(payload.get("path") or "").strip()[:180]
    logged_in = 1 if payload.get("logged_in") else 0
    try:
        amount = float(str(payload.get("amount") or "0").replace(",", "").strip() or 0)
    except Exception:
        amount = 0.0
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:240]
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO package_purchase_requests (
            package_id, package_name, amount, username, logged_in, status,
            source, path, ip, user_agent, note
        )
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
        """,
        (package_id, package_name, amount, username, logged_in, source, path, ip, user_agent, "web queued for bot"),
    )
    request_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "request_id": request_id, "status": "queued"})

@app.post("/packages/group-button-event")
async def packages_group_button_event(request: Request):
    _ensure_tables()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    action = str(payload.get("action") or "enter_group").strip()[:60]
    username = str(payload.get("username") or "").strip()[:120]
    package_name = str(payload.get("package_name") or "").strip()[:120]
    invite_link = str(payload.get("invite_link") or "").strip()[:260]
    source = str(payload.get("source") or "success_page").strip()[:80]
    path = str(payload.get("path") or "").strip()[:180]
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:240]
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO package_group_button_events (
            action, username, package_name, invite_link, source, path, ip, user_agent, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (action, username, package_name, invite_link, source, path, ip, user_agent, "web button clicked"),
    )
    event_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "event_id": event_id})

@app.post("/packages/event")
async def packages_generic_event(request: Request):
    _ensure_tables()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    event_type = str(payload.get("event_type") or payload.get("action") or "custom").strip()[:80]
    session_id = str(payload.get("session_id") or "").strip()[:160]
    user_id = str(payload.get("user_id") or payload.get("chat_id") or "").strip()[:80]
    username = str(payload.get("username") or payload.get("user") or "").strip()[:120]
    package_id = str(payload.get("package_id") or payload.get("package") or "").strip()[:40]
    package_name = str(payload.get("package_name") or "").strip()[:120]
    payment_ref = str(payload.get("payment_ref") or payload.get("attempt_id") or "").strip()[:160]
    status = str(payload.get("status") or "").strip()[:80]
    group_id = str(payload.get("group_id") or "").strip()[:80]
    invite_link = str(payload.get("invite_link") or payload.get("link") or "").strip()[:260]
    source = str(payload.get("source") or "packages_event").strip()[:80]
    path = str(payload.get("path") or "").strip()[:180]
    note = str(payload.get("note") or "").strip()[:500]
    try:
        amount = float(str(payload.get("amount") or "0").replace(",", "").strip() or 0)
    except Exception:
        amount = 0.0
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:240]
    raw_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)[:4000]
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO package_user_events (
            event_type, session_id, user_id, username, package_id, package_name, amount,
            payment_ref, status, group_id, invite_link, source, path, ip,
            user_agent, raw_payload, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type, session_id, user_id, username, package_id, package_name, amount,
            payment_ref, status, group_id, invite_link, source, path, ip,
            user_agent, raw_payload, note,
        ),
    )
    event_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "event_id": event_id, "event_type": event_type})

@app.get("/packages-editor-pan")
def packages_editor_redirect():
    return RedirectResponse("/packages?edit=1", status_code=303)

# =====================================================================
# 🎫 2. หน้าแผงคุมซองเติมเงิน สรุปสถิติ และฟอร์มกรอกราคาสุดลักชัวรี่
# =====================================================================
def _db_has_table(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table_name,))
    return cur.fetchone() is not None


RESULT_SOURCE_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _db_columns(cur: sqlite3.Cursor, table_name: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cur.fetchall()}


def _safe_select_cols(cur: sqlite3.Cursor, table_name: str, columns: list[str]) -> str:
    existing = _db_columns(cur, table_name)
    parts = []
    for column in columns:
        parts.append(column if column in existing else f"NULL AS {column}")
    return ", ".join(parts)


def _pf_badge(status: str) -> str:
    normalized = (status or "pending").strip().lower()
    if normalized in ("approved", "success", "joined", "issued", "paid"):
        label, cls = "approved", "ok"
    elif normalized in ("pending", "checking", "queued", ""):
        label, cls = "pending", "wait"
    elif normalized in ("-", "idle", "none"):
        label, cls = normalized, "wait"
    else:
        label, cls = normalized, "bad"
    return f'<span class="pf-badge pf-{cls}">{escape(label)}</span>'


def _row_text(row: sqlite3.Row, key: str) -> str:
    return str(row[key] or "") if key in row.keys() else ""


def _load_result_matcher_config(cur: sqlite3.Cursor) -> dict[str, str]:
    defaults = {
        "user_check_event_type": "enter_group_click",
        "purchase_event_type": "package_click",
        "success_event_type": "success_view",
        "web_source": "packages_v",
        "require_username_match": "1",
        "pending_message": "payment is not approved yet",
    }
    if not _db_has_table(cur, "result_matcher_config"):
        return defaults
    cur.execute("SELECT key, value FROM result_matcher_config")
    defaults.update({str(row["key"]): str(row["value"] or "") for row in cur.fetchall()})
    return defaults


def _source_matcher_event(cur: sqlite3.Cursor, ref: str, config: dict[str, str]) -> dict | None:
    if not _db_has_table(cur, "package_user_events"):
        return None
    columns = _db_columns(cur, "package_user_events")
    identity_cols = [col for col in ("session_id", "payment_ref", "username", "user_id") if col in columns]
    if not identity_cols:
        return None
    where = ["(" + " OR ".join(f"{col}=?" for col in identity_cols) + ")"]
    params: list[object] = [ref for _ in identity_cols]
    event_type = (config.get("user_check_event_type") or "").strip()
    web_source = (config.get("web_source") or "").strip()
    if event_type and "event_type" in columns:
        where.append("event_type=?")
        params.append(event_type)
    if web_source and "source" in columns:
        where.append("source=?")
        params.append(web_source)
    cur.execute(
        f"""
        SELECT *
        FROM package_user_events
        WHERE {' AND '.join(where)}
        ORDER BY ts DESC, id DESC
        LIMIT 1
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "event_type": _row_text(row, "event_type"),
        "session_id": _row_text(row, "session_id"),
        "user_id": _row_text(row, "user_id"),
        "username": _row_text(row, "username"),
        "package_id": _row_text(row, "package_id"),
        "package_name": _row_text(row, "package_name"),
        "payment_ref": _row_text(row, "payment_ref"),
        "invite_link": _row_text(row, "invite_link"),
        "source": _row_text(row, "source"),
        "path": _row_text(row, "path"),
        "note": _row_text(row, "note"),
    }


def _payment_source_from_attempt(row: sqlite3.Row, ref: str) -> dict:
    status = _row_text(row, "status").lower()
    link_status = _row_text(row, "link_status").lower()
    invite_link = _row_text(row, "invite_link")
    package_id = _row_text(row, "package_id")
    result_url = f"/result/{ref}"
    return {
        "source": "payment_attempts",
        "source_status": status,
        "approved": status in ("success", "approved"),
        "failed": status in ("api_error", "amount_mismatch", "duplicate", "failed", "insufficient", "invalid", "rejected", "used_voucher", "voucher_used"),
        "payment_ref": ref,
        "package_id": package_id,
        "result_url": result_url,
        "invite_link": invite_link if invite_link and link_status == "issued" else "",
        "link_status": link_status,
        "join_status": _row_text(row, "join_status"),
        "detail": _row_text(row, "detail"),
    }


def _payment_source_from_review(row: sqlite3.Row, ref: str) -> dict:
    status = _row_text(row, "status").lower()
    return {
        "source": "api_error_payment_reviews",
        "source_status": status,
        "approved": status == "approved",
        "failed": status in ("rejected", "failed"),
        "payment_ref": ref,
        "review_id": row["id"],
        "voucher_ref": _row_text(row, "v"),
        "amount": row["amount"] if "amount" in row.keys() else None,
    }


def _result_source_payload(ref: str) -> dict:
    if not RESULT_SOURCE_SAFE_REF_RE.match(ref):
        raise HTTPException(status_code=400, detail="invalid ref")
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    config = _load_result_matcher_config(cur)
    matcher = _source_matcher_event(cur, ref, config)
    payment = None
    if _db_has_table(cur, "payment_attempts"):
        cur.execute("SELECT * FROM payment_attempts WHERE id=? LIMIT 1", (ref,))
        row = cur.fetchone()
        if row is not None:
            payment = _payment_source_from_attempt(row, ref)
    if payment is None and _db_has_table(cur, "api_error_payment_reviews"):
        if ref.isdigit():
            cur.execute("SELECT * FROM api_error_payment_reviews WHERE id=? LIMIT 1", (int(ref),))
        else:
            cur.execute("SELECT * FROM api_error_payment_reviews WHERE v=? LIMIT 1", (ref,))
        row = cur.fetchone()
        if row is not None:
            payment = _payment_source_from_review(row, ref)
    conn.close()
    return {
        "ok": True,
        "ref": ref,
        "payment": payment,
        "matcher": {"matched": matcher is not None, "event": matcher},
        "config": config,
    }


def _result_feed_payload(feed_name: str, limit: int = 12) -> dict:
    safe_limit = max(1, min(int(limit or 12), 80))
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    items: list[dict] = []
    if feed_name == "recent_payments":
        if _db_has_table(cur, "payment_attempts"):
            cols = _safe_select_cols(cur, "payment_attempts", [
                "id", "created_at", "status", "package_id", "expected_amount", "paid_amount",
                "link_status", "join_status", "group_id"
            ])
            cur.execute(f"SELECT {cols} FROM payment_attempts ORDER BY created_at DESC LIMIT ?", (safe_limit,))
            for row in cur.fetchall():
                items.append({
                    "source": "payment_attempts",
                    "payment_ref": _row_text(row, "id"),
                    "created_at": row["created_at"] if "created_at" in row.keys() else "",
                    "source_status": _row_text(row, "status"),
                    "package_id": _row_text(row, "package_id"),
                    "expected_amount": row["expected_amount"] if "expected_amount" in row.keys() else "",
                    "paid_amount": row["paid_amount"] if "paid_amount" in row.keys() else "",
                    "link_status": _row_text(row, "link_status"),
                    "join_status": _row_text(row, "join_status"),
                    "group_id": _row_text(row, "group_id"),
                })
        if len(items) < safe_limit and _db_has_table(cur, "api_error_payment_reviews"):
            cur.execute(
                "SELECT id, created_at, amount, status, v FROM api_error_payment_reviews ORDER BY id DESC LIMIT ?",
                (safe_limit - len(items),),
            )
            for row in cur.fetchall():
                items.append({
                    "source": "api_error_payment_reviews",
                    "payment_ref": _row_text(row, "v") or str(row["id"]),
                    "created_at": row["created_at"] if "created_at" in row.keys() else "",
                    "source_status": _row_text(row, "status"),
                    "amount": row["amount"] if "amount" in row.keys() else "",
                })
    conn.close()
    return {"ok": True, "feed": feed_name, "items": items[:safe_limit]}


@app.get("/internal/result-source/{ref}")
def internal_result_source(ref: str):
    return JSONResponse(_result_source_payload(ref))


register_result_source_provider(_result_source_payload)
register_result_feed_provider(_result_feed_payload)


def _private_fastapi_css() -> str:
    return """
    * { box-sizing: border-box; }
    html, body { margin:0; padding:0; background:#f6f7f9; color:#1f2937; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; font-size:14px; }
    a { color:#2563eb; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .pf-shell { width:min(1180px, 100%); margin:0 auto; padding:24px 18px 56px; }
    .pf-top { display:flex; align-items:flex-end; justify-content:space-between; gap:14px; padding-bottom:18px; border-bottom:1px solid #dde1e7; margin-bottom:18px; }
    .pf-title { margin:0; font-size:25px; line-height:1.15; font-weight:650; letter-spacing:0; color:#111827; }
    .pf-sub { margin:6px 0 0; color:#6b7280; font-size:13px; font-weight:350; }
    .pf-actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    .pf-link { display:inline-flex; align-items:center; min-height:34px; padding:7px 11px; border:1px solid #d8dee8; border-radius:6px; background:#fff; color:#374151; font-size:12px; font-weight:500; }
    .pf-grid { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin-bottom:14px; }
    .pf-card { background:#fff; border:1px solid #dfe4ec; border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .pf-card h2 { margin:0 0 12px; font-size:15px; line-height:1.25; font-weight:650; color:#111827; }
    .pf-card h3 { margin:0 0 8px; font-size:13px; font-weight:650; color:#374151; }
    .pf-kicker { margin:0 0 4px; font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:.04em; font-weight:600; }
    .pf-number { font-size:22px; font-weight:650; color:#111827; }
    .pf-muted { color:#6b7280; font-size:12px; font-weight:350; }
    .pf-main { display:grid; grid-template-columns:minmax(0, 1.1fr) minmax(360px, .9fr); gap:14px; align-items:start; }
    .pf-stack { display:flex; flex-direction:column; gap:14px; }
    .pf-form { display:grid; gap:10px; }
    .pf-tier { display:grid; grid-template-columns:120px minmax(110px,.55fr) minmax(180px,1fr); gap:8px; align-items:end; padding:10px; border:1px solid #e5e7eb; border-radius:7px; background:#fafafa; }
    label { display:block; font-size:11px; color:#6b7280; margin-bottom:4px; font-weight:450; }
    input { width:100%; min-height:35px; border:1px solid #ccd3df; border-radius:6px; padding:7px 9px; background:#fff; color:#111827; font-size:13px; font-weight:400; }
    input:focus { outline:2px solid rgba(37,99,235,.14); border-color:#93b4ef; }
    .pf-btn { border:0; border-radius:6px; min-height:35px; padding:8px 12px; background:#1f2937; color:#fff; font-size:12px; font-weight:600; cursor:pointer; }
    .pf-btn:hover { background:#111827; }
    .pf-btn-danger { background:#b91c1c; }
    .pf-btn-danger:hover { background:#991b1b; }
    .pf-table-wrap { width:100%; overflow:auto; border:1px solid #e5e7eb; border-radius:7px; }
    .pf-user-scroll { max-height:260px; overflow:auto; }
    .pf-user-scroll table { min-width:560px; }
    .pf-user-scroll thead th { position:sticky; top:0; z-index:1; }
    table { width:100%; border-collapse:collapse; min-width:620px; background:#fff; }
    th, td { padding:9px 10px; border-bottom:1px solid #edf0f4; text-align:left; vertical-align:top; font-size:12px; }
    th { background:#f9fafb; color:#4b5563; font-weight:650; }
    tr:last-child td { border-bottom:0; }
    code { font-family:Consolas,'SFMono-Regular',monospace; font-size:12px; color:#334155; word-break:break-all; }
    .pf-badge { display:inline-flex; align-items:center; justify-content:center; min-width:62px; padding:3px 7px; border-radius:999px; font-size:11px; font-weight:650; text-transform:lowercase; }
    .pf-ok { background:#ecfdf3; color:#027a48; }
    .pf-wait { background:#fffaeb; color:#b54708; }
    .pf-bad { background:#fef3f2; color:#b42318; }
    .pf-review { display:grid; gap:9px; padding:11px; border:1px solid #e5e7eb; border-radius:7px; background:#fff; }
    .pf-review + .pf-review { margin-top:9px; }
    .pf-review-top { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .pf-review form { display:grid; grid-template-columns:110px 1fr 1fr; gap:8px; }
    .pf-empty { padding:18px; border:1px dashed #d8dee8; border-radius:7px; color:#6b7280; text-align:center; background:#fff; font-size:13px; }
    .pf-api-row { display:flex; justify-content:space-between; gap:10px; padding:9px 0; border-bottom:1px solid #edf0f4; }
    .pf-api-row:last-child { border-bottom:0; }
    .pf-api-key { color:#6b7280; font-size:12px; }
    .pf-api-value { text-align:right; font-size:12px; color:#111827; word-break:break-all; }
    @media (max-width: 940px) {
      .pf-grid, .pf-main { grid-template-columns:1fr; }
      .pf-top { align-items:flex-start; flex-direction:column; }
      .pf-actions { justify-content:flex-start; }
    }
    @media (max-width: 620px) {
      .pf-shell { padding:18px 12px 44px; }
      .pf-tier { grid-template-columns:1fr; }
      .pf-review form { grid-template-columns:1fr; }
    }
    """


def _fetch_private_fastapi_data() -> dict:
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tiers = {}
    for tier_id in (3, 2, 1):
        cur.execute("SELECT * FROM vip_tier_config WHERE tier_id=?", (tier_id,))
        row = cur.fetchone()
        tiers[tier_id] = dict(row) if row else {"tier_id": tier_id, "tier_name": f"Tier {tier_id}", "min_amount": 0.0, "group_link": ""}

    total_paid = 0.0
    approved_count = pending_count = rejected_count = 0
    logs = []
    pending_reviews = []
    if _db_has_table(cur, "api_error_payment_reviews"):
        cur.execute("SELECT COALESCE(SUM(amount), 0) FROM api_error_payment_reviews WHERE status='approved'")
        total_paid = float(cur.fetchone()[0] or 0.0)
        cur.execute("SELECT COUNT(*) FROM api_error_payment_reviews WHERE status='approved'")
        approved_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM api_error_payment_reviews WHERE status='pending'")
        pending_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM api_error_payment_reviews WHERE status='rejected'")
        rejected_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT id, user_id, sender, url, v, amount, status, created_at FROM api_error_payment_reviews ORDER BY id DESC LIMIT 12")
        logs = cur.fetchall()
        cur.execute("SELECT id, user_id, sender, url, v, amount FROM api_error_payment_reviews WHERE status='pending' ORDER BY id DESC LIMIT 20")
        pending_reviews = cur.fetchall()

    attempts = []
    if _db_has_table(cur, "payment_attempts"):
        cols = _safe_select_cols(cur, "payment_attempts", [
            "id", "created_at", "package_id", "expected_amount", "paid_amount",
            "status", "link_status", "join_status", "invite_error",
            "buyer_user_id", "joined_user_id",
        ])
        cur.execute(
            f"""
            SELECT {cols}
            FROM payment_attempts
            ORDER BY created_at DESC
            LIMIT 12
            """
        )
        attempts = cur.fetchall()

    webhook_events = []
    if _db_has_table(cur, "webhook_events"):
        cur.execute(
            """
            SELECT id, ts, event_type, amount, sender_mobile, transaction_id, verify_ok, note
            FROM webhook_events
            ORDER BY ts DESC
            LIMIT 8
            """
        )
        webhook_events = cur.fetchall()

    login_users = []
    if _db_has_table(cur, "package_login_users"):
        cur.execute(
            """
            SELECT id, ts, username, source, path, package_id, ip
            FROM package_login_users
            ORDER BY ts DESC
            LIMIT 30
            """
        )
        login_users = cur.fetchall()

    group_button_events = []
    if _db_has_table(cur, "package_group_button_events"):
        cur.execute(
            """
            SELECT id, ts, action, username, package_name, invite_link, source, path, ip, note
            FROM package_group_button_events
            ORDER BY ts DESC
            LIMIT 80
            """
        )
        group_button_events = cur.fetchall()

    package_user_events = []
    if _db_has_table(cur, "package_user_events"):
        cols = _safe_select_cols(cur, "package_user_events", [
            "id", "ts", "event_type", "session_id", "user_id", "username",
            "package_id", "package_name", "amount", "payment_ref", "status",
            "group_id", "invite_link", "source", "path", "ip", "note",
        ])
        cur.execute(
            f"""
            SELECT {cols}
            FROM package_user_events
            ORDER BY ts DESC
            LIMIT 120
            """
        )
        package_user_events = cur.fetchall()

    purchase_requests = []
    if _db_has_table(cur, "package_purchase_requests"):
        cols = _safe_select_cols(cur, "package_purchase_requests", [
            "id", "ts", "package_id", "package_name", "amount", "username",
            "logged_in", "status", "source", "path", "ip", "bot_claimed_at",
            "bot_result", "note",
        ])
        cur.execute(
            f"""
            SELECT {cols}
            FROM package_purchase_requests
            ORDER BY ts DESC
            LIMIT 80
            """
        )
        purchase_requests = cur.fetchall()

    group_member_events = []
    if _db_has_table(cur, "group_member_events"):
        cols = _safe_select_cols(cur, "group_member_events", [
            "id", "ts", "event_type", "group_id", "invite_link",
            "owner_user_id", "actor_user_id", "actor_username",
            "actor_full_name", "amount", "balance_before", "balance_after",
            "source", "attempt_id", "note",
        ])
        cur.execute(
            f"""
            SELECT {cols}
            FROM group_member_events
            ORDER BY ts DESC
            LIMIT 80
            """
        )
        group_member_events = cur.fetchall()

    membership_rows = []
    if _db_has_table(cur, "payment_attempts"):
        pa_cols = _db_columns(cur, "payment_attempts")
        pending_cols = _db_columns(cur, "pending_invites") if _db_has_table(cur, "pending_invites") else set()
        balance_cols = _db_columns(cur, "user_balance") if _db_has_table(cur, "user_balance") else set()
        if "invite_link" in pa_cols:
            def pa_col(column: str) -> str:
                return f"pa.{column}" if column in pa_cols else f"NULL AS {column}"

            has_pending_invites = {"invite_link", "owner_user_id", "used_by_user_id", "used_at"}.issubset(pending_cols)
            pending_join = "LEFT JOIN pending_invites pi ON pi.invite_link = pa.invite_link" if has_pending_invites else ""
            owner_user_expr = "pi.owner_user_id" if has_pending_invites else ("pa.buyer_user_id" if "buyer_user_id" in pa_cols else ("pa.joined_user_id" if "joined_user_id" in pa_cols else "NULL"))
            balance_join = f"LEFT JOIN user_balance ub ON ub.user_id = {owner_user_expr}" if owner_user_expr != "NULL" and {"user_id", "total"}.issubset(balance_cols) else ""
            owner_cols = "pi.owner_user_id, pi.used_by_user_id, pi.used_at," if has_pending_invites else "NULL AS owner_user_id, NULL AS used_by_user_id, NULL AS used_at,"
            balance_col = "ub.total AS owner_balance" if balance_join else "NULL AS owner_balance"
            order_candidates = [f"pa.{col}" for col in ("joined_at", "link_used_at", "created_at", "id") if col in pa_cols]
            order_expr = f"COALESCE({', '.join(order_candidates)})" if len(order_candidates) > 1 else (order_candidates[0] if order_candidates else "pa.rowid")
            cur.execute(
                f"""
                SELECT
                    {pa_col('id')}, {pa_col('package_id')}, {pa_col('expected_amount')}, {pa_col('paid_amount')}, {pa_col('group_id')},
                    pa.invite_link, {pa_col('link_status')}, {pa_col('link_used_at')}, {pa_col('join_status')},
                    {pa_col('joined_user_id')}, {pa_col('joined_at')}, {pa_col('join_match_status')},
                    {owner_cols}
                    {balance_col}
                FROM payment_attempts pa
                {pending_join}
                {balance_join}
                WHERE pa.invite_link IS NOT NULL AND pa.invite_link != ''
                ORDER BY {order_expr} DESC
                LIMIT 30
                """
            )
            membership_rows = cur.fetchall()

    balance_rows = []
    if _db_has_table(cur, "user_balance"):
        ub_cols = _db_columns(cur, "user_balance")
        ups_cols = _db_columns(cur, "user_payment_state") if _db_has_table(cur, "user_payment_state") else set()
        state_join = "LEFT JOIN user_payment_state ups ON ups.user_id = ub.user_id" if "user_id" in ub_cols and "user_id" in ups_cols else ""
        state_cols = ", ".join(
            f"ups.{col}" if state_join and col in ups_cols else f"NULL AS {col}"
            for col in ("payment_sent", "joined", "invalidated", "active_invite", "updated_at")
        )
        user_id_col = "ub.user_id" if "user_id" in ub_cols else "NULL AS user_id"
        total_col = "ub.total" if "total" in ub_cols else "NULL AS total"
        order_col = "ub.total DESC, ub.user_id DESC" if {"total", "user_id"}.issubset(ub_cols) else "ub.rowid DESC"
        cur.execute(
            f"""
            SELECT {user_id_col}, {total_col}, {state_cols}
            FROM user_balance ub
            {state_join}
            ORDER BY {order_col}
            LIMIT 30
            """
        )
        balance_rows = cur.fetchall()

    bot_api_config = {}
    if _db_has_table(cur, "bot_api_config"):
        cur.execute("SELECT key, value FROM bot_api_config")
        bot_api_config = {str(row["key"]): str(row["value"] or "") for row in cur.fetchall()}

    result_matcher_config = {}
    if _db_has_table(cur, "result_matcher_config"):
        cur.execute("SELECT key, value FROM result_matcher_config")
        result_matcher_config = {str(row["key"]): str(row["value"] or "") for row in cur.fetchall()}

    conn.close()
    return {
        "tiers": tiers,
        "total_paid": total_paid,
        "approved_count": approved_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "logs": logs,
        "pending_reviews": pending_reviews,
        "attempts": attempts,
        "webhook_events": webhook_events,
        "login_users": login_users,
        "group_button_events": group_button_events,
        "package_user_events": package_user_events,
        "purchase_requests": purchase_requests,
        "group_member_events": group_member_events,
        "membership_rows": membership_rows,
        "balance_rows": balance_rows,
        "bot_api_config": bot_api_config,
        "result_matcher_config": result_matcher_config,
    }


@app.get("/private-fastapi", response_class=HTMLResponse)
def private_fastapi_page():
    data = _fetch_private_fastapi_data()
    tiers = data["tiers"]
    tier_inputs = []
    for tier_id, label in ((3, "Tier 3"), (2, "Tier 2"), (1, "Tier 1")):
        tier = tiers[tier_id]
        tier_inputs.append(f"""
        <div class="pf-tier">
          <h3>{label}</h3>
          <div><label>Price</label><input type="number" step="any" name="t{tier_id}_amount" value="{float(tier['min_amount'] or 0):g}" required></div>
          <div><label>Telegram Group ID</label><input type="text" name="t{tier_id}_link" value="{escape(str(tier['group_link'] or ''))}" placeholder="-100xxxxxxxxxx" required></div>
        </div>
        """)

    log_rows = []
    for row in data["logs"]:
        amount = float(row["amount"] or 0)
        log_rows.append(f"<tr><td>#{row['id']}</td><td>{escape(str(row['user_id'] or ''))}</td><td>{escape(str(row['sender'] or '-'))}</td><td><code>{escape(str(row['v'] or '-'))}</code></td><td>{amount:,.2f}</td><td>{_pf_badge(str(row['status'] or 'pending'))}</td></tr>")
    logs_html = "".join(log_rows) if log_rows else "<tr><td colspan='6'>No payment alert records.</td></tr>"

    attempt_rows = []
    for row in data["attempts"]:
        created = _fmt_ts(int(row["created_at"] or 0)) if row["created_at"] else "-"
        paid = row["paid_amount"] if row["paid_amount"] not in (None, "") else row["expected_amount"]
        try:
            paid_text = f"{float(paid or 0):g}"
        except Exception:
            paid_text = escape(str(paid or "-"))
        attempt_rows.append(
            f"<tr><td><code>{escape(str(row['id'] or ''))}</code></td><td>{escape(created)}</td><td>{escape(str(row['package_id'] or '-'))}</td><td>{paid_text}</td><td>{_pf_badge(str(row['status'] or ''))}</td><td>{escape(str(row['link_status'] or '-'))} / {escape(str(row['join_status'] or '-'))}</td></tr>"
        )
    attempts_html = "".join(attempt_rows) if attempt_rows else "<tr><td colspan='6'>No customer payment status records.</td></tr>"

    webhook_rows = []
    for row in data["webhook_events"]:
        verify_status = "approved" if int(row["verify_ok"] or 0) else "failed"
        webhook_rows.append(f"<tr><td>#{row['id']}</td><td>{escape(_fmt_ts(int(row['ts'] or 0)))}</td><td>{escape(str(row['event_type'] or '-'))}</td><td>{escape(str(row['amount'] or '-'))}</td><td><code>{escape(str(row['transaction_id'] or '-'))}</code></td><td>{_pf_badge(verify_status)}</td></tr>")
    webhooks_html = "".join(webhook_rows) if webhook_rows else "<tr><td colspan='6'>No API webhook alerts.</td></tr>"

    login_rows = []
    for row in data["login_users"]:
        login_rows.append(
            f"<tr><td>{escape(_fmt_ts(int(row['ts'] or 0)))}</td><td>{escape(str(row['username'] or '-'))}</td><td>{escape(str(row['package_id'] or '-'))}</td><td>{escape(str(row['source'] or '-'))}</td><td>{escape(str(row['ip'] or '-'))}</td></tr>"
        )
    logins_html = "".join(login_rows) if login_rows else "<tr><td colspan='5'>No package login records yet.</td></tr>"

    group_button_rows = []
    for row in data["group_button_events"]:
        group_button_rows.append(
            f"<tr><td>#{row['id']}</td><td>{escape(_fmt_ts(int(row['ts'] or 0)))}</td><td>{escape(str(row['action'] or '-'))}</td><td>{escape(str(row['username'] or '-'))}</td><td>{escape(str(row['package_name'] or '-'))}</td><td><code>{escape(str(row['invite_link'] or '-'))}</code></td><td>{escape(str(row['ip'] or '-'))}</td></tr>"
        )
    group_buttons_html = "".join(group_button_rows) if group_button_rows else "<tr><td colspan='7'>No group button clicks yet.</td></tr>"

    purchase_rows = []
    for row in data["purchase_requests"]:
        try:
            amount_text = f"{float(row['amount'] or 0):g}"
        except Exception:
            amount_text = "-"
        claimed = _fmt_ts(int(row["bot_claimed_at"] or 0)) if row["bot_claimed_at"] else "-"
        user_text = str(row["username"] or "-")
        if not int(row["logged_in"] or 0):
            user_text += " (guest)"
        purchase_rows.append(
            f"<tr><td>#{row['id']}</td><td>{escape(_fmt_ts(int(row['ts'] or 0)))}</td><td>{escape(str(row['package_id'] or '-'))}</td><td>{escape(str(row['package_name'] or '-'))}</td><td>{escape(amount_text)}</td><td>{escape(user_text)}</td><td>{_pf_badge(str(row['status'] or 'queued'))}</td><td>{escape(claimed)}</td><td>{escape(str(row['bot_result'] or row['note'] or '-'))}</td></tr>"
        )
    purchases_html = "".join(purchase_rows) if purchase_rows else "<tr><td colspan='9'>No package buy requests yet.</td></tr>"

    group_event_rows = []
    for row in data["group_member_events"]:
        try:
            amount_text = f"{float(row['amount'] or 0):g}"
        except Exception:
            amount_text = "-"
        try:
            before_text = f"{float(row['balance_before'] or 0):g}"
        except Exception:
            before_text = "-"
        try:
            after_text = f"{float(row['balance_after'] or 0):g}"
        except Exception:
            after_text = "-"
        actor_name = str(row["actor_full_name"] or row["actor_username"] or "-")
        group_event_rows.append(
            f"<tr><td>{escape(_fmt_ts(int(row['ts'] or 0)))}</td><td>{_pf_badge(str(row['event_type'] or '-'))}</td><td>{escape(str(row['actor_user_id'] or '-'))}</td><td>{escape(actor_name)}</td><td>{escape(str(row['owner_user_id'] or '-'))}</td><td>{escape(amount_text)}</td><td>{escape(before_text)} / {escape(after_text)}</td><td><code>{escape(str(row['attempt_id'] or '-'))}</code></td><td><code>{escape(str(row['invite_link'] or '-'))}</code></td><td>{escape(str(row['note'] or '-'))}</td></tr>"
        )
    group_events_html = "".join(group_event_rows) if group_event_rows else "<tr><td colspan='10'>No raw group member events yet.</td></tr>"

    membership_table_rows = []
    for row in data["membership_rows"]:
        joined_at = _fmt_ts(int(row["joined_at"] or 0)) if row["joined_at"] else "-"
        link_used_at = _fmt_ts(int(row["link_used_at"] or 0)) if row["link_used_at"] else "-"
        paid = row["paid_amount"] if row["paid_amount"] not in (None, "") else row["expected_amount"]
        try:
            paid_text = f"{float(paid or 0):g}"
        except Exception:
            paid_text = escape(str(paid or "-"))
        owner_id = row["owner_user_id"] or "-"
        joined_id = row["joined_user_id"] or row["used_by_user_id"] or "-"
        try:
            balance_text = f"{float(row['owner_balance'] or 0):g}"
        except Exception:
            balance_text = "-"
        membership_table_rows.append(
            f"<tr><td><code>{escape(str(row['id'] or ''))}</code></td><td>{escape(str(row['package_id'] or '-'))}</td><td>{paid_text}</td><td>{escape(str(row['group_id'] or '-'))}</td><td>{escape(str(owner_id))}</td><td>{escape(str(joined_id))}</td><td>{_pf_badge(str(row['join_status'] or row['link_status'] or 'pending'))}</td><td>{escape(link_used_at)} / {escape(joined_at)}</td><td>{escape(balance_text)}</td></tr>"
        )
    memberships_html = "".join(membership_table_rows) if membership_table_rows else "<tr><td colspan='9'>No group link usage records yet.</td></tr>"

    balance_table_rows = []
    for row in data["balance_rows"]:
        joined = "joined" if int(row["joined"] or 0) else ("pending" if int(row["payment_sent"] or 0) else "idle")
        if int(row["invalidated"] or 0):
            joined = "left"
        updated = _fmt_ts(int(row["updated_at"] or 0)) if row["updated_at"] else "-"
        balance_table_rows.append(
            f"<tr><td>{escape(str(row['user_id'] or '-'))}</td><td>{float(row['total'] or 0):g}</td><td>{_pf_badge(joined)}</td><td><code>{escape(str(row['active_invite'] or '-'))}</code></td><td>{escape(updated)}</td></tr>"
        )
    balances_html = "".join(balance_table_rows) if balance_table_rows else "<tr><td colspan='5'>No bot balance ledger records yet.</td></tr>"

    activity_items = []
    for row in data["login_users"]:
        activity_items.append({
            "ts": int(row["ts"] or 0),
            "user": str(row["username"] or "-"),
            "event": "package_login",
            "package": str(row["package_id"] or "-"),
            "amount": "-",
            "payment": "-",
            "group": "-",
            "source": str(row["source"] or "packages_v"),
            "note": str(row["ip"] or "-"),
        })
    for row in data["purchase_requests"]:
        activity_items.append({
            "ts": int(row["ts"] or 0),
            "user": str(row["username"] or ("guest" if not int(row["logged_in"] or 0) else "-")),
            "event": "package_buy_click",
            "package": str(row["package_id"] or row["package_name"] or "-"),
            "amount": f"{float(row['amount'] or 0):g}",
            "payment": str(row["status"] or "queued"),
            "group": "-",
            "source": str(row["source"] or "packages_v"),
            "note": str(row["bot_result"] or row["note"] or "-"),
        })
    for row in data["group_button_events"]:
        activity_items.append({
            "ts": int(row["ts"] or 0),
            "user": str(row["username"] or "-"),
            "event": str(row["action"] or "enter_group"),
            "package": str(row["package_name"] or "-"),
            "amount": "-",
            "payment": "-",
            "group": "button_clicked",
            "source": str(row["source"] or "success_page"),
            "note": str(row["invite_link"] or row["note"] or "-"),
        })
    for row in data["package_user_events"]:
        try:
            amount_text = f"{float(row['amount'] or 0):g}" if row["amount"] not in (None, "") else "-"
        except Exception:
            amount_text = "-"
        activity_items.append({
            "ts": int(row["ts"] or 0),
            "user": str(row["user_id"] or row["username"] or row["session_id"] or "-"),
            "event": str(row["event_type"] or "custom"),
            "package": str(row["package_id"] or row["package_name"] or "-"),
            "amount": amount_text,
            "payment": str(row["status"] or "-"),
            "group": str(row["group_id"] or row["invite_link"] or "-"),
            "source": str(row["source"] or "packages_event"),
            "note": str(row["payment_ref"] or row["note"] or "-"),
        })
    for row in data["attempts"]:
        paid = row["paid_amount"] if row["paid_amount"] not in (None, "") else row["expected_amount"]
        try:
            paid_text = f"{float(paid or 0):g}"
        except Exception:
            paid_text = "-"
        activity_items.append({
            "ts": int(row["created_at"] or 0),
            "user": str(row["buyer_user_id"] or row["joined_user_id"] or "-"),
            "event": "payment_attempt",
            "package": str(row["package_id"] or "-"),
            "amount": paid_text,
            "payment": str(row["status"] or "-"),
            "group": f"{row['link_status'] or '-'} / {row['join_status'] or '-'}",
            "source": "payment_confirm_v",
            "note": str(row["id"] or "-"),
        })
    for row in data["group_member_events"]:
        try:
            amount_text = f"{float(row['amount'] or 0):g}"
        except Exception:
            amount_text = "-"
        activity_items.append({
            "ts": int(row["ts"] or 0),
            "user": str(row["actor_user_id"] or row["actor_username"] or "-"),
            "event": str(row["event_type"] or "group_event"),
            "package": "-",
            "amount": amount_text,
            "payment": "-",
            "group": str(row["group_id"] or row["invite_link"] or "-"),
            "source": str(row["source"] or "bot.py"),
            "note": str(row["note"] or row["attempt_id"] or "-"),
        })
    activity_items.sort(key=lambda item: item["ts"], reverse=True)
    activity_rows = []
    for item in activity_items[:120]:
        activity_rows.append(
            f"<tr><td>{escape(_fmt_ts(item['ts']))}</td><td>{escape(item['user'])}</td><td>{escape(item['event'])}</td><td>{escape(item['package'])}</td><td>{escape(item['amount'])}</td><td>{_pf_badge(item['payment'])}</td><td>{escape(item['group'])}</td><td>{escape(item['source'])}</td><td><code>{escape(item['note'])}</code></td></tr>"
        )
    activity_html = "".join(activity_rows) if activity_rows else "<tr><td colspan='9'>No user activity yet.</td></tr>"

    bot_cfg = data["bot_api_config"]
    bot_api_url = escape(str(bot_cfg.get("bot_api_url", "")), quote=True)
    bot_api_token = escape(str(bot_cfg.get("bot_api_token", "")), quote=True)
    bot_queue_note = escape(str(bot_cfg.get("bot_queue_note", "")), quote=True)
    bot_queue_enabled = "checked" if str(bot_cfg.get("bot_queue_enabled", "0")).lower() in ("1", "true", "yes", "on") else ""
    bot_group_source = escape(str(bot_cfg.get("bot_group_source", "vip_tier_config")), quote=True)
    bot_link_permission = escape(str(bot_cfg.get("bot_link_permission", "administrator:can_invite_users")), quote=True)
    bot_link_mode = escape(str(bot_cfg.get("bot_link_mode", "single_use_invite_after_approved_payment")), quote=True)
    matcher_cfg = data["result_matcher_config"]
    matcher_user_event = escape(str(matcher_cfg.get("user_check_event_type", "enter_group_click")), quote=True)
    matcher_purchase_event = escape(str(matcher_cfg.get("purchase_event_type", "package_click")), quote=True)
    matcher_success_event = escape(str(matcher_cfg.get("success_event_type", "success_view")), quote=True)
    matcher_web_source = escape(str(matcher_cfg.get("web_source", "packages_v")), quote=True)
    matcher_pending_message = escape(str(matcher_cfg.get("pending_message", "waiting for matching user/payment")), quote=True)
    matcher_require_username = "checked" if str(matcher_cfg.get("require_username_match", "1")).lower() in ("1", "true", "yes", "on") else ""

    review_items = []
    for row in data["pending_reviews"]:
        review_items.append(f"""
        <div class="pf-review">
          <div class="pf-review-top"><div><strong>Review #{row['id']}</strong><div class="pf-muted">{escape(str(row['sender'] or 'User'))} / user {escape(str(row['user_id'] or ''))}</div></div>{_pf_badge('pending')}</div>
          <a href="{escape(str(row['url'] or ''), quote=True)}" target="_blank">{escape(str(row['url'] or '-'))}</a>
          <form action="/api/vouchers/action" method="post">
            <input type="hidden" name="review_id" value="{row['id']}">
            <input type="hidden" name="user_id" value="{row['user_id']}">
            <input type="number" name="confirm_amount" value="{float(tiers[3]['min_amount'] or 0):g}" step="any">
            <button class="pf-btn" type="submit" name="btn_action" value="yes">Approve</button>
            <button class="pf-btn pf-btn-danger" type="submit" name="btn_action" value="no">Reject</button>
          </form>
        </div>
        """)
    reviews_html = "".join(review_items) if review_items else '<div class="pf-empty">No pending manual reviews.</div>'

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>privet FastAPI</title>
  <style>{_private_fastapi_css()}</style>
</head>
<body>
  <main class="pf-shell">
    <header class="pf-top">
      <div>
        <h1 class="pf-title">privet FastAPI</h1>
        <p class="pf-sub">Private admin panel for payment alerts, customer status, API health, and VIP group pricing.</p>
      </div>
      <nav class="pf-actions">
        <a class="pf-link" href="/api">Full legacy console</a>
        <a class="pf-link" href="/packages?edit=1">Web editor</a>
        <a class="pf-link" href="/private-fastapi">Refresh</a>
      </nav>
    </header>
    <section class="pf-grid">
      <div class="pf-card"><p class="pf-kicker">Approved Amount</p><div class="pf-number">{data['total_paid']:,.2f}</div><div class="pf-muted">manual approved reviews</div></div>
      <div class="pf-card"><p class="pf-kicker">Approved</p><div class="pf-number">{data['approved_count']}</div><div class="pf-muted">successful records</div></div>
      <div class="pf-card"><p class="pf-kicker">Pending</p><div class="pf-number">{data['pending_count']}</div><div class="pf-muted">waiting for review</div></div>
      <div class="pf-card"><p class="pf-kicker">Rejected</p><div class="pf-number">{data['rejected_count']}</div><div class="pf-muted">manual rejects</div></div>
    </section>
    <section class="pf-main">
      <div class="pf-stack">
        <section class="pf-card"><h2>All User Activity</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>Time</th><th>User</th><th>Event</th><th>Package</th><th>Amount</th><th>Payment</th><th>Group / Link</th><th>Source</th><th>Note</th></tr></thead><tbody>{activity_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Customer Status</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>Attempt</th><th>Time</th><th>Package</th><th>Amount</th><th>Status</th><th>Link / Join</th></tr></thead><tbody>{attempts_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Package Login Users</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>Time</th><th>User</th><th>Package</th><th>Source</th><th>IP</th></tr></thead><tbody>{logins_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Package Buy Queue</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>ID</th><th>Time</th><th>Package</th><th>Name</th><th>Amount</th><th>User</th><th>Status</th><th>Bot Claimed</th><th>Result / Note</th></tr></thead><tbody>{purchases_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Group Button Clicks</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>ID</th><th>Time</th><th>Action</th><th>User</th><th>Package</th><th>Invite Link</th><th>IP</th></tr></thead><tbody>{group_buttons_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Raw Bot Group Events</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>Time</th><th>Event</th><th>User ID</th><th>Name</th><th>Owner</th><th>Amount</th><th>Balance Before / After</th><th>Attempt</th><th>Invite</th><th>Note</th></tr></thead><tbody>{group_events_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Group Link Join / Exit Ledger</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>Attempt</th><th>Package</th><th>Amount</th><th>Group ID</th><th>Owner</th><th>Joined By</th><th>Status</th><th>Used / Joined</th><th>Balance</th></tr></thead><tbody>{memberships_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Bot Balance Ledger</h2><div class="pf-table-wrap pf-user-scroll"><table><thead><tr><th>User ID</th><th>Total Before Deduct</th><th>Status</th><th>Active Link</th><th>Updated</th></tr></thead><tbody>{balances_html}</tbody></table></div></section>
        <section class="pf-card"><h2>Money Alerts</h2><div class="pf-table-wrap"><table><thead><tr><th>ID</th><th>ChatID</th><th>User</th><th>Voucher</th><th>Amount</th><th>Status</th></tr></thead><tbody>{logs_html}</tbody></table></div></section>
        <section class="pf-card"><h2>API Alerts</h2><div class="pf-api-row"><span class="pf-api-key">Webhook URL</span><span class="pf-api-value">{escape(TMN_WEBHOOK_URL)}</span></div><div class="pf-api-row"><span class="pf-api-key">Result API</span><span class="pf-api-value">/result-api/&lt;payment_ref&gt;</span></div><div class="pf-table-wrap" style="margin-top:10px;"><table><thead><tr><th>ID</th><th>Time</th><th>Event</th><th>Amount</th><th>Transaction</th><th>Verify</th></tr></thead><tbody>{webhooks_html}</tbody></table></div></section>
      </div>
      <aside class="pf-stack">
        <section class="pf-card"><h2>VIP Price / Group Form</h2><form class="pf-form" action="/private-fastapi/config/save" method="post">{''.join(tier_inputs)}<button class="pf-btn" type="submit">Save price and group IDs</button></form></section>
        <section class="pf-card"><h2>Bot API Config</h2><form class="pf-form" action="/private-fastapi/bot-api/save" method="post"><div><label>Bot API URL</label><input type="url" name="bot_api_url" value="{bot_api_url}" placeholder="https://..."></div><div><label>Bot API Token</label><input type="password" name="bot_api_token" value="{bot_api_token}" autocomplete="off"></div><div><label>Group source</label><input type="text" value="{bot_group_source}" readonly></div><div><label>Bot permission needed</label><input type="text" value="{bot_link_permission}" readonly></div><div><label>Link mode</label><input type="text" value="{bot_link_mode}" readonly></div><div><label><input type="checkbox" name="bot_queue_enabled" value="1" {bot_queue_enabled} style="width:auto;min-height:auto;margin-right:6px;"> Enable bot queue reader later</label></div><div><label>Note</label><input type="text" name="bot_queue_note" value="{bot_queue_note}" placeholder="how bot should read this queue"></div><button class="pf-btn" type="submit">Save bot API settings</button></form></section>
        <section class="pf-card"><h2>Result API Matcher</h2><form class="pf-form" action="/private-fastapi/result-matcher/save" method="post"><div><label>User check event</label><input type="text" name="user_check_event_type" value="{matcher_user_event}" placeholder="enter_group_click"></div><div><label>Buy click event</label><input type="text" name="purchase_event_type" value="{matcher_purchase_event}" placeholder="package_click"></div><div><label>Success page event</label><input type="text" name="success_event_type" value="{matcher_success_event}" placeholder="success_view"></div><div><label>Web source</label><input type="text" name="web_source" value="{matcher_web_source}" placeholder="packages_v"></div><div><label><input type="checkbox" name="require_username_match" value="1" {matcher_require_username} style="width:auto;min-height:auto;margin-right:6px;"> Match same web user</label></div><div><label>Pending message</label><input type="text" name="pending_message" value="{matcher_pending_message}" placeholder="payment is not approved yet"></div><button class="pf-btn" type="submit">Save matcher rules</button></form></section>
        <section class="pf-card"><h2>Pending API Reviews</h2>{reviews_html}</section>
      </aside>
    </section>
  </main>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/privet-fastapi", include_in_schema=False)
def privet_fastapi_alias():
    return RedirectResponse("/private-fastapi", status_code=303)


@app.post("/private-fastapi/config/save")
async def save_private_fastapi_config(
    t3_amount: float = Form(...), t3_link: str = Form(...),
    t2_amount: float = Form(...), t2_link: str = Form(...),
    t1_amount: float = Form(...), t1_link: str = Form(...),
):
    _ensure_tables()
    t3_link = _clean_group_id(t3_link, "VIP Tier 3")
    t2_link = _clean_group_id(t2_link, "VIP Tier 2")
    t1_link = _clean_group_id(t1_link, "VIP Tier 1")
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=3", (t3_amount, t3_link))
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=2", (t2_amount, t2_link))
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=1", (t1_amount, t1_link))
    conn.commit()
    conn.close()
    return RedirectResponse("/private-fastapi", status_code=303)

@app.post("/private-fastapi/bot-api/save")
async def save_private_fastapi_bot_api(
    bot_api_url: str = Form(""),
    bot_api_token: str = Form(""),
    bot_queue_enabled: str = Form("0"),
    bot_queue_note: str = Form(""),
):
    _ensure_tables()
    values = {
        "bot_api_url": bot_api_url.strip()[:500],
        "bot_api_token": bot_api_token.strip()[:500],
        "bot_queue_enabled": "1" if str(bot_queue_enabled).lower() in ("1", "true", "yes", "on") else "0",
        "bot_queue_note": bot_queue_note.strip()[:500],
    }
    conn = _conn()
    cur = conn.cursor()
    for key, value in values.items():
        cur.execute(
            """
            INSERT INTO bot_api_config (key, value, updated_at)
            VALUES (?, ?, strftime('%s','now'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value),
        )
    conn.commit()
    conn.close()
    return RedirectResponse("/private-fastapi", status_code=303)


@app.post("/private-fastapi/result-matcher/save")
async def save_private_fastapi_result_matcher(
    user_check_event_type: str = Form("enter_group_click"),
    purchase_event_type: str = Form("package_click"),
    success_event_type: str = Form("success_view"),
    web_source: str = Form("packages_v"),
    require_username_match: str = Form("0"),
    pending_message: str = Form("waiting for matching user/payment"),
):
    _ensure_tables()
    values = {
        "user_check_event_type": user_check_event_type.strip()[:120],
        "purchase_event_type": purchase_event_type.strip()[:120],
        "success_event_type": success_event_type.strip()[:120],
        "web_source": web_source.strip()[:120],
        "require_username_match": "1" if str(require_username_match).lower() in ("1", "true", "yes", "on") else "0",
        "pending_message": pending_message.strip()[:240],
    }
    conn = _conn()
    cur = conn.cursor()
    for key, value in values.items():
        cur.execute(
            """
            INSERT INTO result_matcher_config (key, value, updated_at)
            VALUES (?, ?, strftime('%s','now'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value),
        )
    conn.commit()
    conn.close()
    return RedirectResponse("/private-fastapi", status_code=303)


@app.get("/api", response_class=HTMLResponse)
def api_dashboard_page():
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ดึงค่าราคาและลิงก์ล่าสุดส่งตรงขึ้นมาโชว์ในช่อง Input ฟอร์มกรอกหน้าเว็บ
    cur.execute("SELECT * FROM vip_tier_config WHERE tier_id=3")
    t3 = dict(cur.fetchone())
    cur.execute("SELECT * FROM vip_tier_config WHERE tier_id=2")
    t2 = dict(cur.fetchone())
    cur.execute("SELECT * FROM vip_tier_config WHERE tier_id=1")
    t1 = dict(cur.fetchone())

    cur.execute("SELECT key, value FROM package_page_config")
    pkg_cfg = {str(k): str(v or '') for k, v in cur.fetchall()}

    # สรุปยอดเงินรวมทั้งหมดจากหน้าตารางตรวจมือที่อนุมัติผ่าน
    cur.execute("SELECT SUM(amount) FROM api_error_payment_reviews WHERE status='approved'")
    total_paid_row = cur.fetchone()
    total_paid = float(total_paid_row[0] or 0.0)

    cur.execute("SELECT COUNT(id) FROM api_error_payment_reviews WHERE amount >= ? AND status='approved'", (t3["min_amount"],))
    tier3_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(id) FROM api_error_payment_reviews WHERE amount >= ? AND amount < ? AND status='approved'", (t2["min_amount"], t3["min_amount"]))
    tier2_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(id) FROM api_error_payment_reviews WHERE amount >= ? AND amount < ? AND status='approved'", (t1["min_amount"], t2["min_amount"]))
    tier1_cnt = cur.fetchone()[0]

    # ดึงตารางประวัติซอง Log ล่าสุด 6 รายการ
    cur.execute("SELECT id, user_id, sender, v, amount, status FROM api_error_payment_reviews ORDER BY id DESC LIMIT 6")
    logs = cur.fetchall()

    # ดึงรายชื่อตั๋วซองค้างตรวจมือ (Pending) มาขึ้นปุ่มตัดสินใจ Yes/No รายใบ
    cur.execute("SELECT id, user_id, sender, url, v, amount FROM api_error_payment_reviews WHERE status='pending' ORDER BY id DESC")
    pending_reviews = cur.fetchall()
    conn.close()

    # ประกอบตาราง Live DB Status
    log_rows = []
    for r in logs:
        st = str(r["status"]).lower()
        lbl_class = "success" if st == "approved" else ("error" if st == "rejected" else "pending")
        lbl_text = "Success" if st == "approved" else ("Error" if st == "rejected" else "Pending")
        log_rows.append(f"""
            <tr>
                <td>#{r['id']}</td>
                <td>{escape(str(r['user_id']))}</td>
                <td>{escape(str(r['sender'] or 'Admin'))}</td>
                <td><code style='color:#f43f5e; font-family:monospace;'>{escape(str(r['v'] or '-'))}</code></td>
                <td><strong>฿{float(r['amount']):,.2f}</strong></td>
                <td><span class='badge {lbl_class}'>{lbl_text}</span></td>
            </tr>
        """)
    log_table_html = "".join(log_rows) if log_rows else "<tr><td colspan='6' style='text-align:center;'>ยังไม่มีข้อมูลการล็อกซอง</td></tr>"

    # ประกอบกล่องตั๋วตรวจมือพร้อมปุ่ม Yes / No คุมแฮนด์เมดรายซอง
    review_rows = []
    for pr in pending_reviews:
        review_rows.append(f"""
            <div class="review-item">
                <div style='font-weight:bold; color:#f59e0b; font-size:14px;'>ReviewID:{pr['id']}</div>
                <div style='font-size:13px;'>{escape(str(pr['sender'] or 'User'))} <span style='color:#64748b;'>[{pr['user_id']}]</span></div>
                <div><a href="{escape(pr['url'])}" target="_blank" style="color:#38bdf8; text-decoration:underline; font-size:13px; word-break:break-all;">{escape(pr['url'])}</a></div>
                <div>
                    <form action="/api/vouchers/action" method="post" style="margin:0; align-items:center;">
                        <input type="hidden" name="review_id" value="{pr['id']}"/>
                        <input type="hidden" name="user_id" value="{pr['user_id']}"/>
                        <input type="number" name="confirm_amount" value="{t3['min_amount']}" step="any" style="width:70px; background:#0f172a; border:1px solid #334155; color:#fff; padding:8px 4px; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;"/>
                        <button type="submit" name="btn_action" value="yes" class="btn approve">อนุมัติ (Yes)</button>
                        <button type="submit" name="btn_action" value="no" class="btn reject">ปฏิเสธ (No)</button>
                    </form>
                </div>
            </div>
        """)
    review_table_html = "".join(review_rows) if review_rows else "<div style='padding:24px; text-align:center; color:#94a3b8; font-weight:600;'>🎉 สะอาดสะอ้าน ไม่มีซองค้างตรวจสอบแล้วค่ะตัวแม่!</div>"

    sample_json = {"event": "TMN_WEBHOOK_RECEIVED", "data": {"voucher_code": "szX8Y7bK9m...", "amount": "899.00", "status": "logged_to_shared_db"}}

    # ประกอบร่างหน้าจอแสดงผล ผนึกแผง "ฟอร์มกรอกเปลี่ยนราคาหน้าเว็บ" 
    body_html = f"""
    <div class="metrics-grid">
        <div class="metric-card"><div class="lbl">Total Paid (ยอดรวมทั้งหมด)</div><div class="num" style="color:#10b981;">฿{total_paid:,.2f}</div></div>
        <div class="metric-card"><div class="lbl">VIP Tier 3 Users ({t3['min_amount']}฿)</div><div class="num">{tier3_cnt} Users</div></div>
        <div class="metric-card"><div class="lbl">VIP Tier 2 Users ({t2['min_amount']}฿)</div><div class="num">{tier2_cnt} Users</div></div>
        <div class="metric-card"><div class="lbl">VIP Tier 1 Users ({t1['min_amount']}฿)</div><div class="num">{tier1_cnt} Users</div></div>
        <div class="metric-card"><div class="lbl">API Latency</div><div class="num" style="color:#60a5fa;">45ms</div></div>
    </div>

<div class="overlay-admin-box">
    <div style="font-weight:800;font-size:14px;color:#fff;">
        Package Overlay Quick Upload
    </div>

    <div style="font-size:12px;color:#94a3b8;margin-top:4px;">
        อัปโหลดรูปเดียวแล้วแปะเป็นพื้นหลังการ์ดได้ทันที
    </div>

    <select id="packageSelect" class="input-box" style="width:100%;margin-top:12px;">
        <option value="basic">Basic</option>
        <option value="premium">Premium</option>
        <option value="vip">VIP</option>
    </select>

    <input
        id="overlayInput"
        type="file"
        accept="image/*"
        class="input-box"
        style="width:100%;margin-top:10px;padding:10px;"
    >

    <div id="overlayPreview" class="overlay-preview"></div>

    <button
        type="button"
        onclick="saveOverlay()"
        class="btn approve"
        style="width:100%;margin-top:12px;"
    >
        Save Overlay
    </button>
</div>

    <div class="split-row">
        <div class="dashboard-section">
            <div class="title section-title">Live Shared Database Status</div>
            <div class="table-container">
                <table class="responsive-table">
                    <thead><tr><th>ID</th><th>ChatID</th><th>User</th><th>Voucher Code</th><th>Amount</th><th>Status</th></tr></thead>
                    <tbody>{log_table_html}</tbody>
                </table>
            </div>
        </div>
        <div class="dashboard-section">
            <div class="title section-title">PAPAN Centralized API Console</div>
            <div style="font-size:13px; margin-bottom:6px; font-weight:600;">Endpoint URL: <code style="color:#34d399; font-family:monospace; word-break:break-all;">{escape(TMN_WEBHOOK_URL)}</code></div>
            <pre style="background:#0f172a; border:1px solid #232d3f; padding:12px; border-radius:8px; font-size:12px; color:#38bdf8; overflow-x:auto; margin:0; height:130px; font-family:monospace;">{escape(json.dumps(sample_json, indent=2))}</pre>
        </div>
    </div>

    <div class="dashboard-section" style="border: 1px solid #ef4444; background: rgba(239,68,68,0.02);">
        <div class="title section-title" style="border-left-color:#ef4444; margin-bottom:12px;">Voucher Error Review (API ErrorPaymentReviews)</div>
        <div style="display:flex; flex-direction:column; gap:8px;">{review_table_html}</div>
    </div>

    <div class="dashboard-section" style="border: 1px solid #f59e0b; background: rgba(245,158,11,0.01);">
        <div class="title section-title" style="border-left-color:#f59e0b;">VIP Tier Configuration Matrix (ตั้งค่าราคาและ Group ID สำหรับบอทสร้างลิงก์)</div>
        <form action="/api/config/save" method="post" enctype="multipart/form-data" novalidate style="display:flex; flex-direction:column; gap:12px; margin:0;">
            
            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#10b981; font-size:13px; margin-bottom:6px;">👑 VIP Tier 3 (กลุ่มหลักระดับราคาบนสุด)</div>
                <div class="form-group-grid">
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">ราคาซอง (บาท)</label>
                        <input type="number" name="t3_amount" value="{t3['min_amount']}" step="any" class="input-box" style="width:100%; margin-top:4px; font-weight:bold; color:#10b981;" required />
                    </div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">Telegram Group ID เช่น -100xxxxxxxxxx</label>
                        <input type="text" name="t3_link" value="{escape(t3['group_link'])}" class="input-box" style="width:100%; margin-top:4px;" required />
                    </div>
                </div>
            </div>

            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#a78bfa; font-size:13px; margin-bottom:6px;">🔮 VIP Tier 2 (กลุ่มระดับราคากลาง)</div>
                <div class="form-group-grid">
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">ราคาซอง (บาท)</label>
                        <input type="number" name="t2_amount" value="{t2['min_amount']}" step="any" class="input-box" style="width:100%; margin-top:4px; font-weight:bold; color:#a78bfa;" required />
                    </div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">Telegram Group ID เช่น -100xxxxxxxxxx</label>
                        <input type="text" name="t2_link" value="{escape(t2['group_link'])}" class="input-box" style="width:100%; margin-top:4px;" required />
                    </div>
                </div>
            </div>

            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#f472b6; font-size:13px; margin-bottom:6px;">🎀 VIP Tier 1 (กลุ่มระดับราคาเริ่มต้น)</div>
                <div class="form-group-grid">
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">ราคาซอง (บาท)</label>
                        <input type="number" name="t1_amount" value="{t1['min_amount']}" step="any" class="input-box" style="width:100%; margin-top:4px; font-weight:bold; color:#f472b6;" required />
                    </div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">Telegram Group ID เช่น -100xxxxxxxxxx</label>
                        <input type="text" name="t1_link" value="{escape(t1['group_link'])}" class="input-box" style="width:100%; margin-top:4px;" required />
                    </div>
                </div>
            </div>

            <div style="background:rgba(232,191,106,0.06); padding:12px; border-radius:10px; border:1px solid rgba(232,191,106,.25);">
                <div style="font-weight:bold; color:#e8bf6a; font-size:13px; margin-bottom:10px;">🖼 ตั้งค่าหน้าแพ็กเกจ / รูปภาพหน้าปก</div>
                <div class="form-group-grid">
                    <div><label style="font-size:11px; color:#94a3b8;">หัวข้อหน้า</label><input name="page_title" value="{escape(pkg_cfg.get('page_title',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">คำอธิบายใต้หัวข้อ</label><input name="page_subtitle" value="{escape(pkg_cfg.get('page_subtitle',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความสถานะซ้ายบน</label><input name="server_text" value="{escape(pkg_cfg.get('server_text',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความปุ่มกลับ</label><input name="back_text" value="{escape(pkg_cfg.get('back_text',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                </div>
            </div>

            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#e8bf6a; font-size:13px; margin-bottom:10px;">⭐ การ์ดแพ็กเกจ 1</div>
                <div class="form-group-grid">
                    <div><label style="font-size:11px; color:#94a3b8;">ชื่อแพ็กเกจ</label><input name="p1_name" value="{escape(pkg_cfg.get('p1_name',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">รูปหน้าปก URL หรือ /static/xxx.webp</label>
                        <input name="p1_cover" value="{escape(pkg_cfg.get('p1_cover',''))}" class="input-box" style="width:100%; margin-top:4px;" />
                        <input id="p1_cover_picker" type="file" accept="image/png,image/jpeg,image/webp" style="display:none" />
                        <input id="p1_cover_data" type="hidden" name="p1_cover_data" value="" />
                        <button type="button" class="crop-open-btn" data-slot="p1">＋ เพิ่มรูปภาพ / ครอปหน้าปก</button>
                        <div id="p1_cover_preview" class="crop-mini-preview" style="{'background-image:linear-gradient(90deg,rgba(8,10,14,.96),rgba(8,10,14,.35)),url(' + escape(pkg_cfg.get('p1_cover','')) + ');' if pkg_cfg.get('p1_cover','') else ''}">
                            <span>{'มีรูปแล้ว กดเพื่อเปลี่ยน/ครอปใหม่' if pkg_cfg.get('p1_cover','') else 'ยังไม่มีรูปหน้าปก'}</span>
                        </div>
                        <div style="font-size:10.5px; color:#64748b; margin-top:4px;">เลือกภาพแล้วลาก/ซูมในกรอบเดียวกับการ์ด จากนั้นกดใช้รูปนี้ ระบบจะตัดเป็น .webp ให้เลย</div>
                    </div>
                    <div><label style="font-size:11px; color:#94a3b8;">ราคา</label><input name="p1_price" value="{escape(pkg_cfg.get('p1_price',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">หน่วยราคา</label><input name="p1_unit" value="{escape(pkg_cfg.get('p1_unit',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 1</label><input name="p1_feature1" value="{escape(pkg_cfg.get('p1_feature1',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 2</label><input name="p1_feature2" value="{escape(pkg_cfg.get('p1_feature2',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มหลัก</label><input name="p1_btn" value="{escape(pkg_cfg.get('p1_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มรอง</label><input name="p1_sub_btn" value="{escape(pkg_cfg.get('p1_sub_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                </div>
            </div>

            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#e8bf6a; font-size:13px; margin-bottom:10px;">👑 การ์ดแพ็กเกจ 2</div>
                <div class="form-group-grid">
                    <div><label style="font-size:11px; color:#94a3b8;">ชื่อแพ็กเกจ</label><input name="p2_name" value="{escape(pkg_cfg.get('p2_name',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">รูปหน้าปก URL หรือ /static/xxx.webp</label>
                        <input name="p2_cover" value="{escape(pkg_cfg.get('p2_cover',''))}" class="input-box" style="width:100%; margin-top:4px;" />
                        <input id="p2_cover_picker" type="file" accept="image/png,image/jpeg,image/webp" style="display:none" />
                        <input id="p2_cover_data" type="hidden" name="p2_cover_data" value="" />
                        <button type="button" class="crop-open-btn" data-slot="p2">＋ เพิ่มรูปภาพ / ครอปหน้าปก</button>
                        <div id="p2_cover_preview" class="crop-mini-preview" style="{'background-image:linear-gradient(90deg,rgba(8,10,14,.96),rgba(8,10,14,.35)),url(' + escape(pkg_cfg.get('p2_cover','')) + ');' if pkg_cfg.get('p2_cover','') else ''}">
                            <span>{'มีรูปแล้ว กดเพื่อเปลี่ยน/ครอปใหม่' if pkg_cfg.get('p2_cover','') else 'ยังไม่มีรูปหน้าปก'}</span>
                        </div>
                        <div style="font-size:10.5px; color:#64748b; margin-top:4px;">เลือกภาพแล้วลาก/ซูมในกรอบเดียวกับการ์ด จากนั้นกดใช้รูปนี้ ระบบจะตัดเป็น .webp ให้เลย</div>
                    </div>
                    <div><label style="font-size:11px; color:#94a3b8;">ป้ายบนการ์ด</label><input name="p2_badge" value="{escape(pkg_cfg.get('p2_badge',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ราคา</label><input name="p2_price" value="{escape(pkg_cfg.get('p2_price',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">หน่วยราคา</label><input name="p2_unit" value="{escape(pkg_cfg.get('p2_unit',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 1</label><input name="p2_feature1" value="{escape(pkg_cfg.get('p2_feature1',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 2</label><input name="p2_feature2" value="{escape(pkg_cfg.get('p2_feature2',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มหลัก</label><input name="p2_btn" value="{escape(pkg_cfg.get('p2_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มรอง</label><input name="p2_sub_btn" value="{escape(pkg_cfg.get('p2_sub_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                </div>
            </div>

            <div style="background:rgba(0,0,0,0.15); padding:12px; border-radius:10px; border:1px solid #334155;">
                <div style="font-weight:bold; color:#e8bf6a; font-size:13px; margin-bottom:10px;">🔥 การ์ดแพ็กเกจ 3</div>
                <div class="form-group-grid">
                    <div><label style="font-size:11px; color:#94a3b8;">ชื่อแพ็กเกจ</label><input name="p3_name" value="{escape(pkg_cfg.get('p3_name',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div>
                        <label style="font-size:11px; color:#94a3b8;">รูปหน้าปก URL หรือ /static/xxx.webp</label>
                        <input name="p3_cover" value="{escape(pkg_cfg.get('p3_cover',''))}" class="input-box" style="width:100%; margin-top:4px;" />
                        <input id="p3_cover_picker" type="file" accept="image/png,image/jpeg,image/webp" style="display:none" />
                        <input id="p3_cover_data" type="hidden" name="p3_cover_data" value="" />
                        <button type="button" class="crop-open-btn" data-slot="p3">＋ เพิ่มรูปภาพ / ครอปหน้าปก</button>
                        <div id="p3_cover_preview" class="crop-mini-preview" style="{'background-image:linear-gradient(90deg,rgba(8,10,14,.96),rgba(8,10,14,.35)),url(' + escape(pkg_cfg.get('p3_cover','')) + ');' if pkg_cfg.get('p3_cover','') else ''}">
                            <span>{'มีรูปแล้ว กดเพื่อเปลี่ยน/ครอปใหม่' if pkg_cfg.get('p3_cover','') else 'ยังไม่มีรูปหน้าปก'}</span>
                        </div>
                        <div style="font-size:10.5px; color:#64748b; margin-top:4px;">เลือกภาพแล้วลาก/ซูมในกรอบเดียวกับการ์ด จากนั้นกดใช้รูปนี้ ระบบจะตัดเป็น .webp ให้เลย</div>
                    </div>
                    <div><label style="font-size:11px; color:#94a3b8;">ราคา</label><input name="p3_price" value="{escape(pkg_cfg.get('p3_price',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">หน่วยราคา</label><input name="p3_unit" value="{escape(pkg_cfg.get('p3_unit',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 1</label><input name="p3_feature1" value="{escape(pkg_cfg.get('p3_feature1',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ข้อความข้อ 2</label><input name="p3_feature2" value="{escape(pkg_cfg.get('p3_feature2',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มหลัก</label><input name="p3_btn" value="{escape(pkg_cfg.get('p3_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                    <div><label style="font-size:11px; color:#94a3b8;">ปุ่มรอง</label><input name="p3_sub_btn" value="{escape(pkg_cfg.get('p3_sub_btn',''))}" class="input-box" style="width:100%; margin-top:4px;" /></div>
                </div>
            </div>

            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <a class="btn" href="/packages" target="_blank" style="background:#334155; color:#fff; flex:1;">👀 เปิดดูหน้าแพ็กเกจ</a>
                <a class="btn" href="/packages?edit=1" target="_blank" style="background:#7c3aed; color:#fff; flex:1;">✦ Visual editor</a>
            </div>

            <button type="submit" class="btn approve" style="padding:12px; font-size:13px; font-weight:bold; width:100%; margin-top:4px; background:linear-gradient(135deg, #10b981, #059669);">💾 กดบันทึกและอัปเดตราคาใหม่ลงระบบทั้งหมด</button>
        </form>
    </div>
    """

    body_html += r"""
    <style>
      .crop-open-btn{width:100%;margin-top:6px;padding:13px 12px;border-radius:14px;border:1px dashed rgba(232,191,106,.55);background:rgba(232,191,106,.08);color:#ffe3a3;font-weight:800;cursor:pointer}
      .crop-mini-preview{margin-top:8px;min-height:92px;border-radius:16px;border:1px solid rgba(255,255,255,.10);background:#07101e;background-size:cover;background-position:center;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;overflow:hidden}
      .crop-mini-preview span{background:rgba(0,0,0,.45);padding:6px 10px;border-radius:999px;backdrop-filter:blur(6px)}
      .crop-modal{position:fixed;inset:0;display:none;align-items:center;justify-content:center;z-index:9999;background:rgba(0,0,0,.78);backdrop-filter:blur(10px);padding:16px}
      .crop-modal.active{display:flex}
      .crop-panel{width:min(520px,100%);background:#08111f;border:1px solid rgba(232,191,106,.26);border-radius:22px;padding:14px;box-shadow:0 30px 80px rgba(0,0,0,.65)}
      .crop-title{font-weight:900;color:#ffe3a3;margin-bottom:10px}
      .crop-frame{position:relative;width:100%;aspect-ratio:2.05/1;border-radius:20px;overflow:hidden;background:#02050a;border:1px solid rgba(255,255,255,.14);touch-action:none;cursor:grab}
      .crop-frame:active{cursor:grabbing}
      .crop-img{position:absolute;left:50%;top:50%;max-width:none;user-select:none;pointer-events:none;transform-origin:center center}
      .crop-shade{position:absolute;inset:0;pointer-events:none;background:linear-gradient(90deg,rgba(8,10,14,.96) 0%,rgba(8,10,14,.86) 34%,rgba(8,10,14,.38) 65%,rgba(8,10,14,.08) 100%)}
      .crop-help{font-size:12px;color:#94a3b8;margin:9px 0 8px;line-height:1.45}
      .crop-range{width:100%}
      .crop-actions{display:flex;gap:8px;margin-top:12px}
      .crop-actions button{flex:1;border:0;border-radius:14px;padding:12px;font-weight:900;cursor:pointer}
      .crop-use{background:linear-gradient(135deg,#e8bf6a,#c99735);color:#171003}
      .crop-cancel{background:#1e293b;color:#dbe5f2}
      .overlay-admin-box{
    margin-bottom:18px;
    padding:16px;
    border-radius:18px;
    background:rgba(255,255,255,.04);
    border:1px solid rgba(255,255,255,.08);
}

.overlay-preview{
    width:100%;
    aspect-ratio:1200 / 420;
    margin-top:12px;
    border-radius:22px;
    overflow:hidden;
    background-size:cover;
    background-position:center;
    background-repeat:no-repeat;
    border:1px solid rgba(255,255,255,.12);
    background-color:#09111d;
}
    </style>
    <div id="cropModal" class="crop-modal" aria-hidden="true">
      <div class="crop-panel">
        <div class="crop-title">จัดรูปหน้าปกให้พอดีกรอบ</div>
        <div id="cropFrame" class="crop-frame"><img id="cropImg" class="crop-img" alt="crop preview"/><div class="crop-shade"></div></div>
        <div class="crop-help">ลากรูปเพื่อจัดตำแหน่ง ใช้แถบซูมให้พอดีกรอบ แล้วกด “ใช้รูปนี้”</div>
        <input id="cropZoom" class="crop-range" type="range" min="1" max="3" step="0.01" value="1" />
        <div class="crop-actions"><button type="button" id="cropCancel" class="crop-cancel">ยกเลิก</button><button type="button" id="cropUse" class="crop-use">ใช้รูปนี้</button></div>
      </div>
    </div>
    <script>
    (() => {
      const modal=document.getElementById('cropModal'), frame=document.getElementById('cropFrame'), img=document.getElementById('cropImg'), zoomInput=document.getElementById('cropZoom'), cancelBtn=document.getElementById('cropCancel'), useBtn=document.getElementById('cropUse');
      let activeSlot=null,fileInput=null,imageLoaded=false,baseScale=1,zoom=1,x=0,y=0,dragging=false,sx=0,sy=0,ox=0,oy=0;
      function applyTransform(){img.style.transform=`translate(-50%, -50%) translate(${x}px, ${y}px) scale(${baseScale*zoom})`;}
      function fitImage(){const fw=frame.clientWidth,fh=frame.clientHeight;baseScale=Math.max(fw/img.naturalWidth,fh/img.naturalHeight);zoom=1;x=0;y=0;zoomInput.value='1';imageLoaded=true;applyTransform();}
      document.querySelectorAll('.crop-open-btn').forEach(btn=>btn.addEventListener('click',()=>{activeSlot=btn.dataset.slot;fileInput=document.getElementById(`${activeSlot}_cover_picker`);fileInput.click();}));
      ['p1','p2','p3'].forEach(slot=>{const input=document.getElementById(`${slot}_cover_picker`);if(!input)return;input.addEventListener('change',()=>{const file=input.files&&input.files[0];if(!file)return;activeSlot=slot;fileInput=input;imageLoaded=false;img.onload=fitImage;img.src=URL.createObjectURL(file);modal.classList.add('active');});});
      zoomInput.addEventListener('input',()=>{zoom=parseFloat(zoomInput.value||'1');applyTransform();});
      frame.addEventListener('pointerdown',e=>{if(!imageLoaded)return;dragging=true;frame.setPointerCapture(e.pointerId);sx=e.clientX;sy=e.clientY;ox=x;oy=y;});
      frame.addEventListener('pointermove',e=>{if(!dragging)return;x=ox+(e.clientX-sx);y=oy+(e.clientY-sy);applyTransform();});
      frame.addEventListener('pointerup',e=>{dragging=false;try{frame.releasePointerCapture(e.pointerId)}catch(_){}});
      cancelBtn.addEventListener('click',()=>{modal.classList.remove('active');if(fileInput)fileInput.value='';});
      useBtn.addEventListener('click',()=>{if(!imageLoaded||!fileInput||!activeSlot)return;const outW=900,outH=Math.round(outW/2.05),canvas=document.createElement('canvas');canvas.width=outW;canvas.height=outH;const ctx=canvas.getContext('2d');ctx.fillStyle='#050910';ctx.fillRect(0,0,outW,outH);const fw=frame.clientWidth,scaleToCanvas=outW/fw,drawW=img.naturalWidth*baseScale*zoom*scaleToCanvas,drawH=img.naturalHeight*baseScale*zoom*scaleToCanvas,drawX=outW/2-drawW/2+x*scaleToCanvas,drawY=outH/2-drawH/2+y*scaleToCanvas;ctx.drawImage(img,drawX,drawY,drawW,drawH);const grad=ctx.createLinearGradient(0,0,outW,0);grad.addColorStop(0,'rgba(8,10,14,.96)');grad.addColorStop(.34,'rgba(8,10,14,.86)');grad.addColorStop(.65,'rgba(8,10,14,.38)');grad.addColorStop(1,'rgba(8,10,14,.08)');ctx.fillStyle=grad;ctx.fillRect(0,0,outW,outH);const dataUrl=canvas.toDataURL('image/webp',.86);const hidden=document.getElementById(activeSlot+'_cover_data');if(hidden)hidden.value=dataUrl;const preview=document.getElementById(activeSlot+'_cover_preview');if(preview){preview.style.backgroundImage='url('+dataUrl+')';preview.innerHTML='<span>พร้อมบันทึกแล้ว กดบันทึกด้านล่าง</span>';}modal.classList.remove('active');});
      const overlayInput = document.getElementById("overlayInput");
const overlayPreview = document.getElementById("overlayPreview");

if (overlayInput && overlayPreview) {
    overlayInput.addEventListener("change", () => {
        const file = overlayInput.files[0];
        if (!file) return;

        overlayPreview.style.backgroundImage =
            `url(${URL.createObjectURL(file)})`;
    });
}

async function saveOverlay(){
    const input = document.getElementById("overlayInput");

    if (!input.files[0]) {
        alert("เลือกรูปก่อน");
        return;
    }

    const fd = new FormData();

    fd.append(
        "package",
        document.getElementById("packageSelect").value
    );

    fd.append("image", input.files[0]);

    const res = await fetch("/admin/package-overlay", {
        method:"POST",
        body:fd
    });

    const data = await res.json();

    if(data.ok){
        alert("saved");
    }else{
        alert("error");
    }
}
    })();
    </script>
    """
    return _render_page(title="Voucher Management Dashboard", header_title="Papan VIP Central Dashboard", header_subtitle="แผงคุมซองเติมเงินระบบรวมศูนย์แฮนด์เมดรายใบ", body=body_html, back_href="/chats")

# =====================================================================
# 🚀 3. เอนพอยต์หลังบ้านรับค่าข้อมูลจากฟอร์มกรอกราคาส่วนตัว
# =====================================================================
@app.post("/api/config/save")
async def save_api_config_matrix(
    t3_amount: float = Form(...), t3_link: str = Form(...),
    t2_amount: float = Form(...), t2_link: str = Form(...),
    t1_amount: float = Form(...), t1_link: str = Form(...),
    page_title: str = Form(""), page_subtitle: str = Form(""), server_text: str = Form(""), back_text: str = Form(""),
    p1_name: str = Form(""), p1_price: str = Form(""), p1_unit: str = Form(""), p1_cover: str = Form(""), p1_feature1: str = Form(""), p1_feature2: str = Form(""), p1_btn: str = Form(""), p1_sub_btn: str = Form(""),
    p2_name: str = Form(""), p2_price: str = Form(""), p2_unit: str = Form(""), p2_cover: str = Form(""), p2_badge: str = Form(""), p2_feature1: str = Form(""), p2_feature2: str = Form(""), p2_btn: str = Form(""), p2_sub_btn: str = Form(""),
    p3_name: str = Form(""), p3_price: str = Form(""), p3_unit: str = Form(""), p3_cover: str = Form(""), p3_feature1: str = Form(""), p3_feature2: str = Form(""), p3_btn: str = Form(""), p3_sub_btn: str = Form(""),
    p1_cover_data: str = Form(""),
    p2_cover_data: str = Form(""),
    p3_cover_data: str = Form(""),
):
    _ensure_tables()

    uploaded_p1_cover = _save_package_cover_data(p1_cover_data, "p1_cover")
    uploaded_p2_cover = _save_package_cover_data(p2_cover_data, "p2_cover")
    uploaded_p3_cover = _save_package_cover_data(p3_cover_data, "p3_cover")
    if uploaded_p1_cover:
        p1_cover = uploaded_p1_cover
    if uploaded_p2_cover:
        p2_cover = uploaded_p2_cover
    if uploaded_p3_cover:
        p3_cover = uploaded_p3_cover
    p1_price = str(t1_amount).rstrip("0").rstrip(".")
    p2_price = str(t2_amount).rstrip("0").rstrip(".")
    p3_price = str(t3_amount).rstrip("0").rstrip(".")
    t3_link = _clean_group_id(t3_link, "VIP Tier 3")
    t2_link = _clean_group_id(t2_link, "VIP Tier 2")
    t1_link = _clean_group_id(t1_link, "VIP Tier 1")

    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=3", (t3_amount, t3_link))
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=2", (t2_amount, t2_link))
    cur.execute("UPDATE vip_tier_config SET min_amount=?, group_link=? WHERE tier_id=1", (t1_amount, t1_link))
    package_values = {
        "page_title": page_title, "page_subtitle": page_subtitle, "server_text": server_text, "back_text": back_text,
        "p1_name": p1_name, "p1_price": p1_price, "p1_unit": p1_unit, "p1_cover": p1_cover, "p1_feature1": p1_feature1, "p1_feature2": p1_feature2, "p1_btn": p1_btn, "p1_sub_btn": p1_sub_btn,
        "p2_name": p2_name, "p2_price": p2_price, "p2_unit": p2_unit, "p2_cover": p2_cover, "p2_badge": p2_badge, "p2_feature1": p2_feature1, "p2_feature2": p2_feature2, "p2_btn": p2_btn, "p2_sub_btn": p2_sub_btn,
        "p3_name": p3_name, "p3_price": p3_price, "p3_unit": p3_unit, "p3_cover": p3_cover, "p3_feature1": p3_feature1, "p3_feature2": p3_feature2, "p3_btn": p3_btn, "p3_sub_btn": p3_sub_btn,
    }
    for key, value in package_values.items():
        cur.execute("INSERT INTO package_page_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()
    return RedirectResponse("/api", status_code=303)

@app.post("/api/vouchers/action")
async def api_voucher_admin_action(request: Request, review_id: int = Form(...), user_id: int = Form(...), confirm_amount: float = Form(...), btn_action: str = Form(...)):
    _ensure_tables()
    conn = _conn()
    cur = conn.cursor()
    if btn_action == "yes":
        cur.execute("UPDATE api_error_payment_reviews SET status='approved', amount=?, reviewed_at=strftime('%s','now') WHERE id=?", (confirm_amount, review_id))
    else:
        cur.execute("UPDATE api_error_payment_reviews SET status='rejected', amount=0.0, reviewed_at=strftime('%s','now') WHERE id=?", (review_id,))
    conn.commit()
    conn.close()
    referer = request.headers.get("referer", "")
    if "/private-fastapi" in referer:
        return RedirectResponse("/private-fastapi", status_code=303)
    return RedirectResponse("/api", status_code=303)

@app.post("/admin/package-overlay")
async def admin_package_overlay(
    package: str = Form(...),
    image: UploadFile = File(...)
):
    safe_package = package.strip().lower()
    if safe_package not in ("basic", "premium", "vip"):
        return {"ok": False, "error": "invalid package"}

    save_path = os.path.join(OVERLAY_DIR, f"{safe_package}.png")

    with open(save_path, "wb") as f:
        shutil.copyfileobj(image.file, f)

    return {
        "ok": True,
        "url": f"/static/package_overlays/{safe_package}.png"
    }

# =====================================================================
# 🚀 4. [ล้างปีกกาซ้อนเรียบร้อย 100%] ปุ่มกดสั่งคุม Block / Delete รายห้องหลัก 
# =====================================================================
@app.get("/block/{chat_id}")
def block(chat_id: int):
    _ensure_tables()
    conn = _conn()
    conn.cursor().execute("INSERT OR IGNORE INTO blocked_users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/chats", status_code=303)

@app.get("/unblock/{chat_id}")
def unblock(chat_id: int):
    _ensure_tables()
    conn = _conn()
    conn.cursor().execute("DELETE FROM blocked_users WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/blocked", status_code=303)

@app.get("/delete/{chat_id}")
def delete(chat_id: int):
    _ensure_tables()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
    cur.execute("DELETE FROM blocked_users WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/chats", status_code=303)

# =====================================================================
# 🟢 5. ส่วนประวัติแชทและการคัดกรองส่องทราฟฟิกลูกค้า (`_infer_status` ปลดเออเร่อตรงกันเป๊ะ)
# =====================================================================
@app.post("/webhook/tmn")
async def webhook_tmn(request: Request):
    _ensure_tables()
    body = await request.json()
    token = str(body.get("message") or "").strip()
    if not token: raise HTTPException(status_code=400, detail="missing message")
    if TMN_WEBHOOK_SECRET:
        try: payload = jwt.decode(token, TMN_WEBHOOK_SECRET, algorithms=["HS256"])
        except Exception as e:
            _webhook_conn_insert({"raw_message": token[:80]}, verify_ok=False, note=f"verify fail: {e}")
            raise HTTPException(status_code=400, detail=f"verify failed: {e}")
    else: payload = {"raw": token}
    _webhook_conn_insert(payload, verify_ok=True, note="received")
    return JSONResponse({"ok": True, "event_type": payload.get("event_type"), "amount": payload.get("amount"), "transaction_id": payload.get("transaction_id") or payload.get("reference_id")})

def _webhook_conn_insert(payload: dict, *, verify_ok: bool, note: str = "") -> None:
    transaction_id = str(payload.get("transaction_id") or payload.get("reference_id") or payload.get("trans_id") or "").strip()
    event_type = str(payload.get("event_type") or "").strip()
    amount = payload.get("amount")
    sender_mobile = str(payload.get("sender_mobile") or payload.get("mobile") or "").strip()
    raw_payload = json.dumps(payload, ensure_ascii=False)
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO webhook_events (ts, source, event_type, amount, sender_mobile, transaction_id, raw_payload, verify_ok, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(transaction_id) DO UPDATE SET ts=excluded.ts, source=excluded.source, event_type=excluded.event_type, amount=excluded.amount, sender_mobile=excluded.sender_mobile, raw_payload=excluded.raw_payload, verify_ok=excluded.verify_ok, note=excluded.note
    """, (int(time.time()), "truemoney", event_type, "" if amount is None else str(amount), sender_mobile, transaction_id or None, raw_payload, 1 if verify_ok else 0, str(note or "")))
    conn.commit()
    conn.close()

@app.get("/blocked", response_class=HTMLResponse)
def blocked():
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    rows = conn.cursor().execute("SELECT b.chat_id, b.blocked_at, MAX(m.ts) AS last_ts, COUNT(m.id) AS cnt, MAX(COALESCE(m.full_name,'')) AS full_name, MAX(COALESCE(m.username,'')) AS username, MAX(COALESCE(m.user_id,'')) AS user_id FROM blocked_users b LEFT JOIN chat_messages m ON m.chat_id=b.chat_id GROUP BY b.chat_id, b.blocked_at ORDER BY b.blocked_at DESC").fetchall()
    conn.close()
    cards = []
    for r in rows:
        identity_text = " • ".join(filter(None, [r["full_name"], f"@{r['username']}" if r['username'] else "", f"uid {r['user_id']}" if r['user_id'] else ""])) or "ไม่มีชื่อ user"
        cards.append(f"""
            <div class="chat-card"><div class="top"><div><div class="title">Blocked ID: {r['chat_id']}</div><div class="small" style="color:#94a3b8; margin-top:2px;">{escape(identity_text)}</div></div><span class="badge error">BLOCKED</span></div>
            <div class="small" style="color:#64748b;">สั่งล็อกเมื่อ: {escape(_fmt_ts(r['blocked_at']))} | ข้อความสะสม: {r['cnt']} ใบ</div><div class="action-row"><a class="btn approve" href="/unblock/{r['chat_id']}">ปลดบล็อกบัญชี</a></div></div>
        """)
    body = "".join(cards) if cards else "<div class='small' style='text-align:center; padding:40px; color:#64748b;'>ไม่มีรายชื่อยูสเซอร์ที่ถูกบล็อกค้างไว้ค่ะ</div>"
    return _render_page(title="Blocked Users", header_title="Blocked Registry", header_subtitle="รายการไอดีที่ถูกสั่งระงับสิทธิ์", body=body, back_href="/chats")

# 🧠 ฟังก์ชันส่องสเตตัสอัจฉริยะ ล้างคำแปลกปลอมออกเกลี้ยง สอดคล้องตามคลังกลางร้อยเปอร์เซ็นต์
def _infer_status(stats: Counter, last_ts: int):
    now = int(time.time())
    age = max(0, now - int(last_ts or 0))
    if stats["payment"] > 0: return "paid", "💰 ลูกค้าจริง"
    if stats["ticket"] > 0 and stats["payment"] == 0: return "pending", "🟡 Pending"
    if age <= 3600: return "active", "🟢 Active"
    if age >= 86400: return "drop", "🔴 Drop"
    return "idle", "⚪ Idle"

@app.get("/chats", response_class=HTMLResponse)
def chats(kind: str = "all", status: str = "all", q: str = ""):
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    rooms = conn.cursor().execute("SELECT chat_id, MAX(ts) AS last_ts, COUNT(*) AS cnt FROM chat_messages GROUP BY chat_id ORDER BY last_ts DESC LIMIT 1000").fetchall()
    cards = []
    q_norm = (q or "").strip().lower()
    for room in rooms:
        conn.cursor().execute("SELECT 1 FROM blocked_users WHERE chat_id=?", (room["chat_id"],))
        if conn.cursor().fetchone(): continue
        rows = conn.cursor().execute("SELECT ts, text, msg_type, direction, user_id, username, full_name FROM chat_messages WHERE chat_id=? ORDER BY ts DESC LIMIT 150", (room["chat_id"],)).fetchall()
        stats = Counter()
        user_id, username, full_name = None, None, None
        for r in rows:
            event_kind, _ = _classify(r["text"], r["msg_type"], r["direction"])
            stats[event_kind] += 1
            if user_id is None and r["user_id"] is not None: user_id = r["user_id"]
            if not username and r["username"]: username = r["username"]
            if not full_name and r["full_name"]: full_name = r["full_name"]
        
        user_status, status_label = _infer_status(stats, room["last_ts"])
        preview = _preview(rows[0]["text"] if rows else "")
        identity_text = " • ".join(filter(None, [full_name, f"@{username}" if username else "", f"uid {user_id}" if user_id is not None else ""])) or "ไม่มีชื่อ user"
        if q_norm and q_norm not in f"{room['chat_id']} {preview} {username} {full_name}".lower(): continue
        if status != "all" and user_status != status: continue
        entered_badge = "<span class='badge success'>ENTERED</span>" if stats["join"] > 0 else ""
        cards.append(f"""
            <div class="chat-card"><div class="top"><div><div class="title"><a href="/chat/{room['chat_id']}">Chat ID: {room['chat_id']}</a></div><div class="small" style="color:#94a3b8; margin-top:2px;">{escape(identity_text)}</div></div><span class="badge {user_status}">{status_label}</span></div>
            <div style="font-size:13px; color:#cbd5e1; margin:6px 0; background:rgba(0,0,0,0.15); padding:8px; border-radius:6px;">{escape(preview)}</div><div class="small" style="color:#64748b;">อัปเดตเมื่อ: {escape(_fmt_ts(room['last_ts']))} | รวม {room['cnt']} ข้อความ {entered_badge}</div>
            <div class="action-row"><a class="btn approve" href="/chat/{room['chat_id']}" style="background-color:#3b82f6;">ส่องห้องแชท</a><a class="btn reject" href="/block/{room['chat_id']}">บล็อก</a></div></div>
        """)
    body_html = f"""<div class="dashboard-section"><div class="section-title">สืบค้นประวัติข้อความหน้าบ้าน</div><form method="get" action="/chats" style="display:flex; gap:8px; margin-bottom:16px;"><input type="text" name="q" value="{escape(q)}" placeholder="🔎 กรอก ChatID, ชื่อพรีวิวเพื่อค้นหา..." class="input-box" style="flex:1;"/><button type="submit" class="btn approve" style="padding:10px 20px;">ค้นหา</button></form><div>{"".join(cards) if cards else "<div class='small' style='color:#64748b; text-align:center; padding:20px;'>ไม่พบข้อมูลประวัติแชท</div>"}</div></div>"""
    return _render_page(title="Chats Inbox", header_title="Papan Chats Support Center", header_subtitle="ศูนย์ตรวจสอบทราฟฟิกข้อมูลลูกค้า", body=body_html)

@app.get("/chat/{chat_id}", response_class=HTMLResponse)
def chat_room(chat_id: int, kind: str = "all"):
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    rows = conn.cursor().execute("SELECT ts, text, msg_type, direction, user_id, username, full_name FROM chat_messages WHERE chat_id=? ORDER BY ts DESC LIMIT 300", (chat_id,)).fetchall()
    stats = Counter()
    user_id, username, full_name = None, None, None
    for r in rows:
        event_kind, _ = _classify(r["text"], r["msg_type"], r["direction"])
        stats[event_kind] += 1
        if user_id is None and r["user_id"] is not None: user_id = r["user_id"]
        if not username and r["username"]: username = r["username"]
        if not full_name and r["full_name"]: full_name = r["full_name"]
    user_status, status_label = _infer_status(stats, rows[0]["ts"] if rows else 0)
    msg_list = []
    for r in rows:
        ek, _ = _classify(r["text"], r["msg_type"], r["direction"])
        if kind != "all" and ek != kind: continue
        dr_class = "in" if str(r["direction"]).lower() == "in" else "out"
        prefix = "👤 ลูกค้า: " if dr_class == "in" else "👑 บอต/แอดมิน: "
        msg_list.append(f"""<div class="msg-row {dr_class}"><div class="small" style="color:#64748b; margin-bottom:2px;">{escape(_fmt_ts(r['ts']))}</div><div><strong>{prefix}</strong>{escape(str(r['text'] or '(ไม่มีข้อความ)'))}</div></div>""")
    body_content = "".join(msg_list) if msg_list else "<div class='small' style='color:#64748b; text-align:center; padding:20px;'>ไม่มีประวัติในหมวดหมู่นี้</div>"
    html_layout = f"""<div class="dashboard-section"><div class="top" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid #334155; padding-bottom:10px;"><div style="font-size:15px; font-weight:bold; color:#fff;">{escape(f"{full_name or 'ไม่ระบุชื่อ'} | ID: {chat_id}")}</div><span class="badge {user_status}">{status_label}</span></div>{_build_kind_tabs(chat_id, kind)}<div style="display:flex; flex-direction:column; gap:10px;">{body_content}</div><div class="action-row" style="margin-top:20px; border-top:1px solid #334155; padding-top:14px;"><a class="btn reject" href="/block/{chat_id}">สั่งบล็อกบัญชีนี้</a><a class="btn" href="/delete/{chat_id}" style="background:#475569; color:#fff;">ล้างห้องแชท</a><a class="btn approve" href="/chats">กลับหน้าหลัก</a></div></div>"""
    return _render_page(title=f"Chat Room {chat_id}", header_title="Chat Inspector", header_subtitle="เจาะลึกประวัติการพิมพ์คุยรายบุคคล", body=html_layout, back_href="/chats")

def _classify(text: Optional[str], msg_type: Optional[str], direction: Optional[str] = None):
    raw = (text or "").strip().lower()
    mtype = (msg_type or "").lower()
    direction = (direction or "").lower()
    if "callback" in mtype or raw.startswith("button:"): return "button", "BUTTON"
    if raw.startswith("/start"): return "cmd", "START"
    if raw.startswith("/ticker"): return "ticket", "TICKER"
    if raw.startswith("/"): return "cmd", "COMMAND"
    if "join group vip" in raw or ("t.me/" in raw and direction == "out"): return "join", "JOIN GROUP"
    if "gift.truemoney.com" in raw or "truemoney" in raw: return "payment", "PAY / QR"
    if mtype == "copy": return "admin", "ADMIN REPLY"
    if any(k in raw for k in ["รับเรื่อง", "แจ้งปัญหา", "ticket", "ติดต่อแอดมิน"]): return "ticket", "TICKET"
    if raw: return "text", "TEXT"
    return "other", "OTHER"

def _build_kind_tabs(chat_id: int, current_kind: str) -> str:
    tabs = [("all", "ข้อความทั้งหมด"), ("text", "คุยปกติ"), ("payment", "ลิงก์ซองเงิน"), ("ticket", "ตั๋วปัญหา"), ("join", "ลิงก์กลุ่ม")]
    html = []
    for k, lbl in tabs:
        act = "style='background:#3b82f6; color:#fff; font-weight:bold; padding:4px 8px; border-radius:6px; font-size:12px; margin-right:4px;'" if current_kind == k else f"href='/chat/{chat_id}?kind={k}' style='padding:4px 8px; font-size:12px; color:#94a3b8; margin-right:4px;'"
        html.append(f"<a {act}>{lbl}</a>")
    return f"<div style='margin:12px 0; border-bottom:1px solid #334155; padding-bottom:8px;'>{''.join(html)}</div>"
