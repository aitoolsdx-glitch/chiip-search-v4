import asyncio
import os
import json
import logging
import sys
import random
import subprocess
import platform
import shutil
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    FSInputFile, BotCommand, BotCommandScopeDefault
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))
VERSION = "20.0 TITAN-STABLE"

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TITAN-CORE")

# База данных (JSON)
DB_USERS = "titan_users.json"
DB_STATS = "titan_stats.json"

# --- [ FSM ] ---
class AdminStates(StatesGroup):
    terminal = State()
    broadcast = State()
    edit_config = State()

# --- [ СИСТЕМА ДАННЫХ ] ---
def load_db(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding='utf-8') as f:
            json.dump(default, f, ensure_all_ascii=False, indent=4)
        return default
    with open(path, "r", encoding='utf-8') as f:
        try: return json.load(f)
        except: return default

def save_db(path, data):
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_all_ascii=False, indent=4)

db_users = load_db(DB_USERS, {})
db_stats = load_db(DB_STATS, {"total_searches": 0, "errors": 0, "launches": 0})

def init_user(user: types.User):
    uid = str(user.id)
    if uid not in db_users:
        db_users[uid] = {
            "n": user.full_name, "u": user.username,
            "date": datetime.now().strftime("%d.%m.%Y"),
            "count": 0, "vip": False, "history": []
        }
        save_db(DB_USERS, db_users)

