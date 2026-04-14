import asyncio
import os
import json
import subprocess
import logging
import random
import time
import sys
import platform
import shutil
from datetime import datetime, timedelta

# Библиотеки для работы бота
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
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ ГЛОБАЛЬНЫЕ КОНСТАНТЫ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446 # Твой ID (Daxo)
PORT = int(os.environ.get("PORT", 8080))
VERSION = "18.0 OMNI-MAX"

# Настройка логирования в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("omni_max.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("OMNI-MAX-CORE")

# Пути к файлам данных
DB_USERS = "database_users.json"
DB_STATS = "database_stats.json"
SYSTEM_CONFIG = "system_config.json"

# --- [ МАШИНА СОСТОЯНИЙ (FSM) ] ---
class SystemStates(StatesGroup):
    # Состояния для Админа
    admin_terminal = State()
    admin_broadcast = State()
    admin_ban_user = State()
    admin_set_timeout = State()
    admin_add_vip = State()
    # Состояния для Юзера
    user_searching = State()
    user_feedback = State()

# --- [ ЯДРО БАЗЫ ДАННЫХ И КОНФИГУРАЦИИ ] ---

def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding='utf-8') as f:
            json.dump(default, f, ensure_all_ascii=False, indent=4)
        return default
    with open(path, "r", encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_all_ascii=False, indent=4)

# Инициализация системных данных
db_users = load_json(DB_USERS, {})
db_stats = load_json(DB_STATS, {"total_searches": 0, "errors": 0, "api_calls": 0})
sys_config = load_json(SYSTEM_CONFIG, {
    "maint_mode": False,
    "turbo_mode": True,
    "search_timeout": 50000,
    "max_history": 15,
    "allowed_sites": ["Rozetka", "OLX", "Prom", "AutoRia"]
})

def register_user(user: types.User):
    uid = str(user.id)
    if uid not in db_users:
        db_users[uid] = {
            "username": user.username,
            "full_name": user.full_name,
            "join_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "search_count": 0,
            "history": [],
            "is_vip": False,
            "is_banned": False,
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json(DB_USERS, db_users)
        logger.info(f"Зарегистрирован новый пользователь: {uid}")

# --- [ ГЕНЕРАТОРЫ ИНТЕРФЕЙСА ] ---

def get_main_kb(user_id):
    buttons = [
        [KeyboardButton(text="🔍 Начать поиск"), KeyboardButton(text="👤 Мой Профиль")],
        [KeyboardButton(text="📜 История запросов"), KeyboardButton(text="⚙️ Настройки")],
        [KeyboardButton(text="🆘 Поддержка"), KeyboardButton(text="💎 VIP Статус")]
    ]
    # Если зашел админ, добавляем кнопку входа в систему
    if user_id == ADMIN_ID:
        buttons.insert(0, [KeyboardButton(text="🔱 ПАНЕЛЬ УПРАВЛЕНИЯ 🔱")])
        
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика Системы"), KeyboardButton(text="👥 Управление Юзерами")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🐚 Терминал (SSH)")],
        [KeyboardButton(text="⚙️ Конфиг Ядра"), KeyboardButton(text="📂 Дамп БД")],
        [KeyboardButton(text="🛑 Режим Техработ"), KeyboardButton(text="🔙 Выход из Админки")]
    ], resize_keyboard=True)

def get_user_manage_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚫 Забанить ID"), KeyboardButton(text="✅ Разбанить ID")],
        [KeyboardButton(text="👑 Выдать VIP"), KeyboardButton(text="📜 Логи запросов")],
        [KeyboardButton(text="🔙 Назад в Админку")]
    ], resize_keyboard=True)

