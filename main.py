import asyncio, os, json, subprocess
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446 
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

DB_FILE = "quantum_db.json"

def manage_db(action="get", u_id=None, val=None):
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f: json.dump({"users": {}, "stats": {"total": 0}}, f)
    with open(DB_FILE, "r") as f:
        db = json.load(f)
    
    u_id = str(u_id) if u_id else None
    if action == "reg" and u_id not in db["users"]:
        db["users"][u_id] = {"date": datetime.now().strftime("%d.%m.%Y"), "count": 0, "history": []}
    elif action == "inc" and u_id:
        db["users"][u_id]["count"] += 1
        db["stats"]["total"] += 1
        if val: db["users"][u_id]["history"] = ([val] + db["users"][u_id]["history"])[:5]
    
    with open(DB_FILE, "w") as f: json.dump(db, f, indent=4)
    return db

# --- [ КЛАВИАТУРЫ ] ---
def get_main_kb(u_id):
    rows = []
    if u_id == ADMIN_ID:
        rows.append([KeyboardButton(text="🔱 АДМИН-ТЕРМИНАЛ")])
    rows.append([KeyboardButton(text="🔍 Найти товар")])
    rows.append([KeyboardButton(text="👤 Мой Профиль"), KeyboardButton(text="📜 История")])
    rows.append([KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🆘 Поддержка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛡 СТАТУС"), KeyboardButton(text="📁 БЭКАП")],
        [KeyboardButton(text="🔙 НАЗАД")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    manage_db("reg", message.from_user.id)
    await message.answer(
        f"🛡 **CHIIP QUANTUM v15.0 АКТИВИРОВАН**\n\nПривет, {message.from_user.first_name}!\nЯ использую ИИ и Playwright для поиска товаров.",
        reply_markup=get_main_kb(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔱 АДМИН-ТЕРМИНАЛ")
async def adm_menu(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🧬 **QUANTUM CORE: ПАНЕЛЬ УПРАВЛЕНИЯ**", reply_markup=get_admin_kb())

@dp.message(F.text == "👤 Мой Профиль")
async def profile_view(message: types.Message):
    db = manage_db()
    u = db["users"].get(str(message.from_user.id), {})
    text = (f"👤 **ВАШ ПРОФИЛЬ**\n\n🆔 ID: `{message.from_user.id}`\n"
            f"📅 Регистрация: {u.get('date', 'Unknown')}\n🔎 Поисков: {u.get('count', 0)}")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📜 История")
async def history_view(message: types.Message):
    db = manage_db()
    h = db["users"].get(str(message.from_user.id), {}).get("history", [])
    text = "📜 **ПОСЛЕДНИЕ ЗАПРОСЫ:**\n\n" + ("\n".join(h) if h else "Пусто")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🔙 НАЗАД")
async def back_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_kb(message.from_user.id))

# --- [ ЯДРО ПОИСКА ] ---
@dp.message()
async def search_handler(message: types.Message):
    # Блокируем поиск, если нажата любая кнопка меню
    nav = ["🔍 Найти товар", "👤 Мой Профиль", "📜 История", "⚙️ Настройки", "🆘 Поддержка", 
           "🔱 АДМИН-ТЕРМИНАЛ", "🛡 СТАТУС", "📁 БЭКАП", "🔙 НАЗАД"]
    if message.text in nav or message.text.startswith("/"):
        if message.text == "🔍 Найти товар":
            await message.answer("Введите название товара для поиска:")
        return

    manage_db("inc", message.from_user.id, message.text)
    status = await message.answer(f"🛰 *Ищу: {message.text}...*", parse_mode="Markdown")
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            page = await browser.new_page()
            # Поиск на OLX (пример)
            await page.goto(f"https://www.olx.ua/d/uk/list/q-{message.text}/", timeout=30000)
            
            items = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a'))
                    .filter(a => a.innerText.length > 25 && a.href.includes('d/uk/obyavlenie'))
                    .slice(0, 3)
                    .map(a => ({t: a.innerText.split('\\n')[0], h: a.href}))
            """)
            await browser.close()
            await status.delete()

            if items:
                res = "\n\n".join([f"📦 {i['t']}\n🔗 {i['h']}" for i in items])
                await message.answer(f"✅ **РЕЗУЛЬТАТЫ:**\n\n{res}", disable_web_page_preview=True)
            else:
                await message.answer("❌ Ничего не найдено. Попробуйте другой запрос.")
        except Exception as e:
            await status.edit_text(f"⚠️ Ошибка системы поиска. Попробуйте позже.")

# --- [ СЕРВЕР ] ---
async def health(request): return web.Response(text="QUANTUM_LIVE")

async def main():
    # Важный фикс: установка браузера перед запуском бота
    subprocess.run(["playwright", "install", "chromium"])
    
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())