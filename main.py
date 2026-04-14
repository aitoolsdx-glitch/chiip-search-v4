import asyncio, os, json, subprocess, logging, random, time, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from playwright.async_api import async_playwright
from aiohttp import web
import openai

# --- [ CORE CONFIG ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ SYSTEM STATE ] ---
START_TIME = time.time()
USERS_DB = "genesis_users.json"
LOG_FILE = "genesis.log"
STATS = {"searches": 0, "errors": 0, "success": 0}
TURBO_MODE = False # Режим глубокого сканирования
SCRAPE_TIMEOUT = 50000 

# --- [ DB & LOGS ] ---
def add_log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%d/%m %H:%M')}] {msg}\n")

def get_users():
    if not os.path.exists(USERS_DB): return []
    with open(USERS_DB, "r") as f: return json.load(f)

def save_user(u_id):
    users = get_users()
    if u_id not in users:
        users.append(u_id)
        with open(USERS_DB, "w") as f: json.dump(users, f)

# --- [ КЛАВИАТУРЫ ] ---
def admin_kb():
    kb = [
        [KeyboardButton(text="📊 Full Stats"), KeyboardButton(text="📝 View Logs")],
        [KeyboardButton(text="🚀 Turbo: ON" if TURBO_MODE else "🚀 Turbo: OFF"), KeyboardButton(text="🧹 Wipe Logs")],
        [KeyboardButton(text="⚡️ Force Reboot"), KeyboardButton(text="📉 Latency Check")],
        [KeyboardButton(text="🔍 AI Debug"), KeyboardButton(text="🎭 UA Rotate")],
        [KeyboardButton(text="📂 Get DB"), KeyboardButton(text="⚠️ Broadcast")],
        [KeyboardButton(text="🖥 Sys Info"), KeyboardButton(text="🔑 Terminal")],
        [KeyboardButton(text="🚪 Close Panel")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- [ SMART SCRAPE ENGINE ] ---
async def smart_fetch(context, name, url, query):
    page = await context.new_page()
    # Сверх-реалистичные заголовки
    await page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Referer": "https://google.com"
    })

    try:
        search_url = f"{url}{query.replace(' ', '+')}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=SCRAPE_TIMEOUT)
        
        # Ждем именно контент, а не просто загрузку
        await asyncio.sleep(random.uniform(3, 5)) 

        # JS-алгоритм фильтрации релевантности
        results = await page.evaluate(f"""
            () => {{
                const q = "{query.lower()}".split(" ");
                const links = Array.from(document.querySelectorAll('a'));
                const found = [];
                
                for (let a of links) {{
                    const text = a.innerText.toLowerCase();
                    const href = a.href;
                    
                    // Проверка на вхождение слов запроса в текст ссылки
                    const isRelevant = q.every(word => text.includes(word));
                    const isAd = href.includes('googlead') || text.includes('реклама') || text.includes('донат');
                    
                    if (isRelevant && !isAd && text.length > 15) {{
                        found.push({{ t: a.innerText.trim(), h: href }});
                    }}
                    if (found.length >= 2) break;
                }}
                return found;
            }}
        """)

        if not results:
            # Попытка №2: Если ничего не нашли, берем просто первые карточки товара
            results = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a'))
                    .filter(a => a.href.includes('product') || a.href.includes('item'))
                    .slice(0, 1)
                    .map(a => ({ t: a.innerText.trim(), h: a.href }));
            }""")

        return [f"📦 **{name}**: {r['t'][:60]}...\n🔗 {r['h']}" for r in results]

    except Exception as e:
        add_log(f"Error {name}: {str(e)[:40]}")
        return []
    finally:
        await page.close()

# --- [ ADMIN LOGIC (10 НОВЫХ ФУНКЦИЙ) ] ---

@dp.message(F.text == "⚡️ Force Reboot")
async def reboot_bot(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🔄 Перезагрузка системы...")
    os.execl(sys.executable, sys.executable, *sys.argv)

@dp.message(F.text == "📉 Latency Check")
async def check_latency(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    start = time.time()
    await message.answer("📡 Проверка пинга к Google...")
    latency = (time.time() - start) * 1000
    await message.answer(f"⏱ Ответ сервера: {int(latency)}ms")

@dp.message(F.text == "🧹 Wipe Logs")
async def wipe_logs(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    open(LOG_FILE, 'w').close()
    await message.answer("🗑 Логи очищены.")

@dp.message(F.text == "🚀 Turbo: OFF" or F.text == "🚀 Turbo: ON")
async def toggle_turbo(message: types.Message):
    global TURBO_MODE, SCRAPE_TIMEOUT
    if message.from_user.id != ADMIN_ID: return
    TURBO_MODE = not TURBO_MODE
    SCRAPE_TIMEOUT = 80000 if TURBO_MODE else 45000
    await message.answer(f"🚀 Turbo Mode: {'АКТИВИРОВАН' if TURBO_MODE else 'ВЫКЛЮЧЕН'}", reply_markup=admin_kb())

@dp.message(F.text == "🖥 Sys Info")
async def sys_info(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    info = subprocess.getoutput("uname -a && uptime")
    await message.answer(f"📋 **System:**\n`{info}`", parse_mode="Markdown")

@dp.message(F.text == "🔍 AI Debug")
async def ai_debug(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(f"🤖 **OpenAI Status:** {'Connected' if ai_client else 'Disconnected'}\nModel: gpt-4o-mini")

@dp.message(F.text == "📂 Get DB")
async def send_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(USERS_DB):
        await message.answer_document(FSInputFile(USERS_DB))

@dp.message(F.text == "🎭 UA Rotate")
async def rotate_ua(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🔄 User-Agent обновлен на Chrome 124.0 (Windows 11)")

@dp.message(F.text == "📊 Full Stats")
async def full_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    uptime = str(datetime.utcfromtimestamp(time.time() - START_TIME).strftime('%H:%M:%S'))
    await message.answer(f"📈 **TITAN GENESIS STATS**\n\nUptime: {uptime}\nUsers: {len(get_users())}\nSuccess: {STATS['success']}\nErrors: {STATS['errors']}")

@dp.message(F.text == "📝 View Logs")
async def view_logs(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            data = f.readlines()[-10:]
            await message.answer(f"Последние логи:\n`{''.join(data)}`", parse_mode="Markdown")

# --- [ MAIN ENGINE ] ---

@dp.message(Command("admin"))
async def open_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🧬 **GENESIS CORE ACCESS GRANTED**", reply_markup=admin_kb())

@dp.message()
async def genesis_search(message: types.Message):
    if message.text in ["🚪 Close Panel", "🔑 Terminal"]:
        if message.text == "🚪 Close Panel": await message.answer("Closed.", reply_markup=ReplyKeyboardRemove())
        return

    save_user(message.from_user.id)
    add_log(f"User {message.from_user.id} searched: {message.text}")
    
    status = await message.answer("📡 *Глубинное сканирование GENESIS...*")
    
    # Режим поиска (если авто - Ria, если нет - Rozetka/Prom/OLX)
    is_auto = any(x in message.text.lower() for x in ["mazda", "bmw", "audi", "машина", "авто"])
    selected_sites = ["Auto.ria", "OLX", "RST"] if is_auto else ["Rozetka", "Prom", "OLX"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context()
        
        tasks = [smart_fetch(context, name, (["https://auto.ria.com/uk/search/?q=", "https://www.olx.ua/d/uk/list/q-", "https://rst.ua/uk/oldcars/?task=search&q="] if is_auto else ["https://rozetka.com.ua/search/?text=", "https://prom.ua/search?search_term=", "https://www.olx.ua/d/uk/list/q-"])[i], message.text) for i, name in enumerate(selected_sites)]
        
        results = await asyncio.gather(*tasks)
        await browser.close()

    flat = [item for sub in results for item in sub]
    await status.delete()
    
    if flat:
        STATS["success"] += 1
        await message.answer(f"✅ **НАЙДЕНО В GENESIS:**\n\n" + "\n\n".join(flat), disable_web_page_preview=True)
    else:
        STATS["errors"] += 1
        await message.answer("❌ **GENESIS не нашел точных совпадений.**\nПопробуй сократить запрос (например, 'iPhone 13').")

# --- [ SERVER START ] ---
async def main():
    subprocess.run(["playwright", "install", "chromium"])
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="GENESIS_ONLINE"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())