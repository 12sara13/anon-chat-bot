"""پنل ادمین — فقط برای config.ADMIN_IDS."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from telegram import (ForceReply, InlineKeyboardButton, InlineKeyboardMarkup,
                      Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
import core
import db
import keyboards as kb
from utils import (
    ago, bar, esc, fa_num, full_name, human_size, jdate, kind_label, short, user_line,
)

log = logging.getLogger("anonbot")

PER_USER = 8
PER_REPORT = 5
PER_MSG = 10
PER_LOG = 12

# ------------------------------------------------------------------ helpers
def _is_admin(update: Update) -> bool:
    u = update.effective_user
    return u is not None and core.is_admin(u.id)

async def _edit(qy, text: str, markup=None) -> None:
    """ویرایش پیام؛ اگر ممکن نبود پیام تازه بفرست."""
    try:
        await qy.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        try:
            await qy.message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramError:
            pass

def _ask(context, mode: str, **extra) -> None:
    """حالت انتظار ورودی ادمین را ست می‌کند.

    کلید «mode» مال خود روتر است؛ هیچ فراخوانی نباید mode=... پاس بدهد وگرنه با
    پارامتر تابع تصادم می‌کند. حالت‌های داخلی (مثل کپی/فوروارد در ارسال همگانی)
    اسم کلید جداگانه می‌گیرند.
    """
    d = {"mode": mode}
    d.update(extra)
    context.user_data["admin_await"] = d

def _home_text(st: dict) -> str:
    return (
        "🛠 <b>پنل مدیریت ربات ناشناس</b>\n"
        f"<i>{jdate()}</i>\n\n"
        f"👥 کاربران: <b>{fa_num(st['users'])}</b>  "
        f"(امروز +{fa_num(st['users_today'])})\n"
        f"🟢 فعال ۲۴ساعت: <b>{fa_num(st['active_today'])}</b>\n"
        f"📨 پیام‌ها: <b>{fa_num(st['msgs'])}</b>  "
        f"(امروز {fa_num(st['msgs_today'])})\n"
        f"⚠️ گزارش باز: <b>{fa_num(st['reports_open'])}</b>   "
        f"🚷 بن: <b>{fa_num(st['banned'])}</b>\n\n"
        "یکی از گزینه‌ها رو انتخاب کن 👇"
    )

# ------------------------------------------------------------------ entry
async def open_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه «🛠 پنل ادمین» یا /admin"""
    if not _is_admin(update):
        return
    context.user_data.pop("admin_await", None)
    context.user_data.pop("bc", None)
    st = await core.run(db.stats)
    await update.effective_message.reply_text(
        _home_text(st), parse_mode=ParseMode.HTML, reply_markup=kb.admin_kb()
    )

# ------------------------------------------------------------------ views
async def _view_stats(qy) -> None:
    st = await core.run(db.stats)
    size = await core.run(db.db_size)
    seen_pct = round(100 * st["seen"] / st["msgs"]) if st["msgs"] else 0
    txt = (
        "📊 <b>آمار کامل</b>\n\n"
        "<b>کاربران</b>\n"
        f"• کل: <b>{fa_num(st['users'])}</b>\n"
        f"• امروز: {fa_num(st['users_today'])} | این هفته: {fa_num(st['users_week'])}\n"
        f"• فعال ۲۴ساعت: {fa_num(st['active_today'])}\n"
        f"• بن‌شده: {fa_num(st['banned'])} | لینک خاموش: {fa_num(st['with_link_off'])}\n\n"
        "<b>پیام‌ها</b>\n"
        f"• کل: <b>{fa_num(st['msgs'])}</b>\n"
        f"• امروز: {fa_num(st['msgs_today'])} | این هفته: {fa_num(st['msgs_week'])}\n"
        f"• دیده‌شده: {fa_num(st['seen'])} ({fa_num(seen_pct)}٪)\n\n"
        "<b>ناظم</b>\n"
        f"• بلاک‌ها: {fa_num(st['blocks'])}\n"
        f"• گزارش باز: {fa_num(st['reports_open'])} از {fa_num(st['reports_all'])}\n\n"
        f"🗄 حجم دیتابیس: <b>{human_size(size)}</b>"
    )
    await _edit(qy, txt, kb.admin_back_kb())

async def _view_top(qy) -> None:
    recv = await core.run(db.top_receivers, 10)
    send = await core.run(db.top_senders, 10)
    lines = ["🏆 <b>برترین‌ها</b>\n", "<b>📥 بیشترین دریافت</b>"]
    if not recv:
        lines.append("<i>—</i>")
    for i, r in enumerate(recv, 1):
        nm = esc((r["first_name"] or "").strip() or str(r["user_id"]))
        lines.append(f"{fa_num(i)}. {nm} — <b>{fa_num(r['recv_count'])}</b>")
    lines.append("\n<b>📤 بیشترین ارسال</b>")
    if not send:
        lines.append("<i>—</i>")
    for i, r in enumerate(send, 1):
        nm = esc((r["first_name"] or "").strip() or str(r["user_id"]))
        lines.append(f"{fa_num(i)}. {nm} — <b>{fa_num(r['sent_count'])}</b>")
    await _edit(qy, "\n".join(lines), kb.admin_back_kb())

