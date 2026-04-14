import asyncio, os, json, subprocess, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ КОНФИГ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446  # Твой ID проверен
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

USERS_DB = "quantum_users.json"

def db_core(action="get", u_id=None, data=None):
    if not os.path.exists(USERS_DB): 
        with open(USERS_DB, "w") as f: json.dump({}, f)
    with open(USERS_DB, "r") as f:
        db = json.load(f)
    u_id = str(u_id)
    if action == "reg" and u_id not in db:
        db[u_id] = {"joined": datetime.now().strftime("%d.%m.%Y"), "searches": 0, "history": [], "banned": False}
    elif action == "inc" and u_id in db:
        db[u_id]["searches"] += 1
        db[u_id]["history"] = ([data] + db[u_id]["history"])[:5]
    with open(USERS_DB, "w") as f: json.dump(db, f, indent=4)
    return db

# --- [ КЛАВИАТУРЫ ] ---
def get_main_kb(user_id):
    buttons = []
    # Если ты админ — добавляем кнопку терминала первой
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="🔱 АДМИН-ТЕРМИНАЛ")])
    
    buttons.extend([
        [KeyboardButton(text="🔍 Найти товар")],
        [KeyboardButton(text="👤 Мой Профиль"), KeyboardButton(text="📜 История")],
        [KeyboardButton(text="🆘 Поддержка"), KeyboardButton(text="⚙️ Настройки")]
    ])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛡 СТАТУС СЕРВЕРА"), KeyboardButton(text="📁 ДАМП БД")],
        [KeyboardButton(text="🐚 ТЕРМИНАЛ (BASH)")],
        [KeyboardButton(text="🔙 НАЗАД")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    db_core("reg", message.from_user.id)
    await message.answer(
        f"🛡 **CHIIP QUANTUM v15.0 АКТИВИРОВАН**\n\nПривет, {message.from_user.first_name}!",
        reply_markup=get_main_kb(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔱 АДМИН-ТЕРМИНАЛ")
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🧬 **QUANTUM CORE: ПАНЕЛЬ УПРАВЛЕНИЯ**", reply_markup=get_admin_kb())

@dp.message(F.text == "🛡 СТАТУС СЕРВЕРА")
async def server_status(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        mem = subprocess.getoutput("free -m | grep Mem | awk '{print $3}'")
        uptime = subprocess.getoutput("uptime -p")
        await message.answer(f"📊 **SERVER:**\nRAM Used: {mem}MB\nUptime: {uptime}", parse_mode="Markdown")

@dp.message(F.text == "🔙 НАЗАД")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_kb(message.from_user.id))

@dp.message(F.text == "👤 Мой Профиль")
async def profile(message: types.Message):
    user = db_core().get(str(message.from_user.id))
    await message.answer(f"👤 **ПРОФИЛЬ**\nID: `{message.from_user.id}`\nПоисков: {user['searches']}")

@dp.message(F.text == "🔍 Найти товар")
async def find_prompt(message: types.Message):
    await message.answer("Введите название товара:")

# --- [ ПОИСК / GLOBAL HANDLER ] ---
@dp.message()
async def global_handler(message: types.Message):
    # СПИСОК ИСКЛЮЧЕНИЙ (чтобы бот не искал текст кнопок)
    nav_buttons = ["🔍 Найти товар", "👤 Мой Профиль", "📜 История", "🆘 Поддержка", "⚙️ Настройки", 
                   "🔱 АДМИН-ТЕРМИНАЛ", "🛡 СТАТУС СЕРВЕРА", "📁 ДАМП БД", "🐚 ТЕРМИНАЛ (BASH)", "🔙 НАЗАД"]
    
    if message.text in nav_buttons or message.text.startswith("/"):
        return

    db_core("inc", message.from_user.id, message.text)
    status = await message.answer(f"🛰 *Ищу: {message.text}...*", parse_mode="Markdown")
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = await browser.new_page()
            # Для примера только OLX, чтобы не висло
            await page.goto(f"https://www.olx.ua/d/uk/list/q-{message.text}/", timeout=30000)
            
            res = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a'))
                    .filter(a => a.innerText.length > 20 && a.href.includes('http'))
                    .slice(0, 2)
                    .map(a => ({t: a.innerText.trim(), h: a.href}))
            """)
            await browser.close()
            await status.delete()

            if res:
                out = "\n\n".join([f"📦 {i['t'][:50]}...\n🔗 {i['h']}" for i in res])
                await message.answer(f"✅ **РЕЗУЛЬТАТЫ:**\n\n{out}", disable_web_page_preview=True)
            else:
                await message.answer("❌ Ничего не найдено.")
        except Exception as e:
            await status.edit_text(f"⚠️ Ошибка: {str(e)[:50]}")

# --- [ ЗАПУСК ] ---
async def handle(request): return web.Response(text="ONLINE")

async def main():
    try: subprocess.run(["playwright", "install", "chromium"], check=True)
    except: pass
    
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())