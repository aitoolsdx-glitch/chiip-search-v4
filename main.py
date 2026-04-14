import asyncio, os, json, subprocess, logging, random, time, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import async_playwright
from aiohttp import web
import openai

# --- [ CONFIG ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ SYSTEM STATE ] ---
START_TIME = time.time()
USERS_DB = "nebula_users.json"
LOG_FILE = "nebula.log"
CONFIG_FILE = "config.json"
STATS = {"searches": 0, "errors": 0, "success": 0}

# Дефолтный конфиг
DEFAULT_CONFIG = {"timeout": 45000, "turbo": False, "maint": False, "proxy": None}
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f: json.dump(DEFAULT_CONFIG, f)

def get_conf(): return json.load(open(CONFIG_FILE))
def set_conf(c): json.dump(c, open(CONFIG_FILE, "w"))

# --- [ DB & LOGS ] ---
def add_log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def manage_users(action="get", u_id=None):
    if not os.path.exists(USERS_DB): json.dump([], open(USERS_DB, "w"))
    users = json.load(open(USERS_DB))
    if action == "add" and u_id not in users:
        users.append(u_id); json.dump(users, open(USERS_DB, "w"))
    return users

# --- [ КЛАВИАТУРЫ (МНОГОУРОВНЕВЫЕ) ] ---
def kb_admin_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖥 СИСТЕМА"), KeyboardButton(text="👥 ЮЗЕРЫ")],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="📢 РАССЫЛКА")],
        [KeyboardButton(text="🔑 ТЕРМИНАЛ"), KeyboardButton(text="🚪 ВЫХОД")]
    ], resize_keyboard=True)