async def _view_chart(qy) -> None:
    series = await core.run(db.daily_series, 7)
    mx = max([c for _, c in series] + [1])
    lines = ["📈 <b>پیام‌های ۷ روز گذشته</b>\n"]
    n = len(series)
    for idx, (_, c) in enumerate(series):
        days_ago = n - 1 - idx
        lab = {0: "امروز", 1: "دیروز", 2: "پریروز"}.get(
            days_ago, f"{fa_num(days_ago)} روز پیش")
        lines.append(f"<code>{bar(c, mx, 12)}</code> {fa_num(c):>4}  {lab}")
    total = sum(c for _, c in series)
    lines.append(f"\nجمع هفته: <b>{fa_num(total)}</b> | اوج روز: <b>{fa_num(mx)}</b>")
    await _edit(qy, "\n".join(lines), kb.admin_back_kb())

async def _view_users(qy, page: int, only_banned: bool) -> None:
    total = await core.run(db.users_count, only_banned)
    page = max(0, page)
    rows = await core.run(db.users_page, PER_USER, page * PER_USER, only_banned)
    head = "🚷 <b>کاربران بن‌شده</b>" if only_banned else "👥 <b>کاربران</b>"
    lines = [f"{head} — {fa_num(total)} نفر\n"]
    if not rows:
        lines.append("<i>موردی نیست.</i>")
    for r in rows:
        lines.append(
            f"• {user_line(r)}\n"
            f"  📤{fa_num(r['sent_count'])} 📥{fa_num(r['recv_count'])} "
            f"⚠️{fa_num(r['warns'])} — <i>{ago(r['last_seen'])}</i>"
        )
    await _edit(
        qy, "\n".join(lines),
        kb.users_page_kb(rows, page, total, PER_USER, only_banned),
    )

async def _user_card(qy, uid: int) -> None:
    u = await core.run(db.get_user, uid)
    if u is None:
        await qy.answer("کاربر پیدا نشد.", show_alert=True)
        return
    blocks = await core.run(db.block_count, uid)
    blocked_by = await core.run(db.blocked_by_count, uid)
    reports = await core.run(db.reports_about, uid)
    seen = await core.run(db.seen_count_of_sender, uid)
    txt = (
        "👤 <b>پرونده کاربر</b>\n\n"
        f"{user_line(u)}\n"
        f"🎫 توکن: <code>{esc(u['token'])}</code>\n"
        f"🏷 نام نمایشی: {esc(u['nickname'] or '—')}\n\n"
        f"📤 ارسال: <b>{fa_num(u['sent_count'])}</b> "
        f"(دیده‌شده {fa_num(seen)})\n"
        f"📥 دریافت: <b>{fa_num(u['recv_count'])}</b>\n"
        f"🚫 بلاک کرده: {fa_num(blocks)} | بلاک شده توسط: {fa_num(blocked_by)}\n"
        f"⚠️ اخطار: <b>{fa_num(u['warns'])}</b> | گزارش علیه او: {fa_num(reports)}\n"
        f"🔗 لینک: {'فعال 🟢' if u['link_active'] else 'خاموش 🔴'} | "
        f"👀 تیک دیدم: {'روشن' if u['seen_notify'] else 'خاموش'}\n"
        f"🚷 وضعیت: <b>{'بن شده' if u['is_banned'] else 'سالم'}</b>"
    )
    if u["is_banned"] and u["ban_reason"]:
        txt += f"\n📝 دلیل بن: <i>{esc(u['ban_reason'])}</i>"
    txt += (
        f"\n\n📅 عضویت: {jdate(u['created_at'], False)}\n"
        f"🕓 آخرین فعالیت: {ago(u['last_seen'])}"
    )
    await _edit(qy, txt, kb.user_card_kb(u))

async def _view_user_msgs(qy, uid: int) -> None:
    rows = await core.run(db.user_msgs, uid, 12)
    lines = [f"📨 <b>آخرین پیام‌های</b> <code>{uid}</code>\n"]
    if not rows:
        lines.append("<i>پیامی نیست.</i>")
    for r in rows:
        arrow = "📤 به" if r["sender_id"] == uid else "📥 از"
        other = r["receiver_id"] if r["sender_id"] == uid else r["sender_id"]
        tick = "👀" if r["seen_at"] else "•"
        lines.append(
            f"{tick} <code>#{r['id']}</code> {arrow} <code>{other}</code> "
            f"— {kind_label(r['kind'])}\n"
            f"  <i>{esc(short(r['preview'], 70))}</i> — {ago(r['created_at'])}"
        )
    await _edit(qy, "\n".join(lines), kb.admin_back_kb(
        [[kb.B("🔙 پرونده کاربر", callback_data=f"a:u:{uid}")]]
    ))

async def _view_user_blocks(qy, uid: int) -> None:
    rows = await core.run(db.user_blocks_of, uid)
    lines = [f"🚫 <b>بلاک‌های</b> <code>{uid}</code> — {fa_num(len(rows))}\n"]
    if not rows:
        lines.append("<i>خالی.</i>")
    for r in rows:
        nm = esc((r["first_name"] or "").strip() or str(r["blocked_id"]))
        un = f" @{esc(r['username'])}" if r["username"] else ""
        lines.append(f"• {nm}{un} <code>{r['blocked_id']}</code> — {ago(r['created_at'])}")
    await _edit(qy, "\n".join(lines), kb.admin_back_kb(
        [[kb.B("🔙 پرونده کاربر", callback_data=f"a:u:{uid}")]]
    ))

