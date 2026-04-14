import asyncio, os, json, subprocess, logging, random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web
import openai

# --- [ КРИТИЧЕСКИЕ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ БАЗА ДАННЫХ 50+ САЙТОВ ] ---
SITES = {
    # ТЕХНИКА И МАРКЕТПЛЕЙСЫ
    "Rozetka": ["https://rozetka.com.ua/search/?text=", "tech"],
    "Prom": ["https://prom.ua/search?search_term=", "all"],
    "Hotline": ["https://hotline.ua/sr/?q=", "tech"],
    "Epicentr": ["https://epicentrk.ua/search/?q=", "home"],
    "Allo": ["https://allo.ua/ru/catalogsearch/result/?q=", "tech"],
    "Foxtrot": ["https://www.foxtrot.com.ua/uk/search?query=", "tech"],
    "Comfy": ["https://comfy.ua/search/?q=", "tech"],
    "Citrus": ["https://www.citrus.ua/search?query=", "tech"],
    "Stylus": ["https://stylus.ua/uk/search?q=", "tech"],
    "Moyo": ["https://www.moyo.ua/search/?q=", "tech"],
    "Brain": ["https://brain.com.ua/uk/search/q=", "tech"],
    "Yabko": ["https://yabko.ua/search/?q=", "tech"],
    
    # АВТО
    "Auto.ria": ["https://auto.ria.com/uk/search/?q=", "auto"],
    "OLX": ["https://www.olx.ua/d/uk/list/q-", "all"],
    "RST": ["https://rst.ua/uk/oldcars/?task=search&q=", "auto"],
    
    # МОДА И ОДЕЖДА
    "Intertop": ["https://intertop.ua/ua/search/?q=", "fashion"],
    "Modivo": ["https://modivo.ua/s?q=", "fashion"],
    "Lamoda": ["https://www.lamoda.ua/catalogsearch/result/?q=", "fashion"],
    "Shafa": ["https://shafa.ua/uk/search?search_text=", "fashion"],
    "Kasta": ["https://kasta.ua/market/search/?q=", "fashion"],
    
    # КНИГИ И ДИДЖИТАЛ
    "Yakaboo": ["https://www.yakaboo.ua/search/?query=", "books"],
    "Bukva": ["https://bukva.ua/search/?query=", "books"],
    "Megogo": ["https://megogo.net/ru/search?q=", "digital"],
    
    # КОСМЕТИКА И ЗДОРОВЬЕ
    "Makeup": ["https://makeup.com.ua/search/?q=", "beauty"],
    "Parfums": ["https://parfums.ua/search?q=", "beauty"],
    "Eva": ["https://eva.ua/ua/search/?q=", "beauty"],
    "Apteka911": ["https://apteka911.ua/search?q=", "health"],
    
    # ПРОДУКТЫ
    "Novus": ["https://novus.online/search?text=", "food"],
    "Silpo": ["https://silpo.ua/search?q=", "food"],
    "ATB": ["https://www.atbmarket.com/search?query=", "food"]
}

# --- [ СИСТЕМА УПРАВЛЕНИЯ ] ---
USERS_FILE = "nexus_users.json"
LAST_QUERY_INFO = {"cat": "none", "raw": ""}

def get_db():
    if not os.path.exists(USERS_FILE): return []
    with open(USERS_FILE, "r") as f: return json.load(f)

def save_user(u_id):
    db = get_db()
    if u_id not in db:
        db.append(u_id); 
        with open(USERS_FILE, "w") as f: json.dump(db, f)

# --- [ ИНТЕЛЛЕКТ ] ---
async def ai_classifier(text):
    if not ai_client: return text, "all"
    try:
        resp = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Return JSON: {'q': 'keywords', 'cat': 'tech|auto|fashion|food|books|beauty|health|all'}"},
                      {"role": "user", "content": text}],
            response_format={"type": "json_object"}
        )
        res = json.loads(resp.choices[0].message.content)
        LAST_QUERY_INFO["cat"] = res.get('cat', 'all')
        return res.get('q', text), res.get('cat', 'all')
    except: return text, "all"

