import asyncio, os, json, subprocess
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web
import openai

# --- НАСТРОЙКИ ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446  # Твой ID
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Файл для хранения пользователей (базовая БД)
USERS_FILE = "users.json"

def get_users():
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return json.load(f)

def add_user(user_id):
    users = get_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w") as f: json.dump(users, f)

# --- УСТАНОВКА БРАУЗЕРА ПРИ ЗАПУСКЕ (Fix для Render) ---
def install_playwright():
    try:
        print("⏳ Установка Chromium...")
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("✅ Chromium готов!")
    except Exception as e:
        print(f"❌ Ошибка установки: {e}")

# --- AI АНАЛИЗАТОР ---
async def analyze_query(text):
    if not OPENAI_KEY: return {"q": text, "cat": "all"}
    client = openai.AsyncOpenAI(api_key=OPENAI_KEY)
    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Извлеки название товара из текста. Верни только название."}],
            max_tokens=50
        )
        return {"q": response.choices[0].message.content.strip(), "cat": "auto"}
    except:
        return {"q": text, "cat": "all"}

# --- ЯДРО ПАРСЕРА ---
async def scrape_site(url_template, query, name):
    async with async_playwright() as p:
        try:
            # Принудительно указываем параметры для работы в контейнере Render
            browser = await p.chromium.launch(
                headless=True, 
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page()
            await page.goto(f"{url_template}{query}", timeout=60000)
            await asyncio.sleep(2)
            
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Универсальный поиск ссылок (адаптируй под каждый сайт при необходимости)
            items = []
            links = soup.find_all('a', href=True)[:3]
            for link in links:
                href = link['href']
                if "http" not in href: href = "https://olx.ua" + href # Пример для OLX
                items.append(f"📦 **{name}**: {href}")
            
            await browser.close()
            return items if items else [f"🔍 {name}: ничего не найдено."]
        except Exception as e:
            return [f"⚠️ Ошибка на {name}: {str(e)[:50]}"]

# --- АДМИНКА ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = [
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка")],
        [types.KeyboardButton(text="🔄 Переустановить браузер")]
    ]
    await message.answer("👑 **CHIIP COMMAND CENTER v6.5**", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

@dp.message(F.text == "📊 Статистика")
async def stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    users = get_users()
    await message.answer(f"📈 **Статистика системы:**\n\nВсего пользователей: {len(users)}\nСервер: Render (Live)")

@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Введите текст для рассылки всем пользователям:")

@dp.message(F.text == "🔄 Переустановить браузер")
async def force_install(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    install_playwright()
    await message.answer("✅ Команда на установку отправлена в консоль.")

# --- ОБРАБОТКА ПОИСКА ---
@dp.message()
async def handle_search(message: types.Message):
    add_user(message.from_user.id)
    
    # Если админ делает рассылку
    if message.from_user.id == ADMIN_ID and "рассылка" not in message.text.lower():
        # Тут можно добавить логику завершения рассылки
        pass

    status = await message.answer("🛸 **Сканирую рынки...**")
    
    # 1. AI Анализ
    data = await analyze_query(message.text)
    clean_query = data['q'].replace(" ", "+")

    # 2. Запуск парсеров (OLX и Auto.ria)
    tasks = [
        scrape_site("https://www.olx.ua/uk/list/q-", clean_query, "OLX"),
        scrape_site("https://auto.ria.com/uk/search/?categories_id=1&q=", clean_query, "Auto.ria")
    ]
    
    results = await asyncio.gather(*tasks)
    flat_results = [item for sublist in results for item in sublist]
    
    await status.delete()
    await message.answer("🏁 **Результаты поиска:**\n\n" + "\n\n".join(flat_results), parse_mode="Markdown")

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle_ping(request): return web.Response(text="ONLINE")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    install_playwright()
    await asyncio.gather(start_webserver(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())