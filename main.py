import asyncio, os, json, openai
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web

# --- НАСТРОЙКИ ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446  # ЗАМЕНИ ЭТО НА СВОЙ ID (цифры)
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
users_db = set()

# --- ВЕБ-СЕРВЕР ДЛЯ CRON-JOB ---
async def handle_ping(request): return web.Response(text="CHIIP SYSTEM ONLINE")
async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- AI АНАЛИЗАТОР ---
async def analyze_query(text):
    if not OPENAI_KEY: return {"q": text, "cat": "all"}
    openai.api_key = OPENAI_KEY
    try:
        resp = await asyncio.to_thread(openai.ChatCompletion.create, model="gpt-4o-mini", messages=[{"role": "user", "content": f"Extract keywords from: {text}. Return JSON: {{'q': 'keywords'}}" }])
        return json.loads(resp.choices[0].message.content)
    except: return {"q": text}

# --- ЯДРО ПОИСКА (РАБОЧЕЕ) ---
async def scrape_site(url_template, query, name):
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = await context.new_page()
            await page.goto(f"{url_template}{query}", timeout=40000)
            await asyncio.sleep(2)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Логика извлечения (универсальная)
            links = soup.select('a[href*="item"], a[href*="obyavlenie"], a[href*="product"]')[:2]
            res = []
            for l in links:
                title = l.get_text(strip=True)[:50]
                href = l['href']
                if not href.startswith('http'): href = "https://olx.ua" + href # Пример для OLX
                res.append(f"📍 **{name}**\n📦 {title}\n🔗 [Смотреть]({href})")
            return res if res else [f"🔍 На {name} ничего не найдено."]
        except: return [f"⚠️ {name} временно недоступен."]
        finally: await browser.close()

# --- АДМИНКА ---
@dp.message(Command("admin"))
async def admin_main(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = [
        [types.KeyboardButton(text="📊 Юзеры"), types.KeyboardButton(text="📣 Рассылка")],
        [types.KeyboardButton(text="⚙️ Статус сервера"), types.KeyboardButton(text="❌ Выход")]
    ]
    await message.answer("🔧 **CHIIP CONTROL PANEL v5.0**", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

@dp.message(F.text == "📊 Юзеры")
async def get_users(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(f"👥 Всего в базе: {len(users_db)}\nАктивные сессии: {len(users_db)}")

@dp.message(F.text == "📣 Рассылка")
async def start_broadcast(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Отправь сообщение, которое увидят ВСЕ пользователи.")

# --- ОБРАБОТКА ЗАПРОСОВ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    users_db.add(message.from_user.id)
    await message.answer("🚀 **CHIIP UA Search v5.0**\nЯ готов к поиску. Что найти сегодня?")

@dp.message()
async def global_handler(message: types.Message):
    if message.text == "❌ Выход":
        await message.answer("Панель закрыта.", reply_markup=types.ReplyKeyboardRemove())
        return

    users_db.add(message.from_user.id)
    status = await message.answer("🛸 *Начинаю глобальный поиск...*")
    
    data = await analyze_query(message.text)
    query = data.get('q', message.text)

    # Список сайтов для проверки
    engines = {
        "OLX UA": "https://www.olx.ua/d/uk/list/q-",
        "Auto.ria": "https://auto.ria.com/uk/search/?q=",
        "RST": "https://rst.ua/uk/oldcars/?q="
    }

    tasks = [scrape_site(url, query, name) for name, url in engines.items()]
    results = await asyncio.gather(*tasks)
    
    final_text = f"🏁 **Результаты по запросу:** `{query}`\n\n"
    for r_list in results:
        for item in r_list:
            final_text += item + "\n\n"

    await status.delete()
    await message.answer(final_text, parse_mode="Markdown", disable_web_page_preview=True)

async def main():
    await asyncio.gather(start_webserver(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())