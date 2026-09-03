"""کیبوردها و متن‌های ثابت."""
from __future__ import annotations

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as M
from telegram import KeyboardButton, ReplyKeyboardMarkup

import config

# ---------- دکمه‌های کیبورد کاربر ----------
BTN_LINK = "🔗 دریافت لینک ناشناس من"
BTN_BLOCKS = "🚫 لیست بلاکی‌ها"
BTN_STATS = "📊 آمار من"
BTN_SETTINGS = "⚙️ تنظیمات"
BTN_HELP = "❓ راهنما"
BTN_ADMIN = "🛠 پنل ادمین"


def main_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_LINK)],
        [KeyboardButton(BTN_BLOCKS), KeyboardButton(BTN_STATS)],
        [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


# ---------- جوین اجباری ----------

def join_kb(channels, bot_username: str, payload: str = "") -> M:
    rows = []
    for ch in channels:
        link = ch["link"] or (f"https://t.me/{ch['username']}" if ch["username"] else "")
        title = ch["title"] or ch["username"] or "کانال"
        rows.append([B(f"📢 عضویت در {title}", url=link)])
    rows.append([B("✅ عضو شدم، بررسی کن", callback_data=f"chk:{payload}")])
    return M(rows)


# ---------- پیام ناشناس دریافتی ----------

def recv_kb(msg_id: int, seen_shown: bool = True) -> M:
    row1 = [B("پاسخ ↪️", callback_data=f"rp:{msg_id}")]
    if seen_shown:
        row1.append(B("پیامتو دیدم 👀", callback_data=f"sn:{msg_id}"))
    row2 = [
        B("بلاک 🚫", callback_data=f"bl:{msg_id}"),
        B("گزارش تخلف ⚠️", callback_data=f"rc:{msg_id}"),
    ]
    return M([row1, row2])


def seen_only_kb(msg_id: int) -> M:
    return M(
        [
            [B("پاسخ ↪️", callback_data=f"rp:{msg_id}")],
            [
                B("بلاک 🚫", callback_data=f"bl:{msg_id}"),
                B("گزارش تخلف ⚠️", callback_data=f"rc:{msg_id}"),
            ],
        ]
    )


def report_confirm_kb(msg_id: int) -> M:
    return M(
        [
            [B("✅ بله، گزارش کن", callback_data=f"rcy:{msg_id}")],
            [B("↩️ بازگشت", callback_data=f"rcn:{msg_id}")],
        ]
    )


def block_confirm_kb(msg_id: int) -> M:
    return M(
        [
            [B("✅ بله، بلاک کن", callback_data=f"bly:{msg_id}")],
            [B("↩️ بازگشت", callback_data=f"bln:{msg_id}")],
        ]
    )


def sender_ack_kb(msg_id: int) -> M:
    """زیر پیام تأیید ارسال برای فرستنده."""
    return M([[B("🗑 حذف پیام از چت مخاطب", callback_data=f"del:{msg_id}")]])


# ---------- لینک ----------

def link_kb(link: str, token: str) -> M:
    share = f"https://t.me/share/url?url={link}&text=%D8%A8%D9%87%20%D9%85%D9%86%20%D9%BE%DB%8C%D8%A7%D9%85%20%D9%86%D8%A7%D8%B4%D9%86%D8%A7%D8%B3%20%D8%A8%D8%AF%D9%87%20%F0%9F%98%88"
    return M(
        [
            [B("📤 اشتراک‌گذاری لینک", url=share)],
            [B("🖼 دریافت QR کد", callback_data="qr")],
            [B("♻️ ساخت لینک جدید", callback_data="newtok")],
        ]
    )


# ---------- تنظیمات کاربر ----------

def user_settings_kb(u) -> M:
    link_on = u["link_active"] == 1
    seen_on = u["seen_notify"] == 1
    nick = u["nickname"] or "—"
    return M(
        [
            [B(f"لینک ناشناس: {'🟢 روشن' if link_on else '🔴 خاموش'}", callback_data="st:link")],
            [B(f"تیک «دیدم»: {'🟢 فعال' if seen_on else '🔴 غیرفعال'}", callback_data="st:seen")],
            [B(f"نام نمایشی: {nick}", callback_data="st:nick")],
            [B("♻️ ساخت لینک جدید", callback_data="newtok")],
            [B("🗑 پاک کردن همه بلاک‌ها", callback_data="st:clrblk")],
            [B("✖️ بستن", callback_data="close")],
        ]
    )


def blocks_kb(rows, page: int, total_pages: int) -> M:
    kb = []
    for r in rows:
        name = (r["first_name"] or "").strip() or str(r["blocked_id"])
        if len(name) > 22:
            name = name[:21] + "…"
        kb.append([B(f"♻️ آنبلاک {name}", callback_data=f"ub:{r['blocked_id']}")])
    nav = []
    if page > 0:
        nav.append(B("◀️ قبلی", callback_data=f"blkp:{page-1}"))
    if total_pages > 1:
        nav.append(B(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(B("بعدی ▶️", callback_data=f"blkp:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([B("✖️ بستن", callback_data="close")])
    return M(kb)


# ---------- پنل ادمین ----------

def admin_kb() -> M:
    return M(
        [
            [
                B("📊 آمار کامل", callback_data="a:stats"),
                B("👥 کاربران", callback_data="a:users:0"),
            ],
            [
                B("⚠️ گزارش‌ها", callback_data="a:reports:open:0"),
                B("📨 پیام‌های اخیر", callback_data="a:msgs:0"),
            ],
            [
                B("🔍 جستجوی کاربر", callback_data="a:find"),
                B("✉️ پیام به کاربر", callback_data="a:dm"),
            ],
            [
                B("📢 ارسال همگانی", callback_data="a:bc"),
                B("📣 فوروارد همگانی", callback_data="a:fwd"),
            ],
            [
                B("🔒 قفل‌ها و تنظیمات", callback_data="a:cfg"),
                B("📡 کانال‌ها", callback_data="a:ch"),
            ],
            [
                B("🏆 برترین‌ها", callback_data="a:top"),
                B("📈 نمودار ۷ روز", callback_data="a:chart"),
            ],
            [
                B("💾 بکاپ و خروجی", callback_data="a:backup"),
                B("📜 لاگ ادمین", callback_data="a:log:0"),
            ],
            [B("✖️ بستن پنل", callback_data="close")],
        ]
    )


def admin_back_kb(extra=None) -> M:
    rows = list(extra or [])
    rows.append([B("🔙 پنل ادمین", callback_data="a:home")])
    return M(rows)


def cfg_kb(vals: dict) -> M:
    def sw(v):
        return "🟢" if v else "🔴"

    return M(
        [
            [B(f"{sw(vals['force_join'])} جوین اجباری", callback_data="a:tg:force_join")],
            [B(f"{sw(vals['maintenance'])} حالت تعمیر (ربات بسته)", callback_data="a:tg:maintenance")],
            [B(f"{sw(vals['spy_mode'])} مانیتور زنده پیام‌ها", callback_data="a:tg:spy_mode")],
            [B(f"{sw(vals['report_notify'])} اعلان گزارش تخلف", callback_data="a:tg:report_notify")],
            [B(f"{sw(vals['new_user_alert'])} اعلان کاربر جدید", callback_data="a:tg:new_user_alert")],
            [B("📝 متن خوش‌آمد اضافه", callback_data="a:welcome")],
            [B("🔙 پنل ادمین", callback_data="a:home")],
        ]
    )


def users_page_kb(rows, page: int, total: int, per: int, only_banned=False) -> M:
    kb = []
    for r in rows:
        name = (r["first_name"] or "").strip() or str(r["user_id"])
        if len(name) > 18:
            name = name[:17] + "…"
        mark = "🚷 " if r["is_banned"] else ""
        kb.append([B(f"{mark}{name} • {r['user_id']}", callback_data=f"a:u:{r['user_id']}")])
    total_pages = max(1, (total + per - 1) // per)
    nav = []
    tag = "ub" if only_banned else "users"
    if page > 0:
        nav.append(B("◀️", callback_data=f"a:{tag}:{page-1}"))
    nav.append(B(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(B("▶️", callback_data=f"a:{tag}:{page+1}"))
    kb.append(nav)
    kb.append(
        [
            B("همه کاربران" if only_banned else "فقط بن‌شده‌ها",
              callback_data="a:users:0" if only_banned else "a:ub:0"),
        ]
    )
    kb.append([B("🔙 پنل ادمین", callback_data="a:home")])
    return M(kb)


def user_card_kb(u) -> M:
    uid = u["user_id"]
    banned = u["is_banned"] == 1
    return M(
        [
            [
                B("♻️ رفع بن" if banned else "🚷 بن کاربر", callback_data=f"a:ban:{uid}"),
                B("✉️ پیام مستقیم", callback_data=f"a:dm1:{uid}"),
            ],
            [
                B("📨 پیام‌های او", callback_data=f"a:umsg:{uid}"),
                B("🚫 بلاک‌های او", callback_data=f"a:ublk:{uid}"),
            ],
            [
                B("⚠️ اخطار +۱", callback_data=f"a:warn:{uid}"),
                B("🧹 صفر کردن اخطار", callback_data=f"a:warn0:{uid}"),
            ],
            [
                B("🔗 لینک او", callback_data=f"a:ulink:{uid}"),
                B("♻️ توکن جدید", callback_data=f"a:utok:{uid}"),
            ],
            [B("🗑 حذف کامل کاربر", callback_data=f"a:udel:{uid}")],
            [B("🔙 پنل ادمین", callback_data="a:home")],
        ]
    )


def report_kb(r) -> M:
    rid = r["id"]
    return M(
        [
            [
                B("🚷 بن متخلف", callback_data=f"a:rban:{rid}"),
                B("⚠️ اخطار", callback_data=f"a:rwarn:{rid}"),
            ],
            [
                B("✅ بررسی شد", callback_data=f"a:rdone:{rid}"),
                B("🗑 رد گزارش", callback_data=f"a:rrej:{rid}"),
            ],
            [
                B("👤 پرونده متخلف", callback_data=f"a:ruser:{rid}"),
                B("📄 متن پیام", callback_data=f"a:rmsg:{rid}"),
            ],
            [B("🔙 لیست گزارش‌ها", callback_data="a:reports:open:0")],
        ]
    )


def reports_list_kb(rows, status: str, page: int, total: int, per: int = 5) -> M:
    kb = []
    for r in rows:
        mark = {"open": "🟡", "done": "✅", "rejected": "🗑", "banned": "🚷"}.get(r["status"], "•")
        kb.append([B(f"{mark} گزارش #{r['id']}", callback_data=f"a:r:{r['id']}")])
    total_pages = max(1, (total + per - 1) // per)
    nav = []
    if page > 0:
        nav.append(B("◀️", callback_data=f"a:reports:{status}:{page-1}"))
    nav.append(B(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(B("▶️", callback_data=f"a:reports:{status}:{page+1}"))
    kb.append(nav)
    kb.append(
        [
            B("🟡 باز" if status != "open" else "• باز •", callback_data="a:reports:open:0"),
            B("✅ بسته" if status != "done" else "• بسته •", callback_data="a:reports:done:0"),
            B("🗂 همه" if status != "all" else "• همه •", callback_data="a:reports:all:0"),
        ]
    )
    kb.append([B("🔙 پنل ادمین", callback_data="a:home")])
    return M(kb)


def confirm_kb(yes_data: str, no_data: str = "a:home", yes_text: str = "✅ تأیید") -> M:
    return M([[B(yes_text, callback_data=yes_data)], [B("✖️ لغو", callback_data=no_data)]])


def reports_nav_kb(status: str, page: int, total: int, per: int = 5) -> M:
    total_pages = max(1, (total + per - 1) // per)
    nav = []
    if page > 0:
        nav.append(B("◀️", callback_data=f"a:reports:{status}:{page-1}"))
    nav.append(B(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(B("▶️", callback_data=f"a:reports:{status}:{page+1}"))
    tabs = [
        B("🟡 باز" if status != "open" else "• باز •", callback_data="a:reports:open:0"),
        B("✅ بسته" if status != "done" else "• بسته •", callback_data="a:reports:done:0"),
        B("🗂 همه" if status != "all" else "• همه •", callback_data="a:reports:all:0"),
    ]
    return M([nav, tabs, [B("🔙 پنل ادمین", callback_data="a:home")]])


def backup_kb() -> M:
    return M(
        [
            [B("🗄 فایل دیتابیس", callback_data="a:bk:db")],
            [B("📑 CSV کاربران", callback_data="a:bk:users")],
            [B("📑 CSV پیام‌ها", callback_data="a:bk:msgs")],
            [B("🧾 JSON کامل", callback_data="a:bk:json")],
            [B("🧹 پاکسازی و بهینه‌سازی DB", callback_data="a:bk:vac")],
            [B("🔙 پنل ادمین", callback_data="a:home")],
        ]
    )


def channels_kb(rows) -> M:
    kb = []
    for r in rows:
        title = r["title"] or r["username"] or str(r["chat_id"])
        kb.append([B(f"➖ حذف {title}", callback_data=f"a:chdel:{r['chat_id']}")])
    kb.append([B("➕ افزودن کانال", callback_data="a:chadd")])
    kb.append([B("🔙 پنل ادمین", callback_data="a:home")])
    return M(kb)


def bc_confirm_kb(mode: str) -> M:
    return M(
        [
            [B("🚀 ارسال کن", callback_data=f"a:bcgo:{mode}")],
            [B("✖️ لغو", callback_data="a:home")],
        ]
    )


def cancel_kb() -> M:
    return M([[B("✖️ لغو", callback_data="a:home")]])


def close_kb() -> M:
    return M([[B("✖️ بستن", callback_data="close")]])
