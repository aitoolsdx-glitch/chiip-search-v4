import asyncio
import os
import json
import subprocess
import logging
import random
import time
import sys
import platform
from datetime import datetime, timedelta

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

# --- [ СИСТЕМНЫЕ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446 # Твой ID
PORT = int(os.environ.get("PORT", 8080))

# Глубокое логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("omni_system.log"), logging.StreamHandler()]
)
logger = logging.getLogger("OMNI-CORE")

# Файлы данных
DB_PATH = "omni_users.json"
CONFIG_PATH = "omni_config.json"
GLOBAL_STATS_PATH = "omni_stats.json"

# --- [ FSM: СОСТОЯНИЯ ] ---
class OmniStates(StatesGroup):
    wait_for_broadcast = State()
    wait_for_shell = State()
    wait_for_ban = State()
    wait_for_unban = State()
    wait_for_search = State()
    wait_for_vip_add = State()
    wait_for_timeout_change = State()

# --- [ ИНИЦИАЛИЗАЦИЯ БД И КОНФИГА ] ---

def init_system():
    if not os.path.exists(DB_PATH):
        json.dump({}, open(DB_PATH, "w"))
    if not os.path.exists(CONFIG_PATH):
        default_conf = {
            "turbo": False, "maint": False, "timeout": 45000,
            "proxies": [], "max_history": 10, "ver": "17.0 OMNI"
        }
        json.dump(default_conf, open(CONFIG_PATH, "w"))
    if not os.path.exists(GLOBAL_STATS_PATH):
        json.dump({"total_searches": 0, "errors": 0, "starts": 0}, open(GLOBAL_STATS_PATH, "w"))

def get_db(): return json.load(open(DB_PATH))
def save_db(data): json.dump(data, open(DB_PATH, "w", encoding="utf-8"), indent=4, ensure_all_ascii=False)
def get_conf(): return json.load(open(CONFIG_PATH))
def save_conf(c): json.dump(c, open(CONFIG_PATH, "w"), indent=4)
def get_gstats(): return json.load(open(GLOBAL_STATS_PATH))
def save_gstats(s): json.dump(s, open(GLOBAL_STATS_PATH, "w"))

# --- [ КЛАВИАТУРЫ: ГИПЕР-ИНТЕРФЕЙС ] ---

def kb_user_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 ПОИСК ТОВАРА"), KeyboardButton(text="💎 VIP ДОСТУП")],
        [KeyboardButton(text="👤 МОЙ АККАУНТ"), KeyboardButton(text="📜 ИСТОРИЯ")],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="🆘 ПОМОЩЬ")]
    ], resize_keyboard=True)

def kb_admin_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛰 МОНИТОРИНГ"), KeyboardButton(text="👥 ЮЗЕР-МЕНЕДЖЕР")],
        [KeyboardButton(text="📢 РАССЫЛКА"), KeyboardButton(text="💻 КОНСОЛЬ")],
        [KeyboardButton(text="🛠 КОНФИГУРАЦИЯ"), KeyboardButton(text="📂 БЭКАП БД")],
        [KeyboardButton(text="🔄 REBOOT СЕРВЕРА"), KeyboardButton(text="🚪 ВЫЙТИ")]
    ], resize_keyboard=True)

def kb_admin_users():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚫 ЗАБАНИТЬ"), KeyboardButton(text="✅ РАЗБАНИТЬ")],
        [KeyboardButton(text="👑 ВЫДАТЬ VIP"), KeyboardButton(text="📊 ТОП ЮЗЕРОВ")],
        [KeyboardButton(text="🔙 НАЗАД")]
    ], resize_keyboard=True)

def kb_admin_config():
    c = get_conf()
    t = "🚀 ТУРБО: ВКЛ" if c["turbo"] else "🚀 ТУРБО: ВЫКЛ"
    m = "🚧 ТЕХРАБ: ВКЛ" if c["maint"] else "🚧 ТЕХРАБ: ВЫКЛ"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t), KeyboardButton(text=m)],
        [KeyboardButton(text="⏱ ТАЙМАУТ"), KeyboardButton(text="🧹 ЧИСТКА ЛОГОВ")],
        [KeyboardButton(text="🔙 НАЗАД")]
    ], resize_keyboard=True)

# --- [ MIDDLEWARE & UTILS ] ---

def is_admin(u_id): return u_id == ADMIN_ID

def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))

