import asyncio
import os
import json
import logging
import sys
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import web

# --- КОНФИГ ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger("TITAN-FINAL")

# --- БД ---
def load_db():
    if not os.path.exists("users.json"): return {}
    with open("users.json", "r", encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open("users.json", "w", encoding='utf-8') as f: json.dump(data, f, indent=4)

# --- КЛАВИАТУРА ---
def main_kb(uid):
    btns = [[KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="👤 Профиль")]]
    if uid == ADMIN_ID: btns.append([KeyboardButton(text="🔱 Админка")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ПАРСИНГ ---
async def scrape_site(browser_context, name, url_template, query):
    page = await browser_context.new_page()
    try:
        url = url_template.replace("{q}", query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2) # Даем прогрузиться JS
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        results = []
        
        # Общая логика поиска ссылок
        links = soup.find_all('a', href=True)
        for l in links:
            t = l.text.lower()
            if all(word in t for word in query.lower().split()) and len(t) > 10:
                href = l['href']
                if not href.startswith('http'): 
                    href = "https://" + url.split('/')[2] + href
                results.append(f"📦 **{name}**: {l.text.strip()[:50]}...\n🔗 {href}")
                if len(results) >= 2: break
        return results
    except Exception as e:
        logger.error(f"Ошибка {name}: {e}")
        return []
    finally:
        await page.close()

@dp.message(F.text == "🔍 Поиск")
async def ask_search(message: types.Message):
    await message.answer("Введите название товара:")

@dp.message(F.text == "🔱 Админка")
async def admin_cmd(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer_document(FSInputFile("users.json"), caption="База данных")

@dp.message(F.text)
async def handle_search(message: types.Message):
    if message.text in ["🔍 Поиск", "👤 Профиль", "🔱 Админка"]: return
    
    msg = await message.answer("📡 Запуск TITAN-движков...")
    
    async with async_playwright() as p:
        # Важно для Render: --no-sandbox
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        
        targets = {
            "OLX": "https://www.olx.ua/d/uk/list/q-{q}/",
            "Prom": "https://prom.ua/search?search_term={q}",
            "Rozetka": "https://rozetka.com.ua/search/?text={q}"
        }
        
        tasks = [scrape_site(context, n, u, message.text) for n, u in targets.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()
    
    flat = [i for s in results for i in s]
    await msg.delete()
    
    if flat:
        await message.answer("✅ **Найдено:**\n\n" + "\n\n".join(flat), disable_web_page_preview=True)
    else:
        await message.answer("❌ Ничего не найдено.")

# --- SERVER ---
async def health(request): return web.Response(text="ALIVE")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Пытаемся установить браузеры (если есть права)
    try:
        subprocess.run(["playwright", "install", "chromium"])
    except:
        logger.warning("Не удалось установить браузеры через код.")

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())