import asyncio, os, json, subprocess, logging, random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web
import openai

# --- [ СЕРДЦЕ СИСТЕМЫ ] ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()
ai_client = openai.AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- [ БАЗА ДАННЫХ САЙТОВ (Расширенная) ] ---
SITES = {
    "Rozetka": ["https://rozetka.com.ua/search/?text=", "tech"],
    "Prom": ["https://prom.ua/search?search_term=", "all"],
    "Hotline": ["https://hotline.ua/sr/?q=", "tech"],
    "Epicentr": ["https://epicentrk.ua/search/?q=", "home"],
    "Allo": ["https://allo.ua/ru/catalogsearch/result/?q=", "tech"],
    "Foxtrot": ["https://www.foxtrot.com.ua/uk/search?query=", "tech"],
    "Comfy": ["https://comfy.ua/search/?q=", "tech"],
    "Auto.ria": ["https://auto.ria.com/uk/search/?q=", "auto"],
    "OLX": ["https://www.olx.ua/d/uk/list/q-", "all"],
    "RST": ["https://rst.ua/uk/oldcars/?task=search&q=", "auto"],
    "Moyo": ["https://www.moyo.ua/search/?q=", "tech"],
    "Stylus": ["https://stylus.ua/uk/search?q=", "tech"],
    "Yakaboo": ["https://www.yakaboo.ua/search/?query=", "books"],
    "Makeup": ["https://makeup.com.ua/search/?q=", "beauty"],
    "Eva": ["https://eva.ua/ua/search/?q=", "beauty"],
    "Silpo": ["https://silpo.ua/search?q=", "food"],
    "ATB": ["https://www.atbmarket.com/search?query=", "food"]
}

# --- [ СИСТЕМА ЛОГОВ ] ---
LOG_HISTORY = []
USERS_DB = "titan_users.json"
STATS = {"searches": 0, "errors": 0}

def add_log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    LOG_HISTORY.append(f"[{t}] {msg}")
    if len(LOG_HISTORY) > 15: LOG_HISTORY.pop(0)

def manage_users(u_id=None):
    if not os.path.exists(USERS_DB): 
        with open(USERS_DB, "w") as f: json.dump([], f)
    with open(USERS_DB, "r") as f: users = json.load(f)
    if u_id and u_id not in users:
        users.append(u_id)
        with open(USERS_DB, "w") as f: json.dump(users, f)
    return users

# --- [ ИИ ЛОГИКА ] ---
async def titan_ai(text):
    if not ai_client: return text, "all"
    try:
        resp = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Return JSON: {'q': 'clean text', 'cat': 'tech|auto|fashion|food|books|beauty|all'}"},
                      {"role": "user", "content": text}],
            response_format={"type": "json_object"}
        )
        res = json.loads(resp.choices[0].message.content)
        return res.get('q', text), res.get('cat', 'all')
    except: return text, "all"

