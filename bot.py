"""نقطه ورود ربات ناشناس."""
import logging
import os
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import core
import db
import handlers_admin as ha
import handlers_user as hu
import keyboards as kb

# مسیر داده‌ها باید قبل از راه‌اندازی لاگر ساخته شود
os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
os.makedirs(config.EXPORT_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("anonbot")


def register_handlers(app: Application) -> None:
    """ثبت همه‌ی هندلرها — جدا شده تا قابل تست باشد."""
    app.add_handler(CommandHandler("start", hu.cmd_start))
    app.add_handler(CommandHandler("cancel", hu.cmd_cancel))
    app.add_handler(CommandHandler("id", hu.cmd_id))
    app.add_handler(CommandHandler("rules", hu.cmd_rules))

    # پنل ادمین (روی همان گروه پیش‌فرض)
    app.add_handler(CommandHandler("admin", ha.open_panel))
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_ADMIN}$"), ha.open_panel))
    app.add_handler(CallbackQueryHandler(ha.on_cb, pattern=r"^a:"))

    # ورودی متنی ادمین — group=-1 تا قبل از هندلرهای کاربر اجرا شود؛
    # on_text اگر پیام مال او نبود بدون ApplicationHandlerStop برمی‌گردد.
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, ha.on_text), group=-1
    )

    # دکمه‌های کیبورد متنی
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_LINK}$"), hu.show_link))
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_BLOCKS}$"), hu.show_blocks))
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_STATS}$"), hu.show_my_stats))
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_SETTINGS}$"), hu.show_settings))
    app.add_handler(MessageHandler(filters.Regex(f"^{kb.BTN_HELP}$"), hu.show_help))

    # پیام‌های عادی کاربر
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, hu.on_message))

    # کالبک‌ها
    app.add_handler(CallbackQueryHandler(hu.cb_check_join, pattern=r"^chk:"))
    app.add_handler(CallbackQueryHandler(hu.cb_qr, pattern=r"^qr$"))
    app.add_handler(CallbackQueryHandler(hu.cb_newtoken, pattern=r"^newtok$"))
    app.add_handler(CallbackQueryHandler(hu.cb_blocks_page, pattern=r"^blkp:"))
    app.add_handler(CallbackQueryHandler(hu.cb_unblock, pattern=r"^ub:"))
    app.add_handler(CallbackQueryHandler(hu.cb_setting, pattern=r"^st:"))
    app.add_handler(CallbackQueryHandler(hu.cb_seen, pattern=r"^sn:"))
    app.add_handler(CallbackQueryHandler(hu.cb_block_ask, pattern=r"^bl:"))
    app.add_handler(CallbackQueryHandler(hu.cb_block_yes, pattern=r"^bly:"))
    app.add_handler(CallbackQueryHandler(hu.cb_block_no, pattern=r"^bln:"))
    app.add_handler(CallbackQueryHandler(hu.cb_report_ask, pattern=r"^rc:"))
    app.add_handler(CallbackQueryHandler(hu.cb_report_yes, pattern=r"^rcy:"))
    app.add_handler(CallbackQueryHandler(hu.cb_report_no, pattern=r"^rcn:"))
    app.add_handler(CallbackQueryHandler(hu.cb_reply_prompt, pattern=r"^rp:"))
    app.add_handler(CallbackQueryHandler(hu.cb_delete_sent, pattern=r"^del:"))
    app.add_handler(CallbackQueryHandler(hu.cb_close, pattern=r"^close$"))
    app.add_handler(CallbackQueryHandler(hu.cb_noop, pattern=r"^noop$"))


def main() -> None:
    # مقداردهی دیتابیس
    db.init()
    # گرفتن username ربات از API
    app_builder = Application.builder().token(config.BOT_TOKEN)
    app = app_builder.build()

    async def get_bot_username(application: Application) -> None:
        me = await application.bot.get_me()
        core.BOT_USERNAME = me.username
        log.info("Bot started: @%s", me.username)

    app.post_init = get_bot_username

    async def on_error(update, context) -> None:
        log.error("handler error: %s", context.error, exc_info=context.error)

    app.add_error_handler(on_error)

    # هندلرها
    register_handlers(app)

    log.info("Starting bot...")

    # webhook روی Railway (بدون تضاد getUpdates)، polling در محیط لوکال
    port = int(os.environ.get("PORT", "0") or 0)
    domain = (
        os.environ.get("WEBHOOK_DOMAIN")
        or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or ""
    ).strip().replace("https://", "").rstrip("/")

    if port and domain:
        secret = config.BOT_TOKEN.split(":")[-1][:24]
        log.info("Webhook mode on %s:%s", domain, port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=secret,
            webhook_url=f"https://{domain}/{secret}",
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("Polling mode")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
        )


if __name__ == "__main__":
    main()
