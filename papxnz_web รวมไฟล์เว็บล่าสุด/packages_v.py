from __future__ import annotations
import json
import os
import sqlite3
from html import escape
from urllib.parse import urlencode
from fastapi import Request
from fastapi.responses import HTMLResponse

ADMIN_LINK = os.getenv("ADMIN_LINK", "https://t.me/dok_tongg")
MAIN_WEB_LINK = "/"

DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")
EDITOR_VERSION = "visual-editor-20260523-0738"


def _package_defaults() -> dict:
    return {
        "page_title": "เลือกแพ็กเกจ VIP",
        "page_subtitle": "ยกระดับบอทส่วนตัวของคุณด้วยฟีเจอร์พรีเมียม",
        "server_text": "SERVER ONLINE 24HR",
        "back_text": "กลับหน้าหลัก",

        "p1_icon": "star",
        "p1_name": "VIP Starter",
        "p1_price": "199",
        "p1_unit": "บาท / 30 วัน",
        "p1_feature1": "ปลดล็อกเข้ากลุ่มลับ VIP Access Link ได้ทันที",
        "p1_feature2": "ระบบตรวจสอบยอดเติมเงินออโต้ 24 ชั่วโมง",
        "p1_feature3": "",
        "p1_feature4": "",
        "p1_feature5": "",
        "p1_btn": "สมัครแพ็กเกจนี้",
        "p1_sub_btn": "ดูตัวอย่าง",
        "p1_cover": "",

        "p2_icon": "crown",
        "p2_name": "VIP Pro Pass",
        "p2_price": "499",
        "p2_unit": "บาท / 90 วัน",
        "p2_feature1": "รวมสรรพคุณของระดับ Starter ทั้งหมดไว้ครบ",
        "p2_feature2": "ความเร็วประมวลผลคิวพิเศษ (Fast Pass VIP)",
        "p2_feature3": "",
        "p2_feature4": "",
        "p2_feature5": "",
        "p2_btn": "สมัครแพ็กเกจนี้",
        "p2_sub_btn": "ดูตัวอย่าง",
        "p2_badge": "RECOMMENDED",
        "p2_cover": "",

        "p3_icon": "flame",
        "p3_name": "VIP Lifetime",
        "p3_price": "999",
        "p3_unit": "บาท / ตลอดชีพ",
        "p3_feature1": "จ่ายครั้งเดียวจบ ปลดล็อกทุกฟีเจอร์ถาวร 100%",
        "p3_feature2": "รับยศพิเศษประดับโปรไฟล์สมาชิกถาวรสุดเท่",
        "p3_feature3": "",
        "p3_feature4": "",
        "p3_feature5": "",
        "p3_btn": "สมัครแพ็กเกจนี้",
        "p3_sub_btn": "ดูตัวอย่าง",
        "p3_cover": "",
    }


def _load_package_config() -> dict:
    cfg = _package_defaults()
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS package_page_config (key TEXT PRIMARY KEY, value TEXT)")
        for key, value in cfg.items():
            cur.execute(
                "INSERT OR IGNORE INTO package_page_config (key, value) VALUES (?, ?)",
                (key, value),
            )
        cur.execute("SELECT key, value FROM package_page_config")
        for key, value in cur.fetchall():
            cfg[str(key)] = "" if value is None else str(value)
        conn.commit()
        conn.close()
    except Exception:
        pass
    return cfg


def _save_package_config_values(values: dict) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS package_page_config (key TEXT PRIMARY KEY, value TEXT)")
    for key, value in values.items():
        cur.execute(
            "INSERT INTO package_page_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(key), "" if value is None else str(value)),
        )
    conn.commit()
    conn.close()


def save_package_editor_config(payload: dict) -> dict:
    allowed = {
        "page_title", "page_subtitle", "server_text", "back_text",
        "p1_name", "p1_price", "p1_unit", "p1_feature1", "p1_feature2", "p1_feature3", "p1_feature4", "p1_feature5", "p1_btn", "p1_sub_btn", "p1_badge", "p1_cover",
        "p2_name", "p2_price", "p2_unit", "p2_feature1", "p2_feature2", "p2_feature3", "p2_feature4", "p2_feature5", "p2_btn", "p2_sub_btn", "p2_badge", "p2_cover",
        "p3_name", "p3_price", "p3_unit", "p3_feature1", "p3_feature2", "p3_feature3", "p3_feature4", "p3_feature5", "p3_btn", "p3_sub_btn", "p3_badge", "p3_cover",
        "p1_card_w", "p1_card_h", "p1_card_y", "p1_btn_scale", "p1_sub_btn_scale", "p1_btn_x", "p1_btn_y", "p1_sub_btn_x", "p1_sub_btn_y",
        "p2_card_w", "p2_card_h", "p2_card_y", "p2_btn_scale", "p2_sub_btn_scale", "p2_btn_x", "p2_btn_y", "p2_sub_btn_x", "p2_sub_btn_y",
        "p3_card_w", "p3_card_h", "p3_card_y", "p3_btn_scale", "p3_sub_btn_scale", "p3_btn_x", "p3_btn_y", "p3_sub_btn_x", "p3_sub_btn_y",
    }
    clean = {}
    for key, value in (payload or {}).items():
        if key in allowed:
            clean[key] = value
    if clean:
        _save_package_config_values(clean)
    return {"ok": True, "saved": sorted(clean)}


def _num(value: str, fallback: float, min_value: float, max_value: float) -> float:
    try:
        number = float(str(value).strip())
    except Exception:
        number = fallback
    return max(min_value, min(max_value, number))


def _card_style_vars(cfg: dict, prefix: str, edit: bool = False) -> str:
    width = _num(cfg.get(f"{prefix}_card_w", ""), 100, 82, 118)
    height = _num(cfg.get(f"{prefix}_card_h", ""), 320 if edit else 230, 210, 320)
    y = _num(cfg.get(f"{prefix}_card_y", ""), 0, -80, 80)
    main_scale = _num(cfg.get(f"{prefix}_btn_scale", ""), 1, .72, 1.22)
    sub_scale = _num(cfg.get(f"{prefix}_sub_btn_scale", ""), 1, .72, 1.22)
    main_x = _num(cfg.get(f"{prefix}_btn_x", ""), 0, -35, 35)
    main_y = _num(cfg.get(f"{prefix}_btn_y", ""), 0, -32, 32)
    sub_x = _num(cfg.get(f"{prefix}_sub_btn_x", ""), 0, -35, 35)
    sub_y = _num(cfg.get(f"{prefix}_sub_btn_y", ""), 0, -32, 32)
    return (
        f"--card-w:{width:g}%;--card-h:{height:g}px;--card-y:{y:g}px;--content-scale:1;"
        f"--main-btn-scale:{main_scale:g};--sub-btn-scale:{sub_scale:g};"
        f"--main-btn-x:{main_x:g}px;--main-btn-y:{main_y:g}px;"
        f"--sub-btn-x:{sub_x:g}px;--sub-btn-y:{sub_y:g}px;"
    )


def _edit_attr(edit: bool, key: str) -> str:
    return f' contenteditable="true" data-edit-key="{escape(key, quote=True)}" spellcheck="false"' if edit else ""


def _cover_style(cover: str, extra: str = "") -> str:
    cover = (cover or "").strip()
    if not cover and not extra:
        return ""

    safe_cover = escape(cover, quote=True)
    image_layer = f"url('{safe_cover}')" if cover else "none"

    return f""" style="
        background-image:
            radial-gradient(ellipse at center, rgba(0,0,0,0) 42%, rgba(0,0,0,.22) 100%),
            linear-gradient(180deg, rgba(0,0,0,.16) 0%, rgba(0,0,0,.02) 36%, rgba(0,0,0,.06) 64%, rgba(0,0,0,.38) 100%),
            linear-gradient(90deg, rgba(0,0,0,.22) 0%, rgba(0,0,0,.06) 42%, rgba(0,0,0,0) 100%),
            linear-gradient(135deg, rgba(232,191,106,.055) 0%, rgba(255,255,255,.018) 46%, rgba(185,135,50,.035) 100%),
            radial-gradient(circle at 78% 20%, rgba(255,210,120,.055), transparent 38%),
            {image_layer};
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        overflow: visible;
        position: relative;
        isolation: isolate;
        box-shadow: inset 0 0 46px rgba(0,0,0,.20), 0 15px 35px rgba(0,0,0,.40);
        {extra}
    " """


def _package_card(cfg: dict, prefix: str, icon: str, popular: bool = False, edit: bool = False) -> str:
    name = escape(cfg.get(f"{prefix}_name", ""))
    price = escape(cfg.get(f"{prefix}_price", ""))
    unit = escape(cfg.get(f"{prefix}_unit", ""))
    btn = escape(cfg.get(f"{prefix}_btn", "สมัครแพ็กเกจนี้"))
    sub_btn = escape(cfg.get(f"{prefix}_sub_btn", "ดูตัวอย่าง"))
    raw_cover = cfg.get(f"{prefix}_cover", "")
    cover = raw_cover or ("" if edit else f"/static/package_overlays/{prefix}.png")
    raw_amount = cfg.get(f"{prefix}_price", "")
    amount = escape(raw_amount)
    raw_badge = cfg.get(f"{prefix}_badge", "RECOMMENDED" if popular else "")
    badge = escape(raw_badge)
    popular_cls = " popular" if popular else ""
    edit_cls = " is-editable-card" if edit else ""
    data_attrs = f' data-prefix="{prefix}"' if edit else ""
    style_vars = _card_style_vars(cfg, prefix, edit)
    cover_placeholder = ""
    if edit and not raw_cover:
        cover_placeholder = (
            f'<button type="button" class="cover-placeholder" data-cover-picker="{prefix}">'
            '<span>+ image overlay</span></button>'
            f'<input class="cover-file" type="file" accept="image/*" data-cover-input="{prefix}">'
        )
    if edit or (popular and badge):
        badge_text = badge or "BADGE"
        badge_extra = " edit-placeholder" if edit and not raw_badge else ""
        badge_html = f'<div class="popular-badge{badge_extra}"{_edit_attr(edit, f"{prefix}_badge")}>{badge_text}</div>'
    else:
        badge_html = ""
    edit_meter = (
        '<div class="card-edit-meter" data-card-meter>W 100% / H 320px / Y 0px</div>'
        '<span class="card-resize-handle resize-right" data-resize-card="right" aria-hidden="true"></span>'
        '<span class="card-resize-handle resize-left" data-resize-card="left" aria-hidden="true"></span>'
        '<span class="card-resize-handle resize-bottom" data-resize-card="bottom" aria-hidden="true"></span>'
        '<span class="card-resize-handle resize-corner" data-resize-card="corner" aria-hidden="true"></span>'
    ) if edit else ""
    feature_items = []
    for index in range(1, 6):
        key = f"{prefix}_feature{index}"
        raw_feature = cfg.get(key, "")
        if raw_feature or edit:
            placeholder_cls = " feature-placeholder" if edit and not raw_feature else ""
            text = escape(raw_feature or "+ เพิ่มข้อความ")
            feature_items.append(
                f'<div class="feature-item{placeholder_cls}"><span class="feature-check">{_icon("check")}</span><span{_edit_attr(edit, key)}>{text}</span></div>'
            )
    features_html = "".join(feature_items)

    return f"""
    <div class="package-card plan-{prefix}{popular_cls}{edit_cls}"{data_attrs}{_cover_style(cover, style_vars)}>
      {edit_meter}
      {cover_placeholder}
      {badge_html}
      <div class="card-content">
        <div class="card-head">
          <div class="card-icon">{_icon(icon)}</div>
          <div>
            <div class="card-name"{_edit_attr(edit, f"{prefix}_name")}>{name}</div>
            <div class="card-unit"{_edit_attr(edit, f"{prefix}_unit")}>{unit}</div>
          </div>
          <div class="card-price">
            <div class="price-num"{_edit_attr(edit, f"{prefix}_price")}>{price}</div>
            <div class="price-unit">THB</div>
          </div>
        </div>

        <div class="features-list">
          {features_html}
        </div>

        <div class="btn-group">
          <a href="{MAIN_WEB_LINK}?{urlencode({'package': prefix, 'amount': raw_amount})}#topup-focus-anchor" class="btn-main" data-buy-package="{escape(prefix, quote=True)}" data-buy-amount="{amount}" data-buy-name="{name}"{_edit_attr(edit, f"{prefix}_btn")}>{btn}</a>
          <a href="{ADMIN_LINK}" class="btn-sub"{_edit_attr(edit, f"{prefix}_sub_btn")}>{sub_btn}</a>
        </div>
      </div>
    </div>
    """


def _icon(name: str) -> str:
    icons = {
        "check": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
        "crown": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4l3 12h14l3-12-6 7-4-7-4 7-6-7z"></path><path d="M3 20h18"></path></svg>',
        "flame": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2c0 0-7 3.5-7 10a7 7 0 0 0 14 0c0-6.5-7-10-7-10z"></path></svg>',
        "star": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>',
    }
    return icons.get(name, "")