# --- [ ИНИЦИАЛИЗАЦИЯ БОТА ] ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    register_user(message.from_user)
    welcome_msg = (
        f"👋 **Приветствуем в {VERSION}!**\n\n"
        "Я — высокопроизводительный поисковой агрегатор на базе ИИ.\n"
        "Используйте меню ниже для навигации."
    )
    await message.answer(welcome_msg, reply_markup=get_main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⚠️ Доступ запрещен. Ваш ID не в списке Root-администраторов.")
    await message.answer("🛡 **OMNI-MAX CORE: АВТОРИЗАЦИЯ УСПЕШНА**", reply_markup=get_admin_kb())

# --- [ ФУНКЦИОНАЛ ПОЛЬЗОВАТЕЛЯ ] ---

@dp.message(F.text == "👤 Мой Профиль")
async def user_profile(message: types.Message):
    u = db_users.get(str(message.from_user.id))
    if not u: return
    
    vip_status = "✅ Активирован" if u['is_vip'] else "❌ Отсутствует"
    text = (
        f"👤 **ВАШ ТИТАН-ПРОФИЛЬ**\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"📅 Регистрация: `{u['join_date']}`\n"
        f"🔎 Поисков выполнено: `{u['search_count']}`\n"
        f"💎 VIP: {vip_status}\n"
        f"🌐 Язык: `Украинский/Русский`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📜 История запросов")
async def user_history(message: types.Message):
    u = db_users.get(str(message.from_user.id))
    hist = u.get("history", [])
    if not hist:
        return await message.answer("Ваша история поиска пока пуста.")
    
    formatted = "\n".join([f"• {item}" for item in hist[-10:]])
    await message.answer(f"📜 **ВАШИ ПОСЛЕДНИЕ ЗАПРОСЫ:**\n\n{formatted}", parse_mode="Markdown")

@dp.message(F.text == "💎 VIP Статус")
async def user_vip_info(message: types.Message):
    await message.answer(
        "💎 **VIP ПРИВИЛЕГИИ:**\n\n"
        "1. Парсинг закрытых площадок.\n"
        "2. Увеличенная скорость (Turbo Scrape).\n"
        "3. Отсутствие задержек между запросами.\n"
        "4. Ранний доступ к v19.0.\n\n"
        "Для покупки обратитесь к @Daxo_Official"
    )

# --- [ АДМИН-ПАНЕЛЬ: УПРАВЛЕНИЕ СИСТЕМОЙ ] ---

@dp.message(F.text == "📊 Статистика Системы")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    # Сбор данных о системе
    mem_total, mem_used, mem_free = shutil.disk_usage("/")
    uptime = subprocess.getoutput("uptime -p")
    db_size = os.path.getsize(DB_USERS) / 1024
    
    text = (
        "📊 **OMNI-MAX GLOBAL REPORT**\n\n"
        f"👥 Всего юзеров: `{len(db_users)}`\n"
        f"🔎 Всего поисков: `{db_stats['total_searches']}`\n"
        f"❌ Ошибок системы: `{db_stats['errors']}`\n"
        f"💾 База данных: `{db_size:.2f} KB`\n"
        f"⏳ Uptime: `{uptime}`\n"
        f"🧠 Диск: `{mem_used // (2**30)} ГБ / {mem_total // (2**30)} ГБ`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🐚 Терминал (SSH)")
async def admin_terminal_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(SystemStates.admin_terminal)
    await message.answer("🐚 **READY FOR COMMANDS**\nВведите команду для исполнения или 'exit' для выхода.")

@dp.message(SystemStates.admin_terminal)
async def admin_terminal_proc(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Терминал закрыт.", reply_markup=get_admin_kb())
    
    try:
        # Выполнение команды
        result = subprocess.check_output(message.text, shell=True, stderr=subprocess.STDOUT, timeout=15).decode("utf-8")
        if not result: result = "Done (No output)."
        await message.answer(f"✅ **OUTPUT:**\n`{result[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ **ERROR:**\n`{str(e)}`", parse_mode="Markdown")

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(SystemStates.admin_broadcast)
    await message.answer("Отправьте сообщение (текст/фото/видео), которое получат все.")

@dp.message(SystemStates.admin_broadcast)
async def admin_broadcast_proc(message: types.Message, state: FSMContext):
    uids = list(db_users.keys())
    sent = 0
    await message.answer(f"🚀 Запущена рассылка на {len(uids)} человек...")
    
    for uid in uids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except: continue
        
    await state.clear()
    await message.answer(f"✅ Рассылка завершена. Получили: {sent} юзеров.", reply_markup=get_admin_kb())

@dp.message(F.text == "📂 Дамп БД")
async def admin_dump(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer_document(FSInputFile(DB_USERS), caption="📦 Дамп базы пользователей")
    await message.answer_document(FSInputFile(DB_STATS), caption="📈 Дамп статистики")

@dp.message(F.text == "🔙 Выход из Админки")
async def exit_admin(message: types.Message):
    await message.answer("Вы перешли в режим пользователя.", reply_markup=get_main_kb(message.from_user.id))

# --- [ ЯДРО ПОИСКА: TITAN OMNI ENGINE ] ---

async def perform_scraping(context, site_name, url_template, query):
    page = await context.new_page()
    try:
        url = url_template.replace("{q}", query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded", timeout=sys_config["search_timeout"])
        
        # Интеллектуальное ожидание и эмуляция прокрутки
        await asyncio.sleep(random.uniform(2, 4))
        await page.mouse.wheel(0, 500)
        
        # JS-скрипт для извлечения данных (находит ссылки, содержащие слова запроса)
        results = await page.evaluate(f"""
            () => {{
                const qWords = "{query.lower()}".split(" ");
                const links = Array.from(document.querySelectorAll('a'));
                const found = [];
                for (let a of links) {{
                    const t = a.innerText.toLowerCase();
                    if (qWords.every(w => t.includes(w)) && a.href.startsWith('http') && t.length > 10) {{
                        found.push({{ title: a.innerText.trim().split('\\n')[0], link: a.href }});
                    }}
                    if (found.length >= 2) break;
                }}
                return found;
            }}
        """)
        return [f"📦 **{site_name}**: {r['title'][:55]}...\n🔗 {r['link']}" for r in results]
    except Exception as e:
        logger.error(f"Scrape Error at {site_name}: {str(e)}")
        return []
    finally:
        await page.close()

# --- [ ОБРАБОТЧИК ВСЕХ ТЕКСТОВЫХ СООБЩЕНИЙ ] ---

@dp.message(F.text)
async def main_handler(message: types.Message):
    # 1. Исключаем кнопки из поиска
    reserved_texts = [
        "🔍 Начать поиск", "👤 Мой Профиль", "📜 История запросов", "⚙️ Настройки", "🆘 Поддержка", "💎 VIP Статус",
        "📊 Статистика Системы", "👥 Управление Юзерами", "📢 Рассылка", "🐚 Терминал (SSH)", "⚙️ Конфиг Ядра",
        "📂 Дамп БД", "🛑 Режим Техработ", "🔙 Выход из Админки", "🚫 Забанить ID", "✅ Разбанить ID",
        "👑 Выдать VIP", "📜 Логи запросов", "🔙 Назад в Админку", "🔱 ПАНЕЛЬ УПРАВЛЕНИЯ 🔱"
    ]
    if message.text in reserved_texts or message.text.startswith("/"):
        # Если нажата кнопка админки (через текст)
        if message.text == "🔱 ПАНЕЛЬ УПРАВЛЕНИЯ 🔱":
            return await cmd_admin(message)
        return

    # 2. Проверка техработ
    if sys_config["maint_mode"] and message.from_user.id != ADMIN_ID:
        return await message.answer("🚧 **СИСТЕМА НА ОБСЛУЖИВАНИИ**\n\nМы обновляем базу данных. Попробуйте через 30 минут.")

    # 3. Обновление БД
    uid = str(message.from_user.id)
    if uid in db_users:
        db_users[uid]["search_count"] += 1
        db_users[uid]["history"] = ([message.text] + db_users[uid]["history"])[:sys_config["max_history"]]
        db_users[uid]["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_json(DB_USERS, db_users)
    
    db_stats["total_searches"] += 1
    save_json(DB_STATS, db_stats)

    # 4. Процесс парсинга
    status = await message.answer(f"🛰 **OMNI-ENGINE v18 АКТИВИРОВАН**\n📡 *Запрос:* `{message.text}`\n🔍 *Статус:* Сканирование сетей...", parse_mode="Markdown")

    q = message.text.lower()
    search_map = {
        "Rozetka": "https://rozetka.com.ua/search/?text={q}",
        "Prom": "https://prom.ua/search?search_term={q}",
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/"
    }
    
    # Расширенный поиск для авто
    if any(car in q for car in ["авто", "машина", "bmw", "audi", "mazda", "ford", "mercedes"]):
        search_map["AutoRia"] = "https://auto.ria.com/uk/search/?q={q}"

    async with async_playwright() as p:
        # Установка браузера если нет (на всякий случай)
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
        
        tasks = [perform_scraping(context, name, url, message.text) for name, url in search_map.items()]
        combined_results = await asyncio.gather(*tasks)
        await browser.close()

    # Сглаживание списка результатов
    final_results = [item for sublist in combined_results for item in sublist]
    await status.delete()

    if final_results:
        output = "✅ **РЕЗУЛЬТАТЫ ПОИСКА OMNI:**\n\n" + "\n\n".join(final_results)
        await message.answer(output, disable_web_page_preview=True, parse_mode="Markdown")
    else:
        db_stats["errors"] += 1
        save_json(DB_STATS, db_stats)
        await message.answer("❌ **Товаров не найдено.**\nПопробуйте изменить запрос (например, уберите лишние слова).")

# --- [ ЗАПУСК ВЕБ-СЕРВЕРА (RENDER HEALTH CHECK) ] ---

async def health_check(request):
    return web.Response(text=f"OMNI MAX v18.0: RUNNING\nUPTIME: {datetime.now()}", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- [ ГЛАВНЫЙ ЦИКЛ RUN ] ---

async def main():
    logger.info("--- ЗАПУСК СИСТЕМЫ TITAN OMNI-MAX ---")
    
    # 1. Сброс конфликтов (САМОЕ ВАЖНОЕ ДЛЯ ТЕБЯ)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 2. Установка браузера (автоматизация для Render)
    subprocess.run(["playwright", "install", "chromium"])
    
    # 3. Запуск веб-сервера
    await start_web()
    
    # 4. Установка команд меню
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admin", description="Админ-панель (только Root)")
    ], scope=BotCommandScopeDefault())
    
    # 5. Старт поллинга
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка работы: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Система остановлена пользователем.")