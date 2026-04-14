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

# --- КОНФИГ ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("TITAN-V26")

class AdminStates(StatesGroup):
    shell = State()

DB_FILE = "titan_v26_db.json"

def get_db():
    if not os.path.exists(DB_FILE): return {"users": {}, "total": 0}
    with open(DB_FILE, "r", encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- КНОПКИ ---
def main_kb(uid):
    btns = [[KeyboardButton(text="🔎 Поиск товара")], [KeyboardButton(text="👤 Профиль")]]
    if uid == ADMIN_ID: btns.insert(0, [KeyboardButton(text="🔱 АДМИН-ТЕРМИНАЛ")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐚 Консоль"), KeyboardButton(text="📂 Дамп БД")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ПАРСИНГ И ИИ ---
async def fetch(session, url, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        async with session.get(url.format(q=query.replace(" ", "+")), headers=headers, timeout=10) as r:
            if r.status != 200: return []
            soup = BeautifulSoup(await r.text(), 'lxml')
            res = []
            for a in soup.find_all('a', href=True):
                t = a.text.strip()
                if len(t) > 25 and any(w in t.lower() for w in query.lower().split()[:2]):
                    link = a['href']
                    if not link.startswith('http'): link = f"https://{url.split('/')[2]}{link}"
                    res.append(f"{t[:60]} -> {link}")
                if len(res) >= 3: break
            return res
    except: return []

async def ai_filter(query, data):
    if not ai_client: return "\n".join(data[:3])
    try:
        prompt = f"Выбери лучшие товары по запросу '{query}' из списка: {data}. Напиши кратко почему."
        compl = await ai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        return compl.choices[0].message.content
    except: return "\n".join(data[:3])

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def st(m: types.Message):
    await m.answer("🦾 TITAN v26 READY. Используй кнопки.", reply_markup=main_kb(m.from_user.id))

@dp.message(F.text == "🔱 АДМИН-ТЕРМИНАЛ")
async def adm(m: types.Message):
    if m.from_user.id == ADMIN_ID: await m.answer("🛠 ROOT ACCESS", reply_markup=admin_kb())

@dp.message(F.text == "🐚 Консоль")
async def sh_start(m: types.Message, state: FSMContext):
    if m.from_user.id == ADMIN_ID:
        await state.set_state(AdminStates.shell)
        await m.answer("Жду команду (bash):")

@dp.message(AdminStates.shell)
async def sh_exec(m: types.Message, state: FSMContext):
    if m.text.lower() == "exit":
        await state.clear()
        return await m.answer("Закрыто.", reply_markup=admin_kb())
    await m.answer(f"Результат:\n`{subprocess.getoutput(m.text)[:4000]}`", parse_mode="Markdown")

@dp.message(F.text == "🔎 Поиск товара")
async def search_p(m: types.Message):
    await m.answer("Что ищем? (Напиши характеристики)")

@dp.message(F.text)
async def proc(m: types.Message):
    if m.text in ["🔱 АДМИН-ТЕРМИНАЛ", "🐚 Консоль", "🔙 Назад", "🔎 Поиск товара"]: return
    
    s = await m.answer("📡 Поиск по Украине...")
    urls = ["https://www.olx.ua/d/uk/list/q-{q}/", "https://prom.ua/search?search_term={q}", "https://rozetka.com.ua/search/?text={q}"]
    
    async with aiohttp.ClientSession() as sess:
        tasks = [fetch(sess, u, m.text) for u in urls]
        res = await asyncio.gather(*tasks)
    
    flat = [i for sub in res for i in sub]
    if not flat: return await s.edit_text("❌ Ничего не найдено.")
    
    await s.edit_text("🤖 ИИ анализирует...")
    ans = await ai_filter(m.text, flat)
    await s.delete()
    await m.answer(f"✅ **РЕЗУЛЬТАТЫ:**\n\n{ans}", disable_web_page_preview=True)

# --- RUN ---
async def h(request): return web.Response(text="OK")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    app = web.Application()
    app.router.add_get("/", h)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())