from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")

app = FastAPI(title="Chat Viewer Pro Max")

TG_LINK_RE = re.compile(r'https?://t\.me/[^\s<>\'\"]+')
TM_LINK_RE = re.compile(r"https?://gift\.truemoney\.com/campaign/\S+")


def _conn():
    return sqlite3.connect(DB_PATH)


def _ensure_tables():
    conn = _conn()
    cur = conn.cursor()
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            chat_id INTEGER PRIMARY KEY,
            blocked_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    conn.commit()
    conn.close()


@app.on_event("startup")
def _startup():
    _ensure_tables()


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _preview(text: Optional[str], limit: int = 90) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) > limit:
        return t[:limit] + "…"
    return t or "(ไม่มีข้อความ)"


def _extract_links(text: Optional[str]):
    raw = text or ""
    return TG_LINK_RE.findall(raw), TM_LINK_RE.findall(raw)


def _classify(text: Optional[str], msg_type: Optional[str], direction: Optional[str] = None):
    raw = (text or "").strip()
    lower = raw.lower()
    mtype = (msg_type or "").lower()
    direction = (direction or "").lower()

    if lower.startswith("/start"):
        return "cmd", "START"
    if lower.startswith("/ticker"):
        return "ticket", "TICKER"
    if lower.startswith("/"):
        return "cmd", "COMMAND"

    if "join group vip" in lower or ("t.me/" in lower and direction == "out"):
        return "join", "JOIN GROUP"
    if "gift.truemoney.com" in lower or "truemoney" in lower or "qr" in lower:
        return "payment", "PAY / QR"
    if mtype == "copy":
        return "admin", "ADMIN REPLY"
    if any(k in lower for k in ["รับเรื่อง", "แจ้งปัญหา", "ticket", "ติดต่อแอดมิน"]):
        return "ticket", "TICKET"
    if raw:
        return "text", "TEXT"
    return "other", "OTHER"


def _infer_status(stats: Counter, last_ts: int):
    now = int(time.time())
    age = max(0, now - int(last_ts or 0))
    if stats["payment"] > 0:
        return "paid", "💰 ลูกค้าจริง"
    if stats["ticket"] > 0 and stats["payment"] == 0:
        return "pending", "🟡 Pending"
    if age <= 3600:
        return "active", "🟢 Active"
    if age >= 86400:
        return "drop", "🔴 Drop"
    return "idle", "⚪ Idle"


def _build_kind_tabs(chat_id: int, current_kind: str) -> str:
    tabs = [
        ("all", "ทั้งหมด"),
        ("join", "JOIN"),
        ("payment", "PAY"),
        ("ticket", "TICKET"),
        ("cmd", "CMD"),
        ("admin", "ADMIN"),
        ("text", "TEXT"),
    ]
    html = []
    for value, label in tabs:
        cls = "tab active" if value == current_kind else "tab"
        query = urlencode({"kind": value})
        html.append(f"<a class='{cls}' href='/chat/{chat_id}?{query}'>{label}</a>")
    return "".join(html)


