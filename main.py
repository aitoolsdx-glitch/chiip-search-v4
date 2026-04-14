import asyncio
import os
import json
import logging
import sys
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import web

# --- CONFIG ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("TITAN-STEEL")

class AdminStates(StatesGroup):
    shell = State()

# --- КНОПКИ ---
def main_kb(uid):
    btns = [[KeyboardButton(text="🔎 Поиск товара")], [KeyboardButton(text="👤 Профиль")]]
    if uid == ADMIN_ID: btns.insert(0, [KeyboardButton(text="🔱 АДМИН-ТЕРМИНАЛ")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ПАРСИНГ ---
async def fetch_data(session, url, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        search_url = url.format(q=query.replace(" ", "+"))
        async with session.get(search_url, headers=headers, timeout=12) as r:
            if r.status != 200: return []
            # Используем html.parser вместо lxml для стабильности
            soup = BeautifulSoup(await r.text(), 'html.parser')
            res = []
            for a in soup.find_all('a', href=True):
                title = a.text.strip()
                if len(title) > 20 and any(w in title.lower() for w in query.lower().split()[:2]):
                    link = a['href']
                    if not link.startswith('http'): link = f"https://{url.split('/')[2]}{link}"
                    res.append(f"{title[:60]} -> {link}")
                if len(res) >= 3: break
            return res
    except: return []

async def ai_ranking(query, data):
    if not ai_client: return "\n".join(data[:3])
    try:
        prompt = f"Из списка товаров выбери 3 лучших по запросу '{query}': {data}. Ответь кратко."
        res = await ai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content
    except: return "\n".join(data[:3])

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer("🦾 **TITAN STEEL v27.0** запущена.\nОшибки сборки устранены.", reply_markup=main_kb(m.from_user.id))

@dp.message(F.text == "🔱 АДМИН-ТЕРМИНАЛ")
async def admin_main(m: types.Message):
    if m.from_user.id == ADMIN_ID:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🐚 Консоль")], [KeyboardButton(text="🔙 Назад")]], resize_keyboard=True)
        await m.answer("🛠 Доступ к ядру разрешен.", reply_markup=kb)

@dp.message(F.text == "🐚 Консоль")
async def shell_on(m: types.Message, state: FSMContext):
    if m.from_user.id == ADMIN_ID:
        await state.set_state(AdminStates.shell)
        await m.answer("Жду команду (bash). Отправь 'exit' для выхода.")

@dp.message(AdminStates.shell)
async def shell_run(m: types.Message, state: FSMContext):
    if m.text.lower() == "exit":
        await state.clear()
        return await m.answer("Выход...", reply_markup=main_kb(m.from_user.id))
    out = subprocess.getoutput(m.text)
    await m.answer(f"📦 **Output:**\n`{out[:4000]}`", parse_mode="Markdown")

@dp.message(F.text == "🔎 Поиск товара")
async def search_start(m: types.Message):
    await m.answer("Что ты хочешь найти? Опиши характеристики.")

@dp.message(F.text)
async def handle_search(m: types.Message):
    if m.text in ["🔱 АДМИН-ТЕРМИНАЛ", "🐚 Консоль", "🔙 Назад", "🔎 Поиск товара"]: return
    
    st_msg = await m.answer("📡 Сбор данных по маркетплейсам...")
    urls = ["https://www.olx.ua/d/uk/list/q-{q}/", "https://prom.ua/search?search_term={q}", "https://rozetka.com.ua/search/?text={q}"]
    
    async with aiohttp.ClientSession() as sess:
        tasks = [fetch_data(sess, u, m.text) for u in urls]
        results = await asyncio.gather(*tasks)
    
    flat = [i for sub in results for i in sub]
    if not flat: return await st_msg.edit_text("❌ Ничего не найдено.")
    
    await st_msg.edit_text("🤖 ИИ подбирает лучшие варианты...")
    final = await ai_ranking(m.text, flat)
    await st_msg.delete()
    await m.answer(f"✅ **РЕЗУЛЬТАТЫ:**\n\n{final}", disable_web_page_preview=True)

# --- WEB SERVER ---
async def web_h(request): return web.Response(text="WORKING")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    app = web.Application()
    app.router.add_get("/", web_h)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())