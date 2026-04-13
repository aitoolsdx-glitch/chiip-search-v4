import asyncio, os, json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web

# --- НАСТРОЙКИ ---
TG_TOKEN = os.getenv('TG_TOKEN')
ADMIN_ID = 5476069446
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- СИСТЕМА УСТАНОВКИ БРАУЗЕРА (Fix) ---
async def install_browser():
    try:
        from playwright._impl._driver import compute_driver_executable
        import subprocess
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("✅ Chromium успешно установлен!")
    except Exception as e:
        print(f"⚠️ Ошибка установки: {e}")

# --- ВЕБ-СЕРВЕР ---
async def handle_ping(request): return web.Response(text="CHIIP SYSTEM ONLINE")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- ЯДРО ПОИСКА ---
async def scrape_site(url_template, query, name):
    async with async_playwright() as p:
        try:
            # Важно: указываем явный путь для Render
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = await browser.new_page()
            await page.goto(f"{url_template}{query}", timeout=60000)
            await asyncio.sleep(3)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            links = soup.select('a[href*="item"], a[href*="obyavlenie"], a[href*="product"]')[:3]
            res = [f"📦 **{name}**: {l.get_text(strip=True)[:40]}... \n🔗 https://olx.ua{l['href']}" for l in links if 'href' in l.attrs]
            
            await browser.close()
            return res if res else [f"🔍 {name}: ничего не найдено."]
        except Exception as e:
            return [f"⚠️ {name} недоступен: {str(e)[:30]}"]

# --- АДМИНКА ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = [[types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="📢 Рассылка")],
          [types.KeyboardButton(text="🔄 Переустановить браузер")]]
    await message.answer("👑 **ADMIN PANEL v6.0**", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

@dp.message(F.text == "🔄 Переустановить браузер")
async def force_install(message: types.Message):
    await install_browser()
    await message.answer("✅ Браузер переустановлен, пробуй поиск!")

@dp.message()
async def handle_all(message: types.Message):
    if message.text == "📊 Статистика":
        await message.answer("📊 Система работает стабильно. Память очищена.")
        return
    
    status = await message.answer("🛸 *Ищу информацию...*")
    query = message.text.replace(" ", "+")
    tasks = [scrape_site("https://www.olx.ua/uk/list/q-", query, "OLX")]
    res = await asyncio.gather(*tasks)
    
    await status.delete()
    await message.answer("\n\n".join(res[0]), parse_mode="Markdown")

async def main():
    await install_browser() # Устанавливаем при старте
    await asyncio.gather(start_webserver(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())