# --- [ ЯДРО TITAN SCRAPER ] ---
async def scrape_engine(context, name, url, query):
    page = await context.new_page()
    # Скрываем следы бота
    await page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8"
    })
    
    try:
        full_url = f"{url}{query.replace(' ', '+')}"
        await page.goto(full_url, timeout=45000, wait_until="domcontentloaded")
        
        # Проверка на Cloudflare
        if "challenge-platform" in await page.content() or "captcha" in await page.url():
            add_log(f"Blocked by WAF: {name}")
            return [f"🛡 **{name}**: Заблокировано защитой (WAF)."]

        await asyncio.sleep(random.uniform(2, 4)) # Эмуляция человека
        
        # Поиск ссылок через JavaScript (более надежно)
        items = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                return links
                    .filter(a => a.href.includes('product') || a.href.includes('item') || a.href.includes('auto') || a.href.includes('obyavlenie'))
                    .map(a => ({ text: a.innerText.trim(), href: a.href }))
                    .filter(a => a.text.length > 20)
                    .slice(0, 2);
            }
        """)

        if not items: return []
        
        res = []
        for i in items:
            res.append(f"📦 **{name}**: {i['text'][:55]}...\n🔗 {i['href']}")
        return res

    except Exception as e:
        STATS["errors"] += 1
        return [f"⚠️ **{name}**: Тайм-аут или ошибка связи."]
    finally:
        await page.close()

# --- [ ADMIN TITAN PANEL ] ---
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📈 Stats"), KeyboardButton(text="📜 Live Logs")],
        [KeyboardButton(text="🔑 Terminal"), KeyboardButton(text="📢 Broadcast")],
        [KeyboardButton(text="♻️ Reset Browser"), KeyboardButton(text="❌ Exit")]
    ], resize_keyboard=True)

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🦾 **CHIIP TITAN: CONTROL UNIT**", reply_markup=get_admin_kb())

@dp.message(F.text == "📜 Live Logs")
async def show_logs(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        logs = "\n".join(LOG_HISTORY[-10:]) if LOG_HISTORY else "Логи пусты."
        await message.answer(f"📋 **ПОСЛЕДНИЕ СОБЫТИЯ:**\n\n`{logs}`", parse_mode="Markdown")

@dp.message(F.text == "📈 Stats")
async def show_stats(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        users = manage_users()
        await message.answer(f"📊 **ДАННЫЕ:**\n\nЮзеры: {len(users)}\nПоисков: {STATS['searches']}\nОшибок: {STATS['errors']}")

@dp.message(F.text == "🔑 Terminal")
async def term_info(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Введи системную команду через префикс `>`\nПример: `>df -h` или `>free -m`")

@dp.message(F.text.startswith(">"))
async def run_terminal(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        cmd = message.text[1:]
        try:
            res = subprocess.check_output(cmd, shell=True).decode()
            await message.answer(f"💻 **Output:**\n`{res[:3500]}`", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text == "📢 Broadcast")
async def bc_start(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Напиши сообщение с префиксом `!ALL` для рассылки.")

@dp.message(F.text.startswith("!ALL"))
async def bc_run(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        msg = message.text.replace("!ALL", "").strip()
        users = manage_users()
        count = 0
        for u in users:
            try:
                await bot.send_message(u, f"📡 **ОПОВЕЩЕНИЕ:**\n\n{msg}")
                count += 1
            except: continue
        await message.answer(f"✅ Отправлено {count} пользователям.")

# --- [ ГЛАВНЫЙ ЦИКЛ ПОИСКА ] ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    manage_users(message.from_user.id)
    await message.answer("🛡 **CHIIP TITAN v11.0** запущен.\nЯ использую обход блокировок и ИИ для поиска. Что ищем?")

@dp.message()
async def titan_search(message: types.Message):
    if message.text == "❌ Exit":
        await message.answer("Панель закрыта.", reply_markup=ReplyKeyboardRemove()); return
    
    if message.from_user.id == ADMIN_ID and message.text in ["📈 Stats", "📜 Live Logs", "🔑 Terminal", "📢 Broadcast", "♻️ Reset Browser"]: return

    manage_users(message.from_user.id)
    STATS["searches"] += 1
    
    status = await message.answer("📡 *ИИ анализирует запрос...*")
    
    q, cat = await titan_ai(message.text)
    add_log(f"Query: {q} | Cat: {cat}")
    
    # Подбор сайтов: категория + универсальные
    target = [n for n, d in SITES.items() if d[1] == cat or d[1] == "all"]
    random.shuffle(target)
    selected = target[:4] # Берем 4 сайта за раз для стабильности

    await status.edit_text(f"🛰 *Сканирую {', '.join(selected)}...*")
    
    async with async_playwright() as p:
        # Улучшенные аргументы против детекции
        browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-blink-features=AutomationControlled'
        ])
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        tasks = [scrape_engine(context, name, SITES[name][0], q) for name in selected]
        results = await asyncio.gather(*tasks)
        await browser.close()

    flat_results = [item for sub in results for item in sub]
    
    await status.delete()
    if flat_results:
        final_msg = f"🏁 **РЕЗУЛЬТАТЫ ПОИСКА (TITAN):**\n\n" + "\n\n".join(flat_results)
        await message.answer(final_msg, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await message.answer("⚠️ **Ничего не найдено.**\n\nСайты могли временно заблокировать доступ. Попробуй другой запрос или повтори позже.")

# --- [ СЕРВЕР ] ---
async def handle_ping(request): return web.Response(text="TITAN_CORE_ACTIVE")

async def main():
    add_log("System Rebooted")
    # Установка Playwright
    subprocess.run(["playwright", "install", "chromium"])
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())