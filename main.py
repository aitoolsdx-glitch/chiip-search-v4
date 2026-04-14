import asyncio
import os
import json
import subprocess
import logging
import random
import sys
import platform
import shutil
from datetime import datetime, timedelta

# Библиотеки
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ СИСТЕМНЫЕ КОНСТАНТЫ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446 # Твой ID (Daxo)
PORT = int(os.environ.get("PORT", 8080))
VERSION = "19.0 OMNI-RECOVERY"

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("omni_core.log", encoding='utf-8'), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("OMNI-SYSTEM")

# Файлы данных
DB_USERS = "database_users.json"
DB_STATS = "database_stats.json"
SYSTEM_CONFIG = "system_config.json"

# --- [ FSM СОСТОЯНИЯ ] ---
class SystemStates(StatesGroup):
    admin_terminal = State()
    admin_broadcast = State()
    user_searching = State()

# --- [ ЯДРО ДАННЫХ ] ---
def load_data(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding='utf-8') as f:
            json.dump(default, f, ensure_all_ascii=False, indent=4)
        return default
    with open(path, "r", encoding='utf-8') as f:
        try: return json.load(f)
        except: return default

def save_data(path, data):
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_all_ascii=False, indent=4)

db_users = load_data(DB_USERS, {})
db_stats = load_data(DB_STATS, {"total_searches": 0, "errors": 0})
sys_config = load_data(SYSTEM_CONFIG, {"maint_mode": False, "search_timeout": 60000})

def log_user(user: types.User):
    uid = str(user.id)
    if uid not in db_users:
        db_users[uid] = {
            "name": user.full_name, "username": user.username,
            "joined": datetime.now().strftime("%Y-%m-%d"),
            "searches": 0, "vip": False, "history": []
        }
        save_data(DB_USERS, db_users)

# --- [ КЛАВИАТУРЫ ] ---
def get_main_kb(uid):
    btns = [
        [KeyboardButton(text="🔍 ПОИСК"), KeyboardButton(text="👤 ПРОФИЛЬ")],
        [KeyboardButton(text="📜 ИСТОРИЯ"), KeyboardButton(text="💎 VIP")],
        [KeyboardButton(text="🆘 ПОМОЩЬ")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [KeyboardButton(text="🔱 АДМИН-ЦЕНТР 🔱")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛰 СТАТУС"), KeyboardButton(text="🐚 ТЕРМИНАЛ")],
        [KeyboardButton(text="📢 РАССЫЛКА"), KeyboardButton(text="📂 БЭКАП")],
        [KeyboardButton(text="🔙 ВЫХОД")]
    ], resize_keyboard=True)

# --- [ ИНИЦИАЛИЗАЦИЯ ] ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ОБРАБОТЧИКИ ] ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    log_user(message.from_user)
    await message.answer(f"🚀 **OMNI v19.0 СИСТЕМА ЗАПУЩЕНА**\n\nГотов к работе, {message.from_user.first_name}!", 
                         reply_markup=get_main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text == "🔱 АДМИН-ЦЕНТР 🔱")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 **ВХОД В ЯДРО ВЫПОЛНЕН**", reply_markup=get_admin_kb())

@dp.message(F.text == "🛰 СТАТУС")
async def adm_status(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    uptime = subprocess.getoutput("uptime -p")
    text = (f"🛰 **СИСТЕМНЫЙ ОТЧЕТ**\n\n"
            f"👤 Юзеров: `{len(db_users)}`\n"
            f"🔍 Поисков: `{db_stats['total_searches']}`\n"
            f"⏱ Uptime: `{uptime}`\n"
            f"📦 Версия: `{VERSION}`")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🐚 ТЕРМИНАЛ")
async def adm_term(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(SystemStates.admin_terminal)
    await message.answer("🐚 **SSH ЭМУЛЯЦИЯ**\nВведите команду (или 'exit'):")

@dp.message(SystemStates.admin_terminal)
async def term_proc(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход...", reply_markup=get_admin_kb())
    try:
        res = subprocess.check_output(message.text, shell=True, stderr=subprocess.STDOUT, timeout=10).decode("utf-8")
        await message.answer(f"✅ `Result:`\n`{res[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ `Error:`\n`{str(e)}`", parse_mode="Markdown")

@dp.message(F.text == "👤 ПРОФИЛЬ")
async def u_prof(message: types.Message):
    u = db_users.get(str(message.from_user.id))
    if not u: return
    status = "💎 VIP" if u['vip'] else "👤 Обычный"
    await message.answer(f"👤 **ПРОФИЛЬ**\n\nСтатус: {status}\nПоисков: {u['searches']}\nID: `{message.from_user.id}`", parse_mode="Markdown")

# --- [ ПАРСЕР TITAN OMNI ] ---
async def scrape(context, name, url_pattern, query):
    page = await context.new_page()
    try:
        target = url_pattern.replace("{q}", query.replace(" ", "+"))
        await page.goto(target, wait_until="domcontentloaded", timeout=sys_config["search_timeout"])
        await asyncio.sleep(3)
        
        items = await page.evaluate(f"""
            () => {{
                const q = "{query.lower()}".split(" ");
                const links = Array.from(document.querySelectorAll('a'));
                const res = [];
                for (let a of links) {{
                    const t = a.innerText.toLowerCase();
                    if (q.every(w => t.includes(w)) && a.href.includes('http') && t.length > 12) {{
                        res.push({{ title: a.innerText.split('\\n')[0], link: a.href }});
                    }}
                    if (res.length >= 2) break;
                }}
                return res;
            }}
        """)
        return [f"📦 **{name}**: {i['title'][:50]}...\n🔗 {i['link']}" for i in items]
    except Exception as e:
        logger.error(f"Error {name}: {e}")
        return []
    finally:
        await page.close()

@dp.message(F.text)
async def main_engine(message: types.Message):
    if message.text.startswith("/") or message.text in ["🔍 ПОИСК", "👤 ПРОФИЛЬ", "📜 ИСТОРИЯ", "💎 VIP", "🆘 ПОМОЩЬ", "🔱 АДМИН-ЦЕНТР 🔱", "🛰 СТАТУС", "🐚 ТЕРМИНАЛ", "📢 РАССЫЛКА", "📂 БЭКАП", "🔙 ВЫХОД"]:
        return

    uid = str(message.from_user.id)
    if uid in db_users:
        db_users[uid]["searches"] += 1
        db_users[uid]["history"] = ([message.text] + db_users[uid]["history"])[:10]
        save_data(DB_USERS, db_users)
    
    db_stats["total_searches"] += 1
    save_data(DB_STATS, db_stats)

    status = await message.answer(f"🛰 **OMNI-V19 СКАН**\n🔎 `{message.text}`...")

    sites = {
        "Rozetka": "https://rozetka.com.ua/search/?text={q}",
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}"
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        tasks = [scrape(context, n, u, message.text) for n, u in sites.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()

    flat_res = [i for s in results for i in s]
    await status.delete()
    
    if flat_res:
        await message.answer("✅ **НАЙДЕНО:**\n\n" + "\n\n".join(flat_res), disable_web_page_preview=True)
    else:
        await message.answer("❌ Ничего не найдено. Упростите запрос.")

# --- [ SERVER ] ---
async def handle(r): return web.Response(text="OMNI ALIVE")

async def start_omni():
    # ФИКС КОНФЛИКТА
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Установка браузеров (важно для Render)
    subprocess.run(["playwright", "install", "chromium"])
    
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await bot.set_my_commands([BotCommand(command="start", description="Запуск")])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_omni())