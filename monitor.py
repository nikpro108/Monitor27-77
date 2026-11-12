from datetime import datetime
import html, json, os, re, cloudscraper, requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = "9272449199:AAFIbkYxsYgx52VEzkPgjsQ_raq8Ky8lnxM"
TELEGRAM_CHAT_ID = "5563031715"
MAX_PRICE = 20000
FALLBACK_USD_RATE = 42.0
SEEN_ADS_FILE = "seen_ads.json"

TELEGRAM_CHANNELS = [
    "baraholka_ua_tech", "iphone_baraholka_ua", "apple_baraholka_ukraine",
    "baraholka_kiev_ua", "tehnika_bu_ua",
]

EXCLUDE_WORDS = [
    "s24+", "s24 plus", "с24+", "с24 плюс", "15 pro max", "15 про макс",
    "replica", "копия", "копія", "реплика", "репліка", "чехол", "чохол",
    "стекло", "скло", "коробка", "муляж", "дисплей", "экран", "екран",
    "плата", "на запчасти", "на запчастини", "куплю", "скупка",
    "в кредит", "кредит", "рассрочк", "розстрочк", "первый взнос",
    "перший внесок", "оплата частями", "оплата частинами",
]

URGENT_WORDS = ["срочно", "терміново", "торг", "швидко", "быстро"]

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

scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})


def get_live_usd_rate():
    try:
        r = requests.get("https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5", timeout=6)
        if r.status_code == 200:
            for item in r.json():
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
    with open(SEEN_ADS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_list[-2000:], f, ensure_ascii=False, indent=2)


def mark_seen(seen_list, seen_set, ad_id):
    if ad_id not in seen_set:
        seen_set.add(ad_id)
        seen_list.append(ad_id)


def send_telegram(html_text, ad_url, photo_urls=None):
    photos = [p for p in (photo_urls or []) if p and p.startswith("http")][:10]
    markup = {"inline_keyboard": [[{"text": "🔗 Открыть объявление", "url": ad_url}]]}

    if len(photos) >= 2:
        cap = f'{html_text[:900]}\n\n👉 <a href="{html.escape(ad_url)}"><b>ОТКРЫТЬ ОБЪЯВЛЕНИЕ</b></a>'
        media = [{"type": "photo", "media": u, **({"caption": cap, "parse_mode": "HTML"} if i == 0 else {})} for i, u in enumerate(photos)]
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup", json={"chat_id": TELEGRAM_CHAT_ID, "media": media}, timeout=20)
            if r.status_code == 200:
                return
        except Exception:
            pass

    if len(photos) >= 1:
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", json={"chat_id": TELEGRAM_CHAT_ID, "photo": photos[0], "caption": html_text[:1000], "parse_mode": "HTML", "reply_markup": markup}, timeout=15)
            if r.status_code == 200:
                return
        except Exception:
            pass

    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": html_text, "parse_mode": "HTML", "reply_markup": markup}, timeout=15)
    except Exception as e:
        print(f"TG error: {e}")


def detect_exact_model(title, description=""):
    t = f"{title} {description}".lower()
    if any(w in t for w in EXCLUDE_WORDS):
        return None
    if any(k in t for k in ("s24 ultra", "с24 ультра", "s24 ультра")):
        return "Samsung Galaxy S24 Ultra"
    if ("15 pro" in t or "15 про" in t) and "15 pro max" not in t and "15 про макс" not in t:
        return "Apple iPhone 15 Pro"
    if "14 pro max" in t or "14 про макс" in t:
        return "Apple iPhone 14 Pro Max"
    if ("14 pro" in t or "14 про" in t) and "14 pro max" not in t and "14 про макс" not in t:
        return "Apple iPhone 14 Pro"
    return None


def extract_memory(text):
    m = re.search(r"\b(128|256|512|1\s?tb|1\s?тб|12/256|12/512|12/1)\b", text.lower())
    if m:
        val = m.group(0).upper().replace(" ", "")
        return val if any(x in val for x in ("/", "TB", "ТБ")) else f"{val} ГБ"
    return "Не указано"


