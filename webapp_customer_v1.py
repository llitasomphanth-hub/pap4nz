from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

GROUP_LINK = "https://t.me/+R307dlx7C9E4ODQ1"
BOT_LINK = "https://t.me/doktongggggg_bot?start=menu"
CONTACT_LINK = "https://t.me/Dok_tong"
CONTACT_TEXT = "@Dok_tong"

@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>PAPXNZ Customer View</title>

<style>
:root {{
    --bg-top:#02060d;
    --bg-bottom:#061326;
    --panel-top:#0a1a33;
    --panel-bottom:#050d1a;
    --text:#ffffff;
    --sub:#b8c3d6;
    --blue-a:#3cc8ff;
    --blue-b:#2b7fff;
    --tg-text:#244c86;
    --vip-a:#3a1a10;
    --vip-b:#1a0804;
    --gold-soft:#ffd98a;
    --gold-mid:#e8a63c;
    --gold-deep:#8a4d12;
    --vip-core:#f0b34a;
    --vip-glow:#ffcf6a;
}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{
    margin:0;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    background:
      radial-gradient(circle at 82% 20%, rgba(35,118,255,.16), transparent 18%),
      radial-gradient(circle at 16% 90%, rgba(0,155,255,.08), transparent 18%),
      linear-gradient(180deg,var(--bg-top),var(--bg-bottom));
    color:var(--text);
    min-height:100vh;
}}
.container{{
    max-width:420px;
    margin:auto;
    padding:20px 16px 150px;
}}
.box{{
    background:
      radial-gradient(circle at 86% 20%, rgba(31,132,255,.12), transparent 18%),
      linear-gradient(180deg,var(--panel-top),var(--panel-bottom));
    border-radius:26px;
    padding:22px 18px 24px;
    border:1px solid rgba(255,255,255,0.05);
    box-shadow:0 10px 30px rgba(0,0,0,0.4), inset 0 0 0 1px rgba(75,120,255,.05);
}}
.badge{{
    display:inline-flex;
    align-items:center;
    gap:10px;
    padding:8px 16px;
    border-radius:999px;
    background:rgba(255,255,255,0.06);
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.03);
    font-size:12px;
    letter-spacing:.03em;
    margin-bottom:16px;
    color:#dfe8f8;
}}
.badge-dot{{
    width:12px;height:12px;border-radius:50%;
    background:linear-gradient(180deg,#4dc6ff,#2b7fff);
    box-shadow:0 0 10px rgba(79,181,255,.45);
    flex:0 0 12px;
}}
.title{{
    font-size:34px;
    font-weight:930;
    line-height:1.24;
    margin-bottom:22px;
    letter-spacing:-.03em;
    text-shadow:0 2px 10px rgba(0,0,0,.26);
}}
.desc{{
    color:var(--sub);
    font-size:14px;
    line-height:1.8;
    text-shadow:0 1px 4px rgba(0,0,0,.16);
}}
.btn{{
    display:flex;
    align-items:center;
    justify-content:center;
    gap:14px;
    height:72px;
    border-radius:999px;
    font-size:18px;
    font-weight:850;
    text-decoration:none;
    margin-top:18px;
    color:#fff;
}}
.btn-label{{
    position:relative;
    z-index:2;
    font-weight:900;
    text-shadow:0 1px 2px rgba(255,255,255,.08), 0 1px 8px rgba(0,0,0,.16);
}}
.btn-tg{{
    background:linear-gradient(135deg,var(--blue-a),var(--blue-b));
    box-shadow:0 8px 25px rgba(50,150,255,0.25), 0 0 32px rgba(43,127,255,.14);
}}
.btn-tg .btn-label{{
    color:var(--tg-text);
    text-shadow:0 1px 0 rgba(255,255,255,.18), 0 1px 6px rgba(22,56,109,.10);
}}
.btn-vip {{
    position: relative;
    background: linear-gradient(
        145deg,
        #ffe08a 0%,
        #ffb84d 25%,
        #c97a1f 55%,
        #7a3e00 100%
    );

    border: 1px solid rgba(255, 190, 90, 0.5);

    box-shadow:
        0 0 8px rgba(255, 180, 80, 0.35),
        inset 0 2px 4px rgba(255,255,255,0.3),
        inset 0 -3px 8px rgba(0,0,0,0.45);

    border-radius: 999px;

    color: #3b2200;
}}
.btn-vip {{
    position: relative;

    background: linear-gradient(
        145deg,
        #fff6cc 0%,
        #ffe27a 15%,
        #ffbf3f 35%,
        #b8731a 65%,
        #5a2e05 100%
    );

    border: 1px solid rgba(255, 215, 100, 0.6);

    box-shadow:
        0 0 6px rgba(255, 215, 120, 0.4),
        inset 0 1px 2px rgba(255,255,255,0.4),
        inset 0 -2px 6px rgba(0,0,0,0.4);

    border-radius: 999px;
    color: #2b1a00;
}}
.btn-vip::before{{
    content:"";
    position:absolute;
    inset:7px;
    border-radius:999px;
    border:2px solid rgba(232,182,84,.78);
    box-shadow:0 0 8px rgba(255,207,106,.10), inset 0 0 10px rgba(255,213,122,.05);
    pointer-events:none;
}}
.btn-vip::after {{
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 999px;

    background: radial-gradient(
        circle at center,
        rgba(255,230,140,0.5) 0%,
        rgba(255,200,100,0.2) 30%,
        transparent 60%
    );

    pointer-events: none;
}}
.btn-icon-circle{{
    width:54px;height:54px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    position:relative;z-index:2;flex:0 0 54px;
}}
.btn-icon-circle.tg{{
    background:linear-gradient(180deg,#3dbcf3 0%, #0077c8 100%);
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.08), 0 4px 10px rgba(0,0,0,.18);
}}
.btn-icon-badge.vip{{
    width:56px;height:40px;border-radius:4px;
    display:flex;align-items:center;justify-content:center;
    position:relative;z-index:2;flex:0 0 56px;
    background:linear-gradient(180deg,#060606,#121212 55%,#070707);
    box-shadow:0 4px 10px rgba(0,0,0,.18), inset 0 0 0 1px rgba(255,255,255,.06);
    overflow:hidden;
}}
.btn-icon-badge.vip::before,
.btn-icon-badge.vip::after{{
    content:"";position:absolute;left:0;right:0;height:2px;
    background:linear-gradient(90deg,rgba(0,0,0,0), rgba(255,216,128,.92), rgba(255,170,72,.84), rgba(0,0,0,0));
    box-shadow:0 0 10px rgba(255,204,104,.15);
}}
.btn-icon-badge.vip::before{{top:9px}}
.btn-icon-badge.vip::after{{bottom:9px}}
.btn-icon-badge.vip span{{
    position:relative;z-index:1;
    font-size:16px;font-weight:900;letter-spacing:.02em;
    background:linear-gradient(180deg,#ffe6a6 0%, var(--gold-soft) 18%, var(--gold-mid) 58%, #b56614 100%);
    -webkit-background-clip:text;background-clip:text;color:transparent;
    filter:drop-shadow(0 0 5px rgba(255,208,108,.20)) drop-shadow(0 1px 1px rgba(0,0,0,.18));
}}
.icon{{display:block}}
.icon.tg-main{{width:28px;height:28px;fill:#fff;opacity:.96}}
.icon.tg-mini,.icon.vip-mini,.icon.support-mini{{width:19px;height:19px;fill:#e9eef7;opacity:.34}}
.icon.support-main{{width:34px;height:34px;fill:#fff;opacity:.97}}
.menu{{
    margin-top:30px;
    display:flex;
    flex-direction:column;
    gap:18px;
}}
.menu-item{{
    display:flex;
    gap:14px;
    align-items:center;
    font-size:15px;
    color:#eef4ff;
    line-height:1.45;
    padding-bottom:10px;
    border-bottom:1px solid rgba(255,255,255,.055);
}}
.menu-icon{{
    width:26px;
    height:26px;
    flex:0 0 26px;
    display:flex;
    align-items:center;
    justify-content:center;
    opacity:.76;
}}
.menu-item:last-child{{border-bottom:none;padding-bottom:0}}
.menu-item span{{text-shadow:0 1px 2px rgba(0,0,0,.18)}}
.contact{{
    text-align:center;
    margin-top:34px;
    padding-top:14px;
    border-top:1px solid rgba(255,255,255,.08);
    font-size:15px;
    color:#dfe6f5;
    line-height:1.55;
    text-shadow:0 1px 3px rgba(0,0,0,.18);
}}
.contact-title{{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    gap:8px;
    margin-bottom:4px;
}}
.contact-mail{{
    width:15px;
    height:15px;
    fill:#dfe6f5;
    opacity:.45;
}}
.contact-link{{
    color:#bdd2ee;
    text-decoration:underline;
    text-decoration-color:rgba(189,210,238,.55);
    text-underline-offset:3px;
    font-size:18px;
    font-weight:800;
}}
.contact-link:visited{{color:#bdd2ee}}
.support{{
    position:fixed;
    right:20px;
    bottom:92px;
    width:78px;
    height:78px;
    border-radius:50%;
    background: radial-gradient(circle at 40% 32%, #ff6f52, #ff4933 45%, #de1400 75%, #b20000 100%);
    display:flex;
    align-items:center;
    justify-content:center;
    border:2px solid rgba(255,255,255,.18);
    box-shadow:
      0 0 0 6px rgba(255,255,255,.045),
      0 0 0 12px rgba(255,80,50,.075),
      0 0 22px rgba(255,88,52,.28),
      0 0 36px rgba(255,52,24,.10),
      inset 0 0 12px rgba(255,255,255,.13);
    z-index:10;
}}
.support::before{{
    content:"";
    position:absolute;
    inset:-14px;
    border-radius:50%;
    border:1px solid rgba(255,255,255,.09);
    opacity:.72;
}}
.support::after{{
    content:"ติดต่อ/สอบถาม";
    position:absolute;
    left:50%;
    top:calc(100% + 10px);
    transform:translateX(-50%);
    font-size:11px;
    font-weight:600;
    letter-spacing:.01em;
    color:rgba(255,255,255,.72);
    text-shadow:0 1px 8px rgba(255,110,86,.18);
    white-space:nowrap;
}}
@media (max-width:430px){{
    .container{{padding:20px 16px 170px;}}
    .title{{font-size:32px; line-height:1.16; margin-bottom:20px;}}
    .btn{{height:70px;}}
}}

.btn-vip{
    transition: all 0.2s ease;
}
.btn-vip:hover{
    transform: translateY(-2px);
    box-shadow:
        0 10px 25px rgba(0,0,0,0.5),
        0 0 12px rgba(255,180,80,0.35),
        inset 0 2px 4px rgba(255,255,255,0.3),
        inset 0 -3px 8px rgba(0,0,0,0.45);
}
.btn-vip:active{
    transform: translateY(1px);
    box-shadow:
        0 6px 14px rgba(0,0,0,0.4),
        0 0 8px rgba(255,180,80,0.25),
        inset 0 2px 4px rgba(255,255,255,0.25),
        inset 0 -2px 6px rgba(0,0,0,0.4);
}

</style>
</head>
<body>
<div class="container">
<div class="box">
    <div class="badge"><span class="badge-dot"></span>PAPXNZ CUSTOMER VIEW</div>

    <div class="title">
        เข้าสู่ช่องทางหลัก<br>
        ได้ทันที
    </div>

    <div class="desc">
        เข้ากลุ่มหลัก สมัคร VIP และติดต่อแอดมินได้ทันทีจาก<br>หน้านี้
    </div>
</div>

<a href="{GROUP_LINK}" class="btn btn-tg">
    <span class="btn-icon-circle tg">
      <svg class="icon tg-main" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M21.4 4.6L18.3 19c-.23 1.03-.83 1.28-1.68.8l-4.66-3.43-2.25 2.16c-.25.25-.46.46-.95.46l.34-4.83 8.79-7.94c.38-.34-.08-.53-.6-.19l-10.87 6.85-4.68-1.46c-1.02-.32-1.04-1.02.21-1.51L19.55 3c.88-.33 1.64.2 1.35 1.6Z"/>
      </svg>
    </span>
    <span class="btn-label">กลุ่ม Telegram</span>
</a>

<a href="{BOT_LINK}" class="btn btn-vip">
    <span class="btn-icon-badge vip"><span>VIP</span></span>
    <span class="btn-label">สมัคร VIP</span>
</a>

<div class="menu">
    <div class="menu-item">
        <div class="menu-icon">
            <svg class="icon tg-mini" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M21.4 4.6L18.3 19c-.23 1.03-.83 1.28-1.68.8l-4.66-3.43-2.25 2.16c-.25.25-.46.46-.95.46l.34-4.83 8.79-7.94c.38-.34-.08-.53-.6-.19l-10.87 6.85-4.68-1.46c-1.02-.32-1.04-1.02.21-1.51L19.55 3c.88-.33 1.64.2 1.35 1.6Z"/>
            </svg>
        </div>
        <span>เข้ากลุ่มหลักของเราโดยตรง</span>
    </div>

    <div class="menu-item">
        <div class="menu-icon">
            <svg class="icon vip-mini" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 18.2V7.3c0-.7.6-1.3 1.3-1.3h15.4c.7 0 1.3.6 1.3 1.3v10.9c0 .7-.6 1.3-1.3 1.3H4.3c-.7 0-1.3-.6-1.3-1.3Zm2.9-8.1L7.1 12l1.5-1.1-.6 1.8 1.7-1 1.4 1.1-.5-1.9 1.7 1-.7-1.9 1.8.1-1.4-1.1 1.4-1-.9.1.7-1.4-1.4.8.5-1.6-1.3 1-.9-1.1-.8 1.1-1.4-1 .6 1.6-1.6-.9.8 1.5H5.9Zm9.2 4.4h4.1v1.4h-4.1v-1.4Zm0-2.7h4.1v1.3h-4.1v-1.3Z"/>
            </svg>
        </div>
        <span>สมัคร VIP ผ่านบอทได้ทันที</span>
    </div>

    <div class="menu-item">
        <div class="menu-icon">
            <svg class="icon support-mini" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 3.6A7.4 7.4 0 0 0 4.6 11v4c0 1 .8 1.8 1.8 1.8h1v-5.2H6.2a5.8 5.8 0 0 1 11.6 0h-1.2v5.2h.8a2.9 2.9 0 0 1-2.65 1.8h-1.6a1 1 0 1 0 0 2h1.6A4.9 4.9 0 0 0 19.6 15v-4A7.4 7.4 0 0 0 12 3.6Z"/>
            </svg>
        </div>
        <span>ติดต่อแอดมิน</span>
    </div>
</div>

<div class="contact">
    <div class="contact-title">
        <svg class="contact-mail" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 6.8c0-.99.81-1.8 1.8-1.8h14.4c.99 0 1.8.81 1.8 1.8v10.4c0 .99-.81 1.8-1.8 1.8H4.8A1.8 1.8 0 0 1 3 17.2V6.8Zm1.7.2 7.3 5.44L19.3 7H4.7Zm14.6 10.3V8.97l-6.79 5.04a.9.9 0 0 1-1.07 0L4.7 8.97v8.33h14.6Z"/>
        </svg>
        <span>ช่องทางการติดต่อ</span>
    </div>
    <a class="contact-link" href="{CONTACT_LINK}">{CONTACT_TEXT}</a>
</div>

</div>

<a class="support" href="{CONTACT_LINK}" aria-label="contact">
  <svg class="icon support-main" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3.2A7.8 7.8 0 0 0 4.2 11v4.1c0 1.16.94 2.1 2.1 2.1H8a.8.8 0 0 0 .8-.8v-4.7A1.7 1.7 0 0 0 7.1 10H5.9a6.1 6.1 0 0 1 12.2 0h-1.2a1.7 1.7 0 0 0-1.7 1.7v4.7c0 .44.36.8.8.8h.95a2.25 2.25 0 0 1-2.17 1.65h-1.94a1.2 1.2 0 1 0 0 2.4h1.94A4.65 4.65 0 0 0 19.45 17c.8-.37 1.35-1.18 1.35-2.03V11A7.8 7.8 0 0 0 12 3.2Z"/>
    <path d="M14.8 18.7a1.1 1.1 0 0 1-1.1 1.1h-2.25a1.1 1.1 0 1 1 0-2.2h2.25a1.1 1.1 0 0 1 1.1 1.1Z"/>
  </svg>
</a>

</body>
</html>
"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
