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
logger = logging.getLogger("TITAN-CORE")

class SystemStates(StatesGroup):
    adm_term = State()
    adm_mail = State()

# --- DATABASE ---
DB_PATH = "titan_core.json"

def get_data():
    if not os.path.exists(DB_PATH): return {"users": {}, "stats": {"q": 0}}
    with open(DB_PATH, "r", encoding='utf-8') as f: return json.load(f)

def save_data(data):
    with open(DB_PATH, "w", encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- KEYBOARDS ---
def main_kb(uid):
    btns = [[KeyboardButton(text="🔎 Искать по характеристикам")], [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📊 Статистика")]]
    if uid == ADMIN_ID: btns.insert(0, [KeyboardButton(text="🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def adm_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐚 Выполнить команду"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="📂 Выгрузить БД"), KeyboardButton(text="🔙 Выход")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ИИ ФУНКЦИЯ ---
async def titan_ai_filter(query, raw_results):
    if not ai_client or not raw_results: return raw_results[:3]
    prompt = f"Пользователь ищет: {query}. Проанализируй список:\n{raw_results}\nВыбери 3 лучших варианта по характеристикам и цене. Напиши кратко почему."
    try:
        res = await ai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
        return res.choices[0].message.content
    except: return "Ошибка ИИ. Вот что нашел:\n" + "\n".join(raw_results[:3])

# --- ПАРСЕР ---
async def fetch_ads(session, url, query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        async with session.get(url.format(q=query.replace(" ", "+")), headers=headers, timeout=10) as r:
            if r.status != 200: return []
            soup = BeautifulSoup(await r.text(), 'lxml')
            found = []
            for a in soup.find_all('a', href=True):
                txt = a.text.strip().lower()
                if len(txt) > 20 and all(w in txt for w in query.lower().split()[:2]):
                    link = a['href']
                    if not link.startswith('http'): link = "https://" + url.split('/')[2] + link
                    found.append(f"📦 {a.text.strip()[:60]}... \n🔗 {link}")
                if len(found) >= 4: break
            return found
    except: return []

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(m: types.Message):
    db = get_data()
    uid = str(m.from_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": m.from_user.full_name, "reg": str(datetime.now())}
        save_data(db)
    await m.answer("🦾 **TITAN OMNI v24.0 BLACK OPS**\n\nСистема готова к поиску товаров через ИИ.", reply_markup=main_kb(m.from_user.id))

@dp.message(F.text == "🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ")
async def adm_panel(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    await m.answer("⚙️ Доступ к ядру TITAN открыт.", reply_markup=adm_kb())

@dp.message(F.text == "🐚 Выполнить команду")
async def adm_shell(m: types.Message, state: FSMContext):
    await state.set_state(SystemStates.adm_term)
    await m.answer("🐚 Введите Bash-команду:")

@dp.message(SystemStates.adm_term)
async def shell_exec(m: types.Message, state: FSMContext):
    if m.text.lower() == "exit":
        await state.clear()
        return await m.answer("Выход...", reply_markup=adm_kb())
    res = subprocess.getoutput(m.text)
    await m.answer(f"Результат:\n`{res[:4000]}`", parse_mode="Markdown")

@dp.message(F.text == "🔎 Искать по характеристикам")
async def search_init(m: types.Message):
    await m.answer("📝 Напишите характеристики товара (напр. *ноутбук RTX 3060 до 40000грн*):", parse_mode="Markdown")

@dp.message(F.text)
async def process_all(m: types.Message):
    if m.text in ["🔱 ТЕРМИНАЛ УПРАВЛЕНИЯ", "🐚 Выполнить команду", "🔎 Искать по характеристикам", "🔙 Выход"]: return
    
    db = get_data()
    db["stats"]["q"] += 1
    save_data(db)
    
    status = await m.answer("📡 **TITAN SCAN ACTIVE**\nПодключаюсь к OLX, Prom, Rozetka...")
    
    sites = {
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}",
        "Rozetka": "https://rozetka.com.ua/search/?text={q}"
    }
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_ads(session, u, m.text) for u in sites.values()]
        results = await asyncio.gather(*tasks)
    
    all_raw = [i for sub in results for i in sub]
    if not all_raw:
        return await status.edit_text("❌ Ничего не найдено. Упростите запрос.")
    
    await status.edit_text("🤖 **ИИ АНАЛИЗИРУЕТ ВАРИАНТЫ...**")
    final = await titan_ai_filter(m.text, all_raw)
    await status.delete()
    await m.answer(f"✅ **ЛУЧШИЕ ПРЕДЛОЖЕНИЯ:**\n\n{final}", disable_web_page_preview=True)

# --- SERVER ---
async def web_h(r): return web.Response(text="TITAN CORE ONLINE")

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