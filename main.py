import asyncio, os, json, subprocess, random, time, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ КРИТИЧЕСКИЕ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СИСТЕМНЫЕ ФАЙЛЫ ] ---
USERS_DB = "quantum_users.json"
LOG_FILE = "quantum.log"
STATS = {"searches": 0, "errors": 0}

# Инициализация базы данных
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
    elif action == "ban" and u_id in db:
        db[u_id]["banned"] = not db[u_id]["banned"]
    
    with open(USERS_DB, "w") as f: json.dump(db, f, indent=4)
    return db

# --- [ МЕНЮ ПОЛЬЗОВАТЕЛЯ ] ---
def kb_user_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Найти товар")],
        [KeyboardButton(text="👤 Мой Профиль"), KeyboardButton(text="📜 История")],
        [KeyboardButton(text="🆘 Поддержка"), KeyboardButton(text="⚙️ Настройки")]
    ], resize_keyboard=True)

# --- [ МЕНЮ АДМИНА ] ---
def kb_admin_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛡 СЕРВЕР"), KeyboardButton(text="🔋 ПОЛЬЗОВАТЕЛИ")],
        [KeyboardButton(text="📣 РАССЫЛКА"), KeyboardButton(text="☢️ ТЕРМИНАЛ")],
        [KeyboardButton(text="🔙 В МЕНЮ ЮЗЕРА")]
    ], resize_keyboard=True)

def kb_admin_users_manage():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📁 Дамп Базы"), KeyboardButton(text="🚫 Бан/Разбан по ID")],
        [KeyboardButton(text="🔙 Назад в Админку")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    db_core("reg", message.from_user.id)
    welcome_text = (
        f"🛡 **CHIIP QUANTUM v15.0 АКТИВИРОВАН**\n\n"
        f"Привет, {message.from_user.first_name}!\n"
        f"Я использую ИИ и Playwright для поиска товаров по всем топ-площадкам."
    )
    await message.answer(welcome_text, reply_markup=kb_user_main(), parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🧬 **QUANTUM CORE: ПАНЕЛЬ УПРАВЛЕНИЯ**", reply_markup=kb_admin_main())

# --- [ ФУНКЦИИ ЮЗЕРА ] ---

@dp.message(F.text == "👤 Мой Профиль")
async def user_profile(message: types.Message):
    db = db_core()
    user = db.get(str(message.from_user.id))
    text = (f"👤 **ВАШ ПРОФИЛЬ**\n\n"
            f"🆔 ID: `{message.from_user.id}`\n"
            f"📅 Регистрация: {user['joined']}\n"
            f"🔎 Поисков: {user['searches']}")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📜 История")
async def user_history(message: types.Message):
    db = db_core()
    hist = db.get(str(message.from_user.id), {}).get("history", [])
    text = "📜 **ПОСЛЕДНИЕ ЗАПРОСЫ:**\n\n" + ("\n".join([f"- {i}" for i in hist]) if hist else "Пусто")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🔍 Найти товар")
async def find_prompt(message: types.Message):
    await message.answer("Просто введи название товара, и я начну поиск!")

# --- [ ФУНКЦИИ АДМИНА ] ---

@dp.message(F.text == "🔋 ПОЛЬЗОВАТЕЛИ")
async def admin_users(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Управление пользователями:", reply_markup=kb_admin_users_manage())

@dp.message(F.text == "📁 Дамп Базы")
async def admin_dump(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        db_core() # Убедиться, что файл создан
        await message.answer_document(FSInputFile(USERS_DB), caption="📦 Актуальная база QUANTUM")

@dp.message(F.text == "🛡 СЕРВЕР")
async def admin_server(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        mem = subprocess.getoutput("free -m | grep Mem | awk '{print $3}'")
        uptime = subprocess.getoutput("uptime -p")
        db = db_core()
        text = (f"🛡 **SERVER STATUS**\n\n"
                f"🧠 RAM Used: {mem}MB\n"
                f"⏱ Uptime: {uptime}\n"
                f"👥 Всего юзеров: {len(db)}\n"
                f"📊 Общих поисков: {STATS['searches']}")
        await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🔙 В МЕНЮ ЮЗЕРА")
async def back_to_user(message: types.Message):
    await message.answer("Вы вернулись в обычный режим.", reply_markup=kb_user_main())

@dp.message(F.text == "🔙 Назад в Админку")
async def back_to_admin(message: types.Message):
    await message.answer("Главное меню админа:", reply_markup=kb_admin_main())

# --- [ ГЛОБАЛЬНЫЙ ПОИСК (ИСПРАВЛЕННЫЙ) ] ---

@dp.message()
async def global_handler(message: types.Message):
    # 1. Проверка на бан
    db = db_core()
    user_data = db.get(str(message.from_user.id))
    if user_data and user_data.get("banned"):
        return await message.answer("🚫 Вы заблокированы в системе.")

    # 2. ИГНОРИРУЕМ КНОПКИ И КОМАНДЫ (Чтобы не искать их в Google)
    reserved_buttons = [
        "👤 Мой Профиль", "📜 История", "🆘 Поддержка", "⚙️ Настройки", "🔍 Найти товар",
        "🛡 СЕРВЕР", "🔋 ПОЛЬЗОВАТЕЛИ", "📣 РАССЫЛКА", "☢️ ТЕРМИНАЛ", "🔙 В МЕНЮ ЮЗЕРА",
        "📁 Дамп Базы", "🚫 Бан/Разбан по ID", "🔙 Назад в Админку", "📊 Полная Статистика", "📜 Логи", "🔙 Назад"
    ]
    if message.text in reserved_buttons or message.text.startswith("/"):
        # Если это текст кнопки, но он попал сюда — значит мы просто ничего не делаем или логируем
        return

    # 3. ЛОГИКА ПОИСКА
    STATS["searches"] += 1
    db_core("inc", message.from_user.id, message.text)
    
    status = await message.answer(f"🛰 *QUANTUM сканирует сети по запросу: {message.text}...*", parse_mode="Markdown")
    
    # Определение сайтов
    query = message.text.lower()
    sites = {"Prom": f"https://prom.ua/search?search_term={query}", "OLX": f"https://www.olx.ua/d/uk/list/q-{query}"}
    
    if any(x in query for x in ["bmw", "mazda", "audi", "авто", "машина"]):
        sites["AutoRia"] = f"https://auto.ria.com/uk/search/?q={query}"

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = await browser.new_context(user_agent="Mozilla/5.0")
            
            final_results = []
            for name, url in sites.items():
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                # Базовый парсинг ссылок
                links = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a'))
                        .filter(a => a.innerText.length > 20 && a.href.includes('http'))
                        .slice(0, 1)
                        .map(a => ({t: a.innerText.trim(), h: a.href}))
                """)
                for l in links:
                    final_results.append(f"📦 **{name}**: {l['t'][:50]}...\n🔗 {l['h']}")
                await page.close()
            
            await browser.close()
            await status.delete()
            
            if final_results:
                await message.answer("✅ **РЕЗУЛЬТАТЫ QUANTUM:**\n\n" + "\n\n".join(final_results), disable_web_page_preview=True)
            else:
                await message.answer("❌ Ничего не найдено. Попробуй уточнить запрос.")
                
        except Exception as e:
            await status.edit_text(f"⚠️ Ошибка поиска: {str(e)[:50]}")

# --- [ ЗАПУСК ] ---
async def main():
    subprocess.run(["playwright", "install", "chromium"])
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="QUANTUM_RUNNING"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())