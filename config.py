"""تنظیمات پایه ربات چت ناشناس."""
import os

# توکن فقط از متغیر محیطی خوانده می‌شود (هیچ‌وقت داخل کد نگه‌داری نشود)
BOT_TOKEN = os.environ.get("ANON_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit(
        "ANON_BOT_TOKEN تعریف نشده است. آن را در Variables سرور تنظیم کنید."
    )

# فقط این دو آیدی عددی ادمین کامل هستند
ADMIN_IDS = [8963575980, 7312035195]

# کانال جوین اجباری (پیش‌فرض؛ از پنل ادمین قابل تغییر است)
DEFAULT_CHANNELS = [
    {
        "chat_id": -1004458917479,
        "username": "ggggggg_asal",
        "title": "faded echoes",
        "link": "https://t.me/ggggggg_asal",
    }
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "anonbot.db")
LOG_PATH = os.path.join(BASE_DIR, "data", "bot.log")
EXPORT_DIR = os.path.join(BASE_DIR, "data", "exports")

# ضدفلاد
FLOOD_WINDOW = 60          # ثانیه
FLOOD_MAX = 20             # حداکثر پیام در هر پنجره
SEND_COOLDOWN = 1.0        # فاصله حداقلی بین دو ارسال ناشناس
MEMBERSHIP_CACHE_TTL = 300 # کش عضویت کانال (ثانیه)

# طول توکن لینک شخصی
TOKEN_LEN = 8

BROADCAST_SLEEP = 0.045    # فاصله بین ارسال‌های همگانی (~22 msg/s)
