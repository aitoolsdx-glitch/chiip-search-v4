import asyncio
import os
import json
import logging
import sys
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("TITAN-FORCE")

# --- [ СОСТОЯНИЯ ] ---
class AdminStates(StatesGroup):
    broadcast = State()
    terminal = State()

# --- [ БАЗА ДАННЫХ ] ---
DB_PATH = "titan_database.json"

def load_db():
    if not os.path.exists(DB_PATH): return {"users": {}, "stats": {"searches": 0}}
    with open(DB_PATH, "r", encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DB_PATH, "w", encoding='utf-8') as f: 
        json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- [ КЛАВИАТУРЫ ] ---
def main_kb(uid):
    btns = [
        [KeyboardButton(text="🔎 Поиск по характеристикам")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🆘 Инфо")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [KeyboardButton(text="🔱 АДМИН-ЦЕНТР")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🐚 Консоль")],
        [KeyboardButton(text="📊 Метрики"), KeyboardButton(text="📂 Дамп БД")],
        [KeyboardButton(text="🔙 В главное меню")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ИИ-АНАЛИЗАТОР ] ---
async def ai_analyze_results(query, raw_data):
    if not ai_client or not raw_data:
        return "⚠️ ИИ отключен или данных нет. Вот что нашел:\n" + "\n".join(raw_data[:3])
    
    prompt = f"""
    Ты - эксперт по покупкам TITAN OMNI. 
    Пользователь ищет: {query}
    Вот найденные сырые данные: {raw_data}
    Выбери 3 лучших варианта, которые реально подходят под характеристики. 
    Напиши краткий вывод, почему это стоит купить.
    """
    try:
        res = await ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ: {e}\n\n" + "\n".join(raw_data[:3])

# --- [ СТАБИЛЬНЫЙ ПАРСИНГ (БЕЗ PLAYWRIGHT) ] ---
async def fetch_titan(session, name, url_template, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        url = url_template.format(q=query.replace(" ", "+"))
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status != 200: return []
            html = await response.text()
            soup = BeautifulSoup(html, 'lxml')
            
            results = []
            links = soup.find_all('a', href=True)
            for l in links:
                txt = l.text.strip().lower()
                # Умный фильтр совпадений
                if all(word in txt for word in query.lower().split()[:2]):
                    href = l['href']
                    if not href.startswith('http'): 
                        domain = url.split('/')[2]
                        href = f"https://{domain}{href}"
                    if "olx.ua/d/uk/obyavlenie" in href or "/p" in href: # Фильтр только на товары
                        results.append(f"{l.text.strip()[:60]} -> {href}")
                if len(results) >= 5: break
            return results
    except: return []

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    db = load_db()
    uid = str(message.from_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": message.from_user.full_name, "joined": str(datetime.now())}
        save_db(db)
    await message.answer("🦾 **TITAN OMNI v23.0 FORCE ONLINE**\n\nЯ готов искать любые товары по всем площадкам Украины через ИИ.", 
                         reply_markup=main_kb(message.from_user.id))

@dp.message(F.text == "🔱 АДМИН-ЦЕНТР")
async def adm_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Доступ к ядру разрешен.", reply_markup=admin_kb())

@dp.message(F.text == "📊 Метрики")
async def adm_metrics(message: types.Message):
    db = load_db()
    text = f"📊 **СТАТИСТИКА**\n\n👤 Пользователей: {len(db['users'])}\n🔎 Всего поисков: {db['stats']['searches']}"
    await message.answer(text)

@dp.message(F.text == "🐚 Консоль")
async def adm_term(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.terminal)
    await message.answer("🐚 Введите системную команду (bash):")

@dp.message(AdminStates.terminal)
async def term_exec(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход из консоли.", reply_markup=admin_kb())
    try:
        output = subprocess.getoutput(message.text)
        await message.answer(f"📦 **Output:**\n`{output[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text == "🔎 Поиск по характеристикам")
async def search_init(message: types.Message):
    await message.answer("📝 Введите запрос (например: *белые кроссовки Nike 42 размер до 3000 грн*):", parse_mode="Markdown")

@dp.message(F.text)
async def process_search(message: types.Message):
    if message.text in ["🔱 АДМИН-ЦЕНТР", "📊 Метрики", "🐚 Консоль", "🔎 Поиск по характеристикам", "🔙 В главное меню"]: return
    
    db = load_db()
    db["stats"]["searches"] += 1
    save_db(db)

    status = await message.answer("📡 **TITAN SCANNING...**\nПодключаюсь к OLX, Prom, Rozetka...")

    sites = {
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}",
        "Rozetka": "https://rozetka.com.ua/search/?text={q}"
    }

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_titan(session, n, u, message.text) for n, u in sites.items()]
        raw_results = await asyncio.gather(*tasks)

    flat_list = [item for sub in raw_results for item in sub]
    
    if not flat_list:
        await status.edit_text("❌ Ничего не найдено. Попробуйте изменить запрос.")
        return

    await status.edit_text("🤖 **ИИ TITAN АНАЛИЗИРУЕТ ВАРИАНТЫ...**")
    
    ai_final = await ai_analyze_results(message.text, flat_list)
    await status.delete()
    await message.answer(f"✅ **РЕЗУЛЬТАТЫ TITAN-FORCE:**\n\n{ai_final}", disable_web_page_preview=True)

# --- [ СЕРВЕР ] ---
async def web_handle(request): return web.Response(text="TITAN ACTIVE")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск веб-сервера для Render
    app = web.Application()
    app.router.add_get("/", web_handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())