async def update_stat(key):
    s = get_gstats()
    s[key] += 1
    save_gstats(s)

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    db = get_db()
    uid = str(message.from_user.id)
    if uid not in db:
        db[uid] = {
            "u": message.from_user.username,
            "d": datetime.now().strftime("%Y-%m-%d"),
            "s": 0, "h": [], "b": False, "vip": False
        }
        save_db(db)
        await update_stat("starts")
    
    await message.answer(
        f"🤖 **OMNI-SYSTEM v17.0 ONLINE**\n\nПривет, {message.from_user.first_name}!\nЯ готов к поиску любой сложности.",
        reply_markup=kb_user_main(), parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🧪 **ДОСТУП К OMNI-CORE РАЗРЕШЕН**", reply_markup=kb_admin_main())

# --- [ ЮЗЕР-СЕРВИСЫ ] ---

@dp.message(F.text == "👤 МОЙ АККАУНТ")
async def user_acc(message: types.Message):
    db = get_db()
    u = db.get(str(message.from_user.id))
    status = "👑 VIP Пользователь" if u.get("vip") else "👤 Обычный"
    text = (f"👤 **ПРОФИЛЬ: {message.from_user.full_name}**\n\n"
            f"🆔 ID: `{message.from_user.id}`\n"
            f"📊 Статус: {status}\n"
            f"📅 В системе: {u['d']}\n"
            f"🔎 Поисков: {u['s']}")
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📜 ИСТОРИЯ")
async def user_hist(message: types.Message):
    db = get_db()
    h = db.get(str(message.from_user.id), {}).get("h", [])
    if not h: return await message.answer("История пуста.")
    text = "📜 **ПОСЛЕДНИЕ ЗАПРОСЫ:**\n\n" + "\n".join([f"• {x}" for x in h])
    await message.answer(text)

@dp.message(F.text == "💎 VIP ДОСТУП")
async def user_vip(message: types.Message):
    await message.answer("💎 **Преимущества VIP:**\n\n1. Приоритетный поиск.\n2. Доступ к закрытым базам.\n3. Без ограничений по количеству.\n\n*Для получения напишите администратору.*")

# --- [ АДМИН-ЛОГИКА: МОНИТОРИНГ ] ---

@dp.message(F.text == "🛰 МОНИТОРИНГ")
async def adm_mon(message: types.Message):
    if not is_admin(message.from_user.id): return
    
    mem = subprocess.getoutput("free -m | grep Mem | awk '{print $3 \"/\" $2 \"MB\"}'")
    load = platform.loadavg() if platform.system() != 'Windows' else "N/A"
    st = get_gstats()
    
    text = (f"🛰 **SYSTEM OMNI REPORT**\n\n"
            f"🧠 RAM: `{mem}`\n"
            f"📈 Load: `{load}`\n"
            f"👥 Юзеров: {len(get_db())}\n"
            f"🔎 Всего поисков: {st['total_searches']}\n"
            f"❌ Ошибок ИИ: {st['errors']}")
    await message.answer(text, parse_mode="Markdown")

# --- [ АДМИН-ЛОГИКА: КОНСОЛЬ (FSM) ] ---

@dp.message(F.text == "💻 КОНСОЛЬ")
async def adm_shell(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(OmniStates.wait_for_shell)
    await message.answer("💻 **OMNI SHELL READY**\nВведите команду или 'exit':")

@dp.message(OmniStates.wait_for_shell)
async def shell_proc(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Консоль закрыта.", reply_markup=kb_admin_main())
    
    try:
        res = subprocess.check_output(message.text, shell=True, stderr=subprocess.STDOUT, timeout=15).decode("utf-8")
        await message.answer(f"✅ `Result:`\n`{res[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ `Error:`\n`{str(e)}`", parse_mode="Markdown")

# --- [ АДМИН-ЛОГИКА: РАССЫЛКА ] ---

@dp.message(F.text == "📢 РАССЫЛКА")
async def adm_br(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(OmniStates.wait_for_broadcast)
    await message.answer("Введите текст рассылки:")

@dp.message(OmniStates.wait_for_broadcast)
async def br_proc(message: types.Message, state: FSMContext):
    db = get_db()
    ids = list(db.keys())
    done, err = 0, 0
    for uid in ids:
        try:
            await bot.send_message(uid, f"📢 **СООБЩЕНИЕ ОТ АДМИНИСТРАЦИИ**\n\n{message.text}", parse_mode="Markdown")
            done += 1
            await asyncio.sleep(0.05)
        except: err += 1
    await state.clear()
    await message.answer(f"✅ Готово! Успешно: {done}, Ошибок: {err}")

# --- [ АДМИН-ЛОГИКА: КОНФИГ ] ---

@dp.message(F.text == "🛠 КОНФИГУРАЦИЯ")
async def adm_conf(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("Настройки ядра:", reply_markup=kb_admin_config())

@dp.message(F.text.contains("🚀 ТУРБО:"))
async def toggle_turbo(message: types.Message):
    if not is_admin(message.from_user.id): return
    c = get_conf()
    c["turbo"] = not c["turbo"]
    c["timeout"] = 90000 if c["turbo"] else 45000
    save_conf(c)
    await adm_conf(message)

# --- [ ЯДРО ПОИСКА: OMNI SCRAPE ENGINE ] ---

async def titan_parser(context, name, url, query):
    page = await context.new_page()
    conf = get_conf()
    try:
        # Интеллектуальный поиск
        target = url.replace("{q}", query.replace(" ", "+"))
        await page.goto(target, wait_until="domcontentloaded", timeout=conf["timeout"])
        await asyncio.sleep(random.uniform(2, 4)) # Анти-фрод

        # Динамический сбор данных через JS
        results = await page.evaluate(f"""
            () => {{
                const q = "{query.lower()}".split(" ");
                const items = Array.from(document.querySelectorAll('a'));
                return items
                    .filter(a => {{
                        const t = a.innerText.toLowerCase();
                        return q.every(w => t.includes(w)) && a.href.startsWith('http') && t.length > 10;
                    }})
                    .slice(0, 2)
                    .map(a => ({{ title: a.innerText.trim().split('\\n')[0], link: a.href }}));
            }}
        """)
        return [f"📦 **{name}**: {r['title'][:60]}...\n🔗 {r['link']}" for r in results]
    except Exception as e:
        logger.error(f"Scrape Error {name}: {str(e)}")
        return []
    finally:
        await page.close()

# --- [ ГЛАВНЫЙ ОБРАБОТЧИК (SEARCH) ] ---

@dp.message(F.text)
async def main_engine(message: types.Message):
    # Фильтр кнопок
    reserved = [
        "🔍 ПОИСК ТОВАРА", "💎 VIP ДОСТУП", "👤 МОЙ АККАУНТ", "📜 ИСТОРИЯ", "⚙️ НАСТРОЙКИ", "🆘 ПОМОЩЬ",
        "🛰 МОНИТОРИНГ", "👥 ЮЗЕР-МЕНЕДЖЕР", "📢 РАССЫЛКА", "💻 КОНСОЛЬ", "🛠 КОНФИГУРАЦИЯ", "📂 БЭКАП БД",
        "🔄 REBOOT СЕРВЕРА", "🚪 ВЫЙТИ", "🔙 НАЗАД", "🚫 ЗАБАНИТЬ", "✅ РАЗБАНИТЬ", "👑 ВЫДАДЬ VIP", "📊 ТОП ЮЗЕРОВ",
        "🚀 ТУРБО: ВКЛ", "🚀 ТУРБО: ВЫКЛ", "🚧 ТЕХРАБ: ВКЛ", "🚧 ТЕХРАБ: ВЫКЛ", "⏱ ТАЙМАУТ", "🧹 ЧИСТКА ЛОГОВ"
    ]
    if message.text in reserved or message.text.startswith("/"): return

    # Проверка техработ
    conf = get_conf()
    if conf["maint"] and not is_admin(message.from_user.id):
        return await message.answer("🚧 Бот временно на обслуживании.")

    # Логика БД
    db = get_db()
    uid = str(message.from_user.id)
    if uid in db:
        db[uid]["s"] += 1
        db[uid]["h"] = ([message.text] + db[uid]["h"])[:conf["max_history"]]
        save_db(db)
    
    await update_stat("total_searches")
    status = await message.answer(f"🛰 **OMNI ИЩЕТ:** `{message.text}`...", parse_mode="Markdown")

    # Маршрутизация сайтов
    q = message.text.lower()
    sites = {
        "Rozetka": "https://rozetka.com.ua/search/?text={q}",
        "Prom": "https://prom.ua/search?search_term={q}",
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/"
    }
    if any(x in q for x in ["авто", "машина", "bmw", "mercedes", "audi", "mazda"]):
        sites["AutoRia"] = "https://auto.ria.com/uk/search/?q={q}"

    # Парсинг
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        tasks = [titan_parser(context, name, url, message.text) for name, url in sites.items()]
        final_list = await asyncio.gather(*tasks)
        await browser.close()

    res = [item for sub in final_list for item in sub]
    await status.delete()

    if res:
        await message.answer("✅ **РЕЗУЛЬТАТЫ OMNI-CORE:**\n\n" + "\n\n".join(res), disable_web_page_preview=True)
    else:
        await update_stat("errors")
        await message.answer("❌ **Товаров не найдено.** Попробуйте упростить запрос.")

# --- [ ЗАПУСК СЕРВЕРА ] ---

async def web_handle(request): return web.Response(text="OMNI v17.0 ACTIVE")

async def run_omni():
    init_system()
    # Чиним "Conflict" - сбрасываем вебхуки и старые апдейты
    await bot.delete_webhook(drop_pending_updates=True)
    
    subprocess.run(["playwright", "install", "chromium"])
    
    app = web.Application()
    app.router.add_get("/", web_handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    logger.info("OMNI SYSTEM STARTED SUCCESSFULLY")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(run_omni())
    except:
        logger.error("SYSTEM CRITICAL SHUTDOWN")