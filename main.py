import asyncio, os, json, subprocess, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

USERS_DB = "quantum_users.json"
STATS = {"searches": 0}

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

def kb_user_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Найти товар")],
        [KeyboardButton(text="👤 Мой Профиль"), KeyboardButton(text="📜 История")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    db_core("reg", message.from_user.id)
    await message.answer("🛡 **QUANTUM v15.0 ONLINE**", reply_markup=kb_user_main(), parse_mode="Markdown")

@dp.message(F.text == "🔍 Найти товар")
async def find_prompt(message: types.Message):
    await message.answer("Введите название товара для поиска:")

@dp.message()
async def global_handler(message: types.Message):
    if message.text in ["🔍 Найти товар", "👤 Мой Профиль", "📜 История"] or message.text.startswith("/"):
        return

    STATS["searches"] += 1
    db_core("inc", message.from_user.id, message.text)
    status = await message.answer(f"🛰 *Ищу: {message.text}...*", parse_mode="Markdown")
    
    query = message.text.lower()
    sites = {
        "Prom": f"https://prom.ua/search?search_term={query}", 
        "OLX": f"https://www.olx.ua/d/uk/list/q-{query}"
    }

    async with async_playwright() as p:
        try:
            # Запуск Chromium с флагами для работы в Docker/Render
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            context = await browser.new_context(user_agent="Mozilla/5.0")
            
            final_results = []
            for name, url in sites.items():
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
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
                await message.answer("✅ **РЕЗУЛЬТАТЫ:**\n\n" + "\n\n".join(final_results), disable_web_page_preview=True)
            else:
                await message.answer("❌ Ничего не найдено.")
        except Exception as e:
            await status.edit_text(f"⚠️ Ошибка парсинга: {str(e)[:100]}")

# --- [ ЗАПУСК ВЕБ-СЕРВЕРА И БОТА ] ---
async def handle(request): return web.Response(text="QUANTUM_ALIVE")

async def main():
    # Пытаемся установить зависимости браузера прямо при старте
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
        # Это докачивает системные либы, если их нет
        subprocess.run(["playwright", "install-deps"], check=True)
    except:
        pass

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())