"""هندلرهای سمت کاربر: استارت، لینک، بلاک‌ها، تنظیمات، ارسال ناشناس، پاسخ."""
from __future__ import annotations

import io
import logging
import time

from telegram import ForceReply, ReplyParameters, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

import config
import core
import db
import keyboards as kb
import texts as T
from utils import ago, esc, fa_num, full_name, jdate, kind_label, short, user_line

log = logging.getLogger("anonbot")
PER_BLOCK = 6


# ---------------------------------------------------------------- start
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args or []
    payload = args[0].strip() if args else ""

    row = await core.run(
        db.upsert_user, user.id, user.first_name or "", user.last_name or "", user.username
    )
    if row["is_banned"]:
        reason = row["ban_reason"] or ""
        await update.effective_message.reply_text(
            T.BANNED.format(reason=f"\n<i>{esc(reason)}</i>" if reason else ""),
            parse_mode=ParseMode.HTML,
        )
        return
    if await core.run(db.flag, "maintenance") and not core.is_admin(user.id):
        await update.effective_message.reply_text(T.MAINTENANCE, parse_mode=ParseMode.HTML)
        return

    ok, missing = await core.check_membership(context, user.id)
    if not ok:
        context.user_data["pending_payload"] = payload
        await core.show_force_join(update, context, missing, payload)
        return

    await enter_start(update, context, payload, row)


async def enter_start(update: Update, context, payload: str, row) -> None:
    """پس از تأیید عضویت."""
    context.user_data.pop("await", None)
    user = update.effective_user
    new_user = (row["created_at"] or 0) > int(time.time()) - 20

    if payload and payload != row["token"]:
        target = await core.run(db.get_by_token, payload)
        if target is None:
            await _send(update, T.USER_NOT_FOUND, kb.main_kb(core.is_admin(user.id)))
        elif target["user_id"] == user.id:
            await _send(update, T.SELF_MSG, kb.main_kb(core.is_admin(user.id)))
        elif not target["link_active"]:
            await _send(update, T.LINK_OFF, kb.main_kb(core.is_admin(user.id)))
        elif await core.run(db.is_blocked, target["user_id"], user.id):
            await _send(update, T.BLOCKED_BY_TARGET, kb.main_kb(core.is_admin(user.id)))
        else:
            context.user_data["target"] = target["user_id"]
            name = target["nickname"] or full_name(target)
            await _send(
                update,
                T.SEND_INTRO.format(name=esc(name)),
                kb.main_kb(core.is_admin(user.id)),
            )
            return
        return

    context.user_data.pop("target", None)
    link = core.bot_link(row["token"])
    await _send(
        update,
        T.WELCOME_OWNER.format(link=link),
        kb.main_kb(core.is_admin(user.id)),
    )
    extra = await core.run(db.get_setting, "welcome_extra")
    if extra:
        await update.effective_message.reply_text(extra, parse_mode=ParseMode.HTML)
    if new_user and await core.run(db.flag, "new_user_alert"):
        await core.notify_admins(
            context,
            f"🆕 <b>کاربر جدید</b>\n{user_line(row)}\n🕓 {jdate()}",
        )


async def _send(update: Update, text: str, markup=None) -> None:
    m = update.effective_message
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except TelegramError:
            pass
        m = update.callback_query.message
    await m.get_bot().send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode=ParseMode.HTML,
        reply_markup=markup, disable_web_page_preview=True,
    )


# ---------------------------------------------------------------- join check
async def cb_check_join(update: Update, context) -> None:
    qy = update.callback_query
    payload = qy.data.split(":", 1)[1] if ":" in qy.data else ""
    if not payload:
        payload = context.user_data.get("pending_payload", "")
    core.clear_member_cache(update.effective_user.id)
    ok, missing = await core.check_membership(context, update.effective_user.id, force=True)
    if not ok:
        await qy.answer(T.NOT_JOINED_YET, show_alert=True)
        return
    await qy.answer(T.JOIN_OK)
    row = await core.run(db.get_user, update.effective_user.id)
    context.user_data.pop("pending_payload", None)
    await enter_start(update, context, payload, row)


