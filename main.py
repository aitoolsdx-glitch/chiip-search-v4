import asyncio, os, json, subprocess, logging, random, time, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from playwright.async_api import async_playwright
from aiohttp import web
import openai

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ СИСТЕМНЫЕ ПЕРЕМЕННЫЕ ] ---
START_TIME = time.time()
USERS_DB = "apocalypse_users.json"
BLACK_LIST = "blacklist.json"
LOG_FILE = "system.log"
STATS = {"searches": 0, "errors": 0, "blocked": 0}
MAINTENANCE = False
SCRAPE_TIMEOUT = 45000 # 45 секунд
SEMAPHORE = asyncio.Semaphore(2) # Только 2 браузера одновременно для экономии RAM

# --- [ БАЗА САЙТОВ ] ---
SITES = {
    "Rozetka": ["https://rozetka.com.ua/search/?text=", "tech"],
    "Prom": ["https://prom.ua/search?search_term=", "all"],
    "OLX": ["https://www.olx.ua/d/uk/list/q-", "all"],
    "Auto.ria": ["https://auto.ria.com/uk/search/?q=", "auto"],
    "Hotline": ["https://hotline.ua/sr/?q=", "tech"],
    "Epicentr": ["https://epicentrk.ua/search/?q=", "home"],
    "Allo": ["https://allo.ua/ru/catalogsearch/result/?q=", "tech"],
    "Eva": ["https://eva.ua/ua/search/?q=", "beauty"]
}

# --- [ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ] ---
def get_uptime():
    uptime_sec = time.time() - START_TIME
    return str(datetime.utcfromtimestamp(uptime_sec).strftime('%H:%M:%S'))

def manage_json(file, data=None, action="get"):
    if not os.path.exists(file): 
        with open(file, "w") as f: json.dump([], f)
    if action == "save":
        with open(file, "w") as f: json.dump(data, f)
    with open(file, "r") as f: return json.load(f)

def add_log(msg):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{t}] {msg}\n"
    with open(LOG_FILE, "a") as f: f.write(entry)

