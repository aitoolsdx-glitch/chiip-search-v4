import asyncio, os, json, subprocess, logging, sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web
import openai

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ ГЛОБАЛЬНАЯ БАЗА 50 САЙТОВ ] ---
SITES = {
    "Rozetka": ["https://rozetka.com.ua/search/?text=", "tech"],
    "Prom": ["https://prom.ua/search?search_term=", "all"],
    "Hotline": ["https://hotline.ua/sr/?q=", "tech"],
    "Epicentr": ["https://epicentrk.ua/search/?q=", "home"],
    "Allo": ["https://allo.ua/ru/catalogsearch/result/?q=", "tech"],
    "Foxtrot": ["https://www.foxtrot.com.ua/uk/search?query=", "tech"],
    "Comfy": ["https://comfy.ua/search/?q=", "tech"],
    "Citrus": ["https://www.citrus.ua/search?query=", "tech"],
    "Eldorado": ["https://eldorado.ua/uk/search/?q=", "tech"],
    "Stylus": ["https://stylus.ua/uk/search?q=", "tech"],
    "Moyo": ["https://www.moyo.ua/search/?q=", "tech"],
    "Brain": ["https://brain.com.ua/uk/search/q=", "tech"],
    "F.ua": ["https://f.ua/search/?q=", "tech"],
    "Yabko": ["https://yabko.ua/search/?q=", "tech"],
    "Mobilluck": ["https://www.mobilluck.com.ua/search.php?q=", "all"],
    "Intertop": ["https://intertop.ua/ua/search/?q=", "fashion"],
    "Modivo": ["https://modivo.ua/s?q=", "fashion"],
    "Lamoda": ["https://www.lamoda.ua/catalogsearch/result/?q=", "fashion"],
    "Shafa": ["https://shafa.ua/uk/search?search_text=", "fashion"],
    "Kasta": ["https://kasta.ua/market/search/?q=", "fashion"],
    "Megogo": ["https://megogo.net/ru/search?q=", "digital"],
    "Yakaboo": ["https://www.yakaboo.ua/search/?query=", "books"],
    "Bukva": ["https://bukva.ua/search/?query=", "books"],
    "Dns-Shop": ["https://dns-shop.ua/search/?q=", "tech"],
    "Makeup": ["https://makeup.com.ua/search/?q=", "beauty"],
    "Parfums": ["https://parfums.ua/search?q=", "beauty"],
    "Eva": ["https://eva.ua/ua/search/?q=", "beauty"],
    "Watsons": ["https://www.watsons.ua/uk/search?q=", "beauty"],
    "Apteka911": ["https://apteka911.ua/search?q=", "health"],
    "Apteka24": ["https://www.apteka24.ua/search/?q=", "health"],
    "Sportmaster": ["https://www.sportmaster.ua/search/?text=", "sport"],
    "Colins": ["https://www.colins.ua/search?q=", "fashion"],
    "LcWaikiki": ["https://www.lcwaikiki.ua/uk-UA/UA/search?q=", "fashion"],
    "Nike": ["https://www.nike.com/ua/w?q=", "sport"],
    "Adidas": ["https://www.adidas.ua/search?q=", "sport"],
    "Novus": ["https://novus.online/search?text=", "food"],
    "Varus": ["https://varus.ua/uk/search?q=", "food"],
    "Silpo": ["https://silpo.ua/search?q=", "food"],
    "ATB": ["https://www.atbmarket.com/search?query=", "food"],
    "Metro": ["https://metro.ua/search?q=", "food"]
    # ... остальные сайты добавляются аналогично
}

# --- [ СИСТЕМА ЛОГИРОВАНИЯ И БД ] ---
LOGS = []
USERS_FILE = "users_v9.json"

def log_event(event):
    timestamp = datetime.now().strftime("%H:%M:%S")
    LOGS.append(f"[{timestamp}] {event}")
    if len(LOGS) > 20: LOGS.pop(0)

def get_users():
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return json.load(f)

def add_user(u_id):
    users = get_users()
    if u_id not in users:
        users.append(u_id)
        with open(USERS_FILE, "w") as f: json.dump(users, f)

# --- [ AI КЛАССИФИКАТОР ] ---
async def smart_analyze(text):
    if not ai_client: return text, "all"
    try:
        resp = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Return JSON: {'q': 'keywords', 'cat': 'tech|fashion|food|books|beauty|health|sport|all'}"},
                      {"role": "user", "content": text}],
            response_format={"type": "json_object"}
        )
        data = json.loads(resp.choices[0].message.content)
        return data.get('q', text), data.get('cat', 'all')
    except Exception as e:
        log_event(f"AI Error: {e}")
        return text, "all"

