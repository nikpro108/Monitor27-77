from datetime import datetime
import html
import json
import os
import re
import cloudscraper
from bs4 import BeautifulSoup
import requests

# === ВАШИ ДАННЫЕ TELEGRAM ===
TELEGRAM_BOT_TOKEN = "9272449199:AAFIbkYxsYgx52VEzkPgjsQ_raq8Ky8lnxM"
TELEGRAM_CHAT_ID = "5563031715"

MAX_PRICE = 20000          # Строго до 20 000 грн (20 000 не подходит)
FALLBACK_USD_RATE = 42.0   # Запасной курс, если API ПриватБанка недоступен
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

URGENT_WORDS = ["срочно", "терміново", "торг", "швидко", "быстро"]

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


def get_live_usd_rate():
    try:
        resp = requests.get(
            "https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5",
            timeout=6,
        )
        if resp.status_code == 200:
            for item in resp.json():
                if item.get("ccy") == "USD":
                    return float(item.get("sale", FALLBACK_USD_RATE))
    except Exception:
        pass
    return FALLBACK_USD_RATE


def load_seen_ads():
    if os.path.exists(SEEN_ADS_FILE):
        try:
            with open(SEEN_ADS_FILE, "r", encoding="utf-8") as f:
                return list(json.load(f))
        except Exception:
            return []
    return []


def save_seen_ads(seen_list):
    trimmed = seen_list[-2000:]
    with open(SEEN_ADS_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def mark_seen(seen_list, seen_set, ad_id):
    if ad_id not in seen_set:
        seen_set.add(ad_id)
        seen_list.append(ad_id)


def send_telegram(html_text, ad_url, photo_urls=None):
    photo_urls = [p for p in (photo_urls or []) if p and p.startswith("http")][:10]
    reply_markup = {
        "inline_keyboard": [
            [{"text": "🔗 Открыть объявление", "url": ad_url}]
        ]
    }

    # 1. Если фотографий несколько (от 2 до 10) — отправляем альбомом
    if len(photo_urls) >= 2:
        media_endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
        caption_with_link = f'{html_text[:900]}\n\n👉 <a href="{html.escape(ad_url)}"><b>ОТКРЫТЬ ОБЪЯВЛЕНИЕ</b></a>'
        media_group = []
        for idx, p_url in enumerate(photo_urls):
            item = {"type": "photo", "media": p_url}
            if idx == 0:
                item["caption"] = caption_with_link
                item["parse_mode"] = "HTML"
            media_group.append(item)

        try:
            resp = requests.post(
                media_endpoint,
                json={"chat_id": TELEGRAM_CHAT_ID, "media": media_group},
                timeout=20,
            )
            if resp.status_code == 200:
                return
            print(f"sendMediaGroup не сработал ({resp.status_code}), пробую одно фото...")
        except Exception as e:
            print(f"Ошибка sendMediaGroup: {e}")

    # 2. Если фото одно (или альбом не прошёл) — отправляем с большой кнопкой
    if len(photo_urls) >= 1:
        photo_endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": photo_urls[0],
            "caption": html_text[:1000],
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }
        try:
            resp = requests.post(photo_endpoint, json=payload, timeout=15)
            if resp.status_code == 200:
                return
        except Exception as e:
            print(f"Ошибка sendPhoto: {e}")

    # 3. Запасной вариант без фото — текст + кнопка
    msg_endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": reply_markup,
    }
    try:
        resp = requests.post(msg_endpoint, json=payload, timeout=15)
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


def is_urgent_or_bargain(text):
    text_l = text.lower()
    return any(w in text_l for w in URGENT_WORDS)


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


