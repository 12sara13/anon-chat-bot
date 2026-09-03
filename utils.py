"""ابزارهای کمکی: تاریخ شمسی، اعداد فارسی، escape، فرمت نام."""
from __future__ import annotations

import html
import time
from typing import Optional

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_G_DAYS_IN_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
JMONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def fa_num(x) -> str:
    s = str(x)
    out = []
    for ch in s:
        out.append(FA_DIGITS[int(ch)] if ch.isdigit() else ch)
    return "".join(out)


def g2j(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        - 80
        + gd
        + _G_DAYS_IN_MONTH[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jdate(ts: Optional[int] = None, with_time: bool = True) -> str:
    """تاریخ شمسی به وقت تهران."""
    if ts is None:
        ts = int(time.time())
    lt = time.gmtime(ts + 12600)  # UTC+3:30
    jy, jm, jd = g2j(lt.tm_year, lt.tm_mon, lt.tm_mday)
    s = f"{fa_num(jd)} {JMONTHS[jm - 1]} {fa_num(jy)}"
    if with_time:
        s += f" — {fa_num(f'{lt.tm_hour:02d}')}:{fa_num(f'{lt.tm_min:02d}')}"
    return s


def ago(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    d = int(time.time()) - int(ts)
    if d < 60:
        return "همین حالا"
    if d < 3600:
        return f"{fa_num(d // 60)} دقیقه پیش"
    if d < 86400:
        return f"{fa_num(d // 3600)} ساعت پیش"
    if d < 30 * 86400:
        return f"{fa_num(d // 86400)} روز پیش"
    return jdate(ts, with_time=False)


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def full_name(row) -> str:
    """نام نمایشی از رکورد کاربر."""
    if row is None:
        return "ناشناس"
    try:
        fn = (row["first_name"] or "").strip()
        ln = (row["last_name"] or "").strip()
    except (KeyError, IndexError, TypeError):
        fn, ln = "", ""
    name = (fn + " " + ln).strip()
    if not name:
        try:
            name = row["nickname"] or ""
        except (KeyError, IndexError, TypeError):
            name = ""
    return name or "کاربر بی‌نام"


def uname(row) -> str:
    try:
        u = row["username"]
    except (KeyError, IndexError, TypeError):
        u = None
    return f"@{u}" if u else "—"


def user_line(row) -> str:
    """خط اطلاعات کاربر برای ادمین (HTML)."""
    if row is None:
        return "<i>کاربر ناشناس (حذف‌شده)</i>"
    uid = row["user_id"]
    name = esc(full_name(row))
    un = row["username"]
    parts = [f'<a href="tg://user?id={uid}">{name}</a>']
    if un:
        parts.append(f"@{esc(un)}")
    parts.append(f"<code>{uid}</code>")
    return " | ".join(parts)


def short(s: str, n: int = 60) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def bar(value: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = round(width * value / total)
    return "█" * filled + "░" * (width - filled)


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def kind_label(kind: str) -> str:
    return {
        "text": "متن 📝",
        "photo": "عکس 🖼",
        "video": "ویدیو 🎬",
        "voice": "ویس 🎤",
        "audio": "موزیک 🎵",
        "sticker": "استیکر 🩷",
        "document": "فایل 📎",
        "animation": "گیف 🌀",
        "video_note": "ویدیو‌مسیج ⭕️",
        "contact": "مخاطب 👤",
        "location": "موقعیت 📍",
        "poll": "نظرسنجی 📊",
        "dice": "دایس 🎲",
        "other": "پیام 💬",
    }.get(kind or "other", "پیام 💬")
