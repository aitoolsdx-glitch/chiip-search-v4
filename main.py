import asyncio
import os
import json
import logging
import sys
import random
import subprocess
import platform
import shutil
import traceback
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# =================================================================
# [ КОНФИГУРАЦИЯ СИСТЕМЫ ]
# =================================================================
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446 # Твой ID
PORT = int(os.environ.get("PORT", 8080))
VERSION = "20.0 TITAN-STABLE"

# Настройка глубокого логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("titan_main.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TITAN-OMNI")

# Пути к базам данных
DB_USERS = "titan_users.json"
DB_STATS = "titan_stats.json"
DB_CONFIG = "titan_config.json"

# =================================================================
# [ МАШИНА СОСТОЯНИЙ (FSM) ]
# =================================================================
class TitanStates(StatesGroup):
    admin_terminal = State()
    admin_broadcast = State()
    admin_manage_user = State()
    user_feedback = State()
    user_search_wait = State()

# =================================================================
# [ ЯДРО УПРАВЛЕНИЯ ДАННЫМИ ]
# =================================================================
def load_db(path, default_val):
    if not os.path.exists(path):
        with open(path, "w", encoding='utf-8') as f:
            json.dump(default_val, f, ensure_all_ascii=False, indent=4)
        return default_val
    with open(path, "r", encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return default_val

def save_db(path, data):
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_all_ascii=False, indent=4)

# Инициализация баз
db_users = load_db(DB_USERS, {})
db_stats = load_db(DB_STATS, {"total_searches": 0, "errors": 0, "api_calls": 0, "launches": 0})
db_config = load_db(DB_CONFIG, {"maint_mode": False, "turbo_mode": True, "timeout": 20})

def register_user(user: types.User):
    uid = str(user.id)
    if uid not in db_users:
        db_users[uid] = {
            "full_name": user.full_name,
            "username": user.username,
            "reg_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "search_count": 0,
            "is_vip": False,
            "is_banned": False,
            "history": []
        }
        save_db(DB_USERS, db_users)
        logger.info(f"New Titan User: {uid}")