def _base_css() -> str:
    return """
:root{color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0;padding:0;overflow-x:hidden}
body{
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
    background:#0b0b0c;
    color:#eee;
}
a{color:#9ecbff;text-decoration:none}
.header{
    padding:14px 16px;
    border-bottom:1px solid #222;
    position:sticky;
    top:0;
    background:#0b0b0c;
    z-index:5;
    backdrop-filter: blur(8px);
}
.container{
    width:min(1180px, 100%);
    margin:0 auto;
    padding:14px 12px 40px;
}
.small{opacity:.7;font-size:12px}
.search-box{
    display:flex;
    gap:10px;
    align-items:center;
    flex-wrap:wrap;
    margin-top:12px;
}
.search-box input{
    width:min(460px, 100%);
    max-width:100%;
    background:#121214;
    border:1px solid #242428;
    color:#fff;
    padding:10px 12px;
    border-radius:12px;
}
.search-box button{
    background:#1b2740;
    border:1px solid #37527f;
    color:#fff;
    padding:10px 14px;
    border-radius:12px;
    cursor:pointer;
}
.search-box .ghost{
    color:#aaa;
    text-decoration:none;
}
.tabs{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin:10px 0 16px;
}
.tab{
    padding:7px 10px;
    border:1px solid #2a2a30;
    border-radius:999px;
    background:#121214;
    color:#ddd;
    text-decoration:none;
    font-size:12px;
    white-space:nowrap;
}
.tab.active{
    background:#1b2740;
    border-color:#37527f;
    color:#fff;
}
.status-pill{
    font-size:12px;
    padding:6px 10px;
    border-radius:999px;
    border:1px solid #333;
    white-space:nowrap;
}
.status-pill.active{background:#13261b;color:#8af0b5}
.status-pill.pending{background:#122532;color:#7ed9ff}
.status-pill.paid{background:#2a2411;color:#ffd36c}
.status-pill.drop{background:#2b1421;color:#ff9ebf}
.status-pill.idle{background:#1e1f23;color:#ddd}
.badge, .mini{
    font-size:12px;
    padding:5px 9px;
    border-radius:999px;
    border:1px solid #333;
    white-space:nowrap;
}
.badge.join,.mini.join{background:#13261b;color:#8af0b5}
.badge.payment,.mini.payment{background:#2a2411;color:#ffd36c}
.badge.ticket,.mini.ticket{background:#122532;color:#7ed9ff}
.badge.cmd,.mini.cmd{background:#231a35;color:#cfaeff}
.badge.admin,.mini.admin{background:#2b1421;color:#ff9ebf}
.badge.text,.mini.text{background:#1e1f23;color:#ddd}
.badge.entered,.mini.entered{background:#153226;color:#9ff0bf}
.badge.not-entered,.mini.not-entered{background:#232326;color:#b7bcc8}
.empty{
    opacity:.8;
    padding:20px;
    border:1px dashed #333;
    border-radius:14px;
}
.cards-grid{
    display:grid;
    grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));
    gap:12px;
}
.chat-card{
    display:block;
    text-decoration:none;
    color:inherit;
    padding:14px;
    border:1px solid #1f1f22;
    border-radius:18px;
    background:#121214;
    transition:.15s ease;
    min-width:0;
    margin:0;
}
.chat-card:hover{border-color:#32343a;transform:translateY(-1px)}
.chat-card.paid{border-color:#8b6d1d;box-shadow:0 0 0 1px rgba(255,211,108,.15) inset}
.chat-card.pending{border-color:#3d5a80}
.chat-card.active{border-color:#214b32}
.chat-card.drop{opacity:.92}
.top{
    display:grid;
    grid-template-columns:minmax(0,1fr) auto;
    gap:12px;
    align-items:flex-start;
}
.right-box{
    display:flex;
    flex-direction:column;
    gap:8px;
    align-items:flex-end;
}
.title{
    font-weight:800;
    font-size:17px;
    overflow-wrap:anywhere;
}
.meta{opacity:.7;font-size:12px;margin-top:3px}
.count{
    font-size:12px;
    background:#1d2740;
    border:1px solid #2a3d66;
    padding:6px 10px;
    border-radius:999px;
    white-space:nowrap;
}
.preview{
    opacity:.92;
    margin-top:10px;
    line-height:1.45;
    overflow-wrap:anywhere;
}
.identity{
    margin-top:8px;
    font-size:12px;
    color:#b9bfca;
    line-height:1.45;
    overflow-wrap:anywhere;
}
.badges{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    margin-top:12px;
}
.action-row{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-top:12px;
}
.action-btn{
    border:1px solid #2b2f36;
    background:#131416;
    color:#d7dbe3;
    padding:7px 10px;
    border-radius:10px;
    font-size:12px;
    line-height:1;
}
.action-btn:hover{border-color:#444b57;background:#181a1f}
.action-btn.block{color:#ff9ea8;border-color:#4b2b31}
.action-btn.block:hover{background:#241416}
.action-btn.delete{color:#c7c7c7;border-color:#3d3d43}
.action-btn.delete:hover{background:#1c1c1f}
.summary{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    margin:14px 0;
}
.stat-box{
    border:1px solid #262830;
    background:#121214;
    border-radius:14px;
    padding:10px 12px;
    min-width:110px;
}
.stat-box .num{
    font-size:20px;
    font-weight:800;
    line-height:1.1;
}
.stat-box .lbl{
    margin-top:4px;
    font-size:12px;
    opacity:.75;
}
.msg-card{
    padding:14px;
    border:1px solid #1f1f22;
    border-radius:18px;
    background:#121214;
    margin:12px 0;
    min-width:0;
}
.msg-top{
    display:grid;
    grid-template-columns:minmax(0,1fr) auto;
    gap:12px;
    align-items:center;
}
.left-meta{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    min-width:0;
}
.kind,.dir{
    font-size:12px;
    padding:5px 8px;
    border-radius:999px;
    border:1px solid #333;
    white-space:nowrap;
}
.kind.join{background:#13261b;color:#8af0b5}
.kind.payment{background:#2a2411;color:#ffd36c}
.kind.ticket{background:#122532;color:#7ed9ff}
.kind.cmd{background:#231a35;color:#cfaeff}
.kind.admin{background:#2b1421;color:#ff9ebf}
.kind.text,.kind.other{background:#1e1f23;color:#ddd}
.dir.out{background:#17263f;color:#b5cbff}
.dir.in{background:#202125;color:#dbdee5}
.who{
    font-weight:700;
    margin-top:10px;
    overflow-wrap:anywhere;
}
.text-block{
    margin-top:10px;
    line-height:1.6;
    word-break:break-word;
    overflow-wrap:anywhere;
}
.section{
    margin-top:12px;
    padding-top:12px;
    border-top:1px solid #222;
}
.section-title{
    font-size:12px;
    opacity:.7;
    margin-bottom:8px;
}
.kv{
    display:grid;
    grid-template-columns:90px minmax(0,1fr);
    gap:8px;
    margin:6px 0;
}
.kv span{opacity:.8}
.kv a{
    overflow-wrap:anywhere;
    word-break:break-all;
}
.foot{
    margin-top:12px;
    font-size:12px;
    opacity:.7;
}
@media (max-width: 720px){
    .container{padding:12px 10px 28px}
    .cards-grid{grid-template-columns:1fr}
    .top,.msg-top{grid-template-columns:1fr}
    .right-box{align-items:flex-start}
    .search-box input{width:100%}
    .kv{grid-template-columns:1fr}
}
    """


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chats")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


