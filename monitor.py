import json
import os
import re
import cloudscraper
from bs4 import BeautifulSoup
import requests

# === ВАШИ ДАННЫЕ TELEGRAM ===
TELEGRAM_BOT_TOKEN = "9272449199:AAFIbkYxsYgx52VEzkPgjsQ_raq8Ky8lnxM"
TELEGRAM_CHAT_ID = "5563031715"

MAX_PRICE = 20000      # Строго до 20 000 грн (20 000 не подходит)
USD_RATE = 42.0        # Курс для пересчёта цен в $ из Telegram-каналов
SEEN_ADS_FILE = "seen_ads.json"

# Публичные Telegram-барахолки (можно добавлять свои @username без собачки)
TELEGRAM_CHANNELS = [
    "baraholka_ua_tech",
    "iphone_baraholka_ua",
    "apple_baraholka_ukraine",
    "baraholka_kiev_ua",
    "tehnika_bu_ua",
]

EXCLUDE_WORDS = [
    "s24+",
    "s24 plus",
    "с24+",
    "с24 плюс",
    "15 pro max",
    "15 про макс",
    "replica",
    "копия",
    "копія",
    "реплика",
    "репліка",
    "чехол",
    "чохол",
    "стекло",
    "скло",
    "коробка",
    "муляж",
    "дисплей",
    "экран",
    "екран",
    "плата",
    "на запчасти",
    "на запчастини",
    "куплю",
    "скупка",
    "в кредит",
    "кредит",
    "рассрочк",
    "розстрочк",
    "первый взнос",
    "перший внесок",
    "оплата частями",
    "оплата частинами",
]

# Запросы к внутреннему JSON API OLX (категория 37 = Мобильные телефоны / смартфоны)
OLX_API_QUERIES = [
    "https://www.olx.ua/api/v1/offers/?offset=0&limit=40&category_id=37&query=s24%20ultra&filter_float_price%3Ato=19999&sort_by=created_at%3Adesc",
    "https://www.olx.ua/api/v1/offers/?offset=0&limit=40&category_id=37&query=iphone%2014%20pro&filter_float_price%3Ato=19999&sort_by=created_at%3Adesc",
    "https://www.olx.ua/api/v1/offers/?offset=0&limit=40&category_id=37&query=iphone%2015%20pro&filter_float_price%3Ato=19999&sort_by=created_at%3Adesc",
]

SHAFA_URLS = [
    "https://shafa.ua/uk/elektronika/telefony-i-aksessuary/mobilnye-telefony?search_text=s24+ultra&price_to=19999&sort=4",
    "https://shafa.ua/uk/elektronika/telefony-i-aksessuary/mobilnye-telefony?search_text=iphone+14+pro&price_to=19999&sort=4",
    "https://shafa.ua/uk/elektronika/telefony-i-aksessuary/mobilnye-telefony?search_text=iphone+15+pro&price_to=19999&sort=4",
]

PROM_URLS = [
    "https://prom.ua/ua/search?search_term=galaxy+s24+ultra&price_local__lte=19999&condition=used",
    "https://prom.ua/ua/search?search_term=iphone+14+pro&price_local__lte=19999&condition=used",
    "https://prom.ua/ua/search?search_term=iphone+15+pro&price_local__lte=19999&condition=used",
]

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)


def load_seen_ads():
    if os.path.exists(SEEN_ADS_FILE):
        try:
            with open(SEEN_ADS_FILE, "r", encoding="utf-8") as f:
                return list(json.load(f))
        except Exception:
            return []
    return []