# =================================================================
# [ ИНТЕРФЕЙСНЫЕ РЕШЕНИЯ ]
# =================================================================
def get_main_kb(uid):
    keyboard = [
        [KeyboardButton(text="🔍 Найти товар"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📜 Моя История"), KeyboardButton(text="💎 VIP Центр")],
        [KeyboardButton(text="🆘 Техподдержка")]
    ]
    if uid == ADMIN_ID:
        keyboard.insert(0, [KeyboardButton(text="🔱 ТИТАН: АДМИН-ПАНЕЛЬ 🔱")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Метрики Системы"), KeyboardButton(text="🐚 Терминал")],
        [KeyboardButton(text="📢 Массовая Рассылка"), KeyboardButton(text="📂 Дамп Данных")],
        [KeyboardButton(text="⚙️ Конфиг Ядра"), KeyboardButton(text="🔙 Выход в главное меню")]
    ], resize_keyboard=True)

# =================================================================
# [ ИНИЦИАЛИЗАЦИЯ БОТА ]
# =================================================================
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =================================================================
# [ ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ]
# =================================================================
@dp.message(F.text == "🔱 ТИТАН: АДМИН-ПАНЕЛЬ 🔱")
async def open_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛡 **TITAN OS v20: ДОСТУП РАЗРЕШЕН**", reply_markup=get_admin_kb())

@dp.message(F.text == "📊 Метрики Системы")
async def show_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    # Расчет размера БД
    db_size = os.path.getsize(DB_USERS) / 1024
    uptime = subprocess.getoutput("uptime -p")
    
    report = (
        "📈 **TITAN GLOBAL PERFORMANCE REPORT**\n\n"
        f"👥 Зарегистрировано: `{len(db_users)}` юзеров\n"
        f"🔎 Обработано поисков: `{db_stats['total_searches']}`\n"
        f"🚀 Сессий запуска: `{db_stats['launches']}`\n"
        f"❌ Системных сбоев: `{db_stats['errors']}`\n"
        f"💾 Вес базы: `{db_size:.2f} KB`\n"
        f"⏳ Аптайм: `{uptime}`\n"
        f"🛠 Режим техработ: `{'ВКЛ' if db_config['maint_mode'] else 'ВЫКЛ'}`"
    )
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text == "🐚 Терминал")
async def terminal_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(TitanStates.admin_terminal)
    await message.answer("🐚 **TITAN BASH READY**\nОтправьте команду (например `ls` или `pip list`):")

@dp.message(TitanStates.admin_terminal)
async def terminal_execute(message: types.Message, state: FSMContext):
    if message.text.lower() in ["exit", "выход", "stop"]:
        await state.clear()
        return await message.answer("Терминал закрыт.", reply_markup=get_admin_kb())
    
    try:
        proc = await asyncio.create_subprocess_shell(
            message.text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        result = (stdout.decode() or stderr.decode() or "Команда выполнена (без вывода).")
        await message.answer(f"✅ **ОТВЕТ СЕРВЕРА:**\n`{result[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ **ОШИБКА ВЫПОЛНЕНИЯ:**\n`{str(e)}`", parse_mode="Markdown")

@dp.message(F.text == "📂 Дамп Данных")
async def admin_dump(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    for file in [DB_USERS, DB_STATS, "titan_main.log"]:
        if os.path.exists(file):
            await message.answer_document(FSInputFile(file))

# =================================================================
# [ ЛОГИКА ПОИСКОВОГО ДВИЖКА (TITAN-STABLE) ]
# =================================================================
async def titan_scrape(session, site_name, url_template, query):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    try:
        search_url = url_template.format(q=query.replace(" ", "+"))
        async with session.get(search_url, headers=headers, timeout=db_config['timeout']) as resp:
            if resp.status != 200: return []
            
            content = await resp.text()
            soup = BeautifulSoup(content, 'lxml')
            items = []
            
            # Логика для OLX
            if "olx.ua" in url_template:
                cards = soup.select('a.css-z3gu2d') or soup.select('div[data-cy="l-card"] a')
                for c in cards:
                    title = c.find('h6')
                    href = c.get('href')
                    if title and href:
                        link = "https://www.olx.ua" + href if not href.startswith('http') else href
                        items.append(f"📦 **OLX**: {title.text.strip()}\n🔗 {link}")
                        if len(items) >= 2: break
            
            # Логика для Prom
            elif "prom.ua" in url_template:
                links = soup.find_all('a', href=True)
                for l in links:
                    t = l.get('title', '')
                    if all(word in t.lower() for word in query.lower().split()) and "/p" in l['href']:
                        full_link = "https://prom.ua" + l['href'] if not l['href'].startswith('http') else l['href']
                        items.append(f"📦 **Prom**: {t[:60]}...\n🔗 {full_link}")
                        if len(items) >= 2: break
            
            # Логика для Rozetka
            elif "rozetka" in url_template:
                goods = soup.select('a.goods-tile__heading')
                for g in goods:
                    t = g.text.strip()
                    if all(word in t.lower() for word in query.lower().split()):
                        items.append(f"📦 **Rozetka**: {t[:60]}...\n🔗 {g['href']}")
                        if len(items) >= 2: break
            
            return items
    except Exception as e:
        logger.error(f"Scrape error at {site_name}: {e}")
        return []

@dp.message(F.text)
async def handle_all_messages(message: types.Message):
    # Фильтрация кнопок
    if message.text.startswith("/") or message.text in [
        "🔍 Найти товар", "👤 Профиль", "📜 Моя История", "💎 VIP Центр", "🆘 Техподдержка",
        "🔱 ТИТАН: АДМИН-ПАНЕЛЬ 🔱", "📊 Метрики Системы", "🐚 Терминал", 
        "📢 Массовая Рассылка", "📂 Дамп Данных", "⚙️ Конфиг Ядра", "🔙 Выход в главное меню"
    ]:
        if message.text == "🔍 Найти товар":
            await message.answer("📝 Введите название товара для поиска:")
        elif message.text == "👤 Профиль":
            u = db_users.get(str(message.from_user.id))
            status = "👑 VIP" if u['is_vip'] else "👤 Обычный"
            await message.answer(f"👤 **АККАУНТ {message.from_user.first_name}**\n\n🆔 ID: `{message.from_user.id}`\n🌐 Статус: {status}\n🔎 Поисков: {u['search_count']}")
        return

    # Защита от техработ
    if db_config['maint_mode'] and message.from_user.id != ADMIN_ID:
        return await message.answer("🚧 **ТЕХНИЧЕСКИЕ РАБОТЫ**\nЯдро обновляется. Скоро будем в строю!")

    # Обновление статистики юзера
    uid = str(message.from_user.id)
    register_user(message.from_user)
    db_users[uid]["search_count"] += 1
    db_users[uid]["history"] = ([message.text] + db_users[uid]["history"])[:10]
    save_db(DB_USERS, db_users)
    
    db_stats["total_searches"] += 1
    save_db(DB_STATS, db_stats)

    # Старт парсинга
    status_msg = await message.answer(f"🛰 **TITAN ENGINE АКТИВИРОВАН**\n📡 Анализ запроса: `{message.text}`...")

    search_targets = {
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}",
        "Rozetka": "https://rozetka.com.ua/search/?text={q}"
    }

    async with aiohttp.ClientSession() as session:
        tasks = [titan_scrape(session, name, url, message.text) for name, url in search_targets.items()]
        results = await asyncio.gather(*tasks)

    all_links = [item for sublist in results for item in sublist]
    await status_msg.delete()

    if all_links:
        response_text = "✅ **РЕЗУЛЬТАТЫ ПОИСКА TITAN:**\n\n" + "\n\n".join(all_links)
        await message.answer(response_text, disable_web_page_preview=True, parse_mode="Markdown")
    else:
        db_stats["errors"] += 1
        save_db(DB_STATS, db_stats)
        await message.answer("❌ **Товары не найдены.**\nПопробуйте сократить запрос до ключевых слов (например: 'iPhone 13').")

# =================================================================
# [ ЖИЗНЕННЫЙ ЦИКЛ ПРИЛОЖЕНИЯ ]
# =================================================================
async def health_check_server(request):
    return web.Response(text=f"TITAN OMNI STATUS: RUNNING\nVERSION: {VERSION}", status=200)

async def start_titan():
    # ПРИНУДИТЕЛЬНЫЙ СБРОС КОНФЛИКТОВ
    await bot.delete_webhook(drop_pending_updates=True)
    
    db_stats["launches"] += 1
    save_db(DB_STATS, db_stats)

    # Настройка веб-сервера для Render (Health Check)
    app = web.Application()
    app.router.add_get("/", health_check_server)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    # Установка команд меню в ТГ
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Инструкция")
    ], scope=BotCommandScopeDefault())
    
    logger.info(f"--- TITAN OMNI v{VERSION} СИСТЕМА ЗАПУЩЕНА ---")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКИЙ СБОЙ: {traceback.format_exc()}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(start_titan())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Система остановлена.")