def _packages_editor_script(edit: bool) -> str:
    if not edit:
        return ""
    return """
<script>
(() => {
  const dirty = {};
  const cards = [...document.querySelectorAll('.package-card[data-prefix]')];
  const select = document.getElementById('editCardSelect');
  const controls = [...document.querySelectorAll('[data-style-key]')];
  document.documentElement.dataset.packageEditor = 'active';
  const editorStatus = document.getElementById('editorStatus');
  if (editorStatus) editorStatus.textContent = `editor active / ${cards.length} cards / ${document.body.dataset.editorVersion || ''}`;
  const gradients = [
    'radial-gradient(ellipse at center, rgba(0,0,0,0) 42%, rgba(0,0,0,.22) 100%)',
    'linear-gradient(180deg, rgba(0,0,0,.16) 0%, rgba(0,0,0,.02) 36%, rgba(0,0,0,.06) 64%, rgba(0,0,0,.38) 100%)',
    'linear-gradient(90deg, rgba(0,0,0,.22) 0%, rgba(0,0,0,.06) 42%, rgba(0,0,0,0) 100%)',
    'linear-gradient(135deg, rgba(232,191,106,.055) 0%, rgba(255,255,255,.018) 46%, rgba(185,135,50,.035) 100%)',
    'radial-gradient(circle at 78% 20%, rgba(255,210,120,.055), transparent 38%)'
  ].join(',');

  const currentPrefix = () => select?.value || 'p1';
  const cardByPrefix = (prefix) => cards.find((card) => card.dataset.prefix === prefix);
  const selectCard = (prefix) => {
    cards.forEach((card) => card.classList.toggle('is-selected-card', card.dataset.prefix === prefix));
  };
  const varName = (key) => ({
    card_w: '--card-w',
    card_h: '--card-h',
    card_y: '--card-y',
    btn_scale: '--main-btn-scale',
    sub_btn_scale: '--sub-btn-scale',
    btn_x: '--main-btn-x',
    btn_y: '--main-btn-y',
    sub_btn_x: '--sub-btn-x',
    sub_btn_y: '--sub-btn-y'
  })[key];
  const unitFor = (key) => key === 'card_w' ? '%' : (key === 'card_h' || key === 'card_y' || key.endsWith('_x') || key.endsWith('_y') ? 'px' : '');
  const labelUnitFor = (key) => key === 'card_w' || key.includes('scale') ? '%' : 'px';
  const displayValueFor = (key, value) => key.includes('scale') ? `${Math.round(Number(value || 1) * 100)}%` : `${value}${labelUnitFor(key)}`;
  const cleanNumber = (value) => String(value || '').replace(/[^0-9.\-]/g, '');
  const numericStyleValue = (style, key, fallback) => {
    const raw = cleanNumber(style.getPropertyValue(varName(key)));
    const n = Number(raw);
    return Number.isFinite(n) && raw !== '' ? n : fallback;
  };
  const controlFor = (key) => document.querySelector(`[data-style-key="${key}"]`);
  const updateControlOutput = (input) => {
    const out = document.querySelector(`[data-style-output="${input.dataset.styleKey}"]`);
    if (out) out.textContent = displayValueFor(input.dataset.styleKey, input.value);
  };
  const updateCardMeter = (card) => {
    const meter = card?.querySelector('[data-card-meter]');
    if (!card || !meter) return;
    const style = getComputedStyle(card);
    const width = cleanNumber(style.getPropertyValue('--card-w')) || '100';
    const height = cleanNumber(style.getPropertyValue('--card-h')) || '230';
    const y = cleanNumber(style.getPropertyValue('--card-y')) || '0';
    const w = Number(width);
    const h = Number(height);
    let scale = 1;
    if (w < 94 || h < 228) scale = .94;
    if (w < 88 || h < 216) scale = .88;
    card.style.setProperty('--content-scale', String(scale));
    card.classList.toggle('is-compact-card', scale <= .94);
    card.classList.toggle('is-tight-card', scale <= .88);
    meter.textContent = `W ${Math.round(Number(width))}% / H ${Math.round(Number(height))}px / Y ${Math.round(Number(y))}px`;
  };
  const syncControlValue = (key, value, prefix = currentPrefix()) => {
    const input = controlFor(key);
    const card = cardByPrefix(prefix);
    if (!input || !card) return;
    input.value = String(value);
    card.style.setProperty(varName(key), input.value + unitFor(key));
    dirty[`${prefix}_${key}`] = input.value;
    updateControlOutput(input);
    updateCardMeter(card);
  };

  const syncControls = () => {
    const card = cardByPrefix(currentPrefix());
    if (!card) return;
    selectCard(currentPrefix());
    const style = getComputedStyle(card);
    controls.forEach((input) => {
      const key = input.dataset.styleKey;
      input.value = cleanNumber(style.getPropertyValue(varName(key))) || input.min || '0';
      updateControlOutput(input);
    });
    updateCardMeter(card);
  };

  document.querySelectorAll('[data-edit-key]').forEach((node) => {
    node.addEventListener('focus', () => {
      if (/^p[123]_feature[1-5]$/.test(node.dataset.editKey) && node.closest('.feature-item')?.classList.contains('feature-placeholder')) {
        node.innerText = '';
      }
    });
    node.addEventListener('blur', () => {
      if (/^p[123]_feature[1-5]$/.test(node.dataset.editKey) && !node.innerText.trim()) {
        node.innerText = '+ เพิ่มข้อความ';
        node.closest('.feature-item')?.classList.add('feature-placeholder');
        dirty[node.dataset.editKey] = '';
      }
    });
    node.addEventListener('input', () => {
      dirty[node.dataset.editKey] = node.innerText.trim();
      if (/^p[123]_feature[1-5]$/.test(node.dataset.editKey)) {
        node.closest('.feature-item')?.classList.toggle('feature-placeholder', !node.innerText.trim());
      }
    });
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        const match = node.dataset.editKey.match(/^(p[123]_feature)([1-5])$/);
        if (!match) {
          node.blur();
          return;
        }
        const next = document.querySelector(`[data-edit-key="${match[1]}${Number(match[2]) + 1}"]`);
        if (next) {
          next.focus();
          const range = document.createRange();
          range.selectNodeContents(next);
          range.collapse(false);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        } else {
          node.blur();
        }
      }
    });
  });

  document.querySelectorAll('.btn-main,.btn-sub').forEach((link) => {
    link.addEventListener('click', (event) => event.preventDefault());
  });

  controls.forEach((input) => {
    const applyControl = () => {
      const prefix = currentPrefix();
      const card = cardByPrefix(prefix);
      const key = input.dataset.styleKey;
      if (!card) return;
      card.style.setProperty(varName(key), input.value + unitFor(key));
      dirty[`${prefix}_${key}`] = input.value;
      updateControlOutput(input);
      updateCardMeter(card);
    };
    input.addEventListener('input', applyControl);
    input.addEventListener('change', applyControl);
    input.addEventListener('pointermove', (event) => {
      if (event.buttons) applyControl();
    });
  });
  select?.addEventListener('change', syncControls);
  syncControls();

  let activeResize = null;
  const updateResize = (event) => {
    if (!activeResize) return;
    const {card, startX, startY, startWidth, startHeight, listWidth} = activeResize;
    const wInput = controlFor('card_w');
    const hInput = controlFor('card_h');
    if (!wInput || !hInput) return;
    const mode = activeResize.mode;
    const deltaX = ((event.clientX - startX) / listWidth) * 100;
    const deltaY = event.clientY - startY;
    if (mode === 'left' || mode === 'right' || mode === 'corner') {
      const nextW = Math.max(Number(wInput.min), Math.min(Number(wInput.max), startWidth + (mode === 'left' ? -deltaX : deltaX)));
      syncControlValue('card_w', Math.round(nextW), card.dataset.prefix);
    }
    if (mode === 'bottom' || mode === 'corner') {
      const nextH = Math.max(Number(hInput.min), Math.min(Number(hInput.max), startHeight + deltaY));
      syncControlValue('card_h', Math.round(nextH), card.dataset.prefix);
    }
  };
  const stopResize = () => {
    if (!activeResize) return;
    activeResize.card.classList.remove('is-resizing-card');
    activeResize = null;
  };
  window.addEventListener('pointermove', updateResize);
  window.addEventListener('pointerup', stopResize);
  window.addEventListener('pointercancel', stopResize);

  cards.forEach((card) => {
    let drag = null;
    card.addEventListener('pointerdown', (event) => {
      if (event.target.closest('[contenteditable="true"], a, button, input, select, .popular-badge, [data-resize-card]')) return;
      select.value = card.dataset.prefix;
      selectCard(card.dataset.prefix);
      syncControls();
      const yInput = controlFor('card_y');
      drag = {
        pointerId: event.pointerId,
        startY: event.clientY,
        startValue: Number(yInput?.value || 0)
      };
      card.setPointerCapture(event.pointerId);
      card.classList.add('is-dragging-card');
      event.preventDefault();
    });
    card.addEventListener('pointermove', (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const yInput = controlFor('card_y');
      if (!yInput) return;
      const next = Math.max(Number(yInput.min), Math.min(Number(yInput.max), drag.startValue + event.clientY - drag.startY));
      yInput.value = Math.round(next);
      card.style.setProperty('--card-y', `${yInput.value}px`);
      dirty[`${card.dataset.prefix}_card_y`] = yInput.value;
      updateControlOutput(yInput);
      updateCardMeter(card);
    });
    const endDrag = (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      card.classList.remove('is-dragging-card');
      drag = null;
    };
    card.addEventListener('pointerup', endDrag);
    card.addEventListener('pointercancel', endDrag);
    card.addEventListener('lostpointercapture', () => {
      card.classList.remove('is-dragging-card');
      drag = null;
    });

    card.querySelectorAll('[data-resize-card]').forEach((resizeHandle) => resizeHandle.addEventListener('pointerdown', (event) => {
      select.value = card.dataset.prefix;
      selectCard(card.dataset.prefix);
      syncControls();
      const wInput = controlFor('card_w');
      const hInput = controlFor('card_h');
      const listWidth = card.parentElement?.clientWidth || card.clientWidth || 1;
      const style = getComputedStyle(card);
      activeResize = {
        card,
        mode: resizeHandle.dataset.resizeCard || 'corner',
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: (card.getBoundingClientRect().width / listWidth) * 100 || numericStyleValue(style, 'card_w', Number(wInput?.value || 100)),
        startHeight: card.getBoundingClientRect().height || numericStyleValue(style, 'card_h', Number(hInput?.value || 230)),
        listWidth
      };
      resizeHandle.setPointerCapture(event.pointerId);
      card.classList.add('is-resizing-card');
      event.preventDefault();
    }));
  });

  document.querySelectorAll('[data-cover-picker]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelector(`[data-cover-input="${button.dataset.coverPicker}"]`)?.click();
    });
  });
  document.querySelectorAll('[data-cover-input]').forEach((input) => {
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      const prefix = input.dataset.coverInput;
      const card = cardByPrefix(prefix);
      if (!file || !card) return;
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = String(reader.result || '');
        card.style.backgroundImage = `${gradients},url("${dataUrl}")`;
        card.querySelector('.cover-placeholder')?.remove();
        dirty[`${prefix}_cover`] = dataUrl;
      };
      reader.readAsDataURL(file);
    });
  });

  document.getElementById('editorSave')?.addEventListener('click', async () => {
    if (!confirm('Save this package page for customers?')) return;
    const response = await fetch('/packages/edit/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(dirty)
    });
    if (!response.ok) {
      alert('Save failed');
      return;
    }
    window.location.href = '/packages';
  });
})();
</script>
"""


def packages_page(edit: bool = False):
    cfg = _load_package_config()
    edit_body_class = f' class="package-edit-mode" data-editor-version="{EDITOR_VERSION}"' if edit else ""
    edit_toolbar = """
<div class="editor-topbar">
  <a class="editor-view-link" href="/packages">View customer</a>
  <button type="button" class="editor-save-btn" id="editorSave">Save</button>
</div>
""" if edit else ""
    editor_panel = """
<aside class="editor-panel" id="editorPanel">
  <details open>
    <summary class="editor-panel-title">Card control</summary>
    <div class="editor-status" id="editorStatus">editor loading...</div>
    <label>Card <select id="editCardSelect"><option value="p1">p1</option><option value="p2">p2</option><option value="p3">p3</option></select><output></output></label>
    <label>Width <input type="range" min="82" max="118" step="1" data-style-key="card_w"><output data-style-output="card_w"></output></label>
    <label>Height <input type="range" min="210" max="320" step="1" data-style-key="card_h"><output data-style-output="card_h"></output></label>
    <label>Move Y <input type="range" min="-80" max="80" step="1" data-style-key="card_y"><output data-style-output="card_y"></output></label>
    <label>Main scale <input type="range" min=".72" max="1.22" step=".01" data-style-key="btn_scale"><output data-style-output="btn_scale"></output></label>
    <label>Main X <input type="range" min="-35" max="35" step="1" data-style-key="btn_x"><output data-style-output="btn_x"></output></label>
    <label>Main Y <input type="range" min="-32" max="32" step="1" data-style-key="btn_y"><output data-style-output="btn_y"></output></label>
    <label>Sub scale <input type="range" min=".72" max="1.22" step=".01" data-style-key="sub_btn_scale"><output data-style-output="sub_btn_scale"></output></label>
    <label>Sub X <input type="range" min="-35" max="35" step="1" data-style-key="sub_btn_x"><output data-style-output="sub_btn_x"></output></label>
    <label>Sub Y <input type="range" min="-32" max="32" step="1" data-style-key="sub_btn_y"><output data-style-output="sub_btn_y"></output></label>
  </details>
</aside>
""" if edit else ""
    content = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>PAPXNZ BOT - PACKAGES</title>