def kb_admin_sys():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Полная Статистика"), KeyboardButton(text="📜 Логи")],
        [KeyboardButton(text="🧹 Очистить Кэш/RAM"), KeyboardButton(text="⚡️ Ребут")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def kb_admin_users():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📂 Выгрузить БД"), KeyboardButton(text="🔍 Найти Юзера")],
        [KeyboardButton(text="🚫 Бан-лист"), KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def kb_admin_conf():
    c = get_conf()
    t_status = "ВКЛ" if c['turbo'] else "ВЫКЛ"
    m_status = "ВКЛ" if c['maint'] else "ВЫКЛ"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=f"🚀 Турбо: {t_status}"), KeyboardButton(text=f"🛠 Техраб: {m_status}")],
        [KeyboardButton(text="⏱ Сменить Тайм-аут"), KeyboardButton(text="🎭 Сменить User-Agent")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

# --- [ AI ROUTING ENGINE ] ---
async def nebula_ai_router(text):
    if not ai_client: return text, ["Rozetka", "Prom", "OLX"]
    try:
        prompt = f"""Analyze query: '{text}'. 
        Return JSON ONLY: {{"q": "clean product name", "type": "part|car|item"}}"""
        resp = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(resp.choices[0].message.content)
        q = res.get("q", text)
        t = res.get("type", "item")
        
        if t == "car": return q, ["Auto.ria", "OLX", "RST"]
        if t == "part": return q, ["Prom", "OLX", "Epicentr"]
        return q, ["Rozetka", "Prom", "OLX"]
    except: return text, ["Rozetka", "Prom", "OLX"]

# --- [ SCRAPE ENGINE ] ---
async def scrape_nebula(context, name, query):
    urls = {
        "Rozetka": "https://rozetka.com.ua/search/?text=",
        "Prom": "https://prom.ua/search?search_term=",
        "OLX": "https://www.olx.ua/d/uk/list/q-",
        "Auto.ria": "https://auto.ria.com/uk/search/?q=",
        "RST": "https://rst.ua/uk/oldcars/?task=search&q=",
        "Epicentr": "https://epicentrk.ua/search/?q="
    }
    page = await context.new_page()
    conf = get_conf()
    try:
        full_url = f"{urls[name]}{query.replace(' ', '+')}"
        await page.goto(full_url, wait_until="domcontentloaded", timeout=conf['timeout'])
        await asyncio.sleep(3)

        results = await page.evaluate(f"""
            () => {{
                const qWords = "{query.lower()}".split(" ");
                return Array.from(document.querySelectorAll('a'))
                    .filter(a => {{
                        const text = a.innerText.toLowerCase();
                        const href = a.href;
                        return qWords.every(w => text.includes(w)) && 
                               !href.includes('google') && text.length > 15;
                    }})
                    .slice(0, 2)
                    .map(a => ({{ t: a.innerText.trim(), h: a.href }}));
            }}
        """)
        return [f"📦 **{name}**: {r['t'][:55]}...\n🔗 {r['h']}" for r in results]
    except: return []
    finally: await page.close()

# --- [ COMMAND HANDLERS ] ---

@dp.message(Command("admin"))
async def admin_entry(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🦾 **NEBULA CORE: ДОСТУП РАЗРЕШЕН**", reply_markup=kb_admin_main())

@dp.message(F.text == "🖥 СИСТЕМА")
async def admin_sys(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Меню системы:", reply_markup=kb_admin_sys())

@dp.message(F.text == "👥 ЮЗЕРЫ")
async def admin_usr(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Управление пользователями:", reply_markup=kb_admin_users())

@dp.message(F.text == "⚙️ НАСТРОЙКИ")
async def admin_set(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Конфигурация бота:", reply_markup=kb_admin_conf())

@dp.message(F.text == "🔙 Назад")
async def admin_back(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Главное меню:", reply_markup=kb_admin_main())

@dp.message(F.text == "🧹 Очистить Кэш/RAM")
async def clear_system(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        subprocess.run("pkill chromium", shell=True)
        await message.answer("🧹 Все процессы браузера убиты. ОЗУ очищена.")

@dp.message(F.text.startswith("🚀 Турбо:"))
async def toggle_turbo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        c = get_conf(); c['turbo'] = not c['turbo']
        c['timeout'] = 80000 if c['turbo'] else 45000
        set_conf(c)
        await message.answer(f"Турбо-режим: {'ВКЛ' if c['turbo'] else 'ВЫКЛ'}", reply_markup=kb_admin_conf())

@dp.message(F.text == "📊 Полная Статистика")
async def full_stats(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        uptime = str(datetime.utcfromtimestamp(time.time() - START_TIME).strftime('%H:%M:%S'))
        mem = subprocess.getoutput("free -m | grep Mem | awk '{print $3}'")
        await message.answer(f"📈 **NEBULA REPORT**\n\nUptime: {uptime}\nRAM Used: {mem}MB\nUsers: {len(manage_users())}\nSearches: {STATS['searches']}\nSuccess: {STATS['success']}")

@dp.message(F.text == "🔑 ТЕРМИНАЛ")
async def term_info(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Введи команду через `>` (например `>df -h`)")

@dp.message(F.text.startswith(">"))
async def term_exec(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        cmd = message.text[1:].strip().rstrip(".")
        try:
            res = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
            await message.answer(f"💻 `Output:`\n`{res[:3500]}`", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка:\n`{str(e)}`")

# --- [ ОСНОВНОЙ ПОИСК ] ---

@dp.message()
async def main_search(message: types.Message):
    if message.from_user.id == ADMIN_ID and message.text in ["🖥 СИСТЕМА", "👥 ЮЗЕРЫ", "⚙️ НАСТРОЙКИ", "📢 РАССЫЛКА", "🔑 ТЕРМИНАЛ", "🚪 ВЫХОД", "🔙 Назад"]: return
    
    manage_users("add", message.from_user.id)
    conf = get_conf()
    if conf['maint'] and message.from_user.id != ADMIN_ID:
        await message.answer("🛠 Извини, я на техобслуживании."); return

    STATS["searches"] += 1
    status = await message.answer("🛰 *NEBULA анализирует запрос...*")
    
    # ИИ роутинг (запчасти или машина?)
    clean_q, sites = await nebula_ai_router(message.text)
    
    await status.edit_text(f"📡 *Поиск {clean_q} по базе {', '.join(sites)}...*")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        tasks = [scrape_nebula(context, name, clean_q) for name in sites]
        results = await asyncio.gather(*tasks)
        await browser.close()

    flat = [item for sub in results for item in sub]
    await status.delete()
    
    if flat:
        STATS["success"] += 1
        await message.answer(f"✅ **РЕЗУЛЬТАТЫ NEBULA:**\n\n" + "\n\n".join(flat), disable_web_page_preview=True)
    else:
        STATS["errors"] += 1
        await message.answer("❌ **Точных совпадений не найдено.**\nПопробуй изменить запрос.")

# --- [ SERVER ] ---
async def start_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="NEBULA_ONLINE"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    subprocess.run(["playwright", "install", "chromium"])
    await asyncio.gather(start_server(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())