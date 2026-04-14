import asyncio
import os
import json
import logging
import sys
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import web

# --- [ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("TITAN-V25")

# --- [ FSM ] ---
class AdminStates(StatesGroup):
    shell = State()
    mailing = State()

# --- [ БД ] ---
DB_FILE = "titan_v25_db.json"

def get_db():
    if not os.path.exists(DB_FILE): 
        return {"users": {}, "total_searches": 0}
    with open(DB_FILE, "r", encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f: 
        json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- [ КНОПКИ ] ---
def main_kb(uid):
    btns = [
        [KeyboardButton(text="🔎 Поиск по характеристикам")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📊 Статистика")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [KeyboardButton(text="🔱 АДМИН-ТЕРМИНАЛ")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐚 Выполнить Bash-команду")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📂 Скачать БД")],
        [KeyboardButton(text="🔙 Назад в меню")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ИИ ЛОГИКА ] ---
async def ai_search_filter(query, results):
    if not ai_client: return results[:3]
    
    prompt = f"Пользователь ищет товар: {query}. Вот список найденных ссылок: {results}. Выбери 3 самых подходящих по характеристикам и цене. Выдай краткий ответ."
    try:
        resp = await ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content
    except: return results[:3]

# --- [ СИСТЕМА ПАРСИНГА ] ---
async def fetch_products(session, url, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        async with session.get(url.format(q=query.replace(" ", "+")), headers=headers, timeout=10) as r:
            if r.status != 200: return []
            soup = BeautifulSoup(await r.text(), 'lxml')
            links = []
            for a in soup.find_all('a', href=True):
                txt = a.text.strip().lower()
                if any(w in txt for w in query.lower().split()[:2]):
                    href = a['href']
                    if not href.startswith('http'): href = f"https://{url.split('/')[2]}{href}"
                    if "/p" in href or "obyavlenie" in href: # Только товары
                        links.append(f"{a.text.strip()[:50]} -> {href}")
                if len(links) >= 5: break
            return links
    except: return []

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(F.text == "🔱 АДМИН-ТЕРМИНАЛ")
async def adm_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🚀 TITAN CORE v25 READY", reply_markup=admin_kb())

@dp.message(F.text == "🐚 Выполнить Bash-команду")
async def adm_shell_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.shell)
    await message.answer("Введите команду (например: ls, pip list, df -h):")

@dp.message(AdminStates.shell)
async def adm_shell_exec(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход из терминала.", reply_markup=admin_kb())
    
    res = subprocess.getoutput(message.text)
    await message.answer(f"📦 **Результат:**\n`{res[:4000]}`", parse_mode="Markdown")

@dp.message(F.text == "🔎 Поиск по характеристикам")
async def start_search(message: types.Message):
    await message.answer("Напиши, какой товар ты ищешь (характеристики, цена):")

@dp.message(F.text)
async def process_all_text(message: types.Message):
    if message.text in ["🔱 АДМИН-ТЕРМИНАЛ", "🐚 Выполнить Bash-команду", "🔙 Назад в меню", "🔎 Поиск по характеристикам"]: return
    
    db = get_db()
    db["total_searches"] += 1
    save_db(db)

    status = await message.answer("📡 **TITAN SCANNING...**\nПоиск по OLX, Prom, Rozetka...")

    urls = [
        "https://www.olx.ua/d/uk/list/q-{q}/",
        "https://prom.ua/search?search_term={q}",
        "https://rozetka.com.ua/search/?text={q}"
    ]

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_products(session, u, message.text) for u in urls]
        all_res = await asyncio.gather(*tasks)

    flat = [i for s in all_res for i in s]
    
    if not flat:
        return await status.edit_text("❌ Ничего не найдено.")

    await status.edit_text("🤖 **ИИ АНАЛИЗИРУЕТ ВАРИАНТЫ...**")
    ai_answer = await ai_search_filter(message.text, flat)
    
    await status.delete()
    await message.answer(f"✅ **РЕЗУЛЬТАТЫ TITAN v25:**\n\n{ai_answer}", disable_web_page_preview=True)

# --- [ ЗАПУСК ] ---
async def health(request): return web.Response(text="ALIVE")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    logger.info("TITAN V25 STARTED")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())