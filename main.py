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
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import web

# --- [ СИСТЕМНЫЕ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))
VERSION = "24.0 NEBULA"

ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("TITAN-NEBULA")

# --- [ МАШИНА СОСТОЯНИЙ ] ---
class TitanStates(StatesGroup):
    broadcast = State()
    terminal = State()
    search = State()

# --- [ БАЗА ДАННЫХ ] ---
DB_FILE = "nebula_db.json"

def load_db():
    if not os.path.exists(DB_FILE): 
        return {"users": {}, "stats": {"searches": 0, "errors": 0}}
    with open(DB_FILE, "r", encoding='utf-8') as f: 
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f: 
        json.dump(data, f, indent=4, ensure_all_ascii=False)

# --- [ КЛАВИАТУРЫ ] ---
def get_main_kb(uid):
    btns = [
        [KeyboardButton(text="🔍 ИСКАТЬ ТОВАР (AI)")],
        [KeyboardButton(text="👤 МОЙ ПРОФИЛЬ"), KeyboardButton(text="📊 СТАТИСТИКА")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [KeyboardButton(text="🔱 ЯДРО УПРАВЛЕНИЯ")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐚 ТЕРМИНАЛ"), KeyboardButton(text="📢 РАССЫЛКА")],
        [KeyboardButton(text="📂 ДАМП БАЗЫ"), KeyboardButton(text="🔙 В МЕНЮ")]
    ], resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- [ ИИ-ФИЛЬТРАЦИЯ И ХАРАКТЕРИСТИКИ ] ---
async def ai_smart_filter(user_query, raw_results):
    if not ai_client:
        return "⚠️ OpenAI API Key не найден. Вывожу сырые данные:\n\n" + "\n".join(raw_results[:3])
    
    if not raw_results:
        return "❌ К сожалению, на сайтах ничего не найдено по вашему запросу."

    prompt = (
        f"Ты — элитный поисковой ИИ 'TITAN NEBULA'. Юзер ищет: '{user_query}'.\n"
        f"Вот список найденных ссылок и названий: {raw_results}\n"
        "Твоя задача: выбери до 3-х товаров, которые максимально соответствуют характеристикам. "
        "Для каждого товара напиши: \n1. Название\n2. Цену (если есть)\n3. Почему подходит\n4. Ссылку.\n"
        "Отвечай строго и профессионально."
    )
    
    try:
        response = await ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Ты профессиональный ассистент по подбору товаров в Украине."},
                      {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "❌ Ошибка ИИ при анализе. Вот первые результаты:\n\n" + "\n".join(raw_results[:3])

# --- [ ПАРСИНГ-ЯДРО (БЕЗ PLAYWRIGHT) ] ---
async def fetch_results(session, site_name, url_template, query):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        url = url_template.format(q=query.replace(" ", "+"))
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status != 200: return []
            html = await resp.text()
            soup = BeautifulSoup(html, 'lxml')
            
            items = []
            # Ищем все ссылки, которые похожи на карточки товаров
            for a in soup.find_all('a', href=True):
                title = a.text.strip().lower()
                link = a['href']
                
                # Фильтр: название должно содержать слова из запроса
                query_words = query.lower().split()
                if any(word in title for word in query_words) and len(title) > 15:
                    if not link.startswith('http'):
                        domain = url.split('/')[2]
                        link = f"https://{domain}{link}"
                    
                    # Исключаем мусорные ссылки
                    if any(x in link for x in ['/p/', '/obyavlenie/', '/goods/']):
                        items.append(f"{a.text.strip()} | {link}")
                
                if len(items) >= 5: break
            return items
    except Exception as e:
        logger.warning(f"Ошибка на {site_name}: {e}")
        return []

# --- [ ОБРАБОТКА КОМАНД ] ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    db = load_db()
    uid = str(message.from_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": message.from_user.full_name, "date": str(datetime.now())}
        save_db(db)
    
    await message.answer(
        f"🛰 **TITAN NEBULA v{VERSION} СИСТЕМА ЗАПУЩЕНА**\n\n"
        f"Привет, {message.from_user.first_name}! Я ищу товары по всем площадкам Украины (OLX, Prom, Rozetka) и анализирую их через ИИ.",
        reply_markup=get_main_kb(message.from_user.id)
    )

@dp.message(F.text == "🔱 ЯДРО УПРАВЛЕНИЯ")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 **ДОСТУП К ТЕРМИНАЛУ ОТКРЫТ**", reply_markup=get_admin_kb())

@dp.message(F.text == "📊 СТАТИСТИКА")
async def show_stats(message: types.Message):
    db = load_db()
    await message.answer(
        f"📈 **ОТЧЕТ СИСТЕМЫ**\n\n"
        f"👥 Пользователей: `{len(db['users'])}`\n"
        f"🔎 Успешных поисков: `{db['stats']['searches']}`",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🐚 ТЕРМИНАЛ")
async def term_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(TitanStates.terminal)
    await message.answer("🐚 Введите Bash-команду (или 'exit'):")

@dp.message(TitanStates.terminal)
async def term_exec(message: types.Message, state: FSMContext):
    if message.text.lower() == "exit":
        await state.clear()
        return await message.answer("Выход из терминала.", reply_markup=get_admin_kb())
    
    try:
        result = subprocess.getoutput(message.text)
        await message.answer(f"📦 **РЕЗУЛЬТАТ:**\n`{result[:4000]}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text == "🔍 ИСКАТЬ ТОВАР (AI)")
async def search_prompt(message: types.Message):
    await message.answer("✍️ Введите название товара и нужные характеристики (цена, модель, цвет):")

@dp.message(F.text == "🔙 В МЕНЮ")
async def back_to_menu(message: types.Message):
    await message.answer("Главное меню", reply_markup=get_main_kb(message.from_user.id))

@dp.message(F.text)
async def global_search(message: types.Message):
    # Проверка на системные кнопки
    if message.text in ["🔱 ЯДРО УПРАВЛЕНИЯ", "📊 СТАТИСТИКА", "🐚 ТЕРМИНАЛ", "📢 РАССЫЛКА", "📂 ДАМП БАЗЫ", "🔙 В МЕНЮ", "🔍 ИСКАТЬ ТОВАР (AI)"]:
        return

    db = load_db()
    db["stats"]["searches"] += 1
    save_db(db)

    status = await message.answer("🛰 **TITAN SCANNING...**\nПодключаюсь к маркетплейсам Украины...")

    search_map = {
        "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
        "Prom": "https://prom.ua/search?search_term={q}",
        "Rozetka": "https://rozetka.com.ua/search/?text={q}"
    }

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_results(session, name, url, message.text) for name, url in search_map.items()]
        raw_data = await asyncio.gather(*tasks)

    all_items = [item for sub in raw_data for item in sub]
    
    if not all_items:
        await status.edit_text("❌ По вашему запросу ничего не найдено. Попробуйте упростить.")
        return

    await status.edit_text("🧠 **ИИ АНАЛИЗИРУЕТ ХАРАКТЕРИСТИКИ...**")
    
    final_report = await ai_smart_filter(message.text, all_items)
    await status.delete()
    
    await message.answer(f"✅ **РЕЗУЛЬТАТЫ ПОИСКА:**\n\n{final_report}", disable_web_page_preview=True)

# --- [ СЕРВЕРНАЯ ЧАСТЬ ДЛЯ RENDER ] ---
async def web_handler(request):
    return web.Response(text="TITAN NEBULA IS ALIVE")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Веб-сервер
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    # Настройка меню команд
    await bot.set_my_commands([BotCommand(command="start", description="Перезапустить бота")])
    
    logger.info("--- TITAN NEBULA ЗАПУЩЕНА БЕЗ ОШИБОК ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")