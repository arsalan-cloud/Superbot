import os
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import aiohttp
import yt_dlp

# دریافت تنظیمات از محیط سرور
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

if not TOKEN:
    raise ValueError("خطا: توکن ربات (BOT_TOKEN) در تنظیمات Render ست نشده است.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# الگوی تشخیص لینک‌های شبکه‌های اجتماعی
URL_PATTERN = re.compile(r'https?://(www\.)?(instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/.+')

# --- کیبورد اصلی ربات ---
def main_menu():
    kb = [
        [
            KeyboardButton(text="📥 دانلودر شبکه‌های اجتماعی"),
            KeyboardButton(text="🧠 هوش مصنوعی")
        ],
        [
            KeyboardButton(text="📊 نرخ ارز"),
            KeyboardButton(text="👤 حساب کاربری")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- دانلود ویدیو با yt-dlp ---
def download_video_sync(url: str, output_path: str):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# --- دریافت نرخ ارز و رمزارز از API رایگان ---
async def fetch_exchange_rates():
    try:
        async with aiohttp.ClientSession() as session:
            # دریافت نرخ ارزهای فیات
            async with session.get("https://open.er-api.com/v6/latest/USD", timeout=10) as resp:
                fiat_data = await resp.json()
            
            # دریافت قیمت بیت‌کوین
            async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10) as resp_crypto:
                crypto_data = await resp_crypto.json()

        rates = fiat_data.get("rates", {})
        eur = rates.get("EUR", 0)
        afn = rates.get("AFN", 0)
        btc = float(crypto_data.get("price", 0))

        return (
            "📊 **نرخ‌های آنلاین و لحظه‌ای ارز**\n\n"
            f"💵 **۱ دلار آمریکا:** 1.00 USD\n"
            f"💶 **۱ دلار به یورو:** {eur:.2f} EUR\n"
            f"🇦🇫 **۱ دلار به افغانی:** {afn:.2f} AFN\n"
            f"🪙 **بیت‌کوین:** ${btc:,.2f}\n\n"
            "🔄 *منبع: وب‌سرویس‌های جهانی قیمت‌دهی*"
        )
    except Exception as e:
        logging.error(f"Error fetching rates: {e}")
        return "❌ خطا در دریافت اطلاعات نرخ ارز. لطفاً دوباره تلاش کنید."

# --- هندلرهای دستورات و دکمه‌ها ---

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        f"سلام {message.from_user.first_name} عزیز! 👋\n\n"
        "به **ابر ربات همه‌کاره** خوش آمدید.\n"
        "لطفاً یکی از گزینه زیر را انتخاب کنید:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "📥 دانلودر شبکه‌های اجتماعی")
async def downloader_btn(message: types.Message):
    await message.answer(
        "📥 **بخش دانلودر**\n\n"
        "لینک ویدیو را ارسال کنید:\n"
        "• اینستاگرام (Reels, Post)\n"
        "• تیک‌تاک (TikTok)\n"
        "• یوتیوب (Shorts, Video)"
    )

@dp.message(F.text == "🧠 هوش مصنوعی")
async def ai_btn(message: types.Message):
    await message.answer(
        "🧠 **بخش ابزارهای هوش مصنوعی**\n\n"
        "این بخش آماده‌سازی شده است و به‌زودی ابزارهای زیر فعال می‌شوند:\n"
        "• تبدیل ویس به متن\n"
        "• استخراج متن از عکس (OCR)\n"
        "• دستیار هوشمند چت"
    )

@dp.message(F.text == "📊 نرخ ارز")
async def currency_btn(message: types.Message):
    status_msg = await message.answer("⏳ در حال دریافت نرخ‌های زنده...")
    text = await fetch_exchange_rates()
    await status_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == "👤 حساب کاربری")
async def profile_btn(message: types.Message):
    username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    await message.answer(
        f"👤 **اطلاعات حساب کاربری:**\n\n"
        f"▪️ **نام:** {message.from_user.full_name}\n"
        f"▪️ **شناسه عددی:** `{message.from_user.id}`\n"
        f"▪️ **نام کاربری:** {username}\n"
        f"▪️ **وضعیت حساب:** رایگان / فعال",
        parse_mode="Markdown"
    )

@dp.message(F.text.regexp(URL_PATTERN))
async def process_video_download(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ در حال پردازش و دانلود ویدیو...")
    
    file_id = message.from_user.id
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_id}_%(id)s.%(ext)s"
    
    try:
        file_path = await asyncio.to_thread(download_video_sync, url, output_template)
        
        if os.path.exists(file_path):
            await status_msg.edit_text("📤 در حال ارسال ویدیو به تلگرام...")
            video_file = FSInputFile(file_path)
            await message.answer_video(
                video=video_file,
                caption="✅ ویدیو با موفقیت دانلود شد!"
            )
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ خطایی در دانلود فایل رخ داد.")

    except Exception as e:
        logging.error(f"Download error: {e}")
        await status_msg.edit_text("❌ دانلود ناموفق بود. ممکن است لینک خصوصی باشد یا حجم آن بیشتر از ۵۰ مگابایت باشد.")

# --- پاسخ به درخواست‌های Render Health Check ---
async def handle_health(request):
    return web.Response(text="Superbot server is alive!")

# --- اجرای هم‌زمان وب‌سرور و ربات تلگرام ---
async def main():
    logging.basicConfig(level=logging.INFO)
    
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("🤖 Superbot running and web port listening...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
