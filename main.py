import asyncio
import os
import json
import subprocess
import logging
import random
import time
import sys
import shutil
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, 
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ СИСТЕМЫ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TITAN-CORE")

# Файлы БД
DB_PATH = "titan_users.json"
LOG_PATH = "titan_system.log"
CONFIG_PATH = "titan_config.json"

# Инициализация бота
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ КЛАССЫ СОСТОЯНИЙ (FSM) ] ---
class AdminStates(StatesGroup):
    wait_for_broadcast = State()
    wait_for_terminal = State()
    wait_for_ban_id = State()
    wait_for_timeout = State()

# --- [ СИСТЕМНЫЕ ФУНКЦИИ И БД ] ---

def init_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w") as f:
            json.dump({}, f)
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "turbo_mode": False,
            "maint_mode": False,
            "timeout": 40000,
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ]
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(default_config, f)

def get_db():
    with open(DB_PATH, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=4, ensure_all_ascii=False)

def get_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

def write_log(message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {message}\n")

# --- [ КЛАВИАТУРЫ ] ---

def get_user_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Найти товар")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📜 История")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🆘 Поддержка")]
    ], resize_keyboard=True)

def get_admin_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖥 СТАТУС СЕРВЕРА"), KeyboardButton(text="📊 СТАТИСТИКА ЮЗЕРОВ")],
        [KeyboardButton(text="📢 РАССЫЛКА"), KeyboardButton(text="🚫 УПРАВЛЕНИЕ БАНОМ")],
        [KeyboardButton(text="⚙️ КОНФИГУРАЦИЯ"), KeyboardButton(text="🐚 ТЕРМИНАЛ")],
        [KeyboardButton(text="📜 ПОСЛЕДНИЕ ЛОГИ"), KeyboardButton(text="🔙 ВЫЙТИ ИЗ АДМИНКИ")]
    ], resize_keyboard=True)

def get_admin_conf_kb():
    conf = get_config()
    turbo = "🚀 ТУРБО: ВКЛ" if conf["turbo_mode"] else "🚀 ТУРБО: ВЫКЛ"
    maint = "🛠 ТЕХРАБ: ВКЛ" if conf["maint_mode"] else "🛠 ТЕХРАБ: ВЫКЛ"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=turbo), KeyboardButton(text=maint)],
        [KeyboardButton(text="⏱ ИЗМЕНИТЬ ТАЙМАУТ"), KeyboardButton(text="🧹 ОЧИСТИТЬ ЛОГИ")],
        [KeyboardButton(text="🔙 НАЗАД В АДМИНКУ")]
    ], resize_keyboard=True)

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    db = get_db()
    uid = str(message.from_user.id)
    if uid not in db:
        db[uid] = {
            "name": message.from_user.full_name,
            "reg_date": datetime.now().strftime("%d.%m.%Y"),
            "searches": 0,
            "history": [],
            "is_banned": False
        }
        save_db(db)
        write_log(f"Новый пользователь: {uid} ({message.from_user.full_name})")

    welcome_text = (
        "🛡 **CHIIP TITAN v16.0 АКТИВИРОВАН**\n\n"
        f"Добро пожаловать, {message.from_user.first_name}!\n"
        "Я — профессиональный поисковой инструмент. Используйте меню ниже."
    )
    await message.answer(welcome_text, reply_markup=get_user_kb(), parse_mode="Markdown")

@dp.message(Command("admin"))
async def admin_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Доступ запрещен. Ошибка 403.")
    
    await message.answer("🧪 **TITAN CORE: АВТОРИЗАЦИЯ УСПЕШНА**", reply_markup=get_admin_main_kb())