# --- [ КЛАВИАТУРЫ ] ---
def main_kb(uid):
    btns = [
        [KeyboardButton(text="🔎 ПОИСК ТОВАРОВ"), KeyboardButton(text="👤 МОЙ АККАУНТ")],
        [KeyboardButton(text="📜 ИСТОРИЯ ЗАПРОСОВ"), KeyboardButton(text="💎 VIP СТАТУС")],
        [KeyboardButton(text="🆘 ПОМОЩЬ / ИНФО")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [KeyboardButton(text="🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ 🔱")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 ПОЛНАЯ СТАТИСТИКА"), KeyboardButton(text="🐚 КОНСОЛЬ")],
        [KeyboardButton(text="📢 РАССЫЛКА"), KeyboardButton(text="📂 СКАЧАТЬ БД")],
        [KeyboardButton(text="🔙 НА ГЛАВНУЮ")]
    ], resize_keyboard=True)

# --- [ ИНИЦИАЛИЗАЦИЯ БОТА ] ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ЛОГИКА АДМИН-ЦЕНТРА ] ---

@dp.message(F.text == "🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ 🔱")
async def adm_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 **TITAN CORE v20.0: СИСТЕМА УПРАВЛЕНИЯ**", reply_markup=admin_kb())

@dp.message(F.text == "📊 ПОЛНАЯ СТАТИСТИКА")
async def adm_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    mem = psutil.virtual_memory().percent if 'psutil' in sys.modules else "N/A"
    text = (f"📊 **ОТЧЕТ TITAN-OMNI**\n\n"
            f"👥 Пользователей: `{len(db_users)}`\n"
            f"🔎 Всего запросов: `{db_stats['total_searches']}`\n"
            f"⚙️ Ошибок ядра: `{db_stats['errors']}`\n"
            f"🚀 Запусков: `{db_stats['launches']}`\n"
            f"📦 Версия: `{VERSION}`")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🐚 КОНСОЛЬ")
async def adm_shell(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.terminal)
    await message.answer("🐚 **TITAN SHELL ACTIVE**\nВведите системную команду (или 'exit'):")

@dp.message(AdminStates.terminal)
async def shell_proc(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход из консоли.", reply_markup=admin_kb())
    try:
        res = subprocess.check_output(message.text, shell=True, stderr=subprocess.STDOUT, timeout=10).decode("utf-8")
        await message.answer(f"✅ `Output:`\n`{res[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ `Error:`\n`{str(e)}`", parse_mode="Markdown")

@dp.message(F.text == "📂 СКАЧАТЬ БД")
async def adm_db(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer_document(FSInputFile(DB_USERS), caption="База пользователей")
    await message.answer_document(FSInputFile(DB_STATS), caption="Статистика")

# --- [ ЛОГИКА ПОЛЬЗОВАТЕЛЯ ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_user(message.from_user)
    await message.answer(
        f"🤖 **TITAN OMNI v20.0 ONLINE**\n\nДобро пожаловать, {message.from_user.first_name}!\n"
        "Я — мощный агрегатор поиска товаров по Украине.\n"
        "Просто напиши название товара.",
        reply_markup=main_kb(message.from_user.id)
    )

@dp.message(F.text == "👤 МОЙ АККАУНТ")
async def u_acc(message: types.Message):
    u = db_users.get(str(message.from_user.id))
    if not u: return
    status = "👑 VIP" if u['vip'] else "👤 Базовый"
    text = (f"👤 **ВАШ ПРОФИЛЬ**\n\n"
            f"🆔 ID: `{message.from_user.id}`\n"
            f"📊 Статус: {status}\n"
            f"🔎 Поисков: {u['count']}\n"
            f"📅 Дата регистрации: {u['date']}")
    await message.answer(text, parse_mode="Markdown")

# --- [ ЯДРО ПАРСИНГА (TITAN-STABLE) ] ---

async def fetch_site(session, name, url, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        full_url = url.format(q=query.replace(" ", "+"))
        async with session.get(full_url, headers=headers, timeout=15) as response:
            if response.status != 200: return []
            html = await response.text()
            soup = BeautifulSoup(html, 'lxml')
            
            results = []
            if "olx.ua" in url:
                cards = soup.find_all('a', href=True)
                for c in cards:
                    t = c.text.lower()
                    if all(w in t for w in query.lower().split()) and "/d/uk/obyavlenie/" in c['href']:
                        link = "https://www.olx.ua" + c['href'] if not c['href'].startswith('http') else c['href']
                        results.append(f"📦 **OLX**: {c.text.strip()[:60]}...\n🔗 {link}")
                        if len(results) >= 2: break
            
            elif "prom.ua" in url:
                links = soup.find_all('a', href=True)
                for l in links:
                    t = l.get('title', '').lower() or l.text.lower()
                    if all(w in t for w in query.lower().split()) and "/p" in l['href']:
                        link = "https://prom.ua" + l['href'] if not l['href'].startswith('http') else l['href']
                        results.append(f"📦 **Prom**: {t.strip()[:60]}...\n🔗 {link}")
                        if len(results) >= 2: break

            elif "rozetka" in url:
                links = soup.find_all('a', href=True)
                for l in links:
                    if "/p" in l['href'] and len(l.text) > 15:
                        t = l.text.lower()
                        if all(w in t for w in query.lower().split()):
                            results.append(f"📦 **Rozetka**: {l.text.strip()[:60]}...\n🔗 {l['href']}")
                            if len(results) >= 2: break
            return results
    except Exception as e:
        logger.error(f"Error parsing {name}: {e}")
        return []

@dp.message(F.text)
async def search_handler(message: types.Message):
    # Блокировка команд и кнопок
    if message.text.startswith("/") or len(message.text) < 3 or message.text in [
        "🔎 ПОИСК ТОВАРОВ", "👤 МОЙ АККАУНТ", "📜 ИСТОРИЯ ЗАПРОСОВ", "💎 VIP СТАТУС", 
        "🆘 ПОМОЩЬ / ИНФО", "🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ 🔱", "📊 ПОЛНАЯ СТАТИСТИКА", 
        "🐚 КОНСОЛЬ", "📢 РАССЫЛКА", "📂 СКАЧАТЬ БД", "🔙 НА ГЛАВНУЮ"
    ]: return

    uid = str(message.from_user.id)
    if uid in db_users:
        db_users[uid]["count"] += 1
        db_users[uid]["history"] = ([message.text] + db_users[uid]["history"])[:10]
        save_db(DB_USERS, db_users)
    
    db_stats["total_searches"] += 1
    save_db(DB_STATS, db_stats)

    status = await message.answer(f"🛰 **TITAN ENGINE v20**\n📡 Сканирую сеть по запросу: `{message.text}`...", parse_mode="Markdown")

    urls = {
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}",
        "Rozetka": "https://rozetka.com.ua/search/?text={q}"
    }

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_site(session, name, url, message.text) for name, url in urls.items()]
        results = await asyncio.gather(*tasks)

    flat_res = [i for s in results for i in s]
    await status.delete()

    if flat_res:
        await message.answer("✅ **РЕЗУЛЬТАТЫ TITAN-CORE:**\n\n" + "\n\n".join(flat_res), disable_web_page_preview=True)
    else:
        await message.answer("❌ Ничего не найдено. Попробуй уточнить название товара.")

# --- [ СИСТЕМНЫЙ ЗАПУСК ] ---

async def health_check(request): return web.Response(text="TITAN ACTIVE", status=200)

async def main():
    # КРИТИЧЕСКИЙ ФИКС КОНФЛИКТА
    await bot.delete_webhook(drop_pending_updates=True)
    
    db_stats["launches"] += 1
    save_db(DB_STATS, db_stats)

    # Веб-сервер для Render
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    await bot.set_my_commands([BotCommand(command="start", description="Запустить TITAN OMNI")])
    
    logger.info(f"СИСТЕМА TITAN v{VERSION} ЗАПУЩЕНА")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"CRASH: {e}")