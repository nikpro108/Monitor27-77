import json
import os
import re
import cloudscraper
from bs4 import BeautifulSoup
import requests

TELEGRAM_BOT_TOKEN = "9272449199:AAFIbkYxsYgx52VEzkPgjsQ_raq8Ky8lnxM"
TELEGRAM_CHAT_ID = "5563031715"

MAX_PRICE = 20000
SEEN_ADS_FILE = "seen_ads.json"

EXCLUDE_WORDS = [
    "s24+",
    "s24 plus",
    "15 pro max",
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
]

SEARCH_URLS = [
    "https://www.olx.ua/d/uk/elektronika/telefony-i-accessories/mobilnye-telefony-smartfony/q-s24-ultra/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:to%5D=19999",
    "https://www.olx.ua/d/uk/elektronika/telefony-i-accessories/mobilnye-telefony-smartfony/q-iphone-14-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:to%5D=19999",
    "https://www.olx.ua/d/uk/elektronika/telefony-i-accessories/mobilnye-telefony-smartfony/q-iphone-15-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:to%5D=19999",
]

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)


def load_seen_ads():
    if os.path.exists(SEEN_ADS_FILE):
        try:
            with open(SEEN_ADS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen_ads(seen_set):
    with open(SEEN_ADS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, ensure_ascii=False, indent=2)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    requests.post(url, json=payload, timeout=15)


def detect_exact_model(title, description=""):
    text = f"{title} {description}".lower()
    if any(w in text for w in EXCLUDE_WORDS):
        return None

    if "s24 ultra" in text:
        return "Samsung Galaxy S24 Ultra"
    if "15 pro" in text and "15 pro max" not in text:
        return "Apple iPhone 15 Pro"
    if "14 pro max" in text:
        return "Apple iPhone 14 Pro Max"
    if "14 pro" in text and "14 pro max" not in text:
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


def inspect_ad_page(url):
    try:
        resp = scraper.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text(" ", strip=True).lower()
        if (
            "це оголошення більше не доступне" in page_text
            or "это объявление больше не доступно" in page_text
        ):
            return None

        desc_elem = soup.find("div", {"data-cy": "ad_description"})
        return desc_elem.get_text(" ", strip=True) if desc_elem else ""
    except Exception:
        return None


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
    return (
        description[:140] + "..."
        if len(description) > 140
        else (description or "См. описание по ссылке")
    )


def run():
    seen_ads = load_seen_ads()
    new_found = 0

    for search_url in SEARCH_URLS:
        try:
            resp = scraper.get(search_url, timeout=20)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", {"data-cy": "l-card"})

            for card in cards:
                link_elem = card.find("a", href=True)
                if not link_elem:
                    continue

                href = link_elem["href"]
                full_url = "https://www.olx.ua" + href if href.startswith("/") else href
                ad_id = (
                    href.split("-ID")[-1].replace(".html", "")
                    if "-ID" in href
                    else full_url
                )

                if ad_id in seen_ads:
                    continue

                title_elem = card.find("h6") or card.find("h4")
                title = (
                    title_elem.get_text(strip=True)
                    if title_elem
                    else link_elem.get_text(strip=True)
                )

                price_elem = card.find("p", {"data-testid": "ad-price"})
                if not price_elem:
                    continue
                price_digits = re.sub(r"\D", "", price_elem.get_text())
                if not price_digits:
                    continue
                price = int(price_digits)

                if price >= MAX_PRICE or price < 2000:
                    seen_ads.add(ad_id)
                    continue

                if not detect_exact_model(title):
                    seen_ads.add(ad_id)
                    continue

                description = inspect_ad_page(full_url)
                if description is None:
                    continue

                exact_model = detect_exact_model(title, description)
                if not exact_model:
                    seen_ads.add(ad_id)
                    continue

                loc_elem = card.find("p", {"data-testid": "location-date"})
                loc_text = (
                    loc_elem.get_text(strip=True) if loc_elem else "Украина - Сегодня"
                )
                parts = loc_text.split("-")
                city = parts[0].strip()
                pub_date = parts[-1].strip() if len(parts) > 1 else "Сегодня"

                memory = extract_memory(f"{title} {description}")
                condition = summarize_condition(description)
                checklist = get_checklist(exact_model)

                msg = (
                    f"📱 Найдено новое объявление!\n\n"
                    f"Модель: {exact_model}\n"
                    f"Цена: {price:,} грн\n".replace(",", " ")
                    + f"Память: {memory}\n"
                    f"Состояние: {condition}\n"
                    f"Город: {city}\n"
                    f"Дата публикации: {pub_date}\n\n"
                    f"Ссылка: {full_url}\n\n"
                    f"Дополнительно: {checklist}"
                )

                send_telegram(msg)
                seen_ads.add(ad_id)
                new_found += 1

        except Exception as e:
            print(f"Ошибка: {e}")

    save_seen_ads(seen_ads)
    print(f"Готово. Новых: {new_found}")


if __name__ == "__main__":
    run()
      
