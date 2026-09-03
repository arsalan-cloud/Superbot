import os
import asyncio
import logging
import re
import subprocess
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
        [KeyboardButton(text="📈 نرخ ارز"), KeyboardButton(text="🧮 ماشین‌حساب تبدیل ارز")],
        [KeyboardButton(text="ℹ️ درباره من"), KeyboardButton(text="👤 حساب کاربری")]
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

def rates_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 دلار ➡️ افغانی", callback_data="calc_USD_AFN"),
            InlineKeyboardButton(text="💶 یورو ➡️ افغانی", callback_data="calc_EUR_AFN")
        ],
        [
            InlineKeyboardButton(text="🔀 ماشین‌حساب جامع (تبدیل هر ارز به دلخواه)", callback_data="calc_custom")
        ]
    ])

def download_video_sync(url: str, output_path: str):
    ydl_opts = {
        'format': 'best',  # اصلاح فرمت برای اجرا بدون نیاز به ffmpeg در هاست ابری
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'mweb']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
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

@dp.message(F.text == "ℹ️ درباره من")
async def about_me_btn(message: types.Message):
    about_text = (
        "👨‍💻 **درباره سازنده و توسعه‌دهنده ربات:**\n\n"
        "▪️ **نام:** ارسلان حافظی (Arsalan Hafizi)\n"
        "▪️ **تاریخ تولد:** ۲۸ مهر ۱۳۷۹ (19 October 2000)\n"
        "▪️ **تحصیلات:** دیپلم فناوری اطلاعات (کامپیوتر)\n"
        "▪️ **شغل:** روزنامه‌نگار مستقل و تولیدکننده محتوای ویدیویی در یوتیوب 🎥\n\n"
        "🛠 این ربات همه‌کاره با زبان پایتون و کتابخانه‌های مدرن طراحی شده است تا ابزارهای کاربردی مانند دانلودر، نرخ ارز زنده و ماشین‌حساب را در اختیار شما قرار دهد."
    )
    await message.answer(about_text, parse_mode="Markdown")

@dp.message(F.text == "👤 حساب کاربری")
async def profile_btn(message: types.Message):
    username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    await message.answer(
        f"👤 **اطلاعات حساب کاربری شما در تلگرام:**\n\n"
        f"▪️ **نام:** {message.from_user.full_name}\n"
        f"▪️ **شناسه عددی:** `{message.from_user.id}`\n"
        f"▪️ **نام کاربری:** {username}",
        parse_mode="Markdown"
    )

# --- بخش نرخ آنلاین ارزها همراه با دکمه محاسبه در پایین ---
@dp.message(F.text.contains("نرخ ارز"))
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
            "⚡ *برای محاسبه و تبادله سریع ارزها، از دکمه‌های زیر استفاده کنید:*"
        )
        await status_msg.edit_text(text, parse_mode="Markdown", reply_markup=rates_inline_keyboard())
    except Exception as e:
        logging.error(f"Error fetching rates: {e}")
        await status_msg.edit_text("❌ خطا در دریافت نرخ‌های آنلاین.")

@dp.callback_query(F.data.startswith("calc_"))
async def inline_calc_handler(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "calc_custom":
        await state.set_state(CurrencyState.waiting_for_from_curr)
        await callback.message.answer("۱️⃣ **ارز مبدأ** (ارزی که دارید) را انتخاب کنید:", reply_markup=currency_picker_keyboard(), parse_mode="Markdown")
    else:
        _, from_c, to_c = data.split("_")
        await state.update_data(from_code=from_c, to_code=to_c)
        await state.set_state(CurrencyState.waiting_for_amount)
        await callback.message.answer(f"🔢 لطفاً مقدار **{CURRENCIES.get(from_c, from_c)}** را برای تبادله و تبدیل به **{CURRENCIES.get(to_c, to_c)}** وارد کنید:")
    await callback.answer()

@dp.message(F.text == "🧮 ماشین‌حساب تبدیل ارز")
async def converter_section(message: types.Message):
    await message.answer("🧮 **ماشین‌حساب هوشمند و تبادله ارز**\n\nیکی از گزینه‌های سریع زیر را انتخاب کنید یا دکمه **تبدیل ارز دلخواه** را بزنید:", reply_markup=currency_menu())

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
    await message.answer(f"۲️⃣ قصد دارید **{CURRENCIES[from_code]}** را به چه ارزی تبادله کنید؟ (**ارز مقصد** را انتخاب کنید):", reply_markup=currency_picker_keyboard(), parse_mode="Markdown")

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
            f"📊 **نرخ زنده تبادله:**\n"
            f"🔹 **۱ {CURRENCIES.get(from_code)}** = **{unit_price:,.2f} {CURRENCIES.get(to_code)}**\n\n"
            f"🔢 اکنون مقدار **{CURRENCIES.get(from_code)}** را جهت تبادله وارد کنید (مثلاً: 100):",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error fetching unit rate: {e}")
        await status_msg.edit_text("❌ خطا در دریافت نرخ.")

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
            f"📊 **نرخ زنده تبادله:**\n"
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

    status_msg = await message.answer("⏳ در حال محاسبه دقیق تبادله...")
    try:
        rates = await get_live_rates()
        from_rate = 1.0 if from_code == 'USD' else rates.get(from_code, 1.0)
        to_rate = 1.0 if to_code == 'USD' else rates.get(to_code, 1.0)

        unit_price = (1.0 / from_rate) * to_rate
        result = amount * unit_price

        res_text = (
            f"✅ **نتیجه تبادله و محاسبات:**\n\n"
            f"📌 **نرخ مبنا:** ۱ {CURRENCIES.get(from_code, from_code)} = {unit_price:,.2f} {CURRENCIES.get(to_code, to_code)}\n"
            f"🔹 **مبلغ پرداختی:** {amount:,.2f} {CURRENCIES.get(from_code, from_code)}\n"
            f"🔸 **مبلغ دریافتی:** **{result:,.2f} {CURRENCIES.get(to_code, to_code)}**\n\n"
            f"🔄 *محاسبه شده بر اساس نرخ زنده بازار*"
        )
        await status_msg.edit_text(res_text, parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logging.error(f"Conversion error: {e}")
        await status_msg.edit_text("❌ خطا در فرآیند محاسبه.")

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
            await message.answer_video(video=FSInputFile(file_path), caption="✅ دانلود با موفقیت انجام شد!")
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ خطایی در دانلود فایل رخ داد. لینک نامعتبر است.")

    except Exception as e:
        logging.error(f"Download error: {e}")
        await status_msg.edit_text("❌ دانلود ناموفق بود. ممکن است ویدیو خصوصی باشد یا لایو/موزیک‌پارتکشن باشد.")

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