def save_seen_ads(seen_list):
    # Храним последние 2000 записей, чтобы файл не раздувался
    trimmed = seen_list[-2000:]
    with open(SEEN_ADS_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def mark_seen(seen_list, seen_set, ad_id):
    if ad_id not in seen_set:
        seen_set.add(ad_id)
        seen_list.append(ad_id)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Ошибка Telegram API: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Ошибка отправки в ТГ: {e}")


def detect_exact_model(title, description=""):
    text = f"{title} {description}".lower()
    if any(w in text for w in EXCLUDE_WORDS):
        return None

    if "s24 ultra" in text or "с24 ультра" in text or "s24 ультра" in text:
        return "Samsung Galaxy S24 Ultra"

    is_15_pro = ("15 pro" in text or "15 про" in text) and (
        "15 pro max" not in text and "15 про макс" not in text
    )
    if is_15_pro:
        return "Apple iPhone 15 Pro"

    if "14 pro max" in text or "14 про макс" in text:
        return "Apple iPhone 14 Pro Max"

    is_14_pro = ("14 pro" in text or "14 про" in text) and (
        "14 pro max" not in text and "14 про макс" not in text
    )
    if is_14_pro:
        return "Apple iPhone 14 Pro"

    return None


def extract_memory(text):
    match = re.search(
        r"\b(128|256|512|1\s?tb|1\s?тб|12/256|12/512|12/1)\b", text.lower()
    )
    if match:
        val = match.group(0).upper().replace(" ", "")
        return val if ("/" in val or "TB" in val or "ТБ" in val) else f"{val} ГБ"
    return "Не указано"


def get_checklist(model_name):
    if "iPhone" in model_name:
        return "Проверить iCloud (сброс до заводских настроек при встрече), остаток АКБ, Face ID, True Tone и отсутствие MDM-профилей."
    return "Проверить Knox (0x0), стилус S-Pen, экран на выгорание на белом фоне, работу камер и оригинальность (не копия)."


def summarize_condition(description):
    desc_l = description.lower()
    issues = []
    keywords = {
        "царапин": "царапины",
        "подряпин": "царапины",
        "потерт": "потёртости",
        "скол": "сколы",
        "трещин": "трещины",
        "тріщин": "трещины",
        "разбит": "разбит экран/корпус",
        "розбит": "разбит экран/корпус",
        "выгоран": "выгорание экрана",
        "вигоран": "выгорание экрана",
        "полос": "полосы на экране",
        "не работает": "есть неисправности",
        "не працює": "есть неисправности",
        "face id": "упоминается Face ID",
        "icloud": "проверить блокировку iCloud",
        "mdm": "MDM-профиль",
        "r-sim": "R-Sim / залочен",
        "идеал": "состояние близкое к идеальному",
        "ідеал": "состояние близкое к идеальному",
    }
    for key, label in keywords.items():
        if key in desc_l and label not in issues:
            issues.append(label)

    if issues:
        return ", ".join(issues).capitalize()
    clean_desc = re.sub(r"<[^>]+>", " ", description)
    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
    return (
        clean_desc[:140] + "..."
        if len(clean_desc) > 140
        else (clean_desc or "См. описание по ссылке")
    )


def format_and_send(model, price_str, memory, condition, city, pub_date, url, seller_type=""):
    checklist = get_checklist(model)
    seller_line = f"Продавец: {seller_type}\n" if seller_type else ""
    msg = (
        f"📱 Найдено новое объявление!\n\n"
        f"Модель: {model}\n"
        f"Цена: {price_str}\n"
        f"Память: {memory}\n"
        f"Состояние: {condition}\n"
        f"{seller_line}"
        f"Город: {city}\n"
        f"Дата публикации: {pub_date}\n\n"
        f"Ссылка: {url}\n\n"
        f"Дополнительно: {checklist}"
    )
    send_telegram(msg)


# === 1. ПРОВЕРКА OLX ЧЕРЕЗ JSON API ===
def check_olx_api(seen_list, seen_set):
    count = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    for api_url in OLX_API_QUERIES:
        try:
            resp = scraper.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"OLX API статус: {resp.status_code}")
                continue
            data = resp.json()
            offers = data.get("data", [])

            for offer in offers:
                raw_id = str(offer.get("id", ""))
                if not raw_id:
                    continue
                ad_id = f"olx_{raw_id}"
                if ad_id in seen_set:
                    continue

                if offer.get("status") != "active":
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                title = offer.get("title", "")
                description = offer.get("description", "")
                full_url = offer.get("url", f"https://www.olx.ua/d/uk/obyavlenie/-ID{raw_id}.html")

                # Извлекаем точную цену из параметров API
                price = 0
                for param in offer.get("params", []):
                    if param.get("key") == "price":
                        val = param.get("value", {})
                        price = int(float(val.get("value", 0)))
                        break

                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                exact_model = detect_exact_model(title, description)
                if not exact_model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                loc = offer.get("location", {})
                city = loc.get("city", {}).get("name", "Украина")
                created_time = offer.get("created_time", "")[:16].replace("T", " ") or "Сегодня"
                is_business = offer.get("business", False)
                seller_label = "Магазин / Бизнес" if is_business else "Частное лицо"

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(f"{title} {description}"),
                    summarize_condition(description),
                    city,
                    created_time,
                    full_url,
                    seller_label,
                )
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"OLX API error: {e}")
    return count