# --- [ АДМИН-КЛАВИАТУРА (15+ КНОПОК) ] ---
def get_admin_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус Системы"), KeyboardButton(text="📜 Живые Логи")],
        [KeyboardButton(text="👥 Управление Юзерами"), KeyboardButton(text="🚫 Черный Список")],
        [KeyboardButton(text="📂 Экспорт БД"), KeyboardButton(text="🛠 Тех. Работы")],
        [KeyboardButton(text="⚡️ Очистить RAM"), KeyboardButton(text="🔑 Терминал")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🌐 Прокси (Beta)")],
        [KeyboardButton(text="⏱ Изменить Тайм-аут"), KeyboardButton(text="🚪 Выход")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИК ПОИСКА ] ---
async def deep_scrape(context, name, url, query):
    async with SEMAPHORE:
        page = await context.new_page()
        try:
            full_url = f"{url}{query.replace(' ', '+')}"
            add_log(f"Начинаю поиск: {name} -> {query}")
            
            # Рандомный User-Agent для каждого сайта
            await page.set_extra_http_headers({"User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ])})

            await asyncio.wait_for(page.goto(full_url, wait_until="domcontentloaded"), timeout=SCRAPE_TIMEOUT/1000)
            await asyncio.sleep(3) # Даем прогрузиться скриптам

            # Поиск через JS селекторы (универсально)
            results = await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    return links
                        .filter(a => (a.href.includes('product') || a.href.includes('item') || a.href.includes('auto') || a.href.includes('obyavlenie')) && a.innerText.length > 20)
                        .map(a => ({t: a.innerText.trim(), h: a.href}))
                        .slice(0, 2);
                }
            """)
            
            if not results: return []
            return [f"📦 **{name}**: {res['t'][:50]}...\n🔗 {res['h']}" for res in results]
        except Exception as e:
            add_log(f"Ошибка на {name}: {str(e)[:50]}")
            return [f"⚠️ **{name}**: Ошибка или блок."]
        finally:
            await page.close()

# --- [ АДМИН-ФУНКЦИИ (10 НОВЫХ) ] ---
@dp.message(F.text == "📊 Статус Системы")
async def admin_status(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    mem = subprocess.getoutput("free -m | awk 'NR==2{printf \"Memory Usage: %s/%sMB (%.2f%%)\\n\", $3,$2,$3*100/$2 }'")
    msg = (f"🦾 **CHIIP TITAN STATUS**\n\n"
           f"⏱ Uptime: `{get_uptime()}`\n"
           f"👥 Users: `{len(manage_json(USERS_DB))}`\n"
           f"🚫 Banned: `{len(manage_json(BLACK_LIST))}`\n"
           f"🔍 Searches: `{STATS['searches']}`\n"
           f"🧩 Timeout: `{SCRAPE_TIMEOUT/1000}s`\n"
           f"🖥 {mem}")
    await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "⚡️ Очистить RAM")
async def clear_ram(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    subprocess.run("pkill chromium", shell=True)
    add_log("Админ принудительно очистил RAM")
    await message.answer("🧹 Все процессы Chromium убиты. Память очищена.")

@dp.message(F.text == "🛠 Тех. Работы")
async def toggle_maint(message: types.Message):
    global MAINTENANCE
    if message.from_user.id != ADMIN_ID: return
    MAINTENANCE = not MAINTENANCE
    await message.answer(f"⚙️ Режим тех. работ: {'ВКЛ' if MAINTENANCE else 'ВЫКЛ'}")

@dp.message(F.text == "📂 Экспорт БД")
async def export_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(USERS_DB):
        await message.answer_document(FSInputFile(USERS_DB), caption="📦 База данных пользователей")

@dp.message(F.text == "📜 Живые Логи")
async def send_logs(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
                last_logs = "".join(lines[-15:])
                await message.answer(f"📋 **ПОСЛЕДНИЕ ЛОГИ:**\n\n`{last_logs}`", parse_mode="Markdown")

@dp.message(F.text == "🔑 Терминал")
async def term_help(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("⌨️ Режим терминала активен.\nИспользуй `>` перед командой. Пример: `>uptime` или `>ls` (без точек в конце!)")

@dp.message(F.text.startswith(">"))
async def term_exec(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        cmd = message.text[1:].strip().rstrip(".") # Удаляем лишние точки и пробелы
        try:
            res = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
            await message.answer(f"💻 **Output:**\n`{res[:3500]}`", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка выполнения:\n`{str(e)}`", parse_mode="Markdown")

# --- [ ГЛАВНЫЙ ПОИСКОВОЙ ЦИКЛ ] ---
@dp.message(Command("admin"))
async def admin_entry(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🕶 **WELCOME TO TITAN APOCALYPSE UNIT**", reply_markup=get_admin_main())

@dp.message()
async def universal_handler(message: types.Message):
    if message.from_user.id in manage_json(BLACK_LIST): return
    if MAINTENANCE and message.from_user.id != ADMIN_ID:
        await message.answer("⚠️ Бот на техническом обслуживании. Попробуйте позже."); return
    
    if message.text in ["📊 Статус Системы", "📜 Живые Логи", "⚡️ Очистить RAM", "🚪 Выход"]: return

    # Защита от "пустых" запросов и жалоб (ИИ фильтр)
    if len(message.text) < 2 or "сканирует" in message.text.lower():
        return

    db = manage_json(USERS_DB)
    if message.from_user.id not in db:
        db.append(message.from_user.id); manage_json(USERS_DB, db, "save")

    STATS["searches"] += 1
    status = await message.answer("🛰 *CHIIP Инициализирует поиск...*")
    
    # Классификация ИИ
    q = message.text
    cat = "all"
    if ai_client:
        try:
            resp = await ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Extract product name from: {q}. Return only the name."}]
            )
            q = resp.choices[0].message.content
        except: pass

    # Выборка сайтов (берем топ-3 для скорости)
    selected = ["Rozetka", "Prom", "OLX"]
    if "авто" in message.text.lower() or "mazda" in message.text.lower():
        selected = ["Auto.ria", "OLX", "Prom"]

    async with async_playwright() as p:
        # Улучшенный стелс-режим
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 720})
        
        tasks = [deep_scrape(context, name, SITES[name][0], q) for name in selected]
        results = await asyncio.gather(*tasks)
        await browser.close()

    flat_results = [item for sub in results for item in sub]
    await status.delete()
    
    if flat_results:
        await message.answer(f"🏁 **РЕЗУЛЬТАТЫ:**\n\n" + "\n\n".join(flat_results), disable_web_page_preview=True)
    else:
        await message.answer("❌ Ничего не найдено. Сайты могли заблокировать запрос. Попробуйте через 1 минуту.")

# --- [ ЗАПУСК ] ---
async def start_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="APOCALYPSE_ACTIVE"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    add_log("CORE SYSTEM STARTING...")
    subprocess.run(["playwright", "install", "chromium"])
    await asyncio.gather(start_server(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())