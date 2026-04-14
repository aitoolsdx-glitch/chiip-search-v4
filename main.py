import asyncio
import os
import json
import logging
import sys
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_KEY') # Добавь в Environment Variables на Render
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger("TITAN-ULTIMATE")

# --- СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    broadcast = State()
    terminal = State()

# --- БАЗА ДАННЫХ ---
DB_FILE = "titan_db.json"

def get_db():
    if not os.path.exists(DB_FILE): return {"users": {}, "stats": {"total": 0}}
    with open(DB_FILE, "r", encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- КЛАВИАТУРЫ ---
def main_kb(uid):
    btns = [[KeyboardButton(text="🔍 Поиск по характеристикам"), KeyboardButton(text="👤 Профиль")]]
    if uid == ADMIN_ID:
        btns.append([KeyboardButton(text="🔱 АДМИН-ЦЕНТР")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🐚 Терминал")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📂 Выгрузить БД")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ИИ ЛОГИКА ---
async def ai_filter(query, items):
    if not client: return items[:5] # Если ключа нет, просто топ-5
    
    prompt = f"Пользователь ищет: {query}. Вот список найденных товаров:\n{items}\n Выбери 3 самых подходящих и верни их в формате: Название - Ссылка"
    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except:
        return items[:3]

# --- ПАРСИНГ ---
async def scrape(context, name, url_template, query):
    page = await context.new_page()
    try:
        url = url_template.replace("{q}", query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        found = []
        links = soup.find_all('a', href=True)
        for l in links:
            txt = l.text.strip()
            if len(txt) > 20 and any(w in txt.lower() for w in query.lower().split()):
                href = l['href']
                if not href.startswith('http'): href = "https://" + url.split('/')[2] + href
                found.append(f"{txt} | {href}")
        return found
    except: return []
    finally: await page.close()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    db = get_db()
    uid = str(message.from_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": message.from_user.full_name, "count": 0}
        save_db(db)
    await message.answer(f"🚀 **TITAN OMNI v22.0 АКТИВИРОВАН**\nВерсия: Ultimate AI", reply_markup=main_kb(message.from_user.id))

@dp.message(F.text == "🔱 АДМИН-ЦЕНТР")
async def adm_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Панель управления TITAN", reply_markup=admin_kb())

@dp.message(F.text == "📊 Статистика")
async def adm_stats(message: types.Message):
    db = get_db()
    await message.answer(f"👥 Юзеров: {len(db['users'])}\n🔎 Поисков: {db['stats']['total']}")

@dp.message(F.text == "🐚 Терминал")
async def adm_term(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.terminal)
    await message.answer("🐚 Введите системную команду:")

@dp.message(AdminStates.terminal)
async def term_exec(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход...", reply_markup=admin_kb())
    res = subprocess.getoutput(message.text)
    await message.answer(f"Результат:\n`{res[:4000]}`", parse_mode="Markdown")

@dp.message(F.text == "🔍 Поиск по характеристикам")
async def start_search(message: types.Message):
    await message.answer("Напиши, что искать (например: 'Игровой ноутбук 16гб озу до 30000грн')")

@dp.message(F.text)
async def global_search(message: types.Message):
    if message.text in ["🔱 АДМИН-ЦЕНТР", "📊 Статистика", "🔙 Назад", "🔍 Поиск по характеристикам"]: return
    
    db = get_db()
    db["stats"]["total"] += 1
    save_db(db)
    
    status = await message.answer("🔍 **TITAN ИЩЕТ...** (OLX, Prom, Rozetka)")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context()
        
        sites = {
            "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
            "Prom": "https://prom.ua/search?search_term={q}",
            "Rozetka": "https://rozetka.com.ua/search/?text={q}"
        }
        
        tasks = [scrape(context, n, u, message.text) for n, u in sites.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()
    
    all_raw = [i for s in results for i in s]
    await status.edit_text("🤖 **ИИ АНАЛИЗИРУЕТ ХАРАКТЕРИСТИКИ...**")
    
    final_res = await ai_filter(message.text, all_raw)
    await status.delete()
    await message.answer(f"✅ **ЛУЧШИЕ ВАРИАНТЫ ДЛЯ ВАС:**\n\n{final_res}", disable_web_page_preview=True)

# --- ЗАПУСК ---
async def handle(request): return web.Response(text="TITAN ONLINE")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Фикс для Render: установка браузера
    subprocess.run(["playwright", "install", "chromium"])
    
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())