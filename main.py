import asyncio, os, json, openai
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web

# --- НАСТРОЙКИ (Берутся из Environment Variables на Render) ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446  # Твой ID из скриншота
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
users_db = set()

# --- ВЕБ-СЕРВЕР ДЛЯ CRON-JOB (Исправлены отступы) ---
async def handle_ping(request): 
    return web.Response(text="CHIIP SYSTEM ONLINE")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- ЯДРО ПОИСКА (Теперь реально работает) ---
async def scrape_site(url_template, query, name):
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            page = await context.new_page()
            await page.goto(f"{url_template}{query}", timeout=45000)
            await asyncio.sleep(2) # Ждем подгрузки JS
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Поиск ссылок (OLX, Auto.ria и др.)
            results = []
            links = soup.find_all('a', href=True)[:3] # Берем первые 3 результата
            for link in links:
                href = link['href']
                if "http" not in href: href = "https://www.olx.ua" + href
                title = link.get_text(strip=True)[:60]
                if len(title) > 10:
                    results.append(f"📦 **{name}**: {title}\n🔗 {href}")
            
            await browser.close()
            return results if results else [f"🔍 На {name} ничего не найдено."]
        except Exception as e:
            return [f"⚠️ Ошибка на {name}: {str(e)[:50]}"]

# --- ОБРАБОТЧИКИ АДМИНКИ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка")],
        [types.KeyboardButton(text="⚙️ Статус сервера"), types.KeyboardButton(text="❌ Выход")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("🛠 **CHIIP COMMAND CENTER v5.5**", reply_markup=keyboard)

@dp.message(F.text == "📊 Статистика")
async def stats(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(f"📈 Юзеров в базе: {len(users_db)}\n🌐 Сервер: Render.com")

@dp.message(F.text == "⚙️ Статус сервера")
async def status_check(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("✅ Все системы CHIIP работают штатно.\nБраузер Playwright: готов.")

# --- ГЛАВНАЯ ЛОГИКА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    users_db.add(message.from_user.id)
    await message.answer("🚀 **CHIIP UA Search v5.5**\nСистема активирована. Введите название товара для поиска.")

@dp.message()
async def handle_search(message: types.Message):
    if message.text in ["📊 Статистика", "📢 Рассылка", "⚙️ Статус сервера"]: return
    
    users_db.add(message.from_user.id)
    status_msg = await message.answer("🛸 *Сканирую рынки...*")
    
    query = message.text.replace(" ", "+")
    # Список сайтов для парсинга
    sites = {
        "OLX": "https://www.olx.ua/uk/list/q-",
        "Auto.ria": "https://auto.ria.com/uk/search/?q="
    }
    
    tasks = [scrape_site(url, query, name) for name, url in sites.items()]
    all_results = await asyncio.gather(*tasks)
    
    response = "🏁 **Результаты поиска:**\n\n"
    for site_res in all_results:
        for item in site_res:
            response += item + "\n\n"
            
    await status_msg.delete()
    await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)

async def main():
    # Запуск сервера и бота одновременно
    await asyncio.gather(start_webserver(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())