<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
    --gold-b: #e8bf6a;
    --gold-c: #b98732;
    --accent-a: #fff0b7;
    --accent-b: #e8bf6a;
    --accent-c: #b98732;
    --accent-glow: rgba(232,191,106,.22);
    --accent-border: rgba(232,191,106,.28);
    --accent-shadow: rgba(232,191,106,.16);
    --text-1: rgba(255,255,255,.92);
    --text-2: rgba(255,255,255,.66);
    --text-3: rgba(255,255,255,.42);
}}
body {{
    margin: 0;
    padding: 0;
    background:
        radial-gradient(circle at 50% 0%, rgba(232,191,106,.10), transparent 34%),
        linear-gradient(180deg, #080c12 0%, #020305 100%);
    font-family: 'Kanit', sans-serif;
    color: var(--text-1);
    display: flex;
    justify-content: center;
    min-height: 100dvh;
    overflow-x: hidden;
}}
body.modal-open {{
    overflow:hidden;
}}
body:not(.package-edit-mode) {{
    overflow-x: hidden;
    overflow-y: auto;
}}
.app {{
    width: min(430px, 100%);
    padding: 24px 16px 40px 16px;
    box-sizing: border-box;
}}
body:not(.package-edit-mode) .app {{
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    padding-top: clamp(8px, 1.8dvh, 20px);
    padding-bottom: clamp(8px, 1.8dvh, 20px);
}}
.nav-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 28px;
    padding: 0 4px;
    gap: 10px;
}}
body:not(.package-edit-mode) .nav-header {{
    margin-bottom: clamp(8px, 1.6dvh, 18px);
    flex: 0 0 auto;
}}
.server-status {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .06em;
    color: var(--text-3);
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
}}
.server-dot {{
    color: #4ade80;
    animation: blink 2s infinite;
}}
.back-btn {{
    font-size: 13px;
    color: var(--text-2);
    text-decoration: none;
    background: rgba(255,255,255,0.05);
    padding: 6px 14px;
    border-radius: 20px;
    border: 1px solid rgba(255,255,255,0.05);
}}
.auth-actions {{
    display:flex;
    align-items:center;
    gap:8px;
    flex-shrink:0;
}}
.auth-divider {{
    width:1px;
    height:22px;
    background:linear-gradient(180deg, transparent, rgba(255,255,255,.24), transparent);
}}
.auth-btn {{
    height:34px;
    border:0;
    border-radius:999px;
    padding:0 12px;
    font-family:inherit;
    font-size:12px;
    font-weight:800;
    cursor:pointer;
    white-space:nowrap;
}}
.signup-btn {{
    color:rgba(45,45,48,.92);
    background:linear-gradient(180deg, rgba(255,255,255,.92), rgba(255,255,255,.70));
    border:1px solid rgba(255,255,255,.70);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.82), 0 8px 18px rgba(0,0,0,.16);
    backdrop-filter:blur(12px);
}}
.login-open-btn {{
    color:#190805;
    background:linear-gradient(135deg,#ffd5b0 0%,#ff7b3d 40%,#b82418 100%);
    box-shadow:0 10px 22px rgba(255,88,36,.20), inset 0 1px 0 rgba(255,255,255,.42);
}}
.nav-back-auth {{
    display:none;
}}
body.is-logged-in .auth-actions {{
    display:none;
}}
body.is-logged-in .nav-back-auth {{
    display:inline-flex;
}}
.modal-backdrop {{
    position:fixed;
    inset:0;
    z-index:50;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:12px;
    overflow-y:auto;
    background:rgba(1,2,5,.62);
    backdrop-filter:blur(10px);
    -webkit-backdrop-filter:blur(10px);
    opacity:0;
    pointer-events:none;
    transition:opacity .24s ease;
}}
.modal-backdrop.active {{
    opacity:1;
    pointer-events:auto;
}}
.login-modal {{
    box-sizing:border-box;
    width:min(350px, calc(100vw - 34px));
    max-height:calc(100dvh - 24px);
    position:relative;
    overflow-y:auto;
    overflow-x:hidden;
    border-radius:26px;
    padding:20px 16px 16px;
    background:
        linear-gradient(155deg, rgba(255,255,255,.13), rgba(255,255,255,.035) 30%, rgba(0,0,0,.18) 100%),
        radial-gradient(circle at 50% 0%, rgba(255,116,56,.22), transparent 35%),
        rgba(8,9,12,.76);
    border:1px solid rgba(255,202,168,.26);
    box-shadow:0 30px 80px rgba(0,0,0,.72), inset 0 1px 0 rgba(255,255,255,.16);
    transform:translateY(18px) scale(.96);
    transition:transform .28s ease;
}}
@supports (height: 100svh) {{
    .login-modal {{ max-height:calc(100svh - 24px); }}
}}
.login-modal *,
.login-modal *::before,
.login-modal *::after {{
    box-sizing:border-box;
}}
.login-modal::-webkit-scrollbar {{
    width:0;
}}
.modal-backdrop.active .login-modal {{
    transform:translateY(0) scale(1);
}}
.login-modal::before {{
    content:"";
    position:absolute;
    inset:10px;
    border-radius:22px;
    border:1px solid rgba(255,220,196,.12);
    pointer-events:none;
}}
.modal-close {{
    position:absolute;
    top:14px;
    right:14px;
    width:32px;
    height:32px;
    border-radius:999px;
    border:1px solid rgba(255,255,255,.12);
    background:rgba(255,255,255,.06);
    color:#fff;
    font-size:18px;
    cursor:pointer;
    z-index:2;
}}
.login-brand {{
    position:relative;
    z-index:1;
    text-align:center;
    margin:8px 0 16px;
}}
.login-brand .logo {{
    font-size:32px;
    font-weight:900;
    letter-spacing:.08em;
    background:linear-gradient(135deg,#fff 0%,#ffd2b2 42%,#ff6231 100%);
    -webkit-background-clip:text;
    -webkit-text-fill-color:transparent;
}}
.login-brand .title {{
    margin-top:6px;
    font-size:20px;
    font-weight:700;
    color:rgba(255,255,255,.90);
}}
.login-field {{
    position:relative;
    z-index:1;
    margin-top:11px;
}}
.login-field label {{
    display:block;
    margin:0 0 7px 4px;
    font-size:12px;
    color:rgba(255,230,216,.70);
}}
.login-field input {{
    width:100%;
    height:46px;
    border-radius:15px;
    border:1px solid rgba(255,225,206,.38);
    background:rgba(2,3,5,.30);
    color:#fff;
    padding:0 14px;
    font:inherit;
    outline:none;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.06);
}}
.login-field input:focus {{
    border-color:rgba(255,116,56,.78);
    box-shadow:0 0 0 3px rgba(255,116,56,.14);
}}
.login-submit {{
    position:relative;
    z-index:1;
    width:100%;
    height:48px;
    margin-top:16px;
    border:0;
    border-radius:15px;
    color:#1a0704;
    font:inherit;
    font-size:16px;
    font-weight:900;
    cursor:pointer;
    background:linear-gradient(135deg,#ffd4ad 0%,#ff7b3d 42%,#a91f18 100%);
    box-shadow:0 14px 30px rgba(255,82,34,.24), inset 0 1px 0 rgba(255,255,255,.52);
}}
.login-sep {{
    position:relative;
    z-index:1;
    display:flex;
    align-items:center;
    gap:10px;
    margin:16px 0 11px;
    color:rgba(255,255,255,.44);
    font-size:11px;
}}
.login-sep::before,
.login-sep::after {{
    content:"";
    flex:1;
    height:1px;
    background:linear-gradient(90deg, transparent, rgba(255,255,255,.18), transparent);
}}
.social-row {{
    position:relative;
    z-index:1;
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:10px;
}}
.social-btn {{
    height:42px;
    border-radius:14px;
    border:1px solid rgba(255,255,255,.74);
    background:linear-gradient(180deg, rgba(255,255,255,.92), rgba(255,255,255,.72));
    color:rgba(42,42,46,.94);
    font:inherit;
    font-size:13px;
    font-weight:800;
    cursor:pointer;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:8px;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.76), 0 8px 20px rgba(0,0,0,.18);
}}
.social-icon {{
    width:19px;
    height:19px;
    border-radius:999px;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    background:rgba(255,255,255,.92);
    color:#111;
    overflow:hidden;
}}
.telegram-icon svg {{
    width:16px;
    height:16px;
}}
.social-icon svg {{
    width:15px;
    height:15px;
    display:block;
}}
.modal-foot {{
    position:relative;
    z-index:1;
    margin-top:16px;
    text-align:center;
    font-size:12px;
    color:rgba(255,255,255,.54);
}}
.modal-foot button {{
    border:0;
    background:transparent;
    color:#ff9b67;
    font:inherit;
    font-weight:900;
    cursor:pointer;
}}
@media (max-width:380px) {{
    .auth-btn {{ padding:0 10px; font-size:11px; }}
    .modal-backdrop {{ padding:10px 14px; }}
    .login-modal {{ width:min(330px, calc(100vw - 42px)); padding:18px 14px 15px; border-radius:24px; }}
    .login-brand .logo {{ font-size:29px; }}
    .login-brand .title {{ font-size:18px; }}
    .login-field input {{ height:43px; }}
    .login-submit {{ height:45px; }}
    .social-row {{ gap:8px; }}
    .social-btn {{ height:40px; font-size:12px; }}
}}
@media (max-width:380px) and (max-height:760px) {{
    .login-brand {{ margin:4px 0 12px; }}
    .login-brand .logo {{ font-size:27px; }}
    .login-brand .title {{ margin-top:4px; font-size:17px; }}
    .login-field {{ margin-top:9px; }}
    .login-field label {{ margin-bottom:5px; }}
    .login-submit {{ margin-top:13px; }}
    .login-sep {{ margin:12px 0 9px; }}
    .modal-foot {{ margin-top:12px; }}
}}
@media (max-height:700px) {{
    .modal-backdrop {{ align-items:flex-start; }}
}}
.page-title {{
    text-align: center;
    margin-bottom: 32px;
}}
body:not(.package-edit-mode) .page-title {{
    margin-bottom: clamp(8px, 1.7dvh, 18px);
    flex: 0 0 auto;
}}
.page-title h1 {{
    font-size: 26px;
    font-weight: 800;
    margin: 0 0 6px 0;
    background: linear-gradient(135deg, #fff 30%, var(--gold-b));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}}
body:not(.package-edit-mode) .page-title h1 {{
    font-size: clamp(18px, 4dvh, 25px);
}}
.page-title p {{
    font-size: 13px;
    color: var(--text-3);
    margin: 0;
}}
body:not(.package-edit-mode) .page-title p {{
    font-size: clamp(10.5px, 2.2dvh, 13px);
}}
.packages-list {{
    display: flex;
    flex-direction: column;
    gap: 24px;
}}
body:not(.package-edit-mode) .packages-list {{
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    grid-template-rows: repeat(3, minmax(0, 1fr));
    gap: clamp(7px, 1.25dvh, 14px);
}}
.package-card {{
    --accent-a: #fff0b7;
    --accent-b: #e8bf6a;
    --accent-c: #b98732;
    --accent-glow: rgba(232,191,106,.22);
    --accent-border: rgba(232,191,106,.28);
    --accent-shadow: rgba(232,191,106,.16);
    background-color: rgba(18, 18, 18, 0.4);
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 24px;
    padding: 24px;
    position: relative;
    overflow: visible;
    isolation: isolate;
    min-height: 230px;
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4);
}}
.package-card {{
    width: var(--card-w, 100%);
    min-height: var(--card-h, 230px);
    margin-left: auto;
    margin-right: auto;
    transform: translateY(var(--card-y, 0px));
}}
body:not(.package-edit-mode) .package-card {{
    min-height: 0;
    height: 100%;
    padding: clamp(10px, 1.8dvh, 18px);
    display: flex;
    flex-direction: column;
    transform: none;
    overflow: hidden;
}}
.package-card .btn-main {{
    transform: translate(var(--main-btn-x, 0px), var(--main-btn-y, 0px)) scale(var(--main-btn-scale, 1));
    transform-origin: center;
}}
.package-card .btn-sub {{
    transform: translate(var(--sub-btn-x, 0px), var(--sub-btn-y, 0px)) scale(var(--sub-btn-scale, 1));
    transform-origin: center;
}}
.package-card.plan-p1 {{
    --accent-a: #fff6d8;
    --accent-b: #ddb65a;
    --accent-c: #8f6420;
    --accent-glow: rgba(221,182,90,.24);
    --accent-border: rgba(244,211,132,.30);
    --accent-shadow: rgba(221,182,90,.16);
    border-color: rgba(244,211,132,.22);
}}
.package-card.plan-p2 {{
    --accent-a: #ffffff;
    --accent-b: #d7e2ee;
    --accent-c: #7f9fbd;
    --accent-glow: rgba(215,226,238,.26);
    --accent-border: rgba(231,239,248,.34);
    --accent-shadow: rgba(168,194,219,.18);
    border-color: rgba(231,239,248,.28);
}}
.package-card.plan-p3 {{
    --accent-a: #fff3ff;
    --accent-b: #d8b4ff;
    --accent-c: #7750c7;
    --accent-glow: rgba(216,180,255,.24);
    --accent-border: rgba(232,207,255,.34);
    --accent-shadow: rgba(155,112,220,.18);
    border-color: rgba(232,207,255,.25);
}}
.package-card.plan-p3::before {{
    background:
        linear-gradient(180deg, rgba(255,255,255,.045), transparent 22%, rgba(0,0,0,.25) 100%),
        radial-gradient(circle at 84% 16%, rgba(232,207,255,.22), transparent 32%),
        radial-gradient(circle at 18% 80%, rgba(119,80,199,.16), transparent 38%);
}}
.package-card.plan-p3 .price-num,
.package-card.plan-p3 .card-icon,
.package-card.plan-p3 .feature-check {{
    color: #d8b4ff;
    filter: drop-shadow(0 0 10px rgba(216,180,255,.26));
}}
.package-card.plan-p3 .btn-main {{
    background:
        linear-gradient(135deg, #fff3ff 0%, #d8b4ff 34%, #9f7aea 67%, #5f3da8 100%);
}}
.package-card::before {{
    content:"";
    position:absolute;
    inset:0;
    border-radius: inherit;
    background:
        linear-gradient(180deg, rgba(255,255,255,.05), transparent 22%, rgba(0,0,0,.25) 100%),
        radial-gradient(circle at 90% 8%, var(--accent-glow), transparent 34%);
    pointer-events:none;
    z-index:0;
}}
.package-card::after {{
    content:"";
    position:absolute;
    inset:0;
    border-radius: inherit;
    background:
        radial-gradient(ellipse at center, rgba(255,255,255,.02) 0%, transparent 48%, rgba(0,0,0,.16) 100%),
        linear-gradient(180deg, rgba(255,255,255,.022), transparent 32%, rgba(0,0,0,.045) 100%),
        rgba(232,191,106,.012);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    pointer-events:none;
    z-index:0;
}}
.package-card.popular {{
    border-color: var(--accent-border);
    box-shadow: 0 18px 42px var(--accent-shadow);
}}
.package-card.popular .card-head {{
    padding-top: 4px;
}}
.card-content {{
    position:relative;
    z-index:1;
}}
body:not(.package-edit-mode) .card-content {{
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
}}
.popular-badge {{
    position: absolute;
    top: -13px;
    right: 24px;
    background: linear-gradient(135deg, var(--accent-a), var(--accent-b) 45%, var(--accent-c));
    color: #08090d;
    font-size: 10.5px;
    font-weight: 900;
    padding: 5px 12px;
    border-radius: 999px;
    letter-spacing: 0.04em;
    z-index:5;
    box-shadow: 0 8px 18px var(--accent-shadow);
}}
.card-head {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}}
body:not(.package-edit-mode) .card-head {{
    gap: clamp(8px, 1.8dvh, 12px);
    margin-bottom: clamp(7px, 1.4dvh, 12px);
}}
.card-icon {{
    width: 32px;
    height: 32px;
    color: var(--accent-b);
    display: flex;
    align-items: center;
    justify-content: center;
    filter:drop-shadow(0 0 10px var(--accent-glow));
    flex-shrink: 0;
}}
body:not(.package-edit-mode) .card-icon {{
    width: clamp(23px, 4.2dvh, 32px);
    height: clamp(23px, 4.2dvh, 32px);
}}
.card-icon svg {{
    width: 100%;
    height: 100%;
}}
.card-name {{
    font-size: 19px;
    font-weight: 800;
    color: #fff;
    text-shadow:0 2px 12px rgba(0,0,0,.65);
}}
body:not(.package-edit-mode) .card-name {{
    font-size: clamp(14px, 3.1dvh, 19px);
    line-height: 1.12;
}}
.card-unit {{
    font-size: 11px;
    color: var(--text-3);
}}
body:not(.package-edit-mode) .card-unit,
body:not(.package-edit-mode) .price-unit {{
    font-size: clamp(9px, 1.8dvh, 11px);
}}
.card-price {{
    margin-left: auto;
    text-align: right;
}}
.price-num {{
    font-size: 22px;
    font-weight: 800;
    color: var(--accent-b);
    text-shadow:0 2px 10px rgba(0,0,0,.55);
}}
body:not(.package-edit-mode) .price-num {{
    font-size: clamp(17px, 3.4dvh, 22px);
}}
.price-unit {{
    font-size: 11px;
    color: var(--text-3);
}}
.features-list {{
    display: flex;
    flex-direction: column;
    gap: clamp(6px, 2.4vw, 11px);
    margin-bottom: 24px;
    padding-top: 14px;
    border-top: 1px solid rgba(255, 255, 255, 0.07);
}}
body:not(.package-edit-mode) .features-list {{
    flex: 1 1 auto;
    min-height: 0;
    gap: clamp(3px, .8dvh, 7px);
    margin-bottom: clamp(5px, 1dvh, 10px);
    padding-top: clamp(5px, 1dvh, 10px);
}}
.feature-item {{
    display: flex;
    align-items: flex-start;
    gap: 10px;
    font-size: clamp(11.5px, 3.15vw, 13.5px);
    color: rgba(255,255,255,.72);
    line-height: 1.32;
    text-shadow:0 2px 8px rgba(0,0,0,.65);
    min-width: 0;
}}
body:not(.package-edit-mode) .feature-item {{
    gap: clamp(7px, 1.4dvh, 10px);
    font-size: clamp(9.5px, 1.9dvh, 12.5px);
    line-height: 1.16;
}}
.feature-item span:last-child {{
    min-width: 0;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    max-height: calc(1.32em * 2);
}}
body:not(.package-edit-mode) .feature-item span:last-child {{
    max-height: calc(1.16em * 2);
}}
.feature-placeholder {{
    color: rgba(255,255,255,.38);
}}
.feature-check {{
    width: 15px;
    height: 15px;
    color: var(--accent-b);
    flex-shrink: 0;
}}
body:not(.package-edit-mode) .feature-check {{
    width: clamp(12px, 2.2dvh, 15px);
    height: clamp(12px, 2.2dvh, 15px);
}}
.feature-check svg {{
    width: 100%;
    height: 100%;
}}
.btn-group {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 20px;
}}
body:not(.package-edit-mode) .btn-group {{
    margin-top: auto;
    gap: clamp(8px, 1.5dvh, 12px);
}}
.btn-main {{
    flex: 1;
    height: 44px;
    background: linear-gradient(135deg, var(--accent-a), var(--accent-b) 44%, var(--accent-c));
    color: #05070a;
    font-size: 13.5px;
    font-weight: 800;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    box-shadow: 0 8px 22px var(--accent-shadow);
}}
body:not(.package-edit-mode) .btn-main,
body:not(.package-edit-mode) .btn-sub {{
    height: clamp(31px, 4.8dvh, 42px);
    font-size: clamp(10px, 1.9dvh, 12.5px);
}}
.btn-sub {{
    height: 44px;
    padding: 0 16px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.10);
    color: rgba(255, 255, 255, 0.72);
    font-size: 12.5px;
    font-weight: 600;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    backdrop-filter: blur(8px);
}}
body:not(.package-edit-mode) .btn-sub {{
    padding: 0 clamp(10px, 2.1dvh, 16px);
}}
@media (min-width: 900px) {{
    .app {{
        width: min(1120px, calc(100vw - 72px));
        padding-top: 34px;
        padding-bottom: 34px;
    }}
    .nav-header {{
        max-width: 980px;
        margin-left: auto;
        margin-right: auto;
        margin-bottom: 20px;
    }}
    .page-title {{
        margin-bottom: 34px;
    }}
    .packages-list {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        align-items: stretch;
        gap: 22px;
    }}
    .package-card {{
        min-height: var(--card-h, 320px);
        height: auto;
        padding: 22px;
    }}
    .card-content {{
        min-height: 100%;
        display: flex;
        flex-direction: column;
    }}
    .card-head {{
        align-items: flex-start;
        gap: 10px;
        margin-bottom: 14px;
    }}
    .card-icon {{
        width: 30px;
        height: 30px;
    }}
    .card-name {{
        font-size: clamp(17px, 1.55vw, 19px);
        line-height: 1.15;
    }}
    .price-num {{
        font-size: clamp(20px, 1.65vw, 23px);
    }}
    .features-list {{
        flex: 1 1 auto;
        gap: 8px;
        margin-bottom: 14px;
    }}
    .feature-item {{
        font-size: clamp(11.5px, 1.05vw, 13px);
        line-height: 1.28;
    }}
    .btn-group {{
        margin-top: auto;
        gap: 10px;
    }}
    .btn-main,
    .btn-sub {{
        height: 42px;
        font-size: 12.5px;
    }}
    .btn-sub {{
        padding: 0 13px;
    }}
    .popular-badge {{
        right: 20px;
    }}
    body:not(.package-edit-mode) .packages-list {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        grid-template-rows: minmax(0, 1fr);
    }}
}}
@media (min-width: 900px) and (max-height: 760px) {{
    .app {{
        padding-top: 18px;
        padding-bottom: 22px;
    }}
    .nav-header {{
        margin-bottom: 12px;
    }}
    .page-title {{
        margin-bottom: 22px;
    }}
    .page-title h1 {{
        font-size: 24px;
    }}
    .package-card {{
        min-height: var(--card-h, 286px);
        padding: 19px;
    }}
    .features-list {{
        gap: 6px;
        padding-top: 10px;
    }}
    .feature-item {{
        font-size: 11.2px;
        line-height: 1.2;
    }}
    .btn-main,
    .btn-sub {{
        height: 39px;
    }}
}}
body:not(.package-edit-mode) .packages-list {{
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    gap: clamp(7px, 1.15dvh, 13px);
    min-height: 0;
}}
body:not(.package-edit-mode) .package-card {{
    width: min(var(--card-w, 100%), 100%);
    min-height: 0 !important;
    height: clamp(150px, calc((100dvh - 150px) / 3), 226px) !important;
    flex: 0 0 clamp(150px, calc((100dvh - 150px) / 3), 226px);
    transform: none !important;
    overflow: hidden;
}}
body:not(.package-edit-mode) .package-card .btn-main {{
    transform: scale(var(--main-btn-scale, 1));
}}
body:not(.package-edit-mode) .package-card .btn-sub {{
    transform: scale(var(--sub-btn-scale, 1));
}}
@media (max-height: 720px) {{
    body:not(.package-edit-mode) .app {{
        padding-top: 7px;
        padding-bottom: 7px;
    }}
    body:not(.package-edit-mode) .nav-header {{
        margin-bottom: 7px;
    }}
    body:not(.package-edit-mode) .page-title {{
        margin-bottom: 7px;
    }}
    body:not(.package-edit-mode) .package-card {{
        height: clamp(138px, calc((100dvh - 130px) / 3), 202px) !important;
        flex-basis: clamp(138px, calc((100dvh - 130px) / 3), 202px);
    }}
}}
@media (min-width: 900px) {{
    body:not(.package-edit-mode) .packages-list {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        grid-template-rows: auto;
        align-items: stretch;
        gap: 22px;
    }}
    body:not(.package-edit-mode) .package-card {{
        height: clamp(250px, calc(100dvh - 190px), 320px) !important;
        flex: initial;
    }}
}}
body.package-edit-mode {{
    padding-top: 58px;
}}
body.package-edit-mode .app {{
    width: min(560px, 100%);
    padding-bottom: 180px;
}}
@media (min-width: 900px) {{
    body.package-edit-mode .app {{
        width: min(1120px, calc(100vw - 72px));
    }}
}}
body.package-edit-mode .package-card {{
    width: var(--card-w, 100%);
    max-width: none;
    height: var(--card-h, 230px);
    min-height: 0;
    margin-left: auto;
    margin-right: auto;
    transform: translateY(var(--card-y, 0px));
    outline: 1px dashed rgba(255,255,255,.20);
    outline-offset: 5px;
    overflow: visible;
    cursor: ns-resize;
    touch-action: none;
    user-select: none;
}}
body.package-edit-mode .package-card.is-dragging-card {{
    outline-color: rgba(232,191,106,.62);
    box-shadow: 0 20px 48px rgba(0,0,0,.48), 0 0 0 1px rgba(232,191,106,.24);
}}
.card-edit-meter {{
    position: absolute;
    top: -32px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 8;
    padding: 4px 9px;
    border-radius: 999px;
    background: rgba(0,0,0,.62);
    border: 1px solid rgba(255,255,255,.14);
    color: rgba(255,238,194,.82);
    font-size: 10.5px;
    font-weight: 800;
    line-height: 1;
    white-space: nowrap;
    pointer-events: none;
    backdrop-filter: blur(10px);
    opacity: 0;
    transition: opacity .18s ease, transform .18s ease;
}}
body.package-edit-mode .package-card.is-selected-card .card-edit-meter,
body.package-edit-mode .package-card.is-dragging-card .card-edit-meter,
body.package-edit-mode .package-card.is-resizing-card .card-edit-meter {{
    opacity: 1;
    transform: translateX(-50%) translateY(-2px);
}}
.card-resize-handle {{
    position: absolute;
    z-index: 9;
    border-radius: 999px;
    border: 1px solid rgba(232,191,106,.72);
    background:
        radial-gradient(circle at 35% 35%, rgba(255,255,255,.82), rgba(232,191,106,.72) 36%, rgba(92,59,18,.92) 100%);
    box-shadow: 0 8px 18px rgba(0,0,0,.42), 0 0 18px rgba(232,191,106,.20);
    touch-action: none;
}}
.resize-corner {{
    right: -8px;
    bottom: -8px;
    width: 22px;
    height: 22px;
    cursor: nwse-resize;
}}
.resize-right,
.resize-left {{
    top: 50%;
    width: 16px;
    height: 42px;
    transform: translateY(-50%);
    cursor: ew-resize;
}}
.resize-right {{ right: -8px; }}
.resize-left {{ left: -8px; }}
.resize-bottom {{
    left: 50%;
    bottom: -8px;
    width: 54px;
    height: 16px;
    transform: translateX(-50%);
    cursor: ns-resize;
}}
body.package-edit-mode .package-card.is-resizing-card {{
    outline-color: rgba(255,238,194,.82);
}}
body.package-edit-mode .package-card::before {{
    z-index: 0;
}}
body.package-edit-mode .package-card::after {{
    z-index: 0;
}}
body.package-edit-mode .card-content {{
    z-index: 2;
    max-width: 100%;
    height: auto;
    display: block;
    transform: scale(var(--content-scale, 1));
    transform-origin: top left;
    width: calc(100% / var(--content-scale, 1));
}}
body.package-edit-mode .card-head {{
    margin-bottom: 14px;
}}
body.package-edit-mode .features-list {{
    min-height: 0;
    margin-bottom: 16px;
    overflow: hidden;
    gap: clamp(5px, 1.8vw, 9px);
}}
body.package-edit-mode .feature-item {{
    font-size: clamp(10.5px, 2.75vw, 13px);
    line-height: 1.27;
}}
body.package-edit-mode .feature-item span:last-child {{
    max-height: calc(1.27em * 2);
}}
body.package-edit-mode .btn-group {{
    margin-top: 16px;
}}
body.package-edit-mode .package-card.is-compact-card {{
    padding: 20px;
}}
body.package-edit-mode .package-card.is-compact-card .card-head {{
    margin-bottom: 10px;
}}
body.package-edit-mode .package-card.is-compact-card .features-list {{
    padding-top: 10px;
    margin-bottom: 10px;
    gap: 5px;
}}
body.package-edit-mode .package-card.is-compact-card .feature-item {{
    font-size: 11px;
    line-height: 1.18;
}}
body.package-edit-mode .package-card.is-compact-card .feature-item span:last-child {{
    max-height: calc(1.18em * 2);
}}
body.package-edit-mode .package-card.is-compact-card .btn-group {{
    margin-top: 10px;
}}
body.package-edit-mode .package-card.is-tight-card {{
    padding: 17px;
}}
body.package-edit-mode .package-card.is-tight-card .card-name {{
    font-size: 17px;
}}
body.package-edit-mode .package-card.is-tight-card .price-num {{
    font-size: 20px;
}}
body.package-edit-mode .package-card.is-tight-card .feature-item {{
    font-size: 10px;
    line-height: 1.14;
}}
body.package-edit-mode .package-card.is-tight-card .feature-item span:last-child {{
    max-height: calc(1.14em * 2);
}}
body.package-edit-mode [contenteditable="true"] {{
    cursor: text;
    border-radius: 6px;
    transition: background .18s ease, box-shadow .18s ease;
    overflow-wrap: anywhere;
}}
body.package-edit-mode [contenteditable="true"]:hover,
body.package-edit-mode [contenteditable="true"]:focus {{
    outline: 0;
    background: rgba(255,255,255,.08);
    box-shadow: 0 0 0 1px rgba(255,255,255,.18);
}}
body.package-edit-mode .popular-badge.edit-placeholder,
body.package-edit-mode .cover-placeholder {{
    border: 1px dashed rgba(255,255,255,.32);
    background: rgba(255,255,255,.045);
    color: rgba(255,255,255,.48);
    box-shadow: none;
}}
body.package-edit-mode .cover-placeholder {{
    position: absolute;
    inset: 10px;
    z-index: 1;
    border-radius: 18px;
    font: inherit;
    display: grid;
    place-items: center;
    cursor: pointer;
    pointer-events: auto;
}}
body.package-edit-mode .cover-placeholder span {{
    padding: 6px 12px;
    border-radius: 999px;
    background: rgba(0,0,0,.36);
    color: rgba(255,255,255,.62);
    font-size: 12px;
    font-weight: 700;
}}
.cover-file {{
    display: none;
}}
body.package-edit-mode .btn-group {{
    overflow: visible;
}}
body.package-edit-mode .btn-main,
body.package-edit-mode .btn-sub {{
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transform-origin: center;
}}
body.package-edit-mode .btn-main {{
    transform: translate(var(--main-btn-x, 0px), var(--main-btn-y, 0px)) scale(var(--main-btn-scale, 1));
}}
body.package-edit-mode .btn-sub {{
    transform: translate(var(--sub-btn-x, 0px), var(--sub-btn-y, 0px)) scale(var(--sub-btn-scale, 1));
}}
.editor-topbar {{
    position: fixed;
    top: 10px;
    right: 10px;
    z-index: 80;
    display: flex;
    gap: 8px;
    align-items: center;
}}
.editor-save-btn,
.editor-view-link {{
    height: 36px;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,.16);
    padding: 0 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font: inherit;
    font-size: 13px;
    font-weight: 800;
    text-decoration: none;
    cursor: pointer;
}}
.editor-save-btn {{
    color: #130b03;
    background: linear-gradient(135deg, #fff0b7, #e8bf6a 45%, #b98732);
}}
.editor-view-link {{
    color: rgba(255,255,255,.78);
    background: rgba(0,0,0,.46);
    backdrop-filter: blur(12px);
}}
.editor-panel {{
    position: fixed;
    left: 10px;
    bottom: 10px;
    z-index: 80;
    width: min(360px, calc(100vw - 20px));
    padding: 12px;
    border-radius: 18px;
    background: rgba(5,6,9,.76);
    border: 1px solid rgba(255,255,255,.12);
    backdrop-filter: blur(16px);
    box-shadow: 0 18px 40px rgba(0,0,0,.42);
}}
.editor-panel-title {{
    list-style: none;
    font-size: 12px;
    font-weight: 900;
    color: rgba(255,255,255,.78);
    margin-bottom: 8px;
    cursor: pointer;
}}
.editor-panel-title::-webkit-details-marker {{
    display: none;
}}
.editor-panel-title::after {{
    content: "พับ";
    float: right;
    color: rgba(255,236,188,.72);
    font-size: 10px;
}}
.editor-panel details:not([open]) .editor-panel-title {{
    margin-bottom: 0;
}}
.editor-panel details:not([open]) .editor-panel-title::after {{
    content: "เปิด";
}}
.editor-status {{
    margin: -2px 0 8px;
    color: rgba(134,239,172,.82);
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: .02em;
}}
.editor-panel label {{
    display: grid;
    grid-template-columns: 76px 1fr 44px;
    align-items: center;
    gap: 8px;
    color: rgba(255,255,255,.58);
    font-size: 11px;
    margin-top: 7px;
}}
.editor-panel input,
.editor-panel select {{
    width: 100%;
}}
.editor-panel output {{
    color: rgba(255,236,188,.82);
    font-size: 10.5px;
    font-weight: 800;
    text-align: right;
}}
@keyframes blink {{
    0%, 100% {{ opacity: 0.4; }}
    50% {{ opacity: 1; }}
}}
</style>
</head>
<body{edit_body_class}>
{edit_toolbar}
{editor_panel}
<main class="app">
  <header class="nav-header">
    <div class="server-status"><span class="server-dot">●</span><span>{escape(cfg.get('server_text','SERVER ONLINE 24HR'))}</span></div>
    <div class="auth-actions" id="authActions">
      <button type="button" class="auth-btn signup-btn" id="signupBtn">สมัครบัญชี</button>
      <span class="auth-divider" aria-hidden="true"></span>
      <button type="button" class="auth-btn login-open-btn" id="openLogin">เข้าสู่ระบบ</button>
    </div>
    <a href="{MAIN_WEB_LINK}" class="back-btn nav-back-auth" id="navBackAuth">{escape(cfg.get('back_text','กลับหน้าหลัก'))}</a>
  </header>

  <section class="page-title">
    <h1{_edit_attr(edit, 'page_title')}>{escape(cfg.get('page_title','เลือกแพ็กเกจ VIP'))}</h1>
    <p{_edit_attr(edit, 'page_subtitle')}>{escape(cfg.get('page_subtitle',''))}</p>
  </section>

  <section class="packages-list">
    {_package_card(cfg, 'p1', cfg.get('p1_icon','star'), False, edit)}
    {_package_card(cfg, 'p2', cfg.get('p2_icon','crown'), True, edit)}
    {_package_card(cfg, 'p3', cfg.get('p3_icon','flame'), False, edit)}
  </section>
</main>
<div class="modal-backdrop" id="loginModal" aria-hidden="true">
  <section class="login-modal" role="dialog" aria-modal="true" aria-labelledby="loginTitle">
    <button type="button" class="modal-close" id="closeLogin" aria-label="ปิด">×</button>
    <div class="login-brand">
      <div class="logo">PAPXNZ</div>
      <div class="title" id="loginTitle">Create Account</div>
    </div>
    <form id="mockLoginForm">
      <div class="login-field">
        <label for="loginUser">Email / Username</label>
        <input id="loginUser" name="login_user" type="text" placeholder="example@gmail.com" autocomplete="username">
      </div>
      <div class="login-field">
        <label for="loginPass">Password</label>
        <input id="loginPass" name="login_pass" type="password" placeholder="••••••••••••" autocomplete="current-password">
      </div>
      <button type="submit" class="login-submit">สมัครบัญชี</button>
    </form>
    <div class="login-sep">หรือสมัครด้วย</div>
    <div class="social-row">
      <button type="button" class="social-btn">
        <span class="social-icon google-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.15v2.84C3.96 20.53 7.68 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.15A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.15 4.93l3.69-2.84z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.68 1 3.96 3.47 2.15 7.07l3.69 2.84C6.71 7.31 9.14 5.38 12 5.38z"/>
          </svg>
        </span>
        <span>Google</span>
      </button>
      <button type="button" class="social-btn">
        <span class="social-icon telegram-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path fill="#229ED9" d="M12 2C6.48 2 2 6.26 2 11.52c0 3.01 1.47 5.69 3.76 7.43l-.86 3.13c-.08.29.25.52.5.35l3.78-2.48c.9.25 1.85.38 2.82.38 5.52 0 10-4.26 10-9.52S17.52 2 12 2z"/>
            <path fill="#fff" d="M16.96 7.22 6.7 11.02c-.7.27-.7.65-.13.82l2.63.78 1 3.01c.12.34.06.48.41.48.31 0 .45-.14.62-.31l1.5-1.39 3.12 2.2c.57.3.98.15 1.12-.5l2.03-9.1c.2-.78-.32-1.13-.84-.89zM9.61 12.44l6.1-3.66c.3-.18.57-.08.35.11l-5.22 4.49-.2 2.03-1.03-2.97z"/>
          </svg>
        </span>
        <span>Telegram</span>
      </button>
    </div>
    <div class="modal-foot">มีบัญชีแล้ว? <button type="button" id="signupFromModal">เข้าสู่ระบบ</button></div>
  </section>
</div>
<script>
(() => {{
  const modal = document.getElementById('loginModal');
  const openBtn = document.getElementById('openLogin');
  const closeBtn = document.getElementById('closeLogin');
  const form = document.getElementById('mockLoginForm');
  const signupBtn = document.getElementById('signupBtn');
  const signupFromModal = document.getElementById('signupFromModal');
  const storageKey = 'papxnz_packages_mock_login';
  const userKey = 'papxnz_packages_user';
  const sessionKey = 'papxnz_packages_session_id';
  const mainPage = '{MAIN_WEB_LINK}';
  const sessionId = (() => {{
    let current = localStorage.getItem(sessionKey);
    if (!current) {{
      current = `web_${{Date.now()}}_${{Math.random().toString(36).slice(2, 10)}}`;
      localStorage.setItem(sessionKey, current);
    }}
    return current;
  }})();
  const currentPackage = () => new URLSearchParams(window.location.search).get('package') || '';
  const currentUsername = () => localStorage.getItem(userKey) || document.getElementById('loginUser')?.value || '';
  const postWebEvent = (eventType, extra = {{}}) => {{
    try {{
      const payload = {{
        event_type: eventType,
        session_id: sessionId,
        username: currentUsername(),
        source: 'packages_v',
        path: window.location.pathname,
        package_id: currentPackage(),
        ...extra
      }};
      fetch('/packages/event', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload),
        keepalive: true
      }}).catch(() => {{}});
    }} catch (err) {{}}
  }};
  const postLoginEvent = () => postWebEvent('web_login');

  const setLoggedIn = (value) => {{
    document.body.classList.toggle('is-logged-in', value);
    if (value) localStorage.setItem(storageKey, '1');
  }};
  const finishMockLogin = () => {{
    const username = document.getElementById('loginUser')?.value || '';
    if (username) localStorage.setItem(userKey, username);
    setLoggedIn(true);
    postLoginEvent();
    closeModal();
    window.location.href = mainPage;
  }};
  const openModal = () => {{
    document.body.classList.add('modal-open');
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    window.setTimeout(() => document.getElementById('loginUser')?.focus(), 180);
  }};
  const closeModal = () => {{
    document.body.classList.remove('modal-open');
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
  }};

  if (localStorage.getItem(storageKey) === '1') setLoggedIn(true);
  if (!document.body.classList.contains('package-edit-mode')) postWebEvent('web_page_view');
  openBtn?.addEventListener('click', finishMockLogin);
  signupBtn?.addEventListener('click', openModal);
  signupFromModal?.addEventListener('click', finishMockLogin);
  closeBtn?.addEventListener('click', closeModal);
  modal?.addEventListener('click', (event) => {{ if (event.target === modal) closeModal(); }});
  document.addEventListener('keydown', (event) => {{ if (event.key === 'Escape') closeModal(); }});
  form?.addEventListener('submit', (event) => {{
    event.preventDefault();
    finishMockLogin();
  }});
  if (!document.body.classList.contains('package-edit-mode')) document.querySelectorAll('[data-buy-package]').forEach((link) => {{
    link.addEventListener('click', () => {{
      postWebEvent('package_click', {{
          package_id: link.dataset.buyPackage || '',
          package_name: link.dataset.buyName || '',
          amount: link.dataset.buyAmount || '',
          status: localStorage.getItem(storageKey) === '1' ? 'logged_in' : 'guest',
          note: 'package card click'
      }});
    }});
  }});
}})();
</script>
{_packages_editor_script(edit)}
</body>
</html>"""
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    return HTMLResponse(content, headers=headers)


def _success_page_plain_unused(username: str = "username", package_name: str = "VIP LIFETIME", is_link_dead: bool = False):
    vip_link = "https://t.me/+R307dlx7C9E4ODQ1"
    disabled_class = "disabled" if is_link_dead else ""
    safe_link = vip_link.replace("'", "\\'")
    safe_username_js = json.dumps(str(username), ensure_ascii=False)
    safe_package_js = json.dumps(str(package_name), ensure_ascii=False)
    safe_link_js = json.dumps(str(vip_link), ensure_ascii=False)

    content = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>PAPXNZ BOT - SUCCESS</title>
<style>
body {{
    margin:0;
    min-height:100dvh;
    display:flex;
    align-items:center;
    justify-content:center;
    background:
        radial-gradient(circle at 50% 8%, rgba(212,170,95,.16), transparent 34%),
        linear-gradient(180deg,#030509 0%,#000 100%);
    color:#fff;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
}}
.vip-success-container {{
    width:min(430px,100%);
    padding:18px;
}}
.metallic-vip-card {{
    position:relative;
    overflow:hidden;
    min-height:188px;
    border-radius:28px;
    padding:26px 22px 22px;
    background:
        radial-gradient(circle at 85% 12%, rgba(255,210,120,.20), transparent 34%),
        linear-gradient(120deg,#050506 0%,#111216 34%,#020202 58%,#24180c 100%);
    border:1px solid rgba(255,218,150,.46);
    box-shadow:
        0 28px 80px rgba(0,0,0,.80),
        inset 0 1px 0 rgba(255,255,255,.18),
        inset 0 0 70px rgba(255,188,82,.08);
}}
.metallic-vip-card::before {{
    content:"";
    position:absolute;
    inset:-45%;
    background:linear-gradient(115deg, transparent 35%, rgba(255,255,255,.13) 48%, transparent 60%);
    transform:rotate(8deg);
    pointer-events:none;
}}
.metallic-vip-card::after {{
    content:"";
    position:absolute;
    inset:0;
    background:linear-gradient(180deg, rgba(255,255,255,.04), transparent 42%, rgba(0,0,0,.28));
    pointer-events:none;
}}
.member-label {{
    position:relative;
    z-index:1;
    font-size:19px;
    color:rgba(255,255,255,.92);
    line-height:1.25;
}}
.member-name {{
    position:relative;
    z-index:1;
    font-size:20px;
    font-weight:900;
    color:#fff;
}}
.card-package-center {{
    position:relative;
    z-index:1;
    margin:28px 0 22px;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:16px;
    text-align:center;
}}
.vip-main {{
    font-size:52px;
    font-weight:300;
    letter-spacing:.08em;
    color:#fff;
    text-shadow:0 0 20px rgba(255,255,255,.12);
}}
.gold-highlight {{
    font-size:24px;
    font-weight:900;
    color:#f2bf6a;
    text-shadow:0 0 18px rgba(242,191,106,.22);
}}
.card-footer-action {{
    position:relative;
    z-index:1;
    display:flex;
    justify-content:flex-end;
    gap:12px;
    margin-top:8px;
}}
.small-copy-btn,
.small-enter-btn {{
    height:42px;
    min-width:118px;
    padding:0 18px;
    border-radius:999px;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    text-decoration:none;
    font-size:14px;
    font-weight:900;
    cursor:pointer;
}}
.small-copy-btn {{
    color:rgba(255,238,205,.92);
    border:1px solid rgba(255,218,154,.22);
    background:rgba(255,255,255,.035);
    backdrop-filter:blur(10px);
}}
.small-enter-btn {{
    color:#1d1000;
    border:1px solid rgba(255,235,180,.78);
    background:linear-gradient(145deg,#fff4c9 0%,#e7b76a 26%,#c47a2a 62%,#6b3d14 100%);
    box-shadow:
        0 10px 24px rgba(196,122,42,.28),
        inset 0 1px 0 rgba(255,255,255,.42);
}}
.small-enter-btn.disabled {{
    pointer-events:none!important;
    cursor:not-allowed!important;
    color:rgba(255,255,255,.18)!important;
    background:rgba(255,255,255,.035)!important;
    border-color:rgba(255,255,255,.08)!important;
    box-shadow:none!important;
}}
</style>
</head>
<body>
<div class="vip-success-container">
  <div class="metallic-vip-card">
    <div class="member-label">Welcome Member</div>
    <div class="member-name">{escape(username)}</div>

    <div class="card-package-center">
      <div class="vip-main">VIP</div>
      <div class="gold-highlight">{escape(package_name)}</div>
    </div>

    <div class="card-footer-action">
      <button class="small-copy-btn" onclick="navigator.clipboard.writeText('{safe_link}');alert('คัดลอกสำเร็จแล้ว');">Copy Link</button>
      <a href="{vip_link}" class="small-enter-btn {disabled_class}" onclick="fetch('/packages/event', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{event_type:'enter_group_click', session_id:localStorage.getItem('papxnz_packages_session_id')||'', username:{safe_username_js}, package_name:{safe_package_js}, invite_link:{safe_link_js}, source:'packages_v', path:location.pathname, note:'success button'}}), keepalive:true}}).catch(()=>{{}});">เข้ากลุ่ม VIP</a>
    </div>
  </div>
</div>
<script>
fetch('/packages/event', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{event_type:'success_view', session_id:localStorage.getItem('papxnz_packages_session_id')||'', username:{safe_username_js}, package_name:{safe_package_js}, source:'packages_v', path:location.pathname}}), keepalive:true}}).catch(()=>{{}});
</script>
</body>
</html>"""
    return HTMLResponse(content)