def format_and_send(
    model,
    price_str,
    memory,
    condition,
    city,
    pub_date,
    url,
    seller_info="",
    photo_urls=None,
    urgent=False,
):
    checklist = get_checklist(model)
    header = "🔥 <b>СРОЧНО / ТОРГ! Новое объявление!</b>\n\n" if urgent else "📱 <b>Найдено новое объявление!</b>\n\n"
    seller_line = f"{html.escape(seller_info)}\n" if seller_info else ""
    msg = (
        f"{header}"
        f"<b>Модель:</b> {html.escape(model)}\n"
        f"<b>Цена:</b> {html.escape(price_str)}\n"
        f"<b>Память:</b> {html.escape(memory)}\n"
        f"<b>Состояние:</b> {html.escape(condition)}\n"
        f"{seller_line}"
        f"<b>Город:</b> {html.escape(city)}\n"
        f"<b>Дата публикации:</b> {html.escape(pub_date)}\n\n"
        f"<b>Дополнительно:</b> {html.escape(checklist)}"
    )
    send_telegram(msg, url, photo_urls)


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

                # Собираем ВСЕ фото из объявления OLX (до 10 штук)
                photo_urls = []
                for p in offer.get("photos", [])[:10]:
                    raw_photo = p.get("link", "")
                    if raw_photo:
                        photo_urls.append(
                            raw_photo.replace("{width}", "1000").replace("{height}", "1000")
                        )

                # Проверка продавца и OLX Доставки
                is_business = offer.get("business", False)
                seller_type = "Магазин / Бизнес" if is_business else "Частное лицо"
                has_delivery = offer.get("delivery", {}).get("rock", {}).get("active", False)
                delivery_str = "✅ OLX Доставка" if has_delivery else "❌ Без OLX Доставки"

                user_created = offer.get("user", {}).get("created", "")
                is_new_account = False
                reg_str = ""
                if user_created and len(user_created) >= 10:
                    reg_str = f" (на OLX с {user_created[:7]})"
                    try:
                        reg_date = datetime.strptime(user_created[:10], "%Y-%m-%d")
                        if (datetime.now() - reg_date).days < 30:
                            is_new_account = True
                    except Exception:
                        pass

                seller_info = f"Продавец: {seller_type}{reg_str} | {delivery_str}"
                if is_new_account and not has_delivery and not is_business:
                    seller_info += "\n⚠️ ВНИМАНИЕ: Новый аккаунт без OLX Доставки!"

                loc = offer.get("location", {})
                city = loc.get("city", {}).get("name", "Украина")
                created_time = offer.get("created_time", "")[:16].replace("T", " ") or "Сегодня"
                full_text = f"{title} {description}"

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(full_text),
                    summarize_condition(description),
                    city,
                    created_time,
                    full_url,
                    seller_info,
                    photo_urls,
                    is_urgent_or_bargain(full_text),
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

                photo_urls = []
                for img in container.find_all("img"):
                    src = img.get("data-src") or img.get("src")
                    if src and src.startswith("http") and src not in photo_urls:
                        photo_urls.append(src)

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(card_text),
                    summarize_condition(card_text),
                    "Украина (Shafa)",
                    "Сегодня",
                    full_url,
                    photo_urls=photo_urls,
                    urgent=is_urgent_or_bargain(card_text),
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

                photo_urls = []
                for img in card.find_all("img"):
                    src = img.get("data-src") or img.get("src")
                    if src and src.startswith("http") and src not in photo_urls:
                        photo_urls.append(src)

                price_formatted = f"{price:,} грн".replace(",", " ")
                format_and_send(
                    exact_model,
                    price_formatted,
                    extract_memory(title),
                    "Б/у или уценка (см. описание по ссылке)",
                    "Украина (Prom.ua)",
                    "Сегодня",
                    full_url,
                    photo_urls=photo_urls,
                    urgent=is_urgent_or_bargain(title),
                )
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"Prom error: {e}")
    return count


# === 4. ПРОВЕРКА TELEGRAM-БАРАХОЛОК (ГРН + $) ===
def check_telegram_channels(seen_list, seen_set, usd_rate):
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

                post_text = text_el
