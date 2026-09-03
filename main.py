import os
import asyncio
import aiohttp
import yt_dlp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# توکن ربات از متغیرهای محیطی Render خوانده می‌شود
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# FSM States
class ConverterStates(StatesGroup):
    waiting_for_amount = State()

class CalculatorStates(StatesGroup):
    waiting_for_expression = State()

class DownloaderStates(StatesGroup):
    waiting_for_url = State()

# --- کیبورد اصلی ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 دانلودر حرفه‌ای (یوتیوب/تیک‌تاک/اینستاگرام)", callback_data="menu_downloader")],
        [InlineKeyboardButton(text="💱 تبدیل ارزها", callback_data="menu_currency"),
         InlineKeyboardButton(text="🧮 ماشین حساب پیشرفته", callback_data="menu_calc")],
        [InlineKeyboardButton(text="ℹ️ راهنما و درباره ما", callback_data="menu_help")]
    ])

def back_to_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_home")]
    ])

# --- هندلر استارت ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "سلام! 🤖 به ربات چندمنظوره و پیشرفته خوش آمدید.\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "back_home")
async def back_home_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "منوی اصلی ربات:",
        reply_markup=main_menu()
    )
    await callback.answer()

# ==========================================
# بخش دانلودر پیشرفته
# ==========================================
@router.callback_query(F.data == "menu_downloader")
async def downloader_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DownloaderStates.waiting_for_url)
    await callback.message.edit_text(
        "📥 **بخش دانلود مدیا**\n\n"
        "لینک ویدیو یا پست مورد نظر خود (از یوتیوب، تیک‌تاک و...) را ارسال کنید:",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(DownloaderStates.waiting_for_url)
async def process_download_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("⚠️ لطفاً یک لینک معتبر ارسال کنید که با http شروع شود.", reply_markup=back_to_menu())
        return

    processing_msg = await message.answer("⏳ در حال پردازش و دانلود مدیا، لطفاً صبور باشید...")

    media_result = await download_media_engine(url)

    await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

    if isinstance(media_result, dict) and media_result.get("error") == "instagram_restricted":
        await message.answer(
            "❌ **محدودیت اینستاگرام:**\n\n"
            "اینستاگرام دسترسی به این پست را به صورت ناشناس و از روی سرورهای ابری مسدود کرده است. "
            "لطفاً لینک ویدیوهای **یوتیوب** یا **تیک‌تاک** را ارسال کنید.",
            reply_markup=back_to_menu(),
            parse_mode="Markdown"
        )
        await state.clear()
        return

    if not media_result:
        await message.answer("❌ متأسفانه دانلود از این لینک امکان‌پذیر نبود یا لینک نامعتبر است.", reply_markup=back_to_menu())
        await state.clear()
        return

    try:
        if media_result["type"] == "video":
            await message.answer_video(
                video=media_result["url"],
                caption="✅ ویدیو با موفقیت دانلود شد!",
                reply_markup=main_menu()
            )
        elif media_result["type"] == "file":
            file_input = FSInputFile(media_result["path"])
            await message.answer_document(
                document=file_input,
                caption="✅ فایل با موفقیت دانلود شد!",
                reply_markup=main_menu()
            )
            try:
                os.remove(media_result["path"])
            except:
                pass
        elif media_result["type"] == "picker":
            for u in media_result["urls"][:5]:
                await message.answer_photo(photo=u)
            await message.answer("✅ تصاویر اسلاید با موفقیت ارسال شدند.", reply_markup=main_menu())
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال فایل به تلگرام: {str(e)}", reply_markup=main_menu())

    await state.clear()

async def download_media_engine(url: str):
    is_instagram = "instagram.com" in url
    cobalt_url = "https://api.cobalt.tools/"
    payload = {
        "url": url,
        "videoQuality": "1080",
        "downloadMode": "auto"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(cobalt_url, json=payload, headers=headers, timeout=25) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    if status in ["tunnel", "redirect"]:
                        return {"type": "video", "url": data.get("url"), "filename": data.get("filename", "video.mp4")}
                    elif status == "picker":
                        items = [item.get("url") for item in data.get("picker", []) if item.get("url")]
                        if items:
                            return {"type": "picker", "urls": items}
    except Exception as e:
        print(f"Cobalt API error: {e}")

    if is_instagram:
        return {"error": "instagram_restricted"}

    def ytdlp_download():
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': 'downloads/%(id)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': True,
            'socket_timeout': 20,
        }
        os.makedirs('downloads', exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename

    try:
        loop = asyncio.get_event_loop()
        file_path = await loop.run_in_executor(None, ytdlp_download)
        if file_path and os.path.exists(file_path):
            return {"type": "file", "path": file_path}
    except Exception as e:
        print(f"yt-dlp fallback error: {e}")

    return None

# ==========================================
# بخش تبدیل ارز
# ==========================================
@router.callback_query(F.data == "menu_currency")
async def currency_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConverterStates.waiting_for_amount)
    await callback.message.edit_text(
        "💱 **تبدیل ارز**\n\n"
        "لطفاً مبلغ مورد نظر به تومان را وارد کنید تا معادل تقریبی آن به دلار محاسبه شود:",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ConverterStates.waiting_for_amount)
async def process_currency(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", "")
    if not text.isdigit():
        await message.answer("⚠️ لطفاً فقط مقدار عددی وارد کنید:", reply_markup=back_to_menu())
        return
    
    toman = int(text)
    approx_rate = 60000 
    usd = toman / approx_rate

    await message.answer(
        f"💵 مقدار {toman:,} تومان معادل تقریبی **{usd:.2f} دلار** است.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await state.clear()

# ==========================================
# بخش ماشین حساب پیشرفته
# ==========================================
@router.callback_query(F.data == "menu_calc")
async def calc_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalculatorStates.waiting_for_expression)
    await callback.message.edit_text(
        "🧮 **ماشین حساب**\n\n"
        "عبارت ریاضی خود را بفرستید (مثال: `125 * 4 + 50`):",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(CalculatorStates.waiting_for_expression)
async def process_calc(message: Message, state: FSMContext):
    expr = message.text.strip()
    allowed_chars = set("0123456789+-*/(). ")
    if not all(c in allowed_chars for c in expr):
        await message.answer("❌ عبارت وارد شده نامعتبر است.", reply_markup=back_to_menu())
        return

    try:
        result = eval(expr)
        await message.answer(f"🧮 نتیجه محاسبه:\n`{expr} = {result}`", reply_markup=main_menu(), parse_mode="Markdown")
    except Exception:
        await message.answer("❌ خطا در محاسبه!", reply_markup=back_to_menu())
    
    await state.clear()

# ==========================================
# راهنما
# ==========================================
@router.callback_query(F.data == "menu_help")
async def help_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ **راهنمای ربات**\n\n"
        "• این ربات روی سرور ابری Render فعال است.\n"
        "• برای شروع مجدد دستور /start را ارسال کنید.",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

# --- سرور وب کوچک برای گول زدن رندر (باز نگه داشتن پورت) ---
async def handle_ping(request):
    return web.Response(text="Bot is running and alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # رندر پورت را از متغیر محیطی PORT می‌خواند (پیش‌فرض 10000)
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Dummy web server running on port {port}")

# --- اجرای اصلی ربات و سرور وب به صورت همزمان ---
async def main():
    print("Bot is starting...")
    # ابتدا وب‌سایت ساختگی را بالا می‌آوریم تا پورت رندر پر شود
    await start_web_server()
    # سپس ربات تلگرام را استارت می‌کنیم
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
