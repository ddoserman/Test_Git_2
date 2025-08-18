import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import requests
import json
import re
import datetime
import sys

# === Загрузка токена из credentials.json ===
try:
    with open("credentials.json", "r", encoding="utf-8") as f:
        creds = json.load(f)
    TELEGRAM_TOKEN = creds["telegram"]["token"]
except Exception as e:
    print(f"❌ Не удалось прочитать credentials.json или ключ 'telegram.token': {e}")
    sys.exit(2)

# Фиксированный chat_id, как ты указал
TELEGRAM_CHAT_ID = "-4851606651"

SEARCH_URL = (
    "https://www.finn.no/mobility/search/car?"
    "dealer_segment=2&dealer_segment=1&fuel=1&fuel=6&fuel=1352"
    "&location=0.20015&location=0.20016&make=0.813&make=0.817&make=0.777"
    "&mileage_to=130000&price_to=200000&transmission=2&year_from=2017"
)

# Чтение истории
try:
    with open("seen_ads.json", "r", encoding="utf-8") as f:
        seen_ads = set(json.load(f))
except (FileNotFoundError, json.JSONDecodeError):
    seen_ads = set()

def log_event(text: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("ads_log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} | {text}\n")

async def parse_listings(page):
    # дождаться загрузки основного контента
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    # иногда лендинг подгружает карточки после скролла
    for _ in range(5):
        await page.keyboard.press("PageDown")
        await page.wait_for_timeout(800)

    articles = await page.query_selector_all("article")
    ads = []

    for article in articles:
        link_tag = await article.query_selector("a[href*='/mobility/item/']")
        if not link_tag:
            continue
        href = await link_tag.get_attribute("href")
        if not href:
            continue
        if not href.startswith("http"):
            href = "https://www.finn.no" + href

        match = re.search(r"/mobility/item/(\d+)", href)
        if not match:
            continue
        item_id = match.group(1)

        title_el = await article.query_selector("h2, h3, h4")
        title = (await title_el.inner_text()).strip() if title_el else "Без названия"
        if "Yaris" in title or "solgt" in title.lower():
            continue

        info_el = await article.query_selector("span.text-caption.font-bold")
        info_text = (await info_el.inner_text()).strip() if info_el else ""

        year_match = re.search(r'\b(20\d{2}|19\d{2})\b', info_text)
        year = year_match.group(0) if year_match else "Год не указан"

        mileage_match = re.search(r'([\d\s\u00a0]+) km', info_text)
        if mileage_match:
            mileage_value = re.sub(r"[^\d]", "", mileage_match.group(1))
            mileage = f"{int(mileage_value):,} km".replace(",", " ")
        else:
            mileage = "Пробег не указан"

        price_el = await article.query_selector("span.t3.font-bold")
        if price_el:
            price_text = (await price_el.inner_text()).strip()
            price_value = re.sub(r"[^\d]", "", price_text)
            price = f"{int(price_value):,} kr".replace(",", " ") if price_value else "Цена не указана"
        else:
            price = "Цена не указана"

        details_el = await article.query_selector("div.text-detail span.truncate")
        details_text = (await details_el.inner_text()).strip() if details_el else ""
        warranty_match = re.search(r"(\d+)\s*mnd garanti", details_text, re.IGNORECASE)
        warranty = f"{warranty_match.group(1)} месяцев" if warranty_match else "не указана"

        if price == "Цена не указана":
            continue

        ads.append({
            "id": item_id,
            "title": title,
            "price": price,
            "mileage": mileage,
            "year": year,
            "link": href,
            "warranty": warranty
        })

    print(f"🔎 Найдено {len(ads)} объявлений после фильтра")
    return ads

def send_to_telegram(ad, manual_removed=False):
    warning = "⚠️ Возможно уже было" if manual_removed else ""
    message = (
        f"🚗 {ad['title']}\n"
        f"📅 Год: {ad['year']}\n"
        f"💰 Цена: {ad['price']}\n"
        f"📏 Пробег: {ad['mileage']}\n"
        f"🛡️ Гарантия: {ad['warranty']}\n"
        f"🔗 {ad['link']}\n"
        f"{warning}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        r.raise_for_status()
        log_event(f"🚗 {ad['title']} | {ad['year']} | {ad['price']} | {ad['mileage']} | {ad['warranty']} | {ad['link']}")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

async def check_ads():
    global seen_ads
    previous_seen = seen_ads.copy()

    async with async_playwright() as p:
        # headless + --no-sandbox критичны для GitHub Actions
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(SEARCH_URL, wait_until="domcontentloaded")

        # Куки-баннер в iframe
        try:
            await page.wait_for_selector("iframe[src*='consent']", timeout=5000)
            frame = page.frame_locator("iframe[src*='consent']")
            # Кнопка по имени (норвежский вариант)
            await frame.get_by_role("button", name="Godta alle").click(timeout=3000)
            print("✅ Куки приняты (Godta alle)")
            await page.wait_for_timeout(1500)
        except PlaywrightTimeoutError:
            print("⚠️ Баннер куки не найден/не загрузился — продолжаем")

        ads = await parse_listings(page)
        await browser.close()

    new_ads = []
    for ad in ads:
        if ad["id"] not in seen_ads:
            manual_removed = ad["id"] in previous_seen
            send_to_telegram(ad, manual_removed)
            new_ads.append(ad)
            seen_ads.add(ad["id"])

    if not new_ads:
        msg = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Новых объявлений нет."
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=15
            )
        except Exception as e:
            print(f"Ошибка отправки статуса в Telegram: {e}")
        log_event("Новых объявлений нет.")

    with open("seen_ads.json", "w", encoding="utf-8") as f:
        json.dump(list(seen_ads), f, ensure_ascii=False, indent=2)

    print("Готово ✅")

if __name__ == "__main__":
    asyncio.run(check_ads())
