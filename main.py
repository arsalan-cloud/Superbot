import os
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton

# دریافت توکن از متغیرهای محیطی سرور Render
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# الگوی شناسایی لینک‌های اینستاگرام، تیک‌تاک و یوتیوب
URL_PATTERN = re.compile(r'https?://(www\.)?(instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/.+')

# منوی اصلی
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

# تابع دانلود ویدیو در پس‌زمینه
def download_video_sync(url: str, output_path: str):
    import yt_dlp
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,  # محدودیت ۵۰ مگابایت تلگرام
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        f"سلام {message.from_user.first_name} عزیز! 👋\n\n"
        "به **ابر ربات همه‌کاره** خوش آمدید.\n"
        "از منوی زیر بخش مورد نظر را انتخاب کنید یا لینک ویدیو بفرستید:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "📥 دانلودر شبکه‌های اجتماعی")
async def downloader_btn(message: types.Message):
    await message.answer(
        "📥 **بخش دانلودر**\n\n"
        "لطفاً لینک ویدیو یا پست مورد نظر را ارسال کنید:\n"
        "• اینستاگرام (Reels, Post)\n"
        "• تیک‌تاک (TikTok)\n"
        "• یوتیوب (Shorts, Video)"
    )

@dp.message(F.text == "🧠 هوش مصنوعی")
async def ai_btn(message: types.Message):
    await message.answer("🧠 این بخش در فاز بعدی اضافه می‌شود.")

@dp.message(F.text == "📊 نرخ ارز")
async def currency_btn(message: types.Message):
    await message.answer("📊 این بخش در فاز بعدی اضافه می‌شود.")

@dp.message(F.text == "👤 حساب کاربری")
async def profile_btn(message: types.Message):
    await message.answer(
        f"👤 **اطلاعات کاربری:**\n\n"
        f"▪️ **نام:** {message.from_user.full_name}\n"
        f"▪️ **شناسه:** `{message.from_user.id}`\n"
        f"▪️ **وضعیت:** فعال",
        parse_mode="Markdown"
    )

@dp.message(F.text.regexp(URL_PATTERN))
async def process_video_download(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ در حال دانلود و پردازش ویدیو... لطفاً صبور باشید.")
    
    file_id = message.from_user.id
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_id}_%(id)s.%(ext)s"
    
    try:
        file_path = await asyncio.to_thread(download_video_sync, url, output_template)
        
        if os.path.exists(file_path):
            await status_msg.edit_text("📤 در حال آپلود به تلگرام...")
            video_file = FSInputFile(file_path)
            await message.answer_video(
                video=video_file,
                caption="✅ ویدیو با موفقیت دانلود شد!"
            )
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ خطایی در دریافت فایل رخ داد.")

    except Exception as e:
        logging.error(f"Download error: {e}")
        await status_msg.edit_text("❌ دانلود ناموفق بود. ممکن است پست خصوصی باشد یا حجم آن بیشتر از ۵۰ مگابایت باشد.")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🤖 Superbot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
