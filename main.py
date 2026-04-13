import asyncio
import os
import re
import json
import openai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiohttp import web

# --- CONFIG ---
TG_TOKEN = os.getenv('TG_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_KEY')
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- ВЕБ-СЕРВЕР ---
async def handle_ping(request):
    return web.Response(text="CHIIP UA: ACTIVE")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- AI ANALYZER ---
async def analyze_query(text):
    if not OPENAI_KEY: return {"q": text, "cat": "all"}
    openai.api_key = OPENAI_KEY
    prompt = f"Analyze query: '{text}'. Return JSON: {{'q': 'keywords', 'cat': 'car|item', 'max_p': int, 'year': 'start-end'}}"
    try:
        resp = await asyncio.to_thread(openai.ChatCompletion.create, model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return json.loads(resp.choices[0].message.content)
    except:
        return {"q": text, "cat": "all"}

# --- PARSER CORE ---
async def scrape_engine(url, params, platform_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Имитируем реального пользователя
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()
        
        results = []
        try:
            full_url = f"{url}{params['q']}"
            await page.goto(full_url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(2) # Пауза для подгрузки JS
            
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Универсальная логика извлечения (адаптирована под UA сайты)
            items = []
            if "ria" in url: items = soup.select('.ticket-item')[:3]
            elif "olx" in url: items = soup.select('[data-cy="l-card"]')[:3]
            elif "rst" in url: items = soup.select('.rst-oc-i')[:3]
            else: items = soup.select('h3, .title')[:3]

            for item in items:
                try:
                    title = item.get_text(strip=True)[:100]
                    link_tag = item.find('a', href=True) or item.find_parent('a', href=True)
                    link = link_tag['href'] if link_tag else full_url
                    if not link.startswith('http'): link = "https://" + url.split('/')[2] + link
                    
                    results.append(f"📍 **{platform_name}**\n📦 {title}\n🔗 [Открыть]({link})")
                except: continue
                
            return results
        except Exception as e:
            return [f"⚠️ {platform_name}: Временная блокировка или ошибка."]
        finally:
            await browser.close()

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🚀 **CHIIP UA Search v4.0**\n\nИщу по:\n✅ Auto.ria, RST, OLX.ua\n✅ eBay, Mobile.de\n\nПросто напиши, что нужно.")

@dp.message()
async def handle_request(message: types.Message):
    status = await message.answer("🛸 *Сканирую украинские и мировые рынки...*", parse_mode="Markdown")
    
    data = await analyze_query(message.text)
    
    # Список площадок
    engines = {
        "Auto.ria (UA)": "https://auto.ria.com/uk/search/?categories_id=1&q=",
        "OLX (UA)": "https://www.olx.ua/d/uk/list/q-",
        "RST (UA)": "https://rst.ua/uk/oldcars/?task=search&make%5B%5D=0&model%5B%5D=0&price%5B%5D=0&price%5B%5D=0&year%5B%5D=0&year%5B%5D=0&condition=0&transmission=0&fuel=0&drive=0&results=4&drive=0&q=",
        "eBay (INT)": "https://www.ebay.com/sch/i.html?_nkw="
    }

    # Фильтруем площадки: если не машина, убираем авто-сайты
    active_engines = engines
    if data.get('cat') == 'item':
        active_engines = {"OLX (UA)": engines["OLX (UA)"], "eBay (INT)": engines["eBay (INT)"]}

    tasks = [scrape_engine(url, data, name) for name, url in active_engines.items()]
    all_res = await asyncio.gather(*tasks)
    
    output = f"🏁 **Результаты для:** `{message.text}`\n\n"
    found = False
    for res_list in all_res:
        for item in res_list:
            output += item + "\n\n"
            found = True
            
    if not found: output = "❌ Ничего не найдено. Попробуй изменить запрос."

    await status.delete()
    # Разбивка на части, если текст слишком большой
    for i in range(0, len(output), 4096):
        await message.answer(output[i:i+4096], parse_mode="Markdown", disable_web_page_preview=True)

async def main():
    await asyncio.gather(start_webserver(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())