# ---------------------------------------------------------------- my link
async def show_link(update: Update, context) -> None:
    row = await core.guard(update, context)
    if not row:
        return
    link = core.bot_link(row["token"])
    txt = (
        "🔗 <b>لینک ناشناس اختصاصی تو</b>\n\n"
        f"<code>{link}</code>\n\n"
        "📌 این لینک رو هرجایی بذار (بیو اینستاگرام، استوری، استاتوس واتساپ، توییتر) "
        "تا بقیه بتونن بهت پیام ناشناس بدن.\n\n"
        f"📥 تا حالا <b>{fa_num(row['recv_count'])}</b> پیام ناشناس گرفتی.\n"
        f"وضعیت: <b>{'فعال 🟢' if row['link_active'] else 'غیرفعال 🔴'}</b>"
    )
    await update.effective_message.reply_text(
        txt, parse_mode=ParseMode.HTML, reply_markup=kb.link_kb(link, row["token"]),
        disable_web_page_preview=True,
    )


async def cb_qr(update: Update, context) -> None:
    qy = update.callback_query
    await qy.answer("در حال ساخت QR…")
    row = await core.run(db.get_user, update.effective_user.id)
    link = core.bot_link(row["token"])
    try:
        import qrcode

        img = qrcode.make(link)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_photo(
            update.effective_chat.id, photo=buf,
            caption=f"🖼 QR لینک ناشناس تو\n<code>{link}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("qr failed: %s", e)
        await qy.answer("ساخت QR ممکن نشد.", show_alert=True)


async def cb_newtoken(update: Update, context) -> None:
    qy = update.callback_query
    tok = await core.run(db.reset_token, update.effective_user.id)
    link = core.bot_link(tok)
    await qy.answer("لینک جدید ساخته شد ✅")
    await context.bot.send_message(
        update.effective_chat.id,
        "♻️ <b>لینک جدیدت آماده شد.</b> لینک قبلی از این پس کار نمی‌کند.\n\n"
        f"<code>{link}</code>",
        parse_mode=ParseMode.HTML, reply_markup=kb.link_kb(link, tok),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------- blocks
async def show_blocks(update: Update, context, page: int = 0, edit=False) -> None:
    uid = update.effective_user.id
    rows = await core.run(db.block_list, uid)
    if not rows:
        if edit:
            await update.callback_query.edit_message_text(T.NO_BLOCKS)
        else:
            await update.effective_message.reply_text(T.NO_BLOCKS)
        return
    total_pages = max(1, (len(rows) + PER_BLOCK - 1) // PER_BLOCK)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page * PER_BLOCK : (page + 1) * PER_BLOCK]
    lines = [f"🚫 <b>لیست بلاک‌شده‌ها</b> ({fa_num(len(rows))} نفر)\n"]
    for i, r in enumerate(chunk, start=page * PER_BLOCK + 1):
        nm = esc((r["first_name"] or "").strip() or "کاربر")
        un = f" @{esc(r['username'])}" if r["username"] else ""
        lines.append(f"{fa_num(i)}. {nm}{un} — <i>{ago(r['created_at'])}</i>")
    txt = "\n".join(lines)
    markup = kb.blocks_kb(chunk, page, total_pages)
    if edit:
        try:
            await update.callback_query.edit_message_text(
                txt, parse_mode=ParseMode.HTML, reply_markup=markup
            )
        except BadRequest:
            pass
    else:
        await update.effective_message.reply_text(
            txt, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def cb_blocks_page(update: Update, context) -> None:
    page = int(update.callback_query.data.split(":")[1])
    await update.callback_query.answer()
    await show_blocks(update, context, page, edit=True)


async def cb_unblock(update: Update, context) -> None:
    qy = update.callback_query
    other = int(qy.data.split(":")[1])
    await core.run(db.remove_block, update.effective_user.id, other)
    await qy.answer(T.UNBLOCK_DONE)
    await show_blocks(update, context, 0, edit=True)


# ---------------------------------------------------------------- stats / help / settings
async def show_my_stats(update: Update, context) -> None:
    row = await core.guard(update, context)
    if not row:
        return
    blocks = await core.run(db.block_count, row["user_id"])
    seen = await core.run(db.seen_count_of_sender, row["user_id"])
    await update.effective_message.reply_text(
        T.my_stats(row, blocks, seen) + f"\n📅 عضویت: <i>{jdate(row['created_at'], False)}</i>",
        parse_mode=ParseMode.HTML, reply_markup=kb.close_kb(),
    )


async def show_help(update: Update, context) -> None:
    await update.effective_message.reply_text(
        T.HELP, parse_mode=ParseMode.HTML, reply_markup=kb.close_kb()
    )


async def cmd_rules(update: Update, context) -> None:
    await update.effective_message.reply_text(T.RULES, parse_mode=ParseMode.HTML)


async def show_settings(update: Update, context, edit=False) -> None:
    row = await core.run(db.get_user, update.effective_user.id)
    if row is None:
        return
    txt = (
        "⚙️ <b>تنظیمات</b>\n\n"
        "• <b>لینک ناشناس</b>: خاموش کنی، کسی نمی‌تونه بهت پیام بده.\n"
        "• <b>تیک دیدم</b>: اگه غیرفعال باشه، دکمه «پیامتو دیدم» برات نمایش داده نمی‌شه.\n"
        "• <b>نام نمایشی</b>: اسمی که فرستنده‌ها می‌بینن (به‌جای اسم تلگرامت).\n"
    )
    markup = kb.user_settings_kb(row)
    if edit:
        try:
            await update.callback_query.edit_message_text(
                txt, parse_mode=ParseMode.HTML, reply_markup=markup
            )
        except BadRequest:
            pass
    else:
        await update.effective_message.reply_text(
            txt, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def cb_setting(update: Update, context) -> None:
    qy = update.callback_query
    what = qy.data.split(":")[1]
    uid = update.effective_user.id
    row = await core.run(db.get_user, uid)
    if what == "link":
        await core.run(db.set_user_field, uid, "link_active", 0 if row["link_active"] else 1)
        await qy.answer("لینک " + ("غیرفعال شد 🔴" if row["link_active"] else "فعال شد 🟢"))
    elif what == "seen":
        await core.run(db.set_user_field, uid, "seen_notify", 0 if row["seen_notify"] else 1)
        await qy.answer("تغییر یافت ✅")
    elif what == "nick":
        context.user_data["await"] = "nick"
        await qy.answer()
        await context.bot.send_message(
            update.effective_chat.id, T.NICK_PROMPT,
            reply_markup=ForceReply(input_field_placeholder="نام نمایشی"),
        )
        return
    elif what == "clrblk":
        await core.run(db.ex, "DELETE FROM blocks WHERE owner_id=?", (uid,))
        await qy.answer("همه بلاک‌ها پاک شد ♻️", show_alert=True)
    await show_settings(update, context, edit=True)


# ---------------------------------------------------------------- receive buttons
async def cb_seen(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    row = await core.run(db.get_msg, mid)
    if not row or row["receiver_id"] != update.effective_user.id:
        await qy.answer("پیام یافت نشد.", show_alert=True)
        return
    if row["seen_at"]:
        await qy.answer(T.SEEN_ALREADY)
        return
    await core.run(db.mark_seen, mid)
    await qy.answer(T.SEEN_DONE)
    try:
        await context.bot.send_message(
            row["sender_id"],
            T.SEEN_TO_SENDER.format(preview=esc(short(row["preview"], 90))),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass
    try:
        await qy.edit_message_reply_markup(reply_markup=kb.seen_only_kb(mid))
    except BadRequest:
        pass


async def cb_block_ask(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    await qy.answer()
    try:
        await qy.edit_message_reply_markup(reply_markup=kb.block_confirm_kb(mid))
    except BadRequest:
        pass
    await context.bot.send_message(
        update.effective_chat.id, T.BLOCK_ASK, parse_mode=ParseMode.HTML,
        reply_parameters=ReplyParameters(
            message_id=qy.message.message_id, allow_sending_without_reply=True
        ),
        reply_markup=kb.block_confirm_kb(mid),
    )


async def cb_block_yes(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    row = await core.run(db.get_msg, mid)
    if not row or row["receiver_id"] != update.effective_user.id:
        await qy.answer("پیام یافت نشد.", show_alert=True)
        return
    if await core.run(db.is_blocked, update.effective_user.id, row["sender_id"]):
        await qy.answer(T.BLOCK_ALREADY, show_alert=True)
    else:
        await core.run(db.add_block, update.effective_user.id, row["sender_id"])
        await qy.answer(T.BLOCK_DONE, show_alert=True)
    try:
        await qy.edit_message_text("🚫 <b>این فرد بلاک شد.</b>", parse_mode=ParseMode.HTML)
    except BadRequest:
        try:
            await qy.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass


async def cb_block_no(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    await qy.answer(T.REPORT_CANCEL)
    try:
        await qy.message.delete()
    except TelegramError:
        try:
            await qy.edit_message_reply_markup(reply_markup=kb.recv_kb(mid))
        except BadRequest:
            pass


async def cb_report_ask(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    if await core.run(db.already_reported, update.effective_user.id, mid):
        await qy.answer(T.REPORT_ALREADY, show_alert=True)
        return
    await qy.answer()
    await context.bot.send_message(
        update.effective_chat.id, T.REPORT_ASK, parse_mode=ParseMode.HTML,
        reply_parameters=ReplyParameters(
            message_id=qy.message.message_id, allow_sending_without_reply=True
        ),
        reply_markup=kb.report_confirm_kb(mid),
    )


async def cb_report_yes(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    row = await core.run(db.get_msg, mid)
    if not row or row["receiver_id"] != update.effective_user.id:
        await qy.answer("پیام یافت نشد.", show_alert=True)
        return
    if await core.run(db.already_reported, update.effective_user.id, mid):
        await qy.answer(T.REPORT_ALREADY, show_alert=True)
        return
    rid = await core.run(db.add_report, update.effective_user.id, row["sender_id"], mid)
    await qy.answer(T.REPORT_DONE, show_alert=True)
    try:
        await qy.edit_message_text(
            "⚠️ <b>گزارش ثبت شد.</b> ادمین‌ها بررسی می‌کنن.", parse_mode=ParseMode.HTML
        )
    except BadRequest:
        pass

    if await core.run(db.flag, "report_notify"):
        sender = await core.run(db.get_user, row["sender_id"])
        reporter = await core.run(db.get_user, update.effective_user.id)
        txt = (
            f"⚠️ <b>گزارش تخلف جدید</b> <code>#{rid}</code>\n\n"
            f"🚨 <b>متخلف (فرستنده):</b>\n{user_line(sender)}\n"
            f"📊 ارسال: {fa_num(sender['sent_count'] if sender else 0)} | "
            f"اخطار: {fa_num(sender['warns'] if sender else 0)}\n\n"
            f"🙋 <b>گزارش‌دهنده (گیرنده):</b>\n{user_line(reporter)}\n\n"
            f"📝 <b>محتوا:</b> {kind_label(row['kind'])}\n"
            f"<blockquote>{esc(short(row['preview'], 300))}</blockquote>\n"
            f"🕓 {jdate(row['created_at'])}"
        )
        for aid in config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    aid, txt, parse_mode=ParseMode.HTML,
                    reply_markup=kb.report_kb({"id": rid}),
                    disable_web_page_preview=True,
                )
                if row["src_chat_id"] and row["src_msg_id"]:
                    await context.bot.copy_message(
                        aid, row["src_chat_id"], row["src_msg_id"]
                    )
            except TelegramError as e:
                log.info("report notify %s failed: %s", aid, e)


async def cb_report_no(update: Update, context) -> None:
    qy = update.callback_query
    await qy.answer(T.REPORT_CANCEL)
    try:
        await qy.message.delete()
    except TelegramError:
        pass


async def cb_reply_prompt(update: Update, context) -> None:
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    row = await core.run(db.get_msg, mid)
    if not row or row["receiver_id"] != update.effective_user.id:
        await qy.answer("پیام یافت نشد.", show_alert=True)
        return
    await qy.answer()
    sent = await context.bot.send_message(
        update.effective_chat.id, T.REPLY_PROMPT,
        reply_markup=ForceReply(input_field_placeholder="پاسخ ناشناس…"),
    )
    await core.run(db.add_prompt, update.effective_user.id, sent.message_id, mid)


async def cb_delete_sent(update: Update, context) -> None:
    """فرستنده پیام ناشناسش را از چت گیرنده حذف می‌کند."""
    qy = update.callback_query
    mid = int(qy.data.split(":")[1])
    row = await core.run(db.get_msg, mid)
    if not row or row["sender_id"] != update.effective_user.id:
        await qy.answer("پیام یافت نشد.", show_alert=True)
        return
    ok = False
    for target_mid in (row["dst_msg_id"], row["hdr_msg_id"]):
        if not target_mid:
            continue
        try:
            await context.bot.delete_message(row["receiver_id"], target_mid)
            ok = True
        except TelegramError:
            pass
    if ok:
        await core.run(db.mark_deleted, mid)
        await qy.answer(T.DELETED_OK, show_alert=True)
        try:
            await qy.edit_message_text("🗑 <i>پیام حذف شد.</i>", parse_mode=ParseMode.HTML)
        except BadRequest:
            pass
    else:
        await qy.answer(T.DELETE_FAIL, show_alert=True)


# ---------------------------------------------------------------- main message router
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.effective_message
    if m is None or update.effective_chat.type != "private":
        return
    uid = update.effective_user.id

    row = await core.guard(update, context)
    if not row:
        return

    # ۱) در انتظار ورودی متنی (نام نمایشی / حالت‌های ادمین)
    awaiting = context.user_data.get("await")
    if awaiting == "nick":
        context.user_data.pop("await", None)
        txt = (m.text or "").strip()
        if txt in {"-", "حذف", "خالی"}:
            await core.run(db.set_user_field, uid, "nickname", None)
            await m.reply_text(T.NICK_CLEARED)
        else:
            await core.run(db.set_user_field, uid, "nickname", txt[:32])
            await m.reply_text(T.NICK_DONE)
        await show_settings(update, context)
        return

    # ۲) ریپلای؟ → پاسخ ناشناس
    if m.reply_to_message:
        rmid = m.reply_to_message.message_id
        prompt = await core.run(db.get_prompt, uid, rmid)
        parent = None
        if prompt:
            parent = await core.run(db.get_msg, prompt["thread_id"])
        else:
            parent = await core.run(db.msg_by_dst, uid, rmid)
            if parent is None:
                parent = await core.run(
                    db.q1,
                    "SELECT * FROM msgs WHERE receiver_id=? AND hdr_msg_id=? ORDER BY id DESC LIMIT 1",
                    (uid, rmid),
                )
        if parent:
            await do_reply(update, context, row, parent, m)
            return

    # ۳) حالت ارسال به یک هدف
    target_id = context.user_data.get("target")
    if target_id:
        await do_send(update, context, row, target_id, m)
        return

    # ۴) هیچ حالتی نیست
    await m.reply_text(
        "💡 برای فرستادن پیام ناشناس، اول باید روی <b>لینک ناشناس</b> یک نفر بزنی.\n"
        "لینک خودت رو هم از دکمه «🔗 دریافت لینک ناشناس من» بگیر.\n\n"
        "برای پاسخ دادن به پیام ناشناسی که گرفتی، روی همون پیام <b>ریپلای</b> کن.",
        parse_mode=ParseMode.HTML, reply_markup=kb.main_kb(core.is_admin(uid)),
    )


async def _pre_send_checks(update, context, row, target, m) -> bool:
    uid = row["user_id"]
    if target is None:
        await m.reply_text(T.USER_NOT_FOUND)
        context.user_data.pop("target", None)
        return False
    if target["user_id"] == uid:
        await m.reply_text(T.SELF_MSG)
        return False
    if target["is_banned"]:
        await m.reply_text(T.USER_NOT_FOUND)
        return False
    if await core.run(db.is_blocked, target["user_id"], uid):
        await m.reply_text(T.BLOCKED_BY_TARGET)
        return False
    if core.flood_hit(uid):
        await m.reply_text(T.FLOOD)
        return False
    maxlen = int(await core.run(db.get_setting, "max_len") or 4000)
    body = m.text or m.caption or ""
    if len(body) > maxlen:
        await m.reply_text(T.TOO_LONG.format(n=fa_num(maxlen)))
        return False
    return True


async def do_send(update: Update, context, row, target_id: int, m) -> None:
    target = await core.run(db.get_user, target_id)
    if not await _pre_send_checks(update, context, row, target, m):
        return
    if not target["link_active"]:
        await m.reply_text(T.LINK_OFF)
        return

    # آلبوم: فقط اولین آیتم کارت کامل بگیرد
    grp = m.media_group_id
    if grp and context.user_data.get("last_group") == grp:
        try:
            await context.bot.copy_message(target_id, m.chat_id, m.message_id)
        except TelegramError:
            pass
        return
    if grp:
        context.user_data["last_group"] = grp

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    mid = await core.deliver_anon(context, row, target, m)
    if mid is None:
        await m.reply_text(T.NOT_DELIVERED)
        return
    await m.reply_text(
        T.SENT_OK, parse_mode=ParseMode.HTML, reply_markup=kb.sender_ack_kb(mid)
    )


async def do_reply(update: Update, context, row, parent, m) -> None:
    """پاسخ ناشناس به فرستنده‌ی پیام قبلی."""
    uid = row["user_id"]
    other_id = parent["sender_id"] if parent["receiver_id"] == uid else parent["receiver_id"]
    other = await core.run(db.get_user, other_id)
    if not await _pre_send_checks(update, context, row, other, m):
        return
    mid = await core.deliver_anon(context, row, other, m, parent=parent)
    if mid is None:
        await m.reply_text(T.NOT_DELIVERED)
        return
    await m.reply_text(
        T.SENT_REPLY_OK, parse_mode=ParseMode.HTML, reply_markup=kb.sender_ack_kb(mid)
    )


# ---------------------------------------------------------------- misc callbacks
async def cb_close(update: Update, context) -> None:
    qy = update.callback_query
    await qy.answer(T.CLOSED)
    try:
        await qy.message.delete()
    except TelegramError:
        try:
            await qy.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass


async def cb_noop(update: Update, context) -> None:
    await update.callback_query.answer()


async def cmd_cancel(update: Update, context) -> None:
    context.user_data.pop("target", None)
    context.user_data.pop("await", None)
    context.user_data.pop("admin", None)
    await update.effective_message.reply_text(
        T.CANCELLED, reply_markup=kb.main_kb(core.is_admin(update.effective_user.id))
    )


async def cmd_id(update: Update, context) -> None:
    u = update.effective_user
    await update.effective_message.reply_text(
        f"🆔 آیدی عددی تو: <code>{u.id}</code>", parse_mode=ParseMode.HTML
    )