def success_page(username: str = "username", package_name: str = "LIFETIME", is_link_dead: bool = False):
    vip_link = "https://t.me/+R307dlx7C9E4ODQ1"
    disabled_class = "disabled" if is_link_dead else ""
    safe_link = vip_link.replace("'", "\\'")
    safe_username_js = json.dumps(str(username), ensure_ascii=False)
    safe_package_js = json.dumps(str(package_name), ensure_ascii=False)
    safe_link_js = json.dumps(str(vip_link), ensure_ascii=False)

    content = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>PAPXNZ BOT - SUCCESS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@200;300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
    --copper-light:#fff2c7;
    --copper-mid:#d79a4a;
    --copper-deep:#704019;
    --mirror-black:#030304;
}}
* {{ box-sizing:border-box; }}
body {{
    margin:0;
    padding:0;
    min-height:100dvh;
    overflow-x:hidden;
    display:flex;
    align-items:center;
    justify-content:center;
    font-family:'Plus Jakarta Sans',sans-serif;
    color:#fff;
    background:
        radial-gradient(circle at 50% 12%, rgba(255,210,130,.10), transparent 28%),
        radial-gradient(circle at 12% 88%, rgba(215,154,74,.10), transparent 28%),
        linear-gradient(180deg,#05070b 0%,#020203 100%);
}}
.vip-success-container {{
    width:min(430px,100%);
    padding:16px;
}}
.metallic-vip-card {{
    position:relative;
    overflow:hidden;
    min-height:158px;
    border-radius:22px;
    padding:18px 18px 14px;
    background:
        linear-gradient(145deg, rgba(255,255,255,.18), rgba(255,255,255,0) 13%, rgba(255,255,255,.08) 31%, rgba(0,0,0,0) 48%),
        radial-gradient(circle at 22% 0%, rgba(255,255,255,.14), transparent 29%),
        radial-gradient(circle at 84% 88%, rgba(215,154,74,.16), transparent 32%),
        linear-gradient(115deg,#020202 0%,#0d0d0e 31%,#000 54%,#17130e 74%,#050505 100%);
    border:1px solid rgba(255,215,150,.42);
    box-shadow:
        0 24px 58px rgba(0,0,0,.78),
        0 0 0 1px rgba(255,232,180,.13) inset,
        0 0 28px rgba(215,154,74,.18),
        inset 0 1px 0 rgba(255,255,255,.18),
        inset 0 -28px 42px rgba(0,0,0,.72);
    backdrop-filter:blur(18px);
    -webkit-backdrop-filter:blur(18px);
}}
.metallic-vip-card::before {{
    content:"";
    position:absolute;
    inset:7px;
    border-radius:18px;
    border:1px solid rgba(255,224,166,.18);
    pointer-events:none;
    z-index:2;
}}
.metallic-vip-card::after {{
    content:"";
    position:absolute;
    left:-22%;
    top:-70%;
    width:40%;
    height:240%;
    transform:rotate(28deg);
    background:linear-gradient(90deg, transparent, rgba(255,255,255,.23), rgba(255,221,156,.12), transparent);
    filter:blur(.3px);
    animation:cardSweep 5.2s ease-in-out infinite;
    pointer-events:none;
    z-index:1;
}}
.card-shine {{
    position:absolute;
    inset:0;
    z-index:0;
    pointer-events:none;
    background:
        linear-gradient(90deg, transparent 0%, rgba(255,232,174,.82) 18%, rgba(255,249,222,.95) 50%, rgba(155,84,27,.48) 82%, transparent 100%) top/100% 3px no-repeat,
        linear-gradient(90deg, transparent 0%, rgba(255,232,174,.72) 20%, rgba(255,249,222,.9) 50%, rgba(155,84,27,.42) 82%, transparent 100%) bottom/100% 3px no-repeat;
    opacity:.9;
}}
.card-top-row,
.card-meta-row,
.card-package-center,
.card-bottom-details,
.card-footer-action {{
    position:relative;
    z-index:3;
}}
.card-top-row {{
    display:flex;
    justify-content:space-between;
    align-items:flex-start;
    gap:12px;
}}
.card-header-welcome {{ display:flex; flex-direction:column; gap:1px; }}
.welcome-label {{
    font-size:8.5px;
    font-weight:600;
    letter-spacing:.16em;
    color:rgba(255,255,255,.38);
    text-transform:uppercase;
}}
.username-val {{
    max-width:170px;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    font-size:13px;
    font-weight:700;
    color:rgba(255,255,255,.92);
}}
.card-brand-logo {{
    width:30px;
    height:24px;
    display:flex;
    align-items:center;
    justify-content:center;
    color:var(--copper-light);
    filter:drop-shadow(0 0 7px rgba(215,154,74,.45));
}}
.card-brand-logo svg {{ width:22px; height:22px; }}
.card-meta-row {{
    display:flex;
    align-items:center;
    gap:10px;
    margin-top:10px;
}}
.card-chip {{
    width:26px;
    height:18px;
    border-radius:5px;
    background:
        linear-gradient(90deg, rgba(0,0,0,.18) 1px, transparent 1px) 0 0/8px 100%,
        linear-gradient(180deg,#fff1b7 0%,#c78938 48%,#6d3b14 100%);
    box-shadow:inset 0 1px 1px rgba(255,255,255,.5), 0 0 10px rgba(215,154,74,.12);
    opacity:.82;
}}
.card-serial-number {{
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
    font-size:10px;
    letter-spacing:.20em;
    color:rgba(255,255,255,.25);
}}
.card-package-center {{
    margin:2px 0 0;
    text-align:center;
    font-size:34px;
    line-height:.96;
    font-weight:300;
    letter-spacing:.03em;
    color:rgba(255,255,255,.88);
    text-transform:uppercase;
    text-shadow:0 0 20px rgba(255,255,255,.08), 0 2px 3px rgba(0,0,0,.7);
}}
.gold-highlight {{
    display:inline-block;
    font-size:18px;
    font-weight:800;
    letter-spacing:.09em;
    background:linear-gradient(135deg,#fff6d6 0%,#e0aa59 42%,#89501d 72%,#ffe4a3 100%);
    -webkit-background-clip:text;
    background-clip:text;
    -webkit-text-fill-color:transparent;
    filter:drop-shadow(0 0 7px rgba(215,154,74,.18));
}}
.card-bottom-details {{
    margin-top:6px;
}}
.gold-divider-line {{
    width:46%;
    height:1px;
    margin:0 auto 4px;
    background:linear-gradient(90deg, transparent, var(--copper-light), var(--copper-mid), transparent);
    box-shadow:0 0 10px rgba(215,154,74,.35);
}}
.card-member-text {{
    text-align:center;
    font-size:11px;
    font-weight:600;
    letter-spacing:.10em;
    color:rgba(255,255,255,.66);
    text-transform:uppercase;
}}
.card-info-footer {{
    display:none;
}}
.card-footer-action {{
    display:flex;
    justify-content:flex-end;
    align-items:center;
    gap:7px;
    margin-top:12px;
    height:32px;
}}
.small-copy-btn,
.small-enter-btn {{
    height:30px;
    min-width:92px;
    padding:0 12px;
    border-radius:999px;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    text-decoration:none;
    font-family:inherit;
    font-size:10.5px;
    font-weight:800;
    line-height:1;
    white-space:nowrap;
    cursor:pointer;
}}
.small-copy-btn {{
    color:rgba(255,238,205,.86);
    border:1px solid rgba(255,218,154,.20);
    background:rgba(255,255,255,.035);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08);
}}
.small-enter-btn {{
    color:#1d1000;
    border:1px solid rgba(255,230,170,.70);
    background:linear-gradient(145deg,#fff7d5 0%,#e7b76a 24%,#b8732a 58%,#5f3513 100%);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.65),
        inset 0 -2px 5px rgba(45,20,0,.40),
        0 0 14px rgba(215,154,74,.28),
        0 6px 12px rgba(0,0,0,.35);
    text-shadow:0 1px 0 rgba(255,255,255,.25);
}}
.small-copy-btn:hover {{ background:rgba(255,255,255,.07); color:#fff; }}
.small-enter-btn:active,
.small-copy-btn:active {{ transform:translateY(1px); }}
.small-enter-btn.disabled {{
    pointer-events:none!important;
    cursor:not-allowed!important;
    color:rgba(255,255,255,.16)!important;
    background:rgba(255,255,255,.035)!important;
    border-color:rgba(255,255,255,.06)!important;
    box-shadow:none!important;
    text-shadow:none!important;
}}
@keyframes cardSweep {{
    0%,46% {{ transform:translateX(-120%) rotate(28deg); opacity:0; }}
    58% {{ opacity:1; }}
    100% {{ transform:translateX(360%) rotate(28deg); opacity:0; }}
}}
@media (max-width:380px) {{
    .metallic-vip-card {{ padding:17px 14px 13px; min-height:152px; }}
    .card-package-center {{ font-size:30px; }}
    .gold-highlight {{ font-size:16px; }}
    .small-copy-btn,.small-enter-btn {{ min-width:84px; padding:0 10px; font-size:10px; }}
}}
</style>
</head>
<body>
<div class="vip-success-container">
  <div class="metallic-vip-card">
    <div class="card-shine"></div>

    <div class="card-top-row">
      <div class="card-header-welcome">
        <span class="welcome-label">Welcome Member</span>
        <span class="username-val">{username}</span>
      </div>
      <div class="card-brand-logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4l3 12h14l3-12-6 7-4-7-4 7-6-7z"></path><path d="M3 20h18"></path></svg>
      </div>
    </div>

    <div class="card-meta-row">
      <div class="card-chip"></div>
      <div class="card-serial-number">**** **** VIP99</div>
    </div>

    <div class="card-package-center">VIP <span class="gold-highlight">{package_name}</span></div>

    <div class="card-bottom-details">
      <div class="gold-divider-line"></div>
      <div class="card-member-text">MEMBER ONLY</div>
      <div class="card-info-footer"></div>
    </div>

    <div class="card-footer-action">
      <button class="small-copy-btn" onclick="navigator.clipboard.writeText('{safe_link}');alert('คัดลอกสำเร็จแล้ว');">Copy Link</button>
      <a href="{vip_link}" class="small-enter-btn {disabled_class}" onclick="fetch('/packages/event', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{event_type:'enter_group_click', session_id:localStorage.getItem('papxnz_packages_session_id')||'', username:{safe_username_js}, package_name:{safe_package_js}, invite_link:{safe_link_js}, source:'packages_v', path:location.pathname, note:'success button'}}), keepalive:true}}).catch(()=>{{}});">เข้ากลุ่ม VIP</a>
    </div>
  </div>
</div>
<script>
fetch('/packages/event', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{event_type:'success_view', session_id:localStorage.getItem('papxnz_packages_session_id')||'', username:{safe_username_js}, package_name:{safe_package_js}, source:'packages_v', path:location.pathname}}), keepalive:true}}).catch(()=>{{}});
</script>
</body>
</html>"""
    return HTMLResponse(content)


def render_missing_slip_widget() -> str:
    day_labels = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
    month_labels = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    day_labels_js = "[" + ",".join(repr(label) for label in day_labels) + "]"
    month_labels_js = "[" + ",".join(repr(label) for label in month_labels) + "]"
    
    chevron_down = """
        <span class="missing-slip-chevrons" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"></path></svg>
        </span>
    """

    def picker_field(kind: str, input_type: str, value: str, label: str = "") -> str:
        label_attr = f' aria-label="{label}"' if label else ""
        readonly = " readonly" if input_type != "number" else ""
        return f"""
        <span class="missing-slip-control" data-slip-control="{kind}">
          <input class="missing-slip-input" data-slip-display="{kind}" data-slip-input="{kind}" type="{input_type}" value="{value}" inputmode="numeric"{readonly}{label_attr}>
          {chevron_down}
          <span class="missing-slip-picker" data-slip-picker="{kind}" role="listbox"></span>
        </span>
        """

    return f"""
<section class="missing-slip-widget" data-missing-slip-widget data-slip-endpoint="">
  <button class="missing-slip-toggle" type="button" aria-expanded="false">แจ้งสลิปหากยอดไม่เข้า</button>
  <div class="missing-slip-panel" aria-hidden="true">
    
    <h2 class="missing-slip-title">กรุณาระบุข้อมูลให้ตรง</h2>
    
    <div class="missing-slip-container">
      
      <div class="missing-slip-date-group">
      <div class="missing-slip-card">
        <div class="input-block-vertical">
        <label class="block-label">เวลา :</label>
        <div class="select-group-row">
          {picker_field("hour", "number", "00", "ชั่วโมง")}
          <b>:</b>
          {picker_field("minute", "number", "00", "นาที")}
          <b>:</b>
          {picker_field("second", "number", "00", "วินาที")}
        </div>
      </div>

      <div class="input-block-vertical">
        <label class="block-label">วัน/วันที่ :</label>
        <div class="select-group-row">
          {picker_field("weekday", "text", "จันทร์", "วัน")}
          <b>/</b>
          {picker_field("day", "number", "01", "วันที่")}
        </div>
      </div>

      <div class="input-block-vertical">
        <label class="block-label">เดือน/ปี :</label>
        <div class="select-group-row">
        <div class="missing-slip-date-row missing-slip-date-row-month">
          {picker_field("month", "text", "ม.ค.", "เดือน")}
          <span class="missing-slip-control missing-slip-year-control">
            <input class="missing-slip-input missing-slip-year" data-slip-input="year" type="text" value="2569" readonly aria-label="ปี">
          </span>
        </div>
      </div>
        
      </div>

      <div class="missing-slip-amount-group">
        
        <div class="missing-slip-input-container">
          <input class="missing-slip-amount" data-slip-amount type="number" inputmode="decimal" min="0" step="0.01" placeholder="กรอกยอดเงิน">
        </div>
        
        <div class="missing-slip-input-container">
          <label class="missing-slip-file">
            <input data-slip-file type="file" accept="image/*">
            <div class="dashed-drop-zone">
              <span class="upload-text-center"> + แนบภาพสลิป </span>
            </div>
          </label>
        </div>
        
        <div class="missing-slip-action-row">
          <button class="missing-slip-submit" type="button" data-slip-submit>ยืนยัน</button>
        </div>
        
      </div>

    </div>
  </div>
</section>

<style>
.missing-slip-widget {{
  width: min(480px, calc(100% - 20px)); /* ปรับบีบหน้ากว้างรวมให้กะทัดรัดสไตล์แอปชั้นสูง */
  margin: 14px auto 0;
  text-align: center;
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 200;
}}
.missing-slip-widget *,
.missing-slip-widget *::before,
.missing-slip-widget *::after {{
  box-sizing: border-box;
}}
.missing-slip-toggle {{
  min-width: 190px;
  min-height: 40px;
  padding: 0 22px;
  border: .5px solid rgba(255, 255, 255, .1);
  border-radius: 4px;
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 200;
  cursor: pointer;
  background: rgba(255, 255, 255, .01);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
}}
/* พื้นหลังลิ้นชักรวม: ขาวบางเบลอหมอกหนานุ่ม คุมดาร์กหลบความแสบตา */
.missing-slip-panel {{
  max-height: 0;
  overflow: hidden;
  opacity: 0;
  margin-top: 0;
  padding: 0;
  border: .5px solid transparent;
  border-radius: 8px;
  background: rgba(255, 255, 255, .10);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  transition: max-height .28s ease, opacity .18s ease, margin-top .2s ease, padding .2s ease, border-color .2s ease;
}}
.missing-slip-widget.is-open .missing-slip-panel {{
  max-height: 480px; /* ขยายพื้นที่เพื่อรองรับการจัดหมวดหมู่แยกบรรทัดระเบียบจัด */
  opacity: 1;
  margin-top: 12px;
  padding: 24px;
  border-color: rgba(255, 255, 255, .08);
  overflow: visible;
}}
.missing-slip-title {{
  display: block;
  width: 100%;
  margin: 0 0 20px 0;
  text-align: center;
  color: rgba(255, 255, 255, .85);
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0.5px;
}}
/* จัดตำแหน่งคอนเทนเนอร์หลัก แยกโซนเวลา (บน) และโซนเงิน (ล่าง) ออกจากกันเด็ดขาด ไม่ให้ชนกัน */
.missing-slip-container {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px; /* เว้นระยะห่างระหว่างหมวดหมู่ชัดเจน สบายตา */
  width: 100%;
}}
/* [หมวดหมู่เวลา]: จัดเรียงลงมาเป็นระเบียบเตี้ยกระชับกึ่งกลาง */
.missing-slip-date-group {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px; /* บีบช่องไฟแนวตั้งให้เนี้ยบ */
  width: 100%;
}}
.missing-slip-row-block {{
  display: flex;
  justify-content: center;
  width: 100%;
}}
.missing-slip-date-row {{
  display: grid;
  align-items: center;
}}
/* ล็อกหน้ากว้างช่องเวลาตัวเลขเด็ดขาด กล่องละ 48px เตี้ยสั้น ไม่ล้นทะลัก */
.missing-slip-date-row-time {{
  grid-template-columns: 48px 18px 48px 18px 48px;
}}
/* ล็อกช่องวันเต็มตัวกะทัดรัดที่ 114px และวันที่ที่ 48px สวยงามระเบียบจัด */
.missing-slip-date-row-day {{
  grid-template-columns: 114px 18px 48px;
}}
.missing-slip-date-row-month {{
  grid-template-columns: 88px 88px;
  gap: 4px;
}}
.missing-slip-date-row b {{
  color: rgba(255, 255, 255, .25);
  font: inherit;
  font-size: 13px;
  font-weight: 100;
  text-align: center;
}}
.missing-slip-control {{
  position: relative;
  display: block;
  width: 100%;
  height: 30px; /* ล็อกความเตี้ยมินิมอลสไตล์หน้า VIP */
}}