@app.get("/block/{chat_id}")
def block(chat_id: int):
    _ensure_tables()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO blocked_users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/chats", status_code=303)


@app.get("/unblock/{chat_id}")
def unblock(chat_id: int):
    _ensure_tables()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM blocked_users WHERE chat_id=?", (chat_id,))
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


@app.get("/blocked", response_class=HTMLResponse)
def blocked():
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT b.chat_id, b.blocked_at,
               MAX(m.ts) AS last_ts,
               COUNT(m.id) AS cnt,
               MAX(COALESCE(m.full_name,'')) AS full_name,
               MAX(COALESCE(m.username,'')) AS username,
               MAX(COALESCE(m.user_id,'')) AS user_id
        FROM blocked_users b
        LEFT JOIN chat_messages m ON m.chat_id=b.chat_id
        GROUP BY b.chat_id, b.blocked_at
        ORDER BY b.blocked_at DESC
        """
    )
    rows = cur.fetchall()
    conn.close()

    cards = []
    for r in rows:
        identity_parts = []
        if r["full_name"]:
            identity_parts.append(r["full_name"])
        if r["username"]:
            identity_parts.append(f"@{r['username']}")
        if r["user_id"]:
            identity_parts.append(f"uid {r['user_id']}")
        identity_text = " • ".join(identity_parts) if identity_parts else "ไม่มีชื่อ user"

        cards.append(
            f"""
            <div class="chat-card drop">
                <div class="top">
                    <div>
                        <div class="title">Blocked {r['chat_id']}</div>
                        <div class="meta">blocked {escape(_fmt_ts(r['blocked_at']))}</div>
                    </div>
                    <div class="right-box">
                        <div class="count">{r['cnt']} msgs</div>
                    </div>
                </div>
                <div class="identity">{escape(identity_text)}</div>
                <div class="action-row">
                    <a class="action-btn" href="/chat/{r['chat_id']}">เปิดดู</a>
                    <a class="action-btn block" href="/unblock/{r['chat_id']}">ปลด block</a>
                    <a class="action-btn delete" href="/delete/{r['chat_id']}">ลบทั้งหมด</a>
                </div>
            </div>
            """
        )

    body = f"<div class='cards-grid'>{''.join(cards)}</div>" if cards else "<div class='empty'>ยังไม่มี user ที่ถูก block</div>"

    return HTMLResponse(
        f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Blocked Users</title>
<style>{_base_css()}</style>
</head>
<body>
<div class="header">
  <div style="font-weight:800">Blocked Users</div>
  <div class="small"><a href="/chats">← กลับหน้า chats</a></div>
</div>
<div class="container">
  {body}
</div>
</body>
</html>"""
    )