def summarize_condition(desc):
    dl = desc.lower()
    kw = {
        "царапин": "царапины", "подряпин": "царапины", "потерт": "потёртости",
        "скол": "сколы", "трещин": "трещины", "тріщин": "трещины",
        "разбит": "разбит экран/корпус", "розбит": "разбит экран/корпус",
        "выгоран": "выгорание экрана", "вигоран": "выгорание экрана",
        "полос": "полосы на экране", "не работает": "есть неисправности",
        "не працює": "есть неисправности", "face id": "упоминается Face ID",
        "icloud": "проверить блокировку iCloud", "mdm": "MDM-профиль",
        "r-sim": "R-Sim / залочен", "идеал": "состояние близкое к идеальному",
        "ідеал": "состояние близкое к идеальному",
    }
    issues = list(dict.fromkeys(v for k, v in kw.items() if k in dl))
    if issues:
        return ", ".join(issues).capitalize()
    clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", desc)).strip()
    return clean[:140] + "..." if len(clean) > 140 else (clean or "См. описание по ссылке")


def format_and_send(model, price_str, memory, condition, city, pub_date, url, seller_info="", photo_urls=None, urgent=False):
    check = "Проверить iCloud (сброс при встрече), АКБ, Face ID, True Tone и отсутствие MDM." if "iPhone" in model else "Проверить Knox (0x0), стилус S-Pen, экран на выгорание и оригинальность."
    head = "🔥 <b>СРОЧНО / ТОРГ! Новое объявление!</b>\n\n" if urgent else "📱 <b>Найдено новое объявление!</b>\n\n"
    s_line = f"{html.escape(seller_info)}\n" if seller_info else ""
    msg = (
        f"{head}<b>Модель:</b> {html.escape(model)}\n<b>Цена:</b> {html.escape(price_str)}\n"
        f"<b>Память:</b> {html.escape(memory)}\n<b>Состояние:</b> {html.escape(condition)}\n{s_line}"
        f"<b>Город:</b> {html.escape(city)}\n<b>Дата публикации:</b> {html.escape(pub_date)}\n\n"
        f"<b>Дополнительно:</b> {html.escape(check)}"
    )
    send_telegram(msg, url, photo_urls)


def check_olx_api(seen_list, seen_set):
    count = 0
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    for api_url in OLX_API_QUERIES:
        try:
            r = scraper.get(api_url, headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            for offer in r.json().get("data", []):
                raw_id = str(offer.get("id", ""))
                ad_id = f"olx_{raw_id}"
                if not raw_id or ad_id in seen_set:
                    continue
                if offer.get("status") != "active":
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                title, desc = offer.get("title", ""), offer.get("description", "")
                url = offer.get("url", f"https://www.olx.ua/d/uk/obyavlenie/-ID{raw_id}.html")
                price = next((int(float(p.get("value", {}).get("value", 0))) for p in offer.get("params", []) if p.get("key") == "price"), 0)
                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                model = detect_exact_model(title, desc)
                if not model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue

                photos = [p["link"].replace("{width}", "1000").replace("{height}", "1000") for p in offer.get("photos", [])[:10] if p.get("link")]
                is_biz = offer.get("business", False)
                has_del = offer.get("delivery", {}).get("rock", {}).get("active", False)
                u_created = offer.get("user", {}).get("created", "")
                reg_str, is_new = "", False
                if len(u_created) >= 10:
                    reg_str = f" (на OLX с {u_created[:7]})"
                    try:
                        is_new = (datetime.now() - datetime.strptime(u_created[:10], "%Y-%m-%d")).days < 30
                    except Exception:
                        pass
                s_info = f"Продавец: {'Магазин' if is_biz else 'Частное лицо'}{reg_str} | {'✅ OLX Доставка' if has_del else '❌ Без OLX Доставки'}"
                if is_new and not has_del and not is_biz:
                    s_info += "\n⚠️ ВНИМАНИЕ: Новый аккаунт без OLX Доставки!"

                city = offer.get("location", {}).get("city", {}).get("name", "Украина")
                c_time = offer.get("created_time", "")[:16].replace("T", " ") or "Сегодня"
                ft = f"{title} {desc}"
                format_and_send(model, f"{price:,} грн".replace(",", " "), extract_memory(ft), summarize_condition(desc), city, c_time, url, s_info, photos, any(w in ft.lower() for w in URGENT_WORDS))
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"OLX error: {e}")
    return count


def check_shafa(seen_list, seen_set):
    count = 0
    for url in SHAFA_URLS:
        try:
            r = scraper.get(url, timeout=20)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/uk/elektronika/" not in href or not re.search(r"/\d+-", href):
                    continue
                full_url = "https://shafa.ua" + href if href.startswith("/") else href
                ad_id = f"shafa_{href.split('/')[-1].split('-')[0]}"
                if ad_id in seen_set:
                    continue
                box = a
                for _ in range(3):
                    if box.parent and len(box.parent.get_text(strip=True)) < 500:
                        box = box.parent
                txt = box.get_text(" ", strip=True)
                model = detect_exact_model(txt)
                if not model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                pm = re.search(r"(\d[\d\s]{2,6})\s*грн", txt)
                if not pm:
                    continue
                price = int(re.sub(r"\D", "", pm.group(1)))
                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                photos = list(dict.fromkeys(img.get("data-src") or img.get("src") for img in box.find_all("img") if (img.get("data-src") or img.get("src") or "").startswith("http")))
                format_and_send(model, f"{price:,} грн".replace(",", " "), extract_memory(txt), summarize_condition(txt), "Украина (Shafa)", "Сегодня", full_url, photo_urls=photos, urgent=any(w in txt.lower() for w in URGENT_WORDS))
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"Shafa error: {e}")
    return count