# === 2. ПРОВЕРКА SHAFA.UA (включая IZI) ===
def check_shafa(seen_list, seen_set):
    count = 0
    for url in SHAFA_URLS:
        try:
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "/uk/elektronika/" not in href or not re.search(r"/\d+-", href):
                    continue
                full_url = "https://shafa.ua" + href if href.startswith("/") else href
                ad_id = f"shafa_{href.split('/')[-1].split('-')[0]}"
                if ad_id in seen_set:
                    continue

                container = link
                for _ in range(3):
                    if container.parent and len(container.parent.get_text(strip=True)) < 500:
                        container = container.parent
                card_text = container.get_text(" ", strip=True)

                exact_model = detect_exact_model(card_text)
                if not exact_model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                price_match = re.search(r"(\d[\d\s]{2,6})\s*грн", card_text)
                if not price_match:
                    continue
                price = int(re.sub(r"\D", "", price_match.group(1)))
                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(card_text),
                    summarize_condition(card_text),
                    "Украина (Shafa)",
                    "Сегодня",
                    full_url,
                )
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"Shafa error: {e}")
    return count


# === 3. ПРОВЕРКА PROM.UA ===
def check_prom(seen_list, seen_set):
    count = 0
    for url in PROM_URLS:
        try:
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.find_all("div", {"data-qaid": "product_block"}):
                link = card.find("a", {"data-qaid": "product_link"}, href=True)
                if not link:
                    continue
                href = link["href"]
                full_url = "https://prom.ua" + href if href.startswith("/") else href
                ad_id = f"prom_{href.split('/')[-1][:30]}"
                if ad_id in seen_set:
                    continue

                title = link.get_text(" ", strip=True)
                exact_model = detect_exact_model(title)
                if not exact_model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                price_elem = card.find(attrs={"data-qaid": "product_price"})
                if not price_elem:
                    continue
                digits = re.sub(r"\D", "", price_elem.get_text())
                if not digits:
                    continue
                price = int(digits)
                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(title),
                    "Б/у или уценка (см. описание по ссылке)",
                    "Украина (Prom.ua)",
                    "Сегодня",
                    full_url,
                )
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"Prom error: {e}")
    return count


# === 4. ПРОВЕРКА TELEGRAM-БАРАХОЛОК (ГРН + $) ===
def check_telegram_channels(seen_list, seen_set):
    count = 0
    for channel in TELEGRAM_CHANNELS:
        try:
            url = f"https://t.me/s/{channel}"
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for msg_box in soup.find_all("div", class_="tgme_widget_message"):
                post_attr = msg_box.get("data-post")
                if not post_attr:
                    continue
                ad_id = f"tg_{post_attr}"
                if ad_id in seen_set:
                    continue

                text_elem = msg_box.find("div", class_="tgme_widget_message_text")
                if not text_elem:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                post_text = text_elem.get_text(" ", strip=True)
                exact_model = detect_exact_model(post_text)
                if not exact_model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                text_l = post_text.lower()
                price_uah = 0
                price_display = ""

                # Сначала ищем цену в гривнах
                uah_match = re.search(r"\b(\d{1,2}[\s.,]?\d{3})\s*(?:грн|uah|₴)", text_l)
                # Или в долларах
                usd_match = re.search(r"(?:\$\s*(\d{3})|\b(\d{3})\s*(?:\$|usd|у\.е\.|уе|дол))", text_l)

                if uah_match:
                    price_uah = int(re.sub(r"\D", "", uah_match.group(1)))
                    price_display = f"{price_uah:,} грн".replace(",", " ")
                elif usd_match:
                    usd_val = int(usd_match.group(1) or usd_match.group(2))
                    price_uah = int(usd_val * USD_RATE)
                    price_display = f"{usd_val}$ (~{price_uah:,} грн)".replace(",", " ")
                else:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                if price_uah >= MAX_PRICE or price_uah < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                post_url = f"https://t.me/{post_attr}"
                format_and_send(
                    exact_model,
                    price_display,
                    extract_memory(post_text),
                    summarize_condition(post_text),
                    f"Telegram (@{channel})",
                    "Сегодня",
                    post_url,
                )
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"TG {channel} error: {e}")
    return count


def run():
    seen_list = load_seen_ads()
    seen_set = set(seen_list)

    total_new = 0
    total_new += check_olx_api(seen_list, seen_set)
    total_new += check_shafa(seen_list, seen_set)
    total_new += check_prom(seen_list, seen_set)
    total_new += check_telegram_channels(seen_list, seen_set)

    save_seen_ads(seen_list)
    print(f"Проверка завершена. Новых объявлений: {total_new}")


if __name__ == "__main__":
    run()