@app.get("/chats", response_class=HTMLResponse)
def chats(kind: str = "all", status: str = "all", q: str = ""):
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chat_id, MAX(ts) AS last_ts, COUNT(*) AS cnt
        FROM chat_messages
        GROUP BY chat_id
        ORDER BY last_ts DESC
        LIMIT 1000
        """
    )
    rooms = cur.fetchall()

    cards = []
    q_norm = (q or "").strip().lower()

    total_paid = 0
    total_pending = 0
    total_active = 0
    total_entered = 0
    total_not_entered = 0

    for room in rooms:
        cur.execute("SELECT 1 FROM blocked_users WHERE chat_id=?", (room["chat_id"],))
        if cur.fetchone():
            continue

        cur.execute(
            """
            SELECT ts, text, msg_type, direction, user_id, username, full_name
            FROM chat_messages
            WHERE chat_id=?
            ORDER BY ts DESC
            LIMIT 150
            """
            ,
            (room["chat_id"],),
        )
        rows = cur.fetchall()

        stats = Counter()
        user_id = None
        username = None
        full_name = None

        for r in rows:
            event_kind, _ = _classify(r["text"], r["msg_type"], r["direction"])
            stats[event_kind] += 1
            if user_id is None and r["user_id"] is not None:
                user_id = r["user_id"]
            if not username and r["username"]:
                username = r["username"]
            if not full_name and r["full_name"]:
                full_name = r["full_name"]

        user_status, status_label = _infer_status(stats, room["last_ts"])
        preview = _preview(rows[0]["text"] if rows else "")
        joined = stats["join"] > 0

        identity_parts = []
        if full_name:
            identity_parts.append(full_name)
        if username:
            identity_parts.append(f"@{username}")
        if user_id is not None:
            identity_parts.append(f"uid {user_id}")
        identity_text = " • ".join(identity_parts) if identity_parts else "ไม่มีชื่อ user"

        searchable_blob = " ".join(
            filter(
                None,
                [
                    str(room["chat_id"]),
                    preview,
                    str(user_id) if user_id is not None else "",
                    username or "",
                    full_name or "",
                ],
            )
        ).lower()

        if q_norm and q_norm not in searchable_blob:
            continue
        if kind != "all" and stats[kind] <= 0 and kind not in ("joined", "not_joined"):
            continue
        if kind == "joined" and not joined:
            continue
        if kind == "not_joined" and joined:
            continue
        if status != "all" and status != user_status:
            continue

        if user_status == "paid":
            total_paid += 1
        if user_status == "pending":
            total_pending += 1
        if user_status == "active":
            total_active += 1
        if joined:
            total_entered += 1
        else:
            total_not_entered += 1

        carry = urlencode({k: v for k, v in {"kind": kind, "status": status, "q": q}.items() if v and v != "all"})
        href = f"/chat/{room['chat_id']}" + (f"?{carry}" if carry else "")

        priority = stats["payment"] * 4 + stats["ticket"] * 3 + stats["join"] * 2 + (2 if user_status == "active" else 0)

        cards.append(
            (
                priority,
                f"""
                <div class="chat-card {user_status}">
                    <a href="{href}">
                        <div class="top">
                            <div>
                                <div class="title">User {room['chat_id']}</div>
                                <div class="meta">ล่าสุด {escape(_fmt_ts(room['last_ts']))}</div>
                            </div>
                            <div class="right-box">
                                <div class="status-pill {user_status}">{status_label}</div>
                                <div class="count">{room['cnt']} msgs</div>
                            </div>
                        </div>
                        <div class="identity">{escape(identity_text)}</div>
                        <div class="preview">{escape(preview)}</div>
                        <div class="badges">
                            <span class="badge join">JOIN {stats['join']}</span>
                            <span class="badge payment">PAY {stats['payment']}</span>
                            <span class="badge ticket">TICKET {stats['ticket']}</span>
                            <span class="badge cmd">CMD {stats['cmd']}</span>
                            <span class="badge admin">ADMIN {stats['admin']}</span>
                            {"<span class='badge entered'>เคยเข้า</span>" if joined else "<span class='badge not-entered'>ยังไม่เข้า</span>"}
                        </div>
                    </a>
                    <div class="action-row">
                        <a class="action-btn" href="{href}">เปิด timeline</a>
                        <a class="action-btn block" href="/block/{room['chat_id']}">block</a>
                        <a class="action-btn delete" href="/delete/{room['chat_id']}">delete</a>
                    </div>
                </div>
                """
            )
        )

    conn.close()

    cards = sorted(cards, key=lambda x: x[0], reverse=True)
    body = f"<div class='cards-grid'>{''.join(c[1] for c in cards)}</div>" if cards else "<div class='empty'>ยังไม่มีข้อมูลแชทในเงื่อนไขนี้</div>"

    def _filter_link(k=None, s=None):
        params = {}
        k_val = k if k is not None else kind
        s_val = s if s is not None else status
        if k_val and k_val != "all":
            params["kind"] = k_val
        if s_val and s_val != "all":
            params["status"] = s_val
        if q:
            params["q"] = q
        return "/chats" + (f"?{urlencode(params)}" if params else "")

    kind_tabs = "".join(
        f"<a class='tab {'active' if kind == value else ''}' href='{_filter_link(k=value)}'>{label}</a>"
        for value, label in [
            ("all", "ทั้งหมด"),
            ("join", "JOIN"),
            ("payment", "PAY"),
            ("ticket", "TICKET"),
            ("cmd", "CMD"),
            ("admin", "ADMIN"),
            ("joined", "เคยเข้า"),
            ("not_joined", "ยังไม่เข้า"),
        ]
    )
    status_tabs = "".join(
        f"<a class='tab {'active' if status == value else ''}' href='{_filter_link(s=value)}'>{label}</a>"
        for value, label in [("all", "ทุกสถานะ"), ("active", "Active"), ("pending", "Pending"), ("paid", "ลูกค้าจริง"), ("drop", "Drop")]
    )

    dashboard = f"""
    <div class="summary">
      <div class="stat-box"><div class="num">{total_paid}</div><div class="lbl">ลูกค้าจริง</div></div>
      <div class="stat-box"><div class="num">{total_pending}</div><div class="lbl">Pending</div></div>
      <div class="stat-box"><div class="num">{total_active}</div><div class="lbl">Active</div></div>
      <div class="stat-box"><div class="num">{total_entered}</div><div class="lbl">เคยเข้า</div></div>
      <div class="stat-box"><div class="num">{total_not_entered}</div><div class="lbl">ยังไม่เข้า</div></div>
      <div class="stat-box"><div class="num"><a href="/blocked">ดู</a></div><div class="lbl">Blocked</div></div>
    </div>
    """

    return HTMLResponse(
        f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Chat Viewer Pro Max</title>
<style>{_base_css()}</style>
</head>
<body>
<div class="header">
  <div style="font-weight:800">Chat Viewer Pro Max</div>
  <div class="small">รวมตาม user | ค้นหาได้ทั้ง chat id / user id / @username / full name | แยกเคยเข้า / ยังไม่เข้า ได้แล้ว</div>
  <form class="search-box" method="get" action="/chats">
    <input type="text" name="q" value="{escape(q)}" placeholder="ค้นหา chat id, user id, @username, ชื่อ หรือข้อความล่าสุด"/>
    {f'<input type="hidden" name="kind" value="{escape(kind)}"/>' if kind != 'all' else ''}
    {f'<input type="hidden" name="status" value="{escape(status)}"/>' if status != 'all' else ''}
    <button type="submit">ค้นหา</button>
    <a class="ghost" href="/chats">ล้างค่า</a>
  </form>
</div>
<div class="container">
  {dashboard}
  <div class="tabs">{kind_tabs}</div>
  <div class="tabs">{status_tabs}</div>
  {body}
</div>
</body>
</html>"""
    )