# --- [ ЮЗЕР-ФУНКЦИОНАЛ ] ---

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    db = get_db()
    user = db.get(str(message.from_user.id))
    if not user: return
    
    text = (
        "👤 **ВАШ ТИТАН-ПРОФИЛЬ**\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"📅 В системе с: {user['reg_date']}\n"
        f"🔎 Успешных поисков: {user['searches']}\n"
        f"🛡 Статус: {'Активен' if not user['is_banned'] else 'Заблокирован'}"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📜 История")
async def history_handler(message: types.Message):
    db = get_db()
    user = db.get(str(message.from_user.id))
    hist = user.get("history", [])
    
    if not hist:
        return await message.answer("📜 Ваша история поиска пока пуста.")
    
    formatted_hist = "\n".join([f"🔹 {item}" for item in hist])
    await message.answer(f"📜 **ПОСЛЕДНИЕ ЗАПРОСЫ:**\n\n{formatted_hist}", parse_mode="Markdown")

@dp.message(F.text == "🔍 Найти товар")
async def find_info_handler(message: types.Message):
    await message.answer("⌨️ Введите название товара (например: *PlayStation 5* или *Mazda 6*):", parse_mode="Markdown")

@dp.message(F.text == "⚙️ Настройки")
async def user_settings_handler(message: types.Message):
    await message.answer("⚙️ **Настройки поиска**\n\nВ текущей версии v16.0 все параметры оптимизированы автоматически.")

@dp.message(F.text == "🆘 Поддержка")
async def support_handler(message: types.Message):
    await message.answer("🆘 **Служба поддержки**\n\nЕсли у вас возникли проблемы, напишите разработчику: @ваша_ссылка_тут")

# --- [ АДМИН-ФУНКЦИОНАЛ: СЕРВЕР И СТАТИСТИКА ] ---

@dp.message(F.text == "🖥 СТАТУС СЕРВЕРА")
async def admin_server_status(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    mem = psutil_sim_mem = subprocess.getoutput("free -m | grep Mem | awk '{print $3 \" / \" $2 \" MB\"}'")
    cpu = subprocess.getoutput("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
    disk = subprocess.getoutput("df -h / | tail -1 | awk '{print $3 \" / \" $2}'")
    uptime = subprocess.getoutput("uptime -p")
    
    text = (
        "🖥 **TITAN SERVER MONITOR**\n\n"
        f"🧠 RAM: `{mem}`\n"
        f"🔥 CPU Load: `{cpu}%`\n"
        f"💾 Disk: `{disk}`\n"
        f"⏳ Uptime: `{uptime}`\n"
        f"🐍 Python: `{sys.version.split()[0]}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📊 СТАТИСТИКА ЮЗЕРОВ")
async def admin_user_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    db = get_db()
    total_users = len(db)
    banned_users = sum(1 for u in db.values() if u.get("is_banned"))
    total_searches = sum(u.get("searches", 0) for u in db.values())
    
    text = (
        "📊 **GLOBAL STATISTICS**\n\n"
        f"👥 Всего пользователей: `{total_users}`\n"
        f"🚫 Забанено: `{banned_users}`\n"
        f"🔎 Всего поисковых сессий: `{total_searches}`\n"
        f"📂 Размер БД: `{os.path.getsize(DB_PATH) / 1024:.2f} KB`"
    )
    await message.answer(text, parse_mode="Markdown")

# --- [ АДМИН-ФУНКЦИОНАЛ: РАССЫЛКА (FSM) ] ---

@dp.message(F.text == "📢 РАССЫЛКА")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.wait_for_broadcast)
    await message.answer("📢 **РЕЖИМ РАССЫЛКИ**\n\nВведите сообщение, которое получат все пользователи бота. Для отмены напишите 'отмена'.")

@dp.message(AdminStates.wait_for_broadcast)
async def broadcast_process(message: types.Message, state: FSMContext):
    if message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("❌ Рассылка отменена.", reply_markup=get_admin_main_kb())
    
    db = get_db()
    users = list(db.keys())
    count = 0
    
    msg = await message.answer(f"🚀 Начинаю рассылку на {len(users)} юзеров...")
    
    for uid in users:
        try:
            await bot.send_message(uid, message.text)
            count += 1
            if count % 10 == 0:
                await msg.edit_text(f"🚀 Отправлено: {count}/{len(users)}")
            await asyncio.sleep(0.05)
        except Exception:
            continue
            
    await state.clear()
    await message.answer(f"✅ Рассылка завершена! Получили: {count} человек.", reply_markup=get_admin_main_kb())

# --- [ АДМИН-ФУНКЦИОНАЛ: ТЕРМИНАЛ (FSM) ] ---

@dp.message(F.text == "🐚 ТЕРМИНАЛ")
async def terminal_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.wait_for_terminal)
    await message.answer("🐚 **TITAN SHELL АКТИВИРОВАН**\n\nВведите команду для исполнения в ОС. Напишите 'exit' для выхода.")

@dp.message(AdminStates.wait_for_terminal)
async def terminal_process(message: types.Message, state: FSMContext):
    if message.text.lower() in ["exit", "выход"]:
        await state.clear()
        return await message.answer("🐚 Shell закрыт.", reply_markup=get_admin_main_kb())
    
    try:
        # Выполняем команду
        result = subprocess.check_output(message.text, shell=True, stderr=subprocess.STDOUT, timeout=10).decode("utf-8")
        if not result: result = "Команда выполнена (без вывода)."
        await message.answer(f"✅ **Результат:**\n`{result[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ **Ошибка:**\n`{str(e)}`", parse_mode="Markdown")

# --- [ АДМИН-ФУНКЦИОНАЛ: КОНФИГ И ЛОГИ ] ---

@dp.message(F.text == "⚙️ КОНФИГУРАЦИЯ")
async def admin_config_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("⚙️ Управление параметрами системы:", reply_markup=get_admin_conf_kb())

@dp.message(F.text.startswith("🚀 ТУРБО:"))
async def toggle_turbo(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    c = get_config()
    c["turbo_mode"] = not c["turbo_mode"]
    c["timeout"] = 80000 if c["turbo_mode"] else 40000
    save_config(c)
    await message.answer(f"✅ Турбо-режим {'ВКЛЮЧЕН' if c['turbo_mode'] else 'ВЫКЛЮЧЕН'}", reply_markup=get_admin_conf_kb())

@dp.message(F.text == "📜 ПОСЛЕДНИЕ ЛОГИ")
async def admin_view_logs(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            last_logs = "".join(lines[-15:])
            await message.answer(f"📜 **ПОСЛЕДНИЕ ЛОГИ СИСТЕМЫ:**\n\n`{last_logs}`", parse_mode="Markdown")

@dp.message(F.text == "🧹 ОЧИСТИТЬ ЛОГИ")
async def admin_clear_logs(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    open(LOG_PATH, "w").close()
    await message.answer("🧹 Файл логов полностью очищен.")

@dp.message(F.text == "🔙 НАЗАД В АДМИНКУ")
async def back_admin_handler(message: types.Message):
    await admin_handler(message)

@dp.message(F.text == "🔙 ВЫЙТИ ИЗ АДМИНКИ")
async def exit_admin_handler(message: types.Message):
    await message.answer("Вы вышли из админ-панели.", reply_markup=get_user_kb())

# --- [ ЯДРО ПОИСКА: TITAN SCRAPE ENGINE ] ---

async def scrape_site(context, name, url, query):
    page = await context.new_page()
    config = get_config()
    
    # Эмуляция реального юзера
    await page.set_extra_http_headers({"Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"})
    
    try:
        search_url = url.replace("{q}", query.replace(" ", "+"))
        await page.goto(search_url, wait_until="domcontentloaded", timeout=config["timeout"])
        
        # Рандомная пауза
        await asyncio.sleep(random.uniform(2, 4))
        
        # Универсальный алгоритм извлечения релевантных ссылок
        results = await page.evaluate(f"""
            () => {{
                const q = "{query.lower()}".split(" ");
                const links = Array.from(document.querySelectorAll('a'));
                const valid = [];
                
                for (let a of links) {{
                    const text = a.innerText.toLowerCase();
                    const href = a.href;
                    
                    if (q.every(word => text.includes(word)) && 
                        href.startsWith('http') && 
                        !href.includes('google') && 
                        text.length > 15) {{
                        valid.push({{ title: a.innerText.trim(), link: href }});
                    }}
                    if (valid.length >= 2) break;
                }}
                return valid;
            }}
        """)
        
        return [f"📦 **{name}**: {r['title'][:60]}...\n🔗 {r['link']}" for r in results]
    except Exception as e:
        write_log(f"Ошибка парсинга {name}: {str(e)}")
        return []
    finally:
        await page.close()

# --- [ ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ТЕКСТА (ПОИСК) ] ---

@dp.message(F.text)
async def main_search_logic(message: types.Message):
    # 1. Проверка на служебные кнопки
    reserved = [
        "🔍 Найти товар", "👤 Профиль", "📜 История", "⚙️ Настройки", "🆘 Поддержка",
        "🖥 СТАТУС СЕРВЕРА", "📊 СТАТИСТИКА ЮЗЕРОВ", "📢 РАССЫЛКА", "🚫 УПРАВЛЕНИЕ БАНОМ",
        "⚙️ КОНФИГУРАЦИЯ", "🐚 ТЕРМИНАЛ", "📜 ПОСЛЕДНИЕ ЛОГИ", "🔙 ВЫЙТИ ИЗ АДМИНКИ",
        "🚀 ТУРБО: ВКЛ", "🚀 ТУРБО: ВЫКЛ", "🛠 ТЕХРАБ: ВКЛ", "🛠 ТЕХРАБ: ВЫКЛ",
        "⏱ ИЗМЕНИТЬ ТАЙМАУТ", "🧹 ОЧИСТИТЬ ЛОГИ", "🔙 НАЗАД В АДМИНКУ"
    ]
    if message.text in reserved or message.text.startswith("/"):
        return

    # 2. Проверка техработ
    conf = get_config()
    if conf["maint_mode"] and message.from_user.id != ADMIN_ID:
        return await message.answer("🛠 Извините, в боте проводятся технические работы. Попробуйте позже.")

    # 3. Регистрация поиска
    db = get_db()
    uid = str(message.from_user.id)
    if uid in db:
        db[uid]["searches"] += 1
        db[uid]["history"] = ([message.text] + db[uid]["history"])[:5]
        save_db(db)
    
    status_msg = await message.answer(f"🛰 **TITAN ENGINE начал поиск:** `{message.text}`...", parse_mode="Markdown")
    write_log(f"Поиск: {message.text} от {uid}")

    # 4. Выбор сайтов
    query = message.text.lower()
    is_car = any(x in query for x in ["mazda", "bmw", "audi", "mercedes", "ford", "toyota", "авто", "машина"])
    
    target_sites = {
        "AutoRia": "https://auto.ria.com/uk/search/?q={q}",
        "OLX Auto": "https://www.olx.ua/d/uk/transport/legkovye-avtomobili/q-{q}/"
    } if is_car else {
        "Rozetka": "https://rozetka.com.ua/search/?text={q}",
        "Prom": "https://prom.ua/search?search_term={q}",
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/"
    }

    # 5. Процесс парсинга
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(user_agent=random.choice(conf["user_agents"]))
        
        tasks = [scrape_site(context, name, url, message.text) for name, url in target_sites.items()]
        raw_results = await asyncio.gather(*tasks)
        
        await browser.close()

    # 6. Вывод
    final_results = [res for sublist in raw_results for res in sublist]
    await status_msg.delete()

    if final_results:
        response = "✅ **РЕЗУЛЬТАТЫ ПОИСКА TITAN:**\n\n" + "\n\n".join(final_results)
        await message.answer(response, disable_web_page_preview=True, parse_mode="Markdown")
    else:
        await message.answer("❌ **Ничего не найдено.**\nПопробуйте изменить или упростить запрос.")

# --- [ ЗАПУСК СЕРВЕРА И БОТА ] ---

async def handle_web(request):
    return web.Response(text="TITAN CORE v16.0 ONLINE")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

async def main():
    init_db()
    # Установка браузера playwright
    subprocess.run(["playwright", "install", "chromium"])
    
    # Запуск веб-сервера (для Render)
    await start_web_server()
    
    # Запуск бота
    write_log("Система TITAN запущена.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        write_log("Система TITAN остановлена.")