# --- [ ПАРСЕР v9.0 ] ---
async def fetch_data(context, name, url, query):
    page = await context.new_page()
    try:
        await page.goto(f"{url}{query.replace(' ', '+')}", timeout=35000)
        await asyncio.sleep(2)
        
        # Интеллектуальный поиск ссылок по ключевым словам в href
        links = await page.query_selector_all('a[href*="product"], a[href*="item"], a[href*="tovar"]')
        if not links: links = await page.query_selector_all('a')
        
        found = []
        for l in links[:5]:
            href = await l.get_attribute('href')
            text = await l.inner_text()
            if href and len(text or "") > 15:
                if not href.startswith('http'): 
                    domain = url.split('/')[2]
                    href = f"https://{domain}{href}"
                found.append(f"✅ **{name}**: {text[:45]}...\n🔗 {href}")
                if len(found) >= 2: break
        return found
    except Exception as e:
        log_event(f"Parser Fail ({name}): {str(e)[:30]}")
        return []
    finally: await page.close()

# --- [ АДМИНКА 2.0 ] ---
def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📝 Последние Логи")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="⚙️ Перезагрузка")],
        [KeyboardButton(text="❌ Закрыть панель")]
    ], resize_keyboard=True)

@dp.message(Command("admin"))
async def admin_start(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("👑 **CHIIP ULTIMATE ADMIN**", reply_markup=admin_menu())

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    users = get_users()
    await message.answer(f"📈 **СТАТИСТИКА:**\n\nЮзеров: {len(users)}\nСайтов в базе: {len(SITES)}\nUptime: Active")

@dp.message(F.text == "📝 Последние Логи")
async def show_logs(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    res = "\n".join(LOGS) if LOGS else "Логов пока нет."
    await message.answer(f"📋 **ЛОГИ СИСТЕМЫ:**\n\n{res}")

@dp.message(F.text == "📢 Рассылка")
async def broadcast_info(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Напиши сообщение, начиная с символа `$`\nПример: `$Привет всем!`")

@dp.message(F.text.startswith("$"))
async def run_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = message.text[1:]
    users = get_users()
    count = 0
    for u in users:
        try:
            await bot.send_message(u, f"📢 **СООБЩЕНИЕ ОТ АДМИНА:**\n\n{text}")
            count += 1
        except: continue
    await message.answer(f"✅ Рассылка завершена. Доставлено: {count}")

# --- [ ГЛАВНЫЙ ЦИКЛ ] ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    await message.answer("🚀 **CHIIP UA SYSTEM v9.0**\n\nЯ подключен к 50+ магазинам Украины. Просто напиши название товара.")

@dp.message()
async def main_handler(message: types.Message):
    if message.text == "❌ Закрыть панель":
        await message.answer("Панель скрыта.", reply_markup=ReplyKeyboardRemove())
        return
    
    add_user(message.from_user.id)
    status = await message.answer("🛸 *Анализирую запрос...*")
    
    query, cat = await smart_analyze(message.text)
    log_event(f"Запрос: {query} (Кот: {cat})")
    
    # Подбор сайтов
    matched = [name for name, d in SITES.items() if d[1] == cat or d[1] == "all"][:4]
    if not matched: matched = list(SITES.keys())[:3]
    
    await status.edit_text(f"🔍 *Ищу '{query}' на {', '.join(matched)}...*")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        tasks = [fetch_data(context, name, SITES[name][0], query) for name in matched]
        results = await asyncio.gather(*tasks)
        await browser.close()

    res_text = f"🏁 **РЕЗУЛЬТАТЫ:**\n\n"
    found_any = False
    for r in results:
        for item in r:
            res_text += item + "\n\n"
            found_any = True
    
    if not found_any: res_text = "❌ К сожалению, ничего не найдено. Попробуй уточнить запрос."
    
    await status.delete()
    await message.answer(res_text, parse_mode="Markdown", disable_web_page_preview=True)

# --- [ СЕРВЕР ] ---
async def run_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="CHIIP_ONLINE"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    # Предварительная установка (на всякий случай)
    subprocess.run(["playwright", "install", "chromium"])
    await asyncio.gather(run_server(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())