@app.get("/chat/{chat_id}", response_class=HTMLResponse)
def chat(chat_id: int, limit: int = 1200, kind: str = "all"):
    _ensure_tables()
    conn = _conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, direction, user_id, username, full_name, msg_type, text
        FROM chat_messages
        WHERE chat_id=?
        ORDER BY ts ASC
        LIMIT ?
        """
        ,
        (chat_id, limit),
    )
    rows = cur.fetchall()

    cur.execute("SELECT 1 FROM blocked_users WHERE chat_id=?", (chat_id,))
    is_blocked = cur.fetchone() is not None

    conn.close()

    cards = []
    counts = Counter()
    user_id = None
    username = None
    full_name = None

    for r in rows:
        event_kind, label = _classify(r["text"], r["msg_type"], r["direction"])
        counts[event_kind] += 1

        if user_id is None and r["user_id"] is not None:
            user_id = r["user_id"]
        if not username and r["username"]:
            username = r["username"]
        if not full_name and r["full_name"]:
            full_name = r["full_name"]

        if kind != "all" and event_kind != kind:
            continue

        who = r["full_name"] or r["username"] or ("bot" if r["direction"] == "out" else "user")
        tg_links, tm_links = _extract_links(r["text"])

        links_html = ""
        if tg_links or tm_links:
            chunks = []
            for link in tg_links:
                chunks.append(f"<div class='kv'><span>Telegram</span><a href='{escape(link)}' target='_blank'>{escape(link)}</a></div>")
            for link in tm_links:
                chunks.append(f"<div class='kv'><span>Truemoney</span><a href='{escape(link)}' target='_blank'>{escape(link)}</a></div>")
            links_html = f"<div class='section'><div class='section-title'>ลิงก์ที่ดึงออกมา</div>{''.join(chunks)}</div>"

        msg = escape(r["text"] or "").replace("\\n", "<br/>")
        direction_label = "BOT" if r["direction"] == "out" else "USER"
        msg_type = escape(str(r["msg_type"] or "-"))

        cards.append(
            f"""
            <article class="msg-card {event_kind}">
                <div class="msg-top">
                    <div class="left-meta">
                        <span class="kind {event_kind}">{label}</span>
                        <span class="dir {'out' if r['direction'] == 'out' else 'in'}">{direction_label}</span>
                    </div>
                    <div class="time">{escape(_fmt_ts(r['ts']))}</div>
                </div>
                <div class="who">{escape(who)}</div>
                <div class="text-block">{msg}</div>
                {links_html}
                <div class="foot">msg_type: {msg_type}</div>
            </article>
            """
        )

    body = "\\n".join(cards) if cards else "<div class='empty'>ยังไม่มีข้อความในเงื่อนไขนี้</div>"
    tabs = _build_kind_tabs(chat_id, kind)
    last_ts = rows[-1]["ts"] if rows else 0
    user_status, status_label = _infer_status(counts, last_ts)

    id_parts = []
    if full_name:
        id_parts.append(full_name)
    if username:
        id_parts.append(f"@{username}")
    if user_id is not None:
        id_parts.append(f"uid {user_id}")
    identity = " • ".join(id_parts) if id_parts else f"chat {chat_id}"

    joined = counts["join"] > 0
    entered_badge = "<span class='mini entered'>เคยเข้า</span>" if joined else "<span class='mini not-entered'>ยังไม่เข้า</span>"
    block_button = (
        f"<a class='action-btn' href='/unblock/{chat_id}'>ปลด block</a>" if is_blocked else f"<a class='action-btn block' href='/block/{chat_id}'>block</a>"
    )

    summary = (
        f"<div class='summary'>"
        f"<span class='status-pill {user_status}'>{status_label}</span>"
        f"<span class='mini join'>JOIN {counts['join']}</span>"
        f"<span class='mini payment'>PAY {counts['payment']}</span>"
        f"<span class='mini ticket'>TICKET {counts['ticket']}</span>"
        f"<span class='mini cmd'>CMD {counts['cmd']}</span>"
        f"<span class='mini admin'>ADMIN {counts['admin']}</span>"
        f"<span class='mini text'>TEXT {counts['text']}</span>"
        f"{entered_badge}"
        f"</div>"
    )

    action_bar = f"""
    <div class="action-row">
      {block_button}
      <a class="action-btn delete" href="/delete/{chat_id}">delete</a>
      <a class="action-btn" href="/chats">กลับหน้า chats</a>
    </div>
    """

    return HTMLResponse(
        f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Chat {chat_id}</title>
<style>{_base_css()}</style>
</head>
<body>
<div class="header">
  <a href="/chats">← กลับ</a>
  <div>
    <div style="font-weight:800">User {chat_id}</div>
    <div class="small">{escape(identity)} | timeline ทั้งหมดของ user คนนี้ | limit {limit}</div>
  </div>
</div>
<div class="container">
  {summary}
  {action_bar}
  <div class="tabs">{tabs}</div>
  {body}
</div>
</body>
</html>"""
    )