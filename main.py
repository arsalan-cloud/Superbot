import os
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=TOKEN)
dp = Dispatcher()

URL_PATTERN = re.compile(r'https?://(www\.)?(instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/.+')

def main_menu():
    kb = [
        [KeyboardButton(text="📥 دانلودر شبکه‌های اجتماعی"), KeyboardButton(text="🧠 هوش مصنوعی")],
        [KeyboardButton(text="📊 نرخ ارز"), KeyboardButton(text="👤 حساب کاربری")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def download_video_sync(url: str, output_path: str):
    import yt_dlp
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("سلام! به ابر ربات خوش آمدید.", reply_markup=main_menu())

@dp.message(F.text == "📥 دانلودر شبکه‌های اجتماعی")
async def downloader_btn(message: types.Message):
    await message.answer("📥 لینک ویدیو از اینستاگرام، تیک‌تاک یا یوتیوب را بفرستید.")

@dp.message(F.text.regexp(URL_PATTERN))
async def process_video_download(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ در حال دانلود ویدیو...")
    file_id = message.from_user.id
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_id}_%(id)s.%(ext)s"
    
    try:
        file_path = await asyncio.to_thread(download_video_sync, url, output_template)
        if os.path.exists(file_path):
            await status_msg.edit_text("📤 در حال آپلود...")
            await message.answer_video(video=FSInputFile(file_path), caption="✅ دانلود شد!")
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ خطا در دریافت فایل.")
    except Exception as e:
        logging.error(f"Error: {e}")
        await status_msg.edit_text("❌ دانلود ناموفق بود.")

# پاسخ به تاییدیه سلامت ریندر
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # راه اندازی وب‌سرور جهت تایید Health Check ریندر
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("🤖 Superbot is running on Free Tier...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