def check_prom(seen_list, seen_set):
    count = 0
    for url in PROM_URLS:
        try:
            r = scraper.get(url, timeout=20)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.find_all("div", {"data-qaid": "product_block"}):
                a = card.find("a", {"data-qaid": "product_link"}, href=True)
                if not a:
                    continue
                href = a["href"]
                full_url = "https://prom.ua" + href if href.startswith("/") else href
                ad_id = f"prom_{href.split('/')[-1][:30]}"
                if ad_id in seen_set:
                    continue
                title = a.get_text(" ", strip=True)
                model = detect_exact_model(title)
                if not model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                pe = card.find(attrs={"data-qaid": "product_price"})
                digits = re.sub(r"\D", "", pe.get_text()) if pe else ""
                if not digits:
                    continue
                price = int(digits)
                if price >= MAX_PRICE or price < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                photos = list(dict.fromkeys(img.get("data-src") or img.get("src") for img in card.find_all("img") if (img.get("data-src") or img.get("src") or "").startswith("http")))
                format_and_send(model, f"{price:,} грн".replace(",", " "), extract_memory(title), "Б/у или уценка (см. описание)", "Украина (Prom.ua)", "Сегодня", full_url, photo_urls=photos, urgent=any(w in title.lower() for w in URGENT_WORDS))
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"Prom error: {e}")
    return count


def check_telegram_channels(seen_list, seen_set, usd_rate):
    count = 0
    for ch in TELEGRAM_CHANNELS:
        try:
            r = requests.get(f"https://t.me/s/{ch}", timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for box in soup.find_all("div", class_="tgme_widget_message"):
                post = box.get("data-post")
                ad_id = f"tg_{post}"
                if not post or ad_id in seen_set:
                    continue
                te = box.find("div", class_="tgme_widget_message_text")
                if not te:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                txt = te.get_text(" ", strip=True)
                model = detect_exact_model(txt)
                if not model:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                tl = txt.lower()
                um = re.search(r"\b(\d{1,2}[\s.,]?\d{3})\s*(?:грн|uah|₴)", tl)
                dm = re.search(r"(?:\$\s*(\d{3})|\b(\d{3})\s*(?:\$|usd|у\.е\.|уе|дол))", tl)
                if um:
                    uah = int(re.sub(r"\D", "", um.group(1)))
                    p_disp = f"{uah:,} грн".replace(",", " ")
                elif dm:
                    usd = int(dm.group(1) or dm.group(2))
                    uah = int(usd * usd_rate)
                    p_disp = f"{usd}$ (~{uah:,} грн)".replace(",", " ")
                else:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                if uah >= MAX_PRICE or uah < 2000:
                    mark_seen(seen_list, seen_set, ad_id)
                    continue
                photos = []
                for pw in box.find_all("a", class_="tgme_widget_message_photo_wrap"):
                    m = re.search(r"url\(['\"]?(https?://[^'\")]+)['\"]?\)", pw.get("style", ""))
                    if m and m.group(1) not in photos:
                        photos.append(m.group(1))
                format_and_send(model, p_disp, extract_memory(txt), summarize_condition(txt), f"Telegram (@{ch})", "Сегодня", f"https://t.me/{post}", photo_urls=photos, urgent=any(w in tl for w in URGENT_WORDS))
                mark_seen(seen_list, seen_set, ad_id)
                count += 1
        except Exception as e:
            print(f"TG {ch} error: {e}")
    return count


def run():
    seen_list = load_seen_ads()
    seen_set = set(seen_list)
    rate = get_live_usd_rate()
    total = (
        check_olx_api(seen_list, seen_set)
        + check_shafa(seen_list, seen_set)
        + check_prom(seen_list, seen_set)
        + check_telegram_channels(seen_list, seen_set, rate)
    )
    save_seen_ads(seen_list)
    print(f"Готово (USD: {rate}). Новых: {total}")


if __name__ == "__main__":
    run()
    