/* ช่องอินพุต: ขาวโทนฟ้าเทาใสมองทะลุ (Quartz Crystal) ถอดรหัสสีจากหน้า VIP ไม่ขาวลอยแสบตา */
.missing-slip-input {{
  width: 100%;
  height: 100%;
  border: .5px solid rgba(204, 211, 223, 0.3); /* สีขอบละมุนตามรูปถ่าย */
  color: rgba(255, 255, 255, 0.9); /* สีตัวอักษรเทาสว่างนิ่งสุภาพ */
  background: rgba(245, 247, 250, 0.25); /* เนื้อขาวอมฟ้าเทาบางเฉียบ มองทะลุมิติเห็นพื้นหลังเว็บ */
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 200;
  outline: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 14px 0 4px;
  border-radius: 6px; /* โค้งมนเนี้ยบกริบถอดสเปกตามภาพถ่าย */
  text-align: center;
}}
.missing-slip-year-control .missing-slip-input {{
  padding-right: 4px;
  color: rgba(255, 255, 255, .4);
}}
/* ไอคอนลูกศรหัวลงตัวเดียวนิ่งๆ คมกริบ */
.missing-slip-chevrons {{
  position: absolute;
  top: 50%;
  right: 5px;
  width: 10px;
  height: 10px;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}}
