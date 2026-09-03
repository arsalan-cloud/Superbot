import os
import asyncio
import logging
import re
import subprocess
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
import aiohttp
import yt_dlp

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

if not TOKEN:
    raise ValueError("خطا: توکن ربات (BOT_TOKEN) ست نشده است.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

URL_PATTERN = re.compile(r'https?://(www\.)?(instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/.+')

# --- تعریف حالات FSM برای محاسبه ارز ---
class CurrencyState(StatesGroup):
    waiting_for_from_curr = State()
    waiting_for_to_curr = State()
    waiting_for_amount = State()

# --- لیست ارزهای پشتیبانی‌شده ---
CURRENCIES = {
    "AFN": "افغانی 🇦🇫",
    "USD": "دلار آمریکا 💵",
    "EUR": "یورو 💶",
    "TRY": "لیره ترکیه 🇹🇷",
    "PKR": "کلدار پاکستان 🇵🇰",
    "IRR": "تومان ایران 🇮🇷",
    "AED": "درهم امارات 🇦🇪"
}

# --- کیبوردهای ربات ---
def main_menu():
    kb = [
        [KeyboardButton(text="📥 دانلودر شبکه‌های اجتماعی"), KeyboardButton(text="🧠 هوش مصنوعی")],
        [KeyboardButton(text="📊 نرخ آنلاین تمام ارزها"), KeyboardButton(text="🧮 ماشین‌حساب تبدیل ارز")],
        [KeyboardButton(text="👤 حساب کاربری")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def currency_menu():
    kb = [
        [KeyboardButton(text="💵 دلار به افغانی 🇦🇫"), KeyboardButton(text="🇦🇫 افغانی به دلار 💵")],
        [KeyboardButton(text="💶 یورو به افغانی 🇦🇫"), KeyboardButton(text="🇦🇫 افغانی به یورو 💶")],
        [KeyboardButton(text="🇹🇷 لیره به افغانی 🇦🇫"), KeyboardButton(text="🇦🇫 افغانی به لیره 🇹🇷")],
        [KeyboardButton(text="🔀 تبدیل ارز دلخواه (هر ارزی به هر ارزی)")],
        [KeyboardButton(text="🔙 بازگشت به منوی اصلی")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def currency_picker_keyboard():
    kb = [
        [KeyboardButton(text="AFN - افغانی 🇦🇫"), KeyboardButton(text="USD - دلار آمریکا 💵")],
        [KeyboardButton(text="EUR - یورو 💶"), KeyboardButton(text="TRY - لیره ترکیه 🇹🇷")],
        [KeyboardButton(text="PKR - کلدار 🇵🇰"), KeyboardButton(text="IRR - تومان 🇮🇷")],
        [KeyboardButton(text="AED - درهم 🇦🇪")],
        [KeyboardButton(text="🔙 بازگشت به منوی اصلی")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- توابع پردازش و پارت‌بندی ویدیو ---
def get_video_duration(file_path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def split_video_if_needed(file_path: str, max_size_mb: int = 45) -> list[str]:
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        return [file_path]

    duration = get_video_duration(file_path)
    if duration <= 0:
        return [file_path]

    num_parts = int(file_size_mb // max_size_mb) + 1
    part_duration = duration / num_parts
    
    parts = []
    base_name, ext = os.path.splitext(file_path)
    
    for i in range(num_parts):
        start_time = i * part_duration
        part_path = f"{base_name}_part{i+1}{ext}"
        cmd = [
            "ffmpeg", "-y", "-ss", str(start_time), "-i", file_path,
            "-t", str(part_duration), "-c", "copy", part_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
            parts.append(part_path)

    if parts:
        os.remove(file_path)
        return parts
    return [file_path]

def download_video_sync(url: str, output_path: str):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb', 'android']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# --- دریافت نرخ‌های زنده از اینترنت ---
async def get_live_rates():
    async with aiohttp.ClientSession() as session:
        async with session.get("https://open.er-api.com/v6/latest/USD", timeout=10) as resp:
            fiat_data = await resp.json()
        async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10) as resp_crypto:
            crypto_data = await resp_crypto.json()
            
    rates = fiat_data.get("rates", {})
    rates["BTC"] = float(crypto_data.get("price", 0))
    return rates

# --- هندلرهای منو و دستورات اصلی ---
@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"سلام {message.from_user.first_name} عزیز! 👋\n\nبه **ابر ربات همه‌کاره** خوش آمدید.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔙 بازگشت به منوی اصلی")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("به منوی اصلی بازگشتید:", reply_markup=main_menu())

@dp.message(F.text == "📥 دانلودر شبکه‌های اجتماعی")
async def downloader_btn(message: types.Message):
    await message.answer("📥 لینک ویدیو از اینستاگرام، تیک‌تاک یا یوتیوب را ارسال کنید تا با بالاترین کیفیت دانلود شود.")

@dp.message(F.text == "🧠 هوش مصنوعی")
async def ai_btn(message: types.Message):
    await message.answer("🧠 بخش هوش مصنوعی به‌زودی فعال می‌شود.")

@dp.message(F.text == "👤 حساب کاربری")
async def profile_btn(message: types.Message):
    username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    await message.answer(
        f"👤 **اطلاعات حساب کاربری شما:**\n\n"
        f"▪️ **نام:** {message.from_user.full_name}\n"
        f"▪️ **شناسه عددی:** `{message.from_user.id}`\n"
        f"▪️ **نام کاربری:** {username}",
        parse_mode="Markdown"
    )

# --- بخش نرخ آنلاین تمام ارزها (مستقل) ---
@dp.message(F.text == "📊 نرخ آنلاین تمام ارزها")
async def show_all_rates(message: types.Message):
    status_msg = await message.answer("🔄 در حال دریافت آخرین نرخ‌های زنده بازار...")
    try:
        rates = await get_live_rates()
        usd_afn = rates.get("AFN", 1)
        usd_eur = rates.get("EUR", 1)
        usd_try = rates.get("TRY", 1)
        usd_pkr = rates.get("PKR", 1)
        usd_irr = rates.get("IRR", 1)
        usd_aed = rates.get("AED", 1)
        btc = rates.get("BTC", 0)

        eur_afn = usd_afn / usd_eur
        try_afn = usd_afn / usd_try
        pkr_afn = usd_afn / usd_pkr
        aed_afn = usd_afn / usd_aed
        toman_afn = (usd_afn / usd_irr) * 10

        text = (
            "📈 **قیمت‌های لحظه‌ای بازار ارز**\n\n"
            f"💵 **۱ دلار آمریکا:** {usd_afn:.2f} افغانی 🇦🇫\n"
            f"💶 **۱ یورو اروپا:** {eur_afn:.2f} افغانی 🇦🇫\n"
            f"🇹🇷 **۱ لیره ترکیه:** {try_afn:.2f} افغانی 🇦🇫\n"
            f"🇦🇪 **۱ درهم امارات:** {aed_afn:.2f} افغانی 🇦🇫\n"
            f"🇵🇰 **۱,۰۰۰ کلدار پاکستان:** {(pkr_afn * 1000):.2f} افغانی 🇦🇫\n"
            f"🇮🇷 **۱,۰۰۰,۰۰۰ تومان ایران:** {(toman_afn * 1000000):,.0f} افغانی 🇦🇫\n"
            f"💶 **۱ یورو به دلار:** {(1/usd_eur):.2f} USD 💵\n"
            f"🪙 **بیت‌کوین:** ${btc:,.2f}\n\n"
            "⚡ *برای محاسبه و تبدیل دقیق هر ارز، از بخش ماشین‌حساب تبدیل ارز استفاده کنید.*"
        )
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error fetching rates: {e}")
        await status_msg.edit_text("❌ خطا در دریافت نرخ‌های آنلاین.")

# --- بخش ماشین‌حساب و تبدیل ارز هوشمند ---
@dp.message(F.text == "🧮 ماشین‌حساب تبدیل ارز")
async def converter_section(message: types.Message):
    await message.answer("🧮 **ماشین‌حساب هوشمند تبدیل ارز**\n\nیکی از گزینه‌های سریع زیر را انتخاب کنید یا دکمه **تبدیل ارز دلخواه** را بزنید:", reply_markup=currency_menu())

@dp.message(F.text == "🔀 تبدیل ارز دلخواه (هر ارزی به هر ارزی)")
async def start_custom_conversion(message: types.Message, state: FSMContext):
    await state.set_state(CurrencyState.waiting_for_from_curr)
    await message.answer("۱️⃣ **ارز مبدأ** (ارزی که دارید) را انتخاب کنید:", reply_markup=currency_picker_keyboard(), parse_mode="Markdown")

@dp.message(CurrencyState.waiting_for_from_curr)
async def process_from_curr(message: types.Message, state: FSMContext):
    from_code = message.text.split(" - ")[0].strip()
    if from_code not in CURRENCIES:
        await message.answer("⚠️ لطفاً یکی از ارزهای موجود در کیبورد را انتخاب کنید:")
        return

    await state.update_data(from_code=from_code)
    await state.set_state(CurrencyState.waiting_for_to_curr)
    await message.answer(f"۲️⃣ قصد دارید **{CURRENCIES[from_code]}** را به چه ارزی تبدیل کنید؟ (**ارز مقصد** را انتخاب کنید):", reply_markup=currency_picker_keyboard(), parse_mode="Markdown")

@dp.message(CurrencyState.waiting_for_to_curr)
async def process_to_curr(message: types.Message, state: FSMContext):
    to_code = message.text.split(" - ")[0].strip()
    if to_code not in CURRENCIES:
        await message.answer("⚠️ لطفاً یکی از ارزهای موجود در کیبورد را انتخاب کنید:")
        return

    await state.update_data(to_code=to_code)
    data = await state.get_data()
    from_code = data['from_code']

    status_msg = await message.answer("⏳ در حال استعلام نرخ زنده جفت‌ارز...")
    try:
        rates = await get_live_rates()
        from_rate = 1.0 if from_code == 'USD' else rates.get(from_code, 1.0)
        to_rate = 1.0 if to_code == 'USD' else rates.get(to_code, 1.0)
        unit_price = (1.0 / from_rate) * to_rate

        await state.set_state(CurrencyState.waiting_for_amount)
        await status_msg.edit_text(
            f"📊 **نرخ زنده تبدیل:**\n"
            f"🔹 **۱ {CURRENCIES.get(from_code)}** = **{unit_price:,.2f} {CURRENCIES.get(to_code)}**\n\n"
            f"🔢 اکنون مقدار **{CURRENCIES.get(from_code)}** را جهت تبدیل وارد کنید (مثلاً: 100):",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error fetching unit rate: {e}")
        await status_msg.edit_text("❌ خطا در دریافت نرخ.")

# جفت‌ارزهای میانبر سریع
FAST_PAIRS = {
    "💵 دلار به افغانی 🇦🇫": ("USD", "AFN"),
    "🇦🇫 افغانی به دلار 💵": ("AFN", "USD"),
    "💶 یورو به افغانی 🇦🇫": ("EUR", "AFN"),
    "🇦🇫 افغانی به یورو 💶": ("AFN", "EUR"),
    "🇹🇷 لیره به افغانی 🇦🇫": ("TRY", "AFN"),
    "🇦🇫 افغانی به لیره 🇹🇷": ("AFN", "TRY")
}

@dp.message(F.text.in_(FAST_PAIRS.keys()))
async def fast_pair_select(message: types.Message, state: FSMContext):
    from_code, to_code = FAST_PAIRS[message.text]
    await state.update_data(from_code=from_code, to_code=to_code)
    
    status_msg = await message.answer("⏳ در حال استعلام نرخ زنده...")
    try:
        rates = await get_live_rates()
        from_rate = 1.0 if from_code == 'USD' else rates.get(from_code, 1.0)
        to_rate = 1.0 if to_code == 'USD' else rates.get(to_code, 1.0)
        unit_price = (1.0 / from_rate) * to_rate

        await state.set_state(CurrencyState.waiting_for_amount)
        await status_msg.edit_text(
            f"📊 **نرخ زنده تبدیل:**\n"
            f"🔹 **۱ {CURRENCIES.get(from_code, from_code)}** = **{unit_price:,.2f} {CURRENCIES.get(to_code, to_code)}**\n\n"
            f"🔢 اکنون مقدار **{CURRENCIES.get(from_code, from_code)}** را وارد کنید:",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Fast pair rate error: {e}")
        await status_msg.edit_text("❌ خطا در دریافت نرخ.")

@dp.message(CurrencyState.waiting_for_amount)
async def process_conversion_amount(message: types.Message, state: FSMContext):
    if not message.text.replace('.', '', 1).isdigit():
        await message.answer("⚠️ لطفاً فقط عدد وارد کنید:")
        return

    amount = float(message.text)
    data = await state.get_data()
    from_code = data['from_code']
    to_code = data['to_code']

    status_msg = await message.answer("⏳ در حال محاسبه دقیق...")
    try:
        rates = await get_live_rates()
        from_rate = 1.0 if from_code == 'USD' else rates.get(from_code, 1.0)
        to_rate = 1.0 if to_code == 'USD' else rates.get(to_code, 1.0)

        unit_price = (1.0 / from_rate) * to_rate
        result = amount * unit_price

        res_text = (
            f"✅ **نتیجه محاسبه هوشمند:**\n\n"
            f"📌 **نرخ مبنا:** ۱ {CURRENCIES.get(from_code, from_code)} = {unit_price:,.2f} {CURRENCIES.get(to_code, to_code)}\n"
            f"🔹 **مقدار ورودی:** {amount:,.2f} {CURRENCIES.get(from_code, from_code)}\n"
            f"🔸 **معادل دریافتی:** **{result:,.2f} {CURRENCIES.get(to_code, to_code)}**\n\n"
            f"🔄 *محاسبه شده بر اساس نرخ زنده بازار*"
        )
        await status_msg.edit_text(res_text, parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logging.error(f"Conversion error: {e}")
        await status_msg.edit_text("❌ خطا در فرآیند محاسبه.")

# --- بخش دانلودر شبکه‌های اجتماعی ---
@dp.message(F.text.regexp(URL_PATTERN))
async def process_video_download(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ در حال دریافت و بررسی لینک ویدیو...")
    
    file_id = message.from_user.id
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_id}_%(id)s.%(ext)s"
    
    try:
        file_path = await asyncio.to_thread(download_video_sync, url, output_template)
        
        if os.path.exists(file_path):
            await status_msg.edit_text("⚙️ در حال بررسی حجم فایل و آماده‌سازی...")
            file_parts = await asyncio.to_thread(split_video_if_needed, file_path)
            
            total_parts = len(file_parts)
            for idx, part in enumerate(file_parts, 1):
                caption = f"✅ دانلود با موفقیت انجام شد!" if total_parts == 1 else f"📦 پارت {idx} از {total_parts}"
                await status_msg.edit_text(f"📤 در حال ارسال پارت {idx} از {total_parts} به تلگرام...")
                await message.answer_video(video=FSInputFile(part), caption=caption)
                os.remove(part)
            
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ خطایی در دانلود فایل رخ داد. لینک نامعتبر است.")

    except Exception as e:
        logging.error(f"Download error: {e}")
        await status_msg.edit_text("❌ دانلود ناموفق بود. ممکن است ویدیو خصوصی باشد یا پلتفرم محدودیت ایجاد کرده باشد.")

# --- سرور بررسی سلامت (Health Check برای Render) ---
async def handle_health(request):
    return web.Response(text="Superbot server is alive and running!")

async def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("🤖 Superbot is running successfully...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