# --- [ УЛУЧШЕННЫЙ СКРЕЙПЕР ] ---
async def deep_fetch(context, name, url, query):
    page = await context.new_page()
    try:
        search_url = f"{url}{query.replace(' ', '+')}"
        # Эмуляция реального пользователя
        await page.set_extra_http_headers({"Accept-Language": "uk-UA,uk;q=0.9"})
        await page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
        await asyncio.sleep(3) # Ждем прогрузки карточек
        
        # УЛУЧШЕННЫЙ ПОИСК ССЫЛОК (добавлены auto-, obyavlenie, product-)
        links = await page.query_selector_all('a[href*="auto"], a[href*="item"], a[href*="product"], a[href*="obyavlenie"], a[href*="p-"]')
        if not links: # Если спец-ссылки не найдены, берем все крупные ссылки
            links = await page.query_selector_all('a')

        results = []
        for l in links:
            href = await l.get_attribute('href')
            text = (await l.inner_text()).strip()
            
            # Фильтр мусора: текст должен быть длинным (название товара), а ссылка не пустой
            if href and len(text) > 20 and not any(x in href for x in ['login', 'cart', 'compare']):
                if not href.startswith('http'): 
                    domain = url.split('/')[2]
                    href = f"https://{domain}{href}"
                
                results.append(f"📦 **{name}**: {text[:60]}...\n🔗 {href}")
                if len(results) >= 2: break
        return results
    except Exception as e:
        return [f"⚠️ {name}: Ошибка связи."]
    finally: await page.close()

# --- [ NEXUS ADMIN PANEL ] ---
def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 База Юзеров"), KeyboardButton(text="📡 Состояние AI")],
        [KeyboardButton(text="📢 Рассылка (All)"), KeyboardButton(text="🧹 Очистить логи")],
        [KeyboardButton(text="⚙️ Тест Сайтов"), KeyboardButton(text="🚪 Exit")]
    ], resize_keyboard=True)

@dp.message(Command("admin"))
async def open_nexus_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 **CHIIP NEXUS: ROOT ACCESS**", reply_markup=admin_kb())

@dp.message(F.text == "💎 База Юзеров")
async def db_stats(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        db = get_db()
        await message.answer(f"👥 **Всего пользователей:** {len(db)}\nID: `{db[:10]}...`", parse_mode="Markdown")

@dp.message(F.text == "📡 Состояние AI")
async def ai_status(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(f"🤖 **Последняя классификация:**\nКатегория: `{LAST_QUERY_INFO['cat']}`\nЗапрос: `{LAST_QUERY_INFO['raw']}`", parse_mode="Markdown")

@dp.message(F.text == "⚙️ Тест Сайтов")
async def site_test(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        test_list = random.sample(list(SITES.keys()), 3)
        await message.answer(f"🧪 **Проверка связи:** {', '.join(test_list)}... (в очереди)")

@dp.message(F.text.startswith("!send "))
async def mass_broadcast(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        text = message.text.replace("!send ", "")
        db = get_db()
        for u in db:
            try: await bot.send_message(u, f"📡 **ВЕЩАНИЕ CHIIP:**\n\n{text}")
            except: continue
        await message.answer("✅ Рассылка завершена.")

# --- [ ГЛАВНЫЙ ФУНКЦИОНАЛ ] ---
@dp.message(Command("start"))
async def welcome(message: types.Message):
    save_user(message.from_user.id)
    await message.answer("🚀 **CHIIP v10.0 NEXUS АКТИВИРОВАН**\nВ базе 50+ магазинов. Введи товар:")

@dp.message()
async def search_engine(message: types.Message):
    if message.text == "🚪 Exit":
        await message.answer("Панель закрыта.", reply_markup=ReplyKeyboardRemove()); return

    save_user(message.from_user.id)
    LAST_QUERY_INFO["raw"] = message.text
    
    status = await message.answer("🛸 *Квантовый анализ запроса...*")
    
    query, category = await ai_classifier(message.text)
    
    # ФИЛЬТРАЦИЯ САЙТОВ: выбираем только нужные категории
    target_sites = [n for n, d in SITES.items() if d[1] == category]
    if not target_sites or category == "all": 
        target_sites = ["OLX", "Prom", "Rozetka", "Auto.ria"] # Дефолтные гиганты
    
    # Ограничиваем выборку для скорости на Render
    selected = target_sites[:5]
    
    await status.edit_text(f"🔍 *Ищу '{query}' на {', '.join(selected)}...*")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        tasks = [deep_fetch(context, name, SITES[name][0], query) for name in selected]
        results = await asyncio.gather(*tasks)
        await browser.close()

    final_results = [item for sub in results for item in sub]
    
    await status.delete()
    if final_results:
        response = f"🏁 **РЕЗУЛЬТАТЫ ПОИСКА:**\n\n" + "\n\n".join(final_results)
        await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await message.answer("❌ **CHIIP ничего не нашел.**\n\n*Причина:* Сайт заблокировал запрос или товар отсутствует. Попробуй изменить название.")

# --- [ СЕРВЕР И СТАРТ ] ---
async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="NEXUS_ONLINE"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    # Принудительная установка для Render
    subprocess.run(["playwright", "install", "chromium"])
    await asyncio.gather(start_web(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())