.missing-slip-chevrons svg {{
  width: 10px;
  height: 10px;
  fill: none;
  stroke: rgba(255, 255, 255, .4);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}}
.missing-slip-year-control .missing-slip-chevrons {{
  display: none;
}}

/* จัดการให้แต่ละแถวเรียงแนวนอน และล้างปัญหาการเบี้ยวล้น */
.input-row-flex {{
  display: flex !important;
  align-items: center; /* จัดให้ตัวอักษรกับกล่องอยู่กึ่งกลางแนวดิ่งพอดี */
  margin-bottom: 12px; /* เว้นระยะห่างระหว่างแถว */
  width: 100%;
}}

/* บล็อกความกว้างตัวอักษรข้างหน้าให้เท่ากันทุกแถว กล่องหลังจะได้ไม่เยื้อง */
.row-label {{
  font-size: 13px; /* ฟอนต์เล็กกะทัดรัด ไม่ดันกล่อง */
  color: #8a8a8a; /* สีเทาหม่นสไตล์ดาร์กโหมด */
  min-width: 65px; /* ล็อกความกว้างแถวหน้าให้เท่ากันเป๊ะเพื่อยันกล่องหลัง */
  text-align: left;
}}

/* จัดเครื่องหมาย : ให้ตรงแนวเดียวกัน */
.row-divider {{
  font-size: 13px;
  color: #666;
  margin-right: 12px; /* เว้นระยะช่องไฟก่อนถึงตัวกล่อง */
}}

/* คุมกล่องรับข้อมูลด้านหลังให้ยืดหยุ่นและไม่ล้นขอบ */
.missing-slip-date-row {{
  display: flex;
  align-items: center;
  flex: 1; /* ให้กล่องด้านหลังขยายพื้นที่เท่ากันทั้งหมด */
  gap: 6px; /* เว้นระยะห่างระหว่างกล่องจิ๋วข้างใน */
  
}}

/* [หมวดหมู่เงินและหลักฐาน]: คุมหน้ากว้างพิกเซลเท่าชุดบน เรียงแนวดิ่งลงมาเนี้ยบๆ */
.missing-slip-amount-group {{
  width: 180px; /* บีบหน้ากว้างฝั่งช่องกรอกให้กะทัดรัดสมมาตรเท่าชุดปฏิทิน */
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.missing-slip-input-container {{
  width: 100%;
}}

/* คุมแต่ละบล็อกให้เรียงลงมาแนวตั้ง เพื่อให้ข้อความอยู่บนกล่อง */
.input-block-vertical {{
  display: flex !important;
  flex-direction: column !important; /* สั่งให้ข้อความอยู่ด้านบน กล่องอยู่ด้านล่าง */
  align-items: flex-start !important; /* บังคับให้ข้อความชิดซ้ายตรงกับขอบกล่องแรกเป๊ะ */
  margin-bottom: 12px;
  width: 100%;
}}

/* 🎯 ตัวอักษรคำอธิบาย ลอยเหนือกล่องสวย ๆ */
.block-label {{
  font-size: 13px;
  color: #8a8a8a; /* สีเทาชิค ๆ */
  margin-bottom: 6px; /* ระยะห่างสเปซก่อนถึงตัวกล่องด้านล่าง */
  padding-left: 2px; /* ขยับให้ตรงขอบกล่องพอดี */
}}

/* กลุ่มกล่อง Select เดิมของพะแพน ห้ามไปแก้อะไรมันเลยปล่อยรันตามปกติ */
.select-group-row {{
  display: flex;
  width: 100%;
}}

/* [8] ช่องยอดเงิน: ทรงรีแคปซูลมน ผิวขาวโทนฟ้าเทาใสมองทะลุ ไร้ที่เลื่อนเบราว์เซอร์กวนสายตา */
.missing-slip-amount {{
  width: 100%;
  height: 30px;
  border: .5px solid rgba(204, 211, 223, 0.3);
  border-radius: 15px;
  color: rgba(255, 255, 255, 0.9);
  background: rgba(245, 247, 250, 0.20);
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 200;
  text-align: center;
  outline: 0;
}}
.missing-slip-amount::placeholder {{
  color: rgba(255, 255, 255, .32);
}}
.missing-slip-amount:focus {{
  background: rgba(255, 255, 255, .12);
}}

/* [9] ช่องแนบสลิป: แผ่นสีอ่อนเตี้ยกระชับฝังเส้นประละเอียด ขาวโทนฟ้าเทาใสมองทะลุ */
.missing-slip-file input {{
  display: none;
}}
.missing-slip-file {{
  width: 100%;
  cursor: pointer;
  display: block;
}}
.dashed-drop-zone {{
  width: 100%;
  min-height: 44px;
  border: .5px dashed rgba(255, 255, 255, .2);
  border-radius: 6px;
  background: rgba(245, 247, 250, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .2s ease;
}}
.upload-text-center {{
  color: rgba(255, 255, 255, 0.7);
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 200;
}}
.missing-slip-file:hover .dashed-drop-zone {{
  background: rgba(255, 255, 255, .1);
}}

/* [10] ปุ่มคอนเฟิร์ม: จัดสแตนด์บายอยู่มุมขวาสุดด้านล่างสุดของพื้นที่กลุ่มเงินพอดีเป๊ะ */
.missing-slip-action-row {{
  width: 100%;
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
}}
.missing-submit-wrapper {{
  width: 100%;
  display: flex;
  justify-content: flex-end;
}}
.missing-slip-submit {{
  min-width: 90px;
  height: 32px;
  border: .5px solid rgba(255, 255, 255, .1);
  border-radius: 4px;
  color: rgba(255, 255, 255, .95);
  background: #A82B2B; /* แดง Support คุมดาร์กหรูหรา สุภาพเข้ายาก */
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 200;
  cursor: pointer;
  transition: opacity .2s ease;
}}
.missing-slip-submit:hover {{
  opacity: .9;
}}

/* Dropdown สกรอลล์ 5 แถว */
.missing-slip-picker {{
  position: absolute;
  z-index: 40;
  left: 0;
  right: 0;
  top: calc(100% + 4px);
  max-height: 150px;
  display: none;
  overflow-y: scroll;
  overflow-x: hidden;
  border: .5px solid rgba(255, 255, 255, .12);
  border-radius: 6px;
  background: rgba(15, 15, 18, .98);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  scrollbar-width: none;
}}
.missing-slip-picker::-webkit-scrollbar {{
  width: 0;
  height: 0;
}}
.missing-slip-control.is-open .missing-slip-picker {{
  display: block;
}}
.missing-slip-option {{
  width: 100%;
  min-height: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
  color: rgba(255, 255, 255, .4);
  background: transparent;
  border: none;
  font: inherit;
  font-size: 12px;
  font-weight: 200;
  cursor: pointer;
  text-align: center;
}}
.missing-slip-option:hover {{
  background: rgba(255, 255, 255, .03);
  color: rgba(255, 255, 255, .8);
}}
.missing-slip-option.is-selected {{
  color: rgba(255, 255, 255, .95);
  background: rgba(255, 255, 255, .06);
  box-shadow: inset 0 0 6px rgba(0, 0, 0, .6), 0 1px 3px rgba(0, 0, 0, .4);
}}

.missing-slip-info {{
  display: none;
  width: 100%;
  margin-top: 12px;
  padding: 10px 12px;
  border: .5px solid rgba(255, 255, 255, .15);
  border-radius: 6px;
  color: rgba(255, 255, 255, .6);
  background: rgba(255, 255, 255, .015);
  text-align: left;
  backdrop-filter: blur(25px);
  -webkit-backdrop-filter: blur(25px);
}}
.missing-slip-widget.is-open .missing-slip-info {{
  display: block;
}}
.missing-slip-info b,
.missing-slip-info span {{
  display: block;
  font: inherit;
  font-size: 12px;
  font-weight: 200;
  line-height: 1.5;
}}
</style>

<script>
(() => {{
  const root = document.querySelector('[data-missing-slip-widget]');
  if (!root || root.dataset.ready === '1') return;
  root.dataset.ready = '1';

  const toggle = root.querySelector('.missing-slip-toggle');
  const panel = root.querySelector('.missing-slip-panel');
  const file = root.querySelector('[data-slip-file]');
  const fileZone = root.querySelector('.dashed-drop-zone');
  const amount = root.querySelector('[data-slip-amount]');
  const submit = root.querySelector('[data-slip-submit]');
  const dayLabels = {day_labels_js};
  const monthLabels = {month_labels_js};
  const pad2 = (value) => String(value).padStart(2, '0');
  
  const ranges = {{
    hour: Array.from({{length: 24}}, (_, index) => pad2(index)),
    minute: Array.from({{length: 60}}, (_, index) => pad2(index)),
    second: Array.from({{length: 60}}, (_, index) => pad2(index)),
    weekday: dayLabels,
    day: Array.from({{length: 31}}, (_, index) => pad2(index + 1)),
    month: monthLabels
  }};

  const closePickers = (except = null) => {{
    root.querySelectorAll('.missing-slip-control.is-open').forEach((control) => {{
      if (control !== except) control.classList.remove('is-open');
    }});
  }};
  
  const valueOf = (kind) => {{
    const input = root.querySelector(`[data-slip-input="${{kind}}"]`);
    return input ? input.value.trim() : '';
  }};
  
  const setSubmitting = (isSubmitting) => {{
    submit.disabled = isSubmitting;
    submit.textContent = isSubmitting ? 'ยืนยัน...' : 'ยืนยัน';
  }};
  
  const buildPayload = () => {{
    const selectedFile = file.files && file.files[0] ? file.files[0] : null;
    return {{
      hour: valueOf('hour'),
      minute: valueOf('minute'),
      second: valueOf('second'),
      weekday: valueOf('weekday'),
      day: valueOf('day'),
      month: valueOf('month'),
      year: '2569',
      amount: amount ? amount.value.trim() : '',
      fileName: selectedFile ? selectedFile.name : '',
      hasFile: Boolean(selectedFile),
      submittedAt: new Date().toISOString()
    }};
  }};
  
  const buildFormData = (payload) => {{
    const formData = new FormData();
    Object.entries(payload).forEach(([key, value]) => formData.append(key, value));
    if (file.files && file.files[0]) formData.append('slip_file', file.files[0]);
    return formData;
  }};

  const selectValue = (kind, value) => {{
    const input = root.querySelector(`[data-slip-input="${{kind}}"]`);
    if (!input) return;
    input.value = value;
    
    const picker = root.querySelector(`[data-slip-picker="${{kind}}"]`);
    if (picker) {{
      picker.querySelectorAll('.missing-slip-option').forEach((option) => {{
        option.classList.toggle('is-selected', option.dataset.value === value);
      }});
      
      setTimeout(() => {{
        const selected = picker.querySelector('.missing-slip-option.is-selected');
        if (selected) {{
          picker.scrollTop = Math.max(0, selected.offsetTop - (picker.clientHeight / 2) + (selected.clientHeight / 2));
        }}
      }}, 10);
    }}
  }};

  Object.entries(ranges).forEach(([kind, values]) => {{
    const picker = root.querySelector(`[data-slip-picker="${{kind}}"]`);
    if (!picker) return;
    
    picker.innerHTML = values.map((value) => `<button class="missing-slip-option" type="button" role="option" data-value="${{value}}">${{value}}</button>`).join('');
    
    picker.addEventListener('click', (event) => {{
      const option = event.target.closest('.missing-slip-option');
      if (!option) return;
      selectValue(kind, option.dataset.value);
      closePickers();
    }});
  }});

  const now = new Date();
  selectValue('hour', pad2(now.getHours()));
  selectValue('minute', pad2(now.getMinutes()));
  selectValue('second', pad2(now.getSeconds()));
  selectValue('weekday', dayLabels[(now.getDay() + 6) % 7]);
  selectValue('day', pad2(now.getDate()));
  selectValue('month', monthLabels[now.getMonth()]);

  root.querySelectorAll('.missing-slip-control').forEach((control) => {{
    const kind = control.dataset.slipControl;
    const input = control.querySelector('[data-slip-input]');
    if (!input || !ranges[kind]) return;
    
    const open = () => {{
      closePickers(control);
      control.classList.add('is-open');
      selectValue(kind, input.value || ranges[kind][0]);
    }};
    
    control.addEventListener('click', (event) => {{
      event.stopPropagation();
      open();
    }});
    
    input.addEventListener('focus', open);
    
    input.addEventListener('change', () => {{
      if (input.type === 'number') {{
        const numeric = Number(input.value);
        const min = kind === 'day' ? 1 : 0;
        const max = kind === 'day' ? 31 : (kind === 'hour' ? 23 : 59);
        const clamped = Math.max(min, Math.min(max, Number.isFinite(numeric) ? numeric : min));
        selectValue(kind, pad2(clamped));
      }} else if (ranges[kind].includes(input.value)) {{
        selectValue(kind, input.value);
      }}
    }});
  }});

  toggle.addEventListener('click', () => {{
    const open = !root.classList.contains('is-open');
    root.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    closePickers();
  }});

  document.addEventListener('click', () => closePickers());
  
  file.addEventListener('change', () => {{
    const name = file.files && file.files[0] ? file.files[0].name : '';
    if (name) {{
      fileZone.style.background = 'rgba(255, 255, 255, .15)';
      fileZone.innerHTML = `<span class="upload-text-center" style="color: #fff; font-weight:400;">แนบแล้ว: ${{name.slice(0, 12)}}</span>`;
    }} else {{
      fileZone.style.background = 'rgba(245, 247, 250, 0.05)';
      fileZone.innerHTML = `<span class="upload-text-center"> + แนบภาพสลิป </span>`;
    }}
  }});

  submit.addEventListener('click', async () => {{
    if (submit.disabled) return;
    const payload = buildPayload();
    const selectedFile = file.files && file.files[0] ? file.files[0] : null;
    const endpoint = root.dataset.slipEndpoint || '';
    
    root.dispatchEvent(new CustomEvent('missing-slip:submit', {{
      bubbles: true,
      detail: {{ payload, file: selectedFile }}
    }}));

    setSubmitting(true);

    if (!endpoint) {{
      setSubmitting(false);
      return;
    }}

    try {{
      const response = await fetch(endpoint, {{
        method: 'POST',
        body: buildFormData(payload)
      }});
      if (!response.ok) throw new Error(`Request failed: ${{response.status}}`);
      
      root.dispatchEvent(new CustomEvent('missing-slip:success', {{
        bubbles: true,
        detail: {{ payload, response }}
      }}));
    }} catch (error) {{
      root.dispatchEvent(new CustomEvent('missing-slip:error', {{
        bubbles: true,
        detail: {{ payload, error }}
      }}));
    }} finally {{
      setSubmitting(false);
    }}
  }});
}})();
</script>

<script>
(() => {{
  const root = document.querySelector('[data-missing-slip-widget]');
  if (!root || root.dataset.ready === '1') return;
  root.dataset.ready = '1';

  const toggle = root.querySelector('.missing-slip-toggle');
  const panel = root.querySelector('.missing-slip-panel');
  const file = root.querySelector('[data-slip-file]');
  const fileZone = root.querySelector('.dashed-drop-zone');
  const amount = root.querySelector('[data-slip-amount]');
  const submit = root.querySelector('[data-slip-submit]');
  const dayLabels = {day_labels_js};
  const monthLabels = {month_labels_js};
  const pad2 = (value) => String(value).padStart(2, '0');
  
  const ranges = {{
    hour: Array.from({{length: 24}}, (_, index) => pad2(index)),
    minute: Array.from({{length: 60}}, (_, index) => pad2(index)),
    second: Array.from({{length: 60}}, (_, index) => pad2(index)),
    weekday: dayLabels,
    day: Array.from({{length: 31}}, (_, index) => pad2(index + 1)),
    month: monthLabels
  }};

  const closePickers = (except = null) => {{
    root.querySelectorAll('.missing-slip-control.is-open').forEach((control) => {{
      if (control !== except) control.classList.remove('is-open');
    }});
  }};
  
  const valueOf = (kind) => {{
    const input = root.querySelector(`[data-slip-input="${{kind}}"]`);
    return input ? input.value.trim() : '';
  }};
  
  const setSubmitting = (isSubmitting) => {{
    submit.disabled = isSubmitting;
    submit.textContent = isSubmitting ? 'กำลังตรวจสอบ...' : 'ยืนยัน';
  }};
  
  const buildPayload = () => {{
    const selectedFile = file.files && file.files[0] ? file.files[0] : null;
    return {{
      hour: valueOf('hour'),
      minute: valueOf('minute'),
      second: valueOf('second'),
      weekday: valueOf('weekday'),
      day: valueOf('day'),
      month: valueOf('month'),
      year: '2569',
      amount: amount ? amount.value.trim() : '',
      fileName: selectedFile ? selectedFile.name : '',
      hasFile: Boolean(selectedFile),
      submittedAt: new Date().toISOString()
    }};
  }};
  
  const buildFormData = (payload) => {{
    const formData = new FormData();
    Object.entries(payload).forEach(([key, value]) => formData.append(key, value));
    if (file.files && file.files[0]) formData.append('slip_file', file.files[0]);
    return formData;
  }};

  const selectValue = (kind, value) => {{
    const input = root.querySelector(`[data-slip-input="${{kind}}"]`);
    if (!input) return;
    input.value = value;
    
    const picker = root.querySelector(`[data-slip-picker="${{kind}}"]`);
    if (picker) {{
      picker.querySelectorAll('.missing-slip-option').forEach((option) => {{
        option.classList.toggle('is-selected', option.dataset.value === value);
      }});
      
      setTimeout(() => {{
        const selected = picker.querySelector('.missing-slip-option.is-selected');
        if (selected) {{
          picker.scrollTop = Math.max(0, selected.offsetTop - (picker.clientHeight / 2) + (selected.clientHeight / 2));
        }}
      }}, 10);
    }}
  }};

  Object.entries(ranges).forEach(([kind, values]) => {{
    const picker = root.querySelector(`[data-slip-picker="${{kind}}"]`);
    if (!picker) return;
    
    picker.innerHTML = values.map((value) => `<button class="missing-slip-option" type="button" role="option" data-value="${{value}}">${{value}}</button>`).join('');
    
    picker.addEventListener('click', (event) => {{
      const option = event.target.closest('.missing-slip-option');
      if (!option) return;
      selectValue(kind, option.dataset.value);
      closePickers();
    }});
  }});

  const now = new Date();
  selectValue('hour', pad2(now.getHours()));
  selectValue('minute', pad2(now.getMinutes()));
  selectValue('second', pad2(now.getSeconds()));
  selectValue('weekday', dayLabels[(now.getDay() + 6) % 7]);
  selectValue('day', pad2(now.getDate()));
  selectValue('month', monthLabels[now.getMonth()]);

  root.querySelectorAll('.missing-slip-control').forEach((control) => {{
    const kind = control.dataset.slipControl;
    const input = control.querySelector('[data-slip-input]');
    if (!input || !ranges[kind]) return;
    
    const open = () => {{
      closePickers(control);
      control.classList.add('is-open');
      selectValue(kind, input.value || ranges[kind][0]);
    }};
    
    control.addEventListener('click', (event) => {{
      event.stopPropagation();
      open();
    }});
    
    input.addEventListener('focus', open);
    
    input.addEventListener('change', () => {{
      if (input.type === 'number') {{
        const numeric = Number(input.value);
        const min = kind === 'day' ? 1 : 0;
        const max = kind === 'day' ? 31 : (kind === 'hour' ? 23 : 59);
        const clamped = Math.max(min, Math.min(max, Number.isFinite(numeric) ? numeric : min));
        selectValue(kind, pad2(clamped));
      }} else if (ranges[kind].includes(input.value)) {{
        selectValue(kind, input.value);
      }}
    }});
  }});

  toggle.addEventListener('click', () => {{
    const open = !root.classList.contains('is-open');
    root.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    closePickers();
  }});

  document.addEventListener('click', () => closePickers());
  
  file.addEventListener('change', () => {{
    const name = file.files && file.files[0] ? file.files[0].name : '';
    if (name) {{
      fileZone.style.background = 'rgba(255, 255, 255, .9)';
      fileZone.innerHTML = `<span class="upload-text-center" style="color: #A82B2B; font-weight:400;">แนบแล้ว: ${{name.slice(0, 18)}}</span>`;
    }} else {{
      fileZone.style.background = 'rgba(255, 255, 255, .75)';
      fileZone.innerHTML = `<span class="upload-text-center"> + แนบภาพสลิป </span>`;
    }}
  }});

  submit.addEventListener('click', async () => {{
    if (submit.disabled) return;
    const payload = buildPayload();
    const selectedFile = file.files && file.files[0] ? file.files[0] : null;
    const endpoint = root.dataset.slipEndpoint || '';
    
    root.dispatchEvent(new CustomEvent('missing-slip:submit', {{
      bubbles: true,
      detail: {{ payload, file: selectedFile }}
    }}));

    setSubmitting(true);

    if (!endpoint) {{
      setSubmitting(false);
      return;
    }}

    try {{
      const response = await fetch(endpoint, {{
        method: 'POST',
        body: buildFormData(payload)
      }});
      if (!response.ok) throw new Error(`Request failed: ${{response.status}}`);
      
      root.dispatchEvent(new CustomEvent('missing-slip:success', {{
        bubbles: true,
        detail: {{ payload, response }}
      }}));
    }} catch (error) {{
      root.dispatchEvent(new CustomEvent('missing-slip:error', {{
        bubbles: true,
        detail: {{ payload, error }}
      }}));
    }} finally {{
      setSubmitting(false);
    }}
  }});
}})();
</script>
"""


def register_package_routes(app):

    @app.get("/packages", response_class=HTMLResponse)
    async def packages_route(request: Request):
        return packages_page(edit=request.query_params.get("edit") == "1")

    @app.post("/packages/edit/save")
    async def packages_editor_save(request: Request):
        return save_package_editor_config(await request.json())

    @app.get("/packages-editor-pan", response_class=HTMLResponse)
    async def packages_editor():
        return HTMLResponse("""
        <!doctype html>
        <html lang="th">
        <head>
          <meta charset="utf-8">
          <meta http-equiv="refresh" content="0; url=/packages?edit=1">
          <title>Package Editor</title>
        </head>
        <body>
          <a href="/packages?edit=1">เปิด Visual editor</a>
        </body>
        </html>
        """)
        return HTMLResponse("""
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8">
        <title>Package Editor</title>
        </head>
        <body style="
            background:#07090d;
            color:white;
            font-family:sans-serif;
            padding:20px;
        ">

        <h1>Package Editor</h1>

        <p>
        เดี๋ยวรอบต่อไปพะแพนจะใส่ editor preview สดตรงนี้ได้เลย
        </p>

        </body>
        </html>
        """)
