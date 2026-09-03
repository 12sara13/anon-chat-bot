"""منطق مشترک: نگهبان‌ها، بررسی عضویت، تحویل پیام ناشناس، اعلان ادمین."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from telegram import Message, ReplyParameters, Update
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import texts as T
from utils import esc, jdate, kind_label, short, user_line

log = logging.getLogger("anonbot")

_MEMBER_CACHE: dict[int, tuple[float, bool]] = {}
_FLOOD: dict[int, list[float]] = {}
_LAST_SEND: dict[int, float] = {}

OK_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}

BOT_USERNAME = ""


def is_admin(uid: Optional[int]) -> bool:
    return uid in config.ADMIN_IDS


async def run(fn, *a, **k):
    """اجرای تابع sync دیتابیس در thread جدا."""
    return await asyncio.to_thread(fn, *a, **k)


def bot_link(token: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={token}"


# ---------------- flood ----------------

def flood_hit(uid: int) -> bool:
    """True اگر کاربر باید محدود شود."""
    now = time.time()
    lst = [t for t in _FLOOD.get(uid, []) if now - t < config.FLOOD_WINDOW]
    lst.append(now)
    _FLOOD[uid] = lst
    if len(lst) > config.FLOOD_MAX:
        return True
    last = _LAST_SEND.get(uid, 0)
    if now - last < config.SEND_COOLDOWN:
        return True
    _LAST_SEND[uid] = now
    return False


# ---------------- membership ----------------

async def check_membership(context: ContextTypes.DEFAULT_TYPE, uid: int, force=False):
    """(ok, missing_rows)"""
    if not await run(db.flag, "force_join"):
        return True, []
    if is_admin(uid):
        return True, []
    chans = await run(db.get_channels)
    if not chans:
        return True, []
    ent = _MEMBER_CACHE.get(uid)
    if not force and ent and time.time() - ent[0] < config.MEMBERSHIP_CACHE_TTL and ent[1]:
        return True, []
    missing = []
    for ch in chans:
        try:
            m = await context.bot.get_chat_member(ch["chat_id"], uid)
            if m.status not in OK_STATUSES:
                missing.append(ch)
        except BadRequest as e:
            # ربات در کانال ادمین نیست یا کاربر یافت نشد
            if "user not found" in str(e).lower():
                missing.append(ch)
            else:
                log.warning("membership check failed for %s: %s", ch["chat_id"], e)
        except TelegramError as e:
            log.warning("membership error: %s", e)
    ok = not missing
    _MEMBER_CACHE[uid] = (time.time(), ok)
    return ok, missing


def clear_member_cache(uid: int) -> None:
    _MEMBER_CACHE.pop(uid, None)


async def show_force_join(update: Update, context, missing, payload: str = "") -> None:
    lines = []
    for ch in missing:
        title = ch["title"] or ch["username"] or "کانال"
        link = ch["link"] or (f"https://t.me/{ch['username']}" if ch["username"] else "")
        lines.append(f"📢 <a href=\"{link}\">{esc(title)}</a>")
    txt = T.FORCE_JOIN.format(chans="\n".join(lines) + "\n")
    chans = await run(db.get_channels)
    markup = kb.join_kb(missing or chans, BOT_USERNAME, payload)
    tgt = update.effective_message
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                txt, parse_mode=ParseMode.HTML, reply_markup=markup,
                disable_web_page_preview=True,
            )
            return
        except BadRequest:
            pass
    await tgt.reply_text(
        txt, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True
    )


# ---------------- guards ----------------

async def guard(update: Update, context) -> Optional[db.sqlite3.Row]:
    """بررسی تعمیر/بن/عضویت. رکورد کاربر یا None برمی‌گرداند."""
    user = update.effective_user
    if user is None:
        return None
    row = await run(
        db.upsert_user, user.id, user.first_name or "", user.last_name or "", user.username
    )
    if row["is_banned"]:
        reason = row["ban_reason"] or ""
        await _reply(update, T.BANNED.format(reason=f"\n<i>{esc(reason)}</i>" if reason else ""))
        return None
    if await run(db.flag, "maintenance") and not is_admin(user.id):
        await _reply(update, T.MAINTENANCE)
        return None
    ok, missing = await check_membership(context, user.id)
    if not ok:
        await show_force_join(update, context, missing)
        return None
    return row


async def _reply(update: Update, text: str, **kw) -> None:
    kw.setdefault("parse_mode", ParseMode.HTML)
    if update.callback_query:
        try:
            await update.callback_query.answer(text[:190].replace("<b>", "").replace("</b>", ""),
                                               show_alert=True)
            return
        except TelegramError:
            pass
    m = update.effective_message
    if m:
        try:
            await m.reply_text(text, **kw)
        except TelegramError as e:
            log.warning("reply failed: %s", e)


# ---------------- message kind ----------------

def msg_kind(m: Message) -> str:
    for k in (
        "text", "photo", "video", "voice", "audio", "sticker", "document",
        "animation", "video_note", "contact", "location", "poll", "dice",
        "venue", "game", "story",
    ):
        if getattr(m, k, None):
            return "text" if k == "text" else k
    return "other"


CAPTIONABLE = {"photo", "video", "audio", "document", "animation", "voice"}


def preview_of(m: Message) -> str:
    if m.text:
        return m.text
    if m.caption:
        return f"[{msg_kind(m)}] {m.caption}"
    return f"[{msg_kind(m)}]"


# ---------------- delivery ----------------

async def deliver_anon(
    context: ContextTypes.DEFAULT_TYPE,
    sender: db.sqlite3.Row,
    target: db.sqlite3.Row,
    m: Message,
    parent: Optional[db.sqlite3.Row] = None,
) -> Optional[int]:
    """ارسال پیام ناشناس. آیدی رکورد msgs یا None در صورت شکست."""
    receiver_id = target["user_id"]
    kind = msg_kind(m)
    is_reply = parent is not None

    header = T.REPLY_HEADER if is_reply else T.MSG_HEADER
    sub = f"\n🕓 <i>{jdate()}</i>"
    if is_reply and parent["preview"]:
        sub = f"\n💬 <i>در پاسخ به: «{esc(short(parent['preview'], 70))}»</i>" + sub
    head = header + sub

    # ادمین‌ها هویت فرستنده را می‌بینند (خواسته‌ی مالک ربات)
    if is_admin(receiver_id):
        head += (
            "\n━━━━━━━━━━━━━━\n"
            f"👤 <b>فرستنده:</b> {user_line(sender)}\n"
            f"📊 ارسال: {sender['sent_count']} • اخطار: {sender['warns']}"
        )

    seen_shown = bool(target["seen_notify"])
    mid = await run(
        db.add_msg, sender["user_id"], receiver_id, m.chat_id, m.message_id,
        None, kind, preview_of(m), parent["id"] if parent else None,
    )
    markup = kb.recv_kb(mid, seen_shown)

    # reply_parameters: پاسخ روی پیام اصلی خودِ گیرنده
    rp = None
    if is_reply and parent["src_msg_id"]:
        rp = ReplyParameters(
            message_id=parent["src_msg_id"], allow_sending_without_reply=True
        )

    dst_id = None
    hdr_id = None
    try:
        if kind == "text":
            body = m.text_html or esc(m.text or "")
            txt = f"{head}\n\n{body}"
            if len(txt) > 4090:
                txt = txt[:4080] + "…"
            sent = await context.bot.send_message(
                receiver_id, txt, parse_mode=ParseMode.HTML,
                reply_markup=markup, reply_parameters=rp,
                disable_web_page_preview=True,
            )
            dst_id = sent.message_id
        elif kind in CAPTIONABLE and len((m.caption or "")) < 800:
            cap_html = m.caption_html or ""
            cap = f"{head}\n\n{cap_html}" if cap_html else head
            res = await context.bot.copy_message(
                chat_id=receiver_id, from_chat_id=m.chat_id, message_id=m.message_id,
                caption=cap, parse_mode=ParseMode.HTML,
                reply_markup=markup, reply_parameters=rp,
            )
            dst_id = res.message_id
        else:
            # محتوا بدون کپشن (استیکر، ویدیومسیج، ...) → محتوا + کارت دکمه‌ها
            res = await context.bot.copy_message(
                chat_id=receiver_id, from_chat_id=m.chat_id, message_id=m.message_id,
                reply_parameters=rp,
            )
            dst_id = res.message_id
            card = await context.bot.send_message(
                receiver_id, f"{head}\n\n<i>{kind_label(kind)}</i>",
                parse_mode=ParseMode.HTML, reply_markup=markup,
                reply_parameters=ReplyParameters(
                    message_id=dst_id, allow_sending_without_reply=True
                ),
            )
            hdr_id = card.message_id
    except Forbidden:
        await run(db.ex, "DELETE FROM msgs WHERE id=?", (mid,))
        return None
    except BadRequest as e:
        log.warning("deliver BadRequest: %s", e)
        try:
            res = await context.bot.copy_message(
                chat_id=receiver_id, from_chat_id=m.chat_id, message_id=m.message_id,
                reply_markup=markup,
            )
            dst_id = res.message_id
        except TelegramError:
            await run(db.ex, "DELETE FROM msgs WHERE id=?", (mid,))
            return None

    await run(db.set_msg_dst, mid, dst_id, hdr_id)
    await run(db.bump, sender["user_id"], "sent_count")
    await run(db.bump, receiver_id, "recv_count")

    if await run(db.flag, "spy_mode"):
        context.application.create_task(
            spy_copy(context, sender, target, m, mid, is_reply)
        )
    return mid


async def spy_copy(context, sender, target, m: Message, mid: int, is_reply: bool):
    """کپی ترافیک برای ادمین‌ها (مانیتور زنده)."""
    info = (
        f"👁 <b>مانیتور زنده</b> {'(پاسخ ↪️)' if is_reply else ''}\n"
        f"از: {user_line(sender)}\n"
        f"به: {user_line(target)}\n"
        f"🆔 <code>#{mid}</code> • {kind_label(msg_kind(m))}"
    )
    for aid in config.ADMIN_IDS:
        try:
            await context.bot.send_message(aid, info, parse_mode=ParseMode.HTML,
                                          disable_web_page_preview=True)
            await context.bot.copy_message(aid, m.chat_id, m.message_id)
        except TelegramError:
            pass


async def notify_admins(context, text: str, markup=None, exclude: Optional[int] = None):
    for aid in config.ADMIN_IDS:
        if exclude is not None and aid == exclude:
            continue
        try:
            await context.bot.send_message(
                aid, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramError as e:
            log.info("admin notify failed %s: %s", aid, e)