async def _view_msgs(qy, page: int) -> None:
    total = await core.run(db.msgs_count)
    page = max(0, page)
    rows = await core.run(db.recent_msgs, PER_MSG, page * PER_MSG)
    lines = [f"📨 <b>پیام‌های اخیر</b> — {fa_num(total)}\n"]
    if not rows:
        lines.append("<i>پیامی نیست.</i>")
    for r in rows:
        tick = "👀" if r["seen_at"] else ("🗑" if r["deleted"] else "•")
        rep = "↪️" if r["parent_id"] else ""
        lines.append(
            f"{tick} <code>#{r['id']}</code> {rep} "
            f"<code>{r['sender_id']}</code> → <code>{r['receiver_id']}</code> "
            f"{kind_label(r['kind'])}\n"
            f"  <i>{esc(short(r['preview'], 70))}</i> — {ago(r['created_at'])}"
        )
    total_pages = max(1, (total + PER_MSG - 1) // PER_MSG)
    nav = []
    if page > 0:
        nav.append(kb.B("◀️", callback_data=f"a:msgs:{page-1}"))
    nav.append(kb.B(f"{page+1}/{total_pages}", callback_data="a:noop"))
    if page < total_pages - 1:
        nav.append(kb.B("▶️", callback_data=f"a:msgs:{page+1}"))
    await _edit(qy, "\n".join(lines), kb.admin_back_kb([nav]))

async def _view_reports(qy, status: str, page: int) -> None:
    flt = None if status == "all" else status
    total = await core.run(db.reports_count, flt)
    page = max(0, page)
    rows = await core.run(db.reports_page, flt, PER_REPORT, page * PER_REPORT)
    title = {"open": "🟡 باز", "done": "✅ بسته", "all": "🗂 همه"}.get(status, status)
    lines = [f"⚠️ <b>گزارش‌های تخلف</b> — {title} ({fa_num(total)})\n"]
    if not rows:
        lines.append("<i>گزارشی نیست.</i>")
    for r in rows:
        lines.append(
            f"<code>#{r['id']}</code> علیه <code>{r['target_id']}</code> "
            f"— گزارش‌دهنده <code>{r['reporter_id']}</code>\n"
            f"  وضعیت: <b>{esc(r['status'])}</b> — {ago(r['created_at'])}"
        )
    await _edit(qy, "\n".join(lines),
                kb.reports_list_kb(rows, status, page, total, PER_REPORT))

async def _report_card(qy, rid: int) -> None:
    r = await core.run(db.get_report, rid)
    if r is None:
        await qy.answer("گزارش پیدا نشد.", show_alert=True)
        return
    target = await core.run(db.get_user, r["target_id"])
    reporter = await core.run(db.get_user, r["reporter_id"])
    msg = await core.run(db.get_msg, r["msg_ref"])
    txt = (
        f"⚠️ <b>گزارش</b> <code>#{r['id']}</code>\n"
        f"وضعیت: <b>{esc(r['status'])}</b> — {jdate(r['created_at'])}\n\n"
        f"🚨 <b>متخلف:</b>\n{user_line(target)}\n"
        f"⚠️ اخطار: {fa_num(target['warns'] if target else 0)} | "
        f"📤 ارسال: {fa_num(target['sent_count'] if target else 0)}\n\n"
        f"🙋 <b>گزارش‌دهنده:</b>\n{user_line(reporter)}\n"
    )
    if msg:
        txt += (
            f"\n📝 <b>پیام</b> <code>#{msg['id']}</code> — {kind_label(msg['kind'])}\n"
            f"<blockquote>{esc(short(msg['preview'], 300))}</blockquote>"
        )
    else:
        txt += "\n<i>پیام حذف شده است.</i>"
    if r["handled_by"]:
        txt += (
            f"\n\n👮 رسیدگی: <code>{r['handled_by']}</code> — "
            f"{jdate(r['handled_at'])}"
        )
    await _edit(qy, txt, kb.report_kb(r))

async def _view_cfg(qy) -> None:
    keys = ["force_join", "maintenance", "spy_mode", "report_notify", "new_user_alert"]
    vals = {}
    for k in keys:
        vals[k] = await core.run(db.flag, k)
    extra = await core.run(db.get_setting, "welcome_extra")
    txt = (
        "🔒 <b>قفل‌ها و تنظیمات</b>\n\n"
        "• <b>جوین اجباری</b>: بدون عضویت در کانال، ربات کار نمی‌کند.\n"
        "• <b>حالت تعمیر</b>: ربات برای همه بسته می‌شود (جز ادمین‌ها).\n"
        "• <b>مانیتور زنده</b>: کپی همه پیام‌های ناشناس برای ادمین‌ها.\n"
        "• <b>اعلان گزارش</b>: گزارش تخلف فوری به ادمین‌ها.\n"
        "• <b>اعلان کاربر جدید</b>: خبر ثبت‌نام هر کاربر تازه.\n\n"
        f"📝 متن خوش‌آمد اضافه: "
        f"{'<i>' + esc(short(extra, 80)) + '</i>' if extra else '—'}"
    )
    await _edit(qy, txt, kb.cfg_kb(vals))

async def _view_channels(qy) -> None:
    rows = await core.run(db.get_channels)
    lines = ["📡 <b>کانال‌های جوین اجباری</b>\n"]
    if not rows:
        lines.append("<i>کانالی ثبت نشده — جوین اجباری عملاً خاموش است.</i>")
    for r in rows:
        lines.append(
            f"• <b>{esc(r['title'] or r['username'] or r['chat_id'])}</b>\n"
            f"  <code>{r['chat_id']}</code> — {esc(r['link'] or '—')}"
        )
    lines.append(
        "\n⚠️ ربات باید در هر کانال <b>ادمین</b> باشد وگرنه بررسی عضویت کار نمی‌کند."
    )
    await _edit(qy, "\n".join(lines), kb.channels_kb(rows))

async def _view_log(qy, page: int) -> None:
    total = await core.run(db.admin_log_count)
    page = max(0, page)
    rows = await core.run(db.admin_logs, PER_LOG, page * PER_LOG)
    lines = [f"📜 <b>لاگ عملیات ادمین</b> — {fa_num(total)}\n"]
    if not rows:
        lines.append("<i>خالی.</i>")
    for r in rows:
        lines.append(
            f"• <code>{r['admin_id']}</code> — <b>{esc(r['action'])}</b> "
            f"{esc(r['target'])}\n  <i>{esc(short(r['detail'], 60))}</i> "
            f"— {ago(r['created_at'])}"
        )
    total_pages = max(1, (total + PER_LOG - 1) // PER_LOG)
    nav = []
    if page > 0:
        nav.append(kb.B("◀️", callback_data=f"a:log:{page-1}"))
    nav.append(kb.B(f"{page+1}/{total_pages}", callback_data="a:noop"))
    if page < total_pages - 1:
        nav.append(kb.B("▶️", callback_data=f"a:log:{page+1}"))
    await _edit(qy, "\n".join(lines), kb.admin_back_kb([nav]))

# ------------------------------------------------------------------ backup
async def _do_backup(qy, context, what: str, admin_id: int) -> None:
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    chat = qy.message.chat_id
    try:
        if what == "db":
            path = os.path.join(config.EXPORT_DIR, f"anonbot-{stamp}.db")
            await core.run(db.backup_to, path)
            cap = "🗄 بکاپ کامل دیتابیس"
        elif what == "users":
            path = os.path.join(config.EXPORT_DIR, f"users-{stamp}.csv")
            await core.run(db.export_users_csv, path)
            cap = "📑 خروجی CSV کاربران"
        elif what == "msgs":
            path = os.path.join(config.EXPORT_DIR, f"msgs-{stamp}.csv")
            await core.run(db.export_msgs_csv, path)
            cap = "📑 خروجی CSV پیام‌ها (۵۰۰۰ آخر)"
        elif what == "json":
            path = os.path.join(config.EXPORT_DIR, f"dump-{stamp}.json")
            await core.run(db.dump_json, path)
            cap = "🧾 دامپ JSON کامل"
        elif what == "vac":
            before = await core.run(db.db_size)
            await core.run(db.clean_prompts, 7)
            await core.run(db.vacuum)
            after = await core.run(db.db_size)
            await qy.answer("انجام شد ✅")
            await core.run(db.log_action, admin_id, "vacuum", "",
                           f"{before}->{after}")
            await _edit(
                qy,
                "🧹 <b>پاکسازی انجام شد</b>\n\n"
                f"حجم قبل: {human_size(before)}\n"
                f"حجم بعد: {human_size(after)}",
                kb.backup_kb(),
            )
            return
        else:
            await qy.answer("نامشخص", show_alert=True)
            return

        await qy.answer("در حال ارسال فایل…")
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat, document=f, filename=os.path.basename(path),
                caption=f"{cap}\n🕓 {jdate()}",
            )
        await core.run(db.log_action, admin_id, "backup", what, path)
    except TelegramError as e:
        log.warning("backup send failed: %s", e)
        await qy.answer("ارسال فایل ممکن نشد.", show_alert=True)

# ------------------------------------------------------------------ broadcast
def _stop_kb() -> InlineKeyboardMarkup:
    """کیبورد دکمه توقف برای پیام وضعیت ارسال همگانی."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⛔️ توقف", callback_data="a:bcstop")]]
    )

async def _run_broadcast(context, admin_id: int, src_chat: int, src_msg: int,
                         mode: str, status) -> None:
    """ارسال همگانی در تسک پس‌زمینه؛ با پرچم bot_data['bc_stop'] قابل توقف است."""
    try:
        context.bot_data["bc_stop"] = False
        ids = await core.run(db.all_user_ids)
        ok = fail = 0
        total = len(ids)
        stopped = False
        for i, uid in enumerate(ids, 1):
            if context.bot_data.get("bc_stop"):
                stopped = True
                break
            try:
                if mode == "fwd":
                    await context.bot.forward_message(uid, src_chat, src_msg)
                else:
                    await context.bot.copy_message(uid, src_chat, src_msg)
                ok += 1
            except TelegramError:
                fail += 1
            await asyncio.sleep(config.BROADCAST_SLEEP)
            if i % 25 == 0:
                try:
                    await status.edit_text(
                        f"📢 <b>در حال ارسال…</b>\n\n"
                        f"<code>{bar(i, total, 14)}</code> {fa_num(i)}/{fa_num(total)}\n"
                        f"✅ {fa_num(ok)} | ❌ {fa_num(fail)}",
                        parse_mode=ParseMode.HTML, reply_markup=_stop_kb(),
                    )
                except TelegramError:
                    pass
        head = ("📢 <b>ارسال همگانی متوقف شد</b>" if stopped
                else "📢 <b>ارسال همگانی تمام شد</b>")
        try:
            await status.edit_text(
                f"{head}\n\n"
                f"👥 کل: <b>{fa_num(total)}</b>\n"
                f"✅ موفق: <b>{fa_num(ok)}</b>\n"
                f"❌ ناموفق (بلاک/حذف): <b>{fa_num(fail)}</b>",
                parse_mode=ParseMode.HTML, reply_markup=kb.admin_back_kb(),
            )
        except TelegramError:
            pass
        detail = f"ok={ok} fail={fail} total={total}"
        if stopped:
            detail += " stopped"
        await core.run(db.log_action, admin_id, "broadcast", mode, detail)
    except Exception:
        # تسک پس‌زمینه است؛ اگر استثنا بی‌صدا بماند هیچ‌کس متوجه نمی‌شود.
        log.exception("broadcast task crashed")
        try:
            await status.edit_text(
                "❌ <b>ارسال همگانی با خطا متوقف شد.</b>\nجزئیات در لاگ ربات.",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

# ------------------------------------------------------------------ callbacks
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    qy = update.callback_query
    if not _is_admin(update):
        await qy.answer("⛔️ دسترسی نداری.", show_alert=True)
        return

    admin_id = update.effective_user.id
    p = qy.data.split(":")
    cmd = p[1] if len(p) > 1 else "home"
    a1 = p[2] if len(p) > 2 else ""
    a2 = p[3] if len(p) > 3 else ""

    def i1(default=0) -> int:
        try:
            return int(a1)
        except (TypeError, ValueError):
            return default

    def i2(default=0) -> int:
        try:
            return int(a2)
        except (TypeError, ValueError):
            return default

    # ---- ناوبری اصلی
    if cmd == "home":
        context.user_data.pop("admin_await", None)
        context.user_data.pop("bc", None)
        await qy.answer()
        st = await core.run(db.stats)
        await _edit(qy, _home_text(st), kb.admin_kb())

    elif cmd == "stats":
        await qy.answer()
        await _view_stats(qy)

    elif cmd == "top":
        await qy.answer()
        await _view_top(qy)

    elif cmd == "chart":
        await qy.answer()
        await _view_chart(qy)

    elif cmd == "users":
        await qy.answer()
        await _view_users(qy, i1(), only_banned=False)

    elif cmd == "ub":
        await qy.answer()
        await _view_users(qy, i1(), only_banned=True)

    elif cmd == "u":
        await qy.answer()
        await _user_card(qy, i1())

    elif cmd == "umsg":
        await qy.answer()
        await _view_user_msgs(qy, i1())

    elif cmd == "ublk":
        await qy.answer()
        await _view_user_blocks(qy, i1())

    elif cmd == "msgs":
        await qy.answer()
        await _view_msgs(qy, i1())

    elif cmd == "reports":
        await qy.answer()
        await _view_reports(qy, a1 or "open", i2())

    elif cmd == "r":
        await qy.answer()
        await _report_card(qy, i1())

    elif cmd == "cfg":
        await qy.answer()
        await _view_cfg(qy)

    elif cmd == "ch":
        await qy.answer()
        await _view_channels(qy)

    elif cmd == "log":
        await qy.answer()
        await _view_log(qy, i1())

    elif cmd == "backup":
        await qy.answer()
        await _edit(
            qy,
            "💾 <b>بکاپ و خروجی</b>\n\n"
            "فایل انتخابی به‌صورت داکیومنت همین‌جا ارسال می‌شود.\n"
            "«پاکسازی» پرامپت‌های قدیمی را حذف و دیتابیس را VACUUM می‌کند.",
            kb.backup_kb(),
        )

    elif cmd == "bk":
        await _do_backup(qy, context, a1, admin_id)

    # ---- سوییچ تنظیمات
    elif cmd == "tg":
        if a1 not in {"force_join", "maintenance", "spy_mode",
                      "report_notify", "new_user_alert"}:
            await qy.answer("نامشخص", show_alert=True)
            return
        new = await core.run(db.toggle, a1)
        await core.run(db.log_action, admin_id, "toggle", a1, str(new))
        await qy.answer(("روشن شد 🟢" if new else "خاموش شد 🔴"))
        await _view_cfg(qy)

    # ---- عملیات روی کاربر
    elif cmd == "ban":
        uid = i1()
        u = await core.run(db.get_user, uid)
        if u is None:
            await qy.answer("کاربر پیدا نشد.", show_alert=True)
            return
        if u["is_banned"]:
            await core.run(db.set_user_field, uid, "is_banned", 0)
            await core.run(db.set_user_field, uid, "ban_reason", None)
            await core.run(db.log_action, admin_id, "unban", uid)
            await qy.answer("بن برداشته شد ♻️")
            try:
                await context.bot.send_message(
                    uid, "♻️ <b>محدودیت حساب تو برداشته شد.</b>\n"
                         "می‌تونی دوباره از ربات استفاده کنی. /start",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            await _user_card(qy, uid)
        else:
            _ask(context, "ban", uid=uid)
            await qy.answer()
            await context.bot.send_message(
                qy.message.chat_id,
                f"📝 دلیل بن کاربر <code>{uid}</code> را بفرست\n"
                "(برای بن بدون دلیل، یک خط تیره «-» بفرست):",
                parse_mode=ParseMode.HTML,
                reply_markup=ForceReply(input_field_placeholder="دلیل بن"),
            )

    elif cmd == "warn":
        uid = i1()
        u = await core.run(db.get_user, uid)
        if u is None:
            await qy.answer("کاربر پیدا نشد.", show_alert=True)
            return
        await core.run(db.bump, uid, "warns")
        u = await core.run(db.get_user, uid)
        await core.run(db.log_action, admin_id, "warn", uid, str(u["warns"]))
        await qy.answer(f"اخطار ثبت شد ({u['warns']}) ⚠️")
        try:
            await context.bot.send_message(
                uid,
                "⚠️ <b>اخطار از طرف مدیریت</b>\n\n"
                f"تعداد اخطارهای تو: <b>{fa_num(u['warns'])}</b>\n"
                "با تکرار تخلف، دسترسی‌ت به ربات قطع می‌شه. /rules",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        await _user_card(qy, uid)

    elif cmd == "warn0":
        uid = i1()
        await core.run(db.set_user_field, uid, "warns", 0)
        await core.run(db.log_action, admin_id, "warn_reset", uid)
        await qy.answer("اخطارها صفر شد 🧹")
        await _user_card(qy, uid)

    elif cmd == "ulink":
        uid = i1()
        u = await core.run(db.get_user, uid)
        if u is None:
            await qy.answer("کاربر پیدا نشد.", show_alert=True)
            return
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            f"🔗 لینک ناشناس <code>{uid}</code>:\n"
            f"<code>{core.bot_link(u['token'])}</code>",
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )

    elif cmd == "utok":
        uid = i1()
        tok = await core.run(db.reset_token, uid)
        await core.run(db.log_action, admin_id, "reset_token", uid)
        await qy.answer("توکن جدید ساخته شد ♻️")
        await context.bot.send_message(
            qy.message.chat_id,
            f"♻️ توکن جدید <code>{uid}</code>:\n"
            f"<code>{core.bot_link(tok)}</code>",
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
        await _user_card(qy, uid)

    elif cmd == "udel":
        uid = i1()
        await qy.answer()
        await _edit(
            qy,
            f"🗑 <b>حذف کامل کاربر</b> <code>{uid}</code>\n\n"
            "رکورد کاربر، بلاک‌ها و پرامپت‌هایش پاک می‌شود. "
            "این عمل <b>برگشت‌ناپذیر</b> است.",
            kb.confirm_kb(f"a:udel2:{uid}", f"a:u:{uid}", "🗑 بله، حذف کن"),
        )

    elif cmd == "udel2":
        uid = i1()
        await core.run(db.delete_user, uid)
        await core.run(db.log_action, admin_id, "delete_user", uid)
        await qy.answer("حذف شد 🗑", show_alert=True)
        await _view_users(qy, 0, only_banned=False)

    elif cmd == "dm1":
        uid = i1()
        _ask(context, "dm_text", uid=uid)
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            f"✉️ پیامت برای <code>{uid}</code> را بفرست (هر نوع محتوایی):",
            parse_mode=ParseMode.HTML,
            reply_markup=ForceReply(input_field_placeholder="پیام مدیریت"),
        )

    # ---- عملیات روی گزارش
    elif cmd in {"rban", "rwarn", "rdone", "rrej", "ruser", "rmsg"}:
        rid = i1()
        r = await core.run(db.get_report, rid)
        if r is None:
            await qy.answer("گزارش پیدا نشد.", show_alert=True)
            return
        tid = r["target_id"]

        if cmd == "ruser":
            await qy.answer()
            await _user_card(qy, tid)
            return

        if cmd == "rmsg":
            msg = await core.run(db.get_msg, r["msg_ref"])
            if msg is None:
                await qy.answer("پیام حذف شده.", show_alert=True)
                return
            await qy.answer()
            try:
                await context.bot.copy_message(
                    qy.message.chat_id, msg["src_chat_id"], msg["src_msg_id"]
                )
            except TelegramError:
                await context.bot.send_message(
                    qy.message.chat_id,
                    f"📄 <b>محتوای پیام</b> <code>#{msg['id']}</code>\n"
                    f"<blockquote>{esc(msg['preview'])}</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            return

        if cmd == "rban":
            await core.run(db.set_user_field, tid, "is_banned", 1)
            await core.run(db.set_user_field, tid, "ban_reason",
                           f"تخلف — گزارش #{rid}")
            await core.run(db.set_report_status, rid, "banned", admin_id, "بن شد")
            await core.run(db.log_action, admin_id, "ban_by_report", tid, f"#{rid}")
            await qy.answer("متخلف بن شد 🚷", show_alert=True)
            try:
                await context.bot.send_message(
                    tid,
                    "🚷 <b>دسترسی تو به ربات قطع شد.</b>\n"
                    "<i>دلیل: گزارش تخلف تأییدشده</i>",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        elif cmd == "rwarn":
            await core.run(db.bump, tid, "warns")
            await core.run(db.set_report_status, rid, "done", admin_id, "اخطار")
            await core.run(db.log_action, admin_id, "warn_by_report", tid, f"#{rid}")
            await qy.answer("اخطار داده شد ⚠️")
            try:
                await context.bot.send_message(
                    tid,
                    "⚠️ <b>اخطار</b>\n\nیکی از پیام‌های ناشناست گزارش شد و "
                    "توسط مدیریت تخلف تشخیص داده شد. تکرار = بن دائمی. /rules",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        elif cmd == "rdone":
            await core.run(db.set_report_status, rid, "done", admin_id, "بررسی شد")
            await core.run(db.log_action, admin_id, "report_done", rid)
            await qy.answer("بسته شد ✅")
        elif cmd == "rrej":
            await core.run(db.set_report_status, rid, "rejected", admin_id, "رد شد")
            await core.run(db.log_action, admin_id, "report_reject", rid)
            await qy.answer("رد شد 🗑")

        # به گزارش‌دهنده خبر بده
        if cmd in {"rban", "rwarn"}:
            try:
                await context.bot.send_message(
                    r["reporter_id"],
                    "✅ <b>گزارش تو بررسی شد</b>\n"
                    "ممنون که به سالم‌نگه‌داشتن ربات کمک کردی 🌹",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        await _report_card(qy, rid)

    # ---- کانال‌ها
    elif cmd == "chadd":
        _ask(context, "chadd")
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            "📡 <b>افزودن کانال جوین اجباری</b>\n\n"
            "یکی از این‌ها را بفرست:\n"
            "• یوزرنیم کانال مثل <code>@mychannel</code>\n"
            "• آیدی عددی مثل <code>-1001234567890</code>\n"
            "• یا یک پیام از کانال را <b>فوروارد</b> کن\n\n"
            "⚠️ ربات باید از قبل در آن کانال ادمین باشد.",
            parse_mode=ParseMode.HTML, reply_markup=kb.cancel_kb(),
        )

    elif cmd == "chdel":
        try:
            cid = int(a1)
        except ValueError:
            await qy.answer("نامشخص", show_alert=True)
            return
        await core.run(db.remove_channel, cid)
        await core.run(db.log_action, admin_id, "channel_remove", cid)
        await qy.answer("کانال حذف شد ➖")
        await _view_channels(qy)

    # ---- ورودی‌های متنی
    elif cmd == "find":
        _ask(context, "find")
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            "🔍 آیدی عددی، یوزرنیم (با یا بدون @) یا توکن لینک را بفرست:",
            reply_markup=ForceReply(input_field_placeholder="جستجوی کاربر"),
        )

    elif cmd == "dm":
        _ask(context, "dm_target")
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            "✉️ اول آیدی عددی یا یوزرنیم مقصد را بفرست:",
            reply_markup=ForceReply(input_field_placeholder="مقصد"),
        )

    elif cmd == "welcome":
        _ask(context, "welcome")
        await qy.answer()
        await context.bot.send_message(
            qy.message.chat_id,
            "📝 متن خوش‌آمد اضافه را بفرست (HTML مجاز است).\n"
            "برای حذف، یک خط تیره «-» بفرست:",
            reply_markup=ForceReply(input_field_placeholder="متن خوش‌آمد"),
        )

    elif cmd in {"bc", "fwd"}:
        # bcmode و نه mode: کلید mode مال روتر on_text است و اگر بازنویسی شود،
        # حالت انتظار از «bc» به «copy» تغییر می‌کرد و ارسال همگانی بی‌صدا می‌افتاد.
        _ask(context, "bc", bcmode=("copy" if cmd == "bc" else "fwd"))
        await qy.answer()
        total = len(await core.run(db.all_user_ids))
        label = "کپی بی‌نام (بدون برچسب فرواردشده)" if cmd == "bc" else "فوروارد با منبع"
        await context.bot.send_message(
            qy.message.chat_id,
            f"📢 <b>ارسال همگانی</b> — حالت: <b>{label}</b>\n\n"
            f"پیام مورد نظر را بفرست. به <b>{fa_num(total)}</b> کاربر ارسال می‌شود.",
            parse_mode=ParseMode.HTML, reply_markup=kb.cancel_kb(),
        )

    elif cmd == "bcgo":
        bc = context.user_data.get("bc")
        if not bc:
            await qy.answer("پیامی برای ارسال نیست.", show_alert=True)
            return
        context.user_data.pop("bc", None)
        await qy.answer("شروع شد 🚀")
        status = qy.message
        try:
            await status.edit_text("📢 <b>در حال آماده‌سازی…</b>",
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=_stop_kb())
        except TelegramError:
            pass
        context.application.create_task(
            _run_broadcast(context, admin_id, bc["chat_id"], bc["msg_id"],
                           a1 or bc["mode"], status)
        )

    elif cmd == "bcstop":
        # دکمه «⛔️ توقف» روی پیام وضعیت ارسال همگانی
        context.bot_data["bc_stop"] = True
        await qy.answer("در حال توقف ارسال…")

    elif cmd == "noop":
        # دکمه‌های نمایشی (مثل شماره صفحه) — فقط باید answer شوند
        await qy.answer()

    else:
        await qy.answer("این گزینه شناخته نشد.", show_alert=True)

# ------------------------------------------------------------------ text input
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """روتر ورودی‌های ادمین — در group=-1 ثبت می‌شود."""
    if not _is_admin(update):
        return
    st = context.user_data.get("admin_await")
    if not st:
        return
    m = update.effective_message
    if m is None:
        return

    admin_id = update.effective_user.id
    mode = st.get("mode")
    txt = (m.text or m.caption or "").strip()

    # لغو سریع
    if txt in {"/cancel", "لغو", "کنسل"}:
        context.user_data.pop("admin_await", None)
        await m.reply_text("✖️ لغو شد.", reply_markup=kb.admin_kb())
        raise ApplicationHandlerStop

    # ---- جستجوی کاربر
    if mode == "find":
        context.user_data.pop("admin_await", None)
        u = await core.run(db.find_user, txt)
        if u is None:
            await m.reply_text("❌ کاربری با این مشخصات پیدا نشد.",
                               reply_markup=kb.admin_back_kb())
        else:
            blocks = await core.run(db.block_count, u["user_id"])
            blocked_by = await core.run(db.blocked_by_count, u["user_id"])
            await m.reply_text(
                "👤 <b>نتیجه جستجو</b>\n\n"
                f"{user_line(u)}\n"
                f"🎫 <code>{esc(u['token'])}</code>\n"
                f"📤 {fa_num(u['sent_count'])} | 📥 {fa_num(u['recv_count'])} | "
                f"⚠️ {fa_num(u['warns'])}\n"
                f"🚫 بلاک کرده {fa_num(blocks)} | بلاک شده {fa_num(blocked_by)}\n"
                f"وضعیت: <b>{'بن' if u['is_banned'] else 'سالم'}</b>",
                parse_mode=ParseMode.HTML, reply_markup=kb.user_card_kb(u),
            )
        raise ApplicationHandlerStop

    # ---- دلیل بن
    if mode == "ban":
        uid = st["uid"]
        context.user_data.pop("admin_await", None)
        reason = "" if txt in {"-", "بدون دلیل"} else txt[:300]
        await core.run(db.set_user_field, uid, "is_banned", 1)
        await core.run(db.set_user_field, uid, "ban_reason", reason or None)
        await core.run(db.log_action, admin_id, "ban", uid, reason)
        await m.reply_text(
            f"🚷 کاربر <code>{uid}</code> بن شد.", parse_mode=ParseMode.HTML,
            reply_markup=kb.admin_back_kb(),
        )
        try:
            await context.bot.send_message(
                uid,
                "🚷 <b>دسترسی تو به ربات قطع شد.</b>"
                + (f"\n<i>دلیل: {esc(reason)}</i>" if reason else ""),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        raise ApplicationHandlerStop

    # ---- مقصد پیام مستقیم
    if mode == "dm_target":
        u = await core.run(db.find_user, txt)
        if u is None:
            await m.reply_text("❌ پیدا نشد. دوباره بفرست یا /cancel بزن.")
            raise ApplicationHandlerStop
        _ask(context, "dm_text", uid=u["user_id"])
        await m.reply_text(
            f"✅ مقصد: {user_line(u)}\n\nحالا پیامت را بفرست:",
            parse_mode=ParseMode.HTML,
            reply_markup=ForceReply(input_field_placeholder="پیام مدیریت"),
        )
        raise ApplicationHandlerStop

    # ---- متن پیام مستقیم
    if mode == "dm_text":
        uid = st["uid"]
        context.user_data.pop("admin_await", None)
        try:
            if m.text:
                await context.bot.send_message(
                    uid,
                    "📣 <b>پیام از طرف مدیریت</b>\n"
                    "━━━━━━━━━━━━━━\n" + (m.text_html or esc(m.text)),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    uid, "📣 <b>پیام از طرف مدیریت</b>", parse_mode=ParseMode.HTML
                )
                await context.bot.copy_message(uid, m.chat_id, m.message_id)
            await core.run(db.log_action, admin_id, "dm", uid, short(txt, 80))
            await m.reply_text("✅ ارسال شد.", reply_markup=kb.admin_back_kb())
        except TelegramError as e:
            await m.reply_text(f"❌ ارسال نشد: <code>{esc(e)}</code>",
                               parse_mode=ParseMode.HTML,
                               reply_markup=kb.admin_back_kb())
        raise ApplicationHandlerStop

    # ---- متن خوش‌آمد
    if mode == "welcome":
        context.user_data.pop("admin_await", None)
        if txt in {"-", "حذف", "خالی"}:
            await core.run(db.set_setting, "welcome_extra", "")
            await m.reply_text("✅ متن خوش‌آمد حذف شد.",
                               reply_markup=kb.admin_back_kb())
        else:
            await core.run(db.set_setting, "welcome_extra",
                           m.text_html or txt)
            await m.reply_text("✅ متن خوش‌آمد ذخیره شد.",
                               reply_markup=kb.admin_back_kb())
        await core.run(db.log_action, admin_id, "welcome_set", "", short(txt, 80))
        raise ApplicationHandlerStop

    # ---- افزودن کانال
    if mode == "chadd":
        context.user_data.pop("admin_await", None)
        target = None
        fwd = getattr(m, "forward_origin", None)
        if fwd is not None and getattr(fwd, "chat", None) is not None:
            target = fwd.chat.id
        elif txt:
            target = txt
            if txt.lstrip("-").isdigit():
                target = int(txt)
            elif not txt.startswith("@"):
                target = "@" + txt
        if target is None:
            await m.reply_text("❌ ورودی نامعتبر بود.",
                               reply_markup=kb.admin_back_kb())
            raise ApplicationHandlerStop
        try:
            chat = await context.bot.get_chat(target)
            me = await context.bot.get_chat_member(chat.id, context.bot.id)
            if me.status not in {"administrator", "creator"}:
                await m.reply_text(
                    f"⚠️ ربات در «{esc(chat.title or '')}» ادمین نیست.\n"
                    "اول ادمینش کن، بعد دوباره اضافه کن.",
                    parse_mode=ParseMode.HTML, reply_markup=kb.admin_back_kb(),
                )
                raise ApplicationHandlerStop
            link = (f"https://t.me/{chat.username}" if chat.username
                    else (await context.bot.export_chat_invite_link(chat.id)))
            await core.run(db.add_channel, chat.id, chat.username,
                           chat.title, link)
            await core.run(db.log_action, admin_id, "channel_add", chat.id,
                           chat.title or "")
            await m.reply_text(
                f"✅ کانال <b>{esc(chat.title or chat.id)}</b> اضافه شد.\n"
                f"<code>{chat.id}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb.admin_back_kb(),
            )
        except TelegramError as e:
            await m.reply_text(
                f"❌ خطا: <code>{esc(e)}</code>\n"
                "مطمئن شو ربات در کانال ادمین است و آیدی درست است.",
                parse_mode=ParseMode.HTML, reply_markup=kb.admin_back_kb(),
            )
        raise ApplicationHandlerStop

    # ---- ارسال همگانی: دریافت پیام و تأیید
    if mode == "bc":
        context.user_data.pop("admin_await", None)
        bmode = st.get("bcmode", "copy")
        context.user_data["bc"] = {
            "chat_id": m.chat_id, "msg_id": m.message_id, "mode": bmode,
        }
        total = len(await core.run(db.all_user_ids))
        await m.reply_text(
            "📢 <b>پیش‌نمایش بالا ↑</b>\n\n"
            f"حالت: <b>{'فوروارد با منبع' if bmode == 'fwd' else 'کپی بی‌نام'}</b>\n"
            f"گیرندگان: <b>{fa_num(total)}</b> کاربر\n\n"
            "تأیید می‌کنی؟",
            parse_mode=ParseMode.HTML, reply_markup=kb.bc_confirm_kb(bmode),
        )
        raise ApplicationHandlerStop

    # حالت ناشناخته
    context.user_data.pop("admin_await", None)
