"""Puma UA: кроссовки со скидкой -> Telegram.

Источник: ua.puma.com, разделы «скидки -> обувь» (мужская и женская).
Шлёт фото, цену, старую цену, процент, цвет и размеры в наличии.
Повторы отсекаются по SQLite: товар уходит в телегу один раз,
и ещё раз — только если цена упала ниже прошлой.

Запуск:
    python bot.py          — живёт постоянно, проверяет раз в INTERVAL_MIN минут
    python bot.py --once   — одна проверка и выход (для GitHub Actions / cron)
"""
import asyncio
import html
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass

import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
def env_int(name: str, default: int) -> int:
    """Число из .env, терпимое к мусору вокруг значения."""
    digits = re.match(r"-?\d+", (os.getenv(name) or "").strip())
    return int(digits.group()) if digits else default


CHAT_ID = env_int("CHAT_ID", 0)
INTERVAL_MIN = env_int("INTERVAL_MIN", 60)
DB_PATH = os.getenv("DB_PATH") or "puma.db"
CHAT_ID_PATH = "chat_id.txt"
MIN_DISCOUNT = env_int("MIN_DISCOUNT", 0)  # шлём только от N% скидки

BASE = "https://ua.puma.com"
# Распродажа, разрезанная по обуви — намного короче, чем общая /uk/skidki.html
SALE_URLS = [
    BASE + "/uk/skidki/muzhchiny/obuv.html",
    BASE + "/uk/skidki/zhenschiny/obuv.html",
]
IMG = ("https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:fafafa"
       "/global/{model}/{color}/sv01/fnd/UKR/w/1000/h/1000/fmt/png")
MAX_PAGES = 40
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9",
}

log = logging.getLogger("puma")
checking = asyncio.Lock()  # чтобы два обхода не шли внахлёст


@dataclass
class Item:
    sku: str
    name: str
    url: str
    price: int
    old_price: int

    @property
    def discount(self) -> int:
        return round((1 - self.price / self.old_price) * 100) if self.old_price else 0

    @property
    def image(self) -> str:
        model, _, color = self.sku.partition("_")
        return IMG.format(model=model, color=color)


def amount(el, price_type: str) -> int:
    p = el.select_one(f'[data-price-type="{price_type}"]')
    try:
        return round(float(p["data-price-amount"])) if p else 0
    except (KeyError, ValueError):
        return 0


def is_sneakers(name: str) -> bool:
    n = name.lower()
    return "кросівки" in n or "кеди" in n


def parse_listing(page_html: str) -> list[Item]:
    soup = BeautifulSoup(page_html, "html.parser")
    items = []
    for el in soup.select(".product-item[data-product-sku]"):
        name = el.get("data-product-name", "")
        if not is_sneakers(name):
            continue
        price = amount(el, "finalPrice")
        old = amount(el, "oldPrice")
        if not price or not old or price >= old:
            continue
        link = el.select_one("a.product-item__img-w") or el.select_one("a")
        if not link:
            continue
        items.append(Item(el["data-product-sku"], name, link["href"], price, old))
    return items


def parse_product(page_html: str) -> dict:
    """Размеры в наличии и цвет. Цвет берём из <title>:
    'Кросівки X | Колір: Білий | Warm White-Alpine Snow | Puma'."""
    soup = BeautifulSoup(page_html, "html.parser")
    sizes = []
    for li in soup.select(".size-list__item[data-label]"):
        if li.get("data-available") == "1" and "unavailable" not in li.get("class", []):
            label = li["data-label"]
            if label not in sizes:
                sizes.append(label)

    color = ""
    title = soup.title.get_text() if soup.title else ""
    m = re.search(r"Колір:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", title)
    if m:
        color = f"{m.group(2)} ({m.group(1).lower()})"
    else:
        m = re.search(r'"color"\s*:\s*"([^"]+)"', page_html)
        color = m.group(1) if m else "—"
    return {"sizes": sizes, "color": color}


async def fetch_sale(client: httpx.AsyncClient) -> list[Item]:
    found: dict[str, Item] = {}
    for url in SALE_URLS:
        seen_skus: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            r = await client.get(url, params={"p": page})
            r.raise_for_status()
            page_skus = set(re.findall(r'data-product-sku="([^"]+)"[^>]*data-product-item', r.text))
            if not page_skus - seen_skus:  # пусто или повтор последней страницы — конец
                break
            seen_skus |= page_skus
            for it in parse_listing(r.text):
                found.setdefault(it.sku, it)
            log.info("%s p%d: всего кроссовок со скидкой %d",
                     url.rsplit("/", 2)[-2], page, len(found))
            await asyncio.sleep(0.5)
    return list(found.values())


def db_init() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS seen (sku TEXT PRIMARY KEY, price INTEGER, ts REAL)")
    db.commit()
    return db


def money(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₴"


def caption(it: Item, info: dict, reason: str) -> str:
    sizes = ", ".join(info["sizes"]) if info["sizes"] else "нет в наличии"
    return (
        f"<b>{html.escape(it.name, quote=False)}</b>\n"
        f"{reason}\n"
        f"Цена: <b>{money(it.price)}</b> <s>{money(it.old_price)}</s> (-{it.discount}%)\n"
        f"Цвет: {html.escape(info['color'], quote=False)}\n"
        f"Размеры: {sizes}\n"
        f'<a href="{it.url}">Открыть на puma.com</a>'
    )


async def send(bot: Bot, chat_id: int, it: Item, info: dict, reason: str) -> None:
    text = caption(it, info, reason)
    try:
        await bot.send_photo(chat_id, it.image, caption=text, parse_mode="HTML")
    except Exception as e:  # телега не смогла забрать картинку — шлём текстом
        log.warning("фото не ушло (%s), шлю текстом", e)
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def send_top(bot: Bot, chat_id: int, limit: int = 10) -> int:
    """Прислать первые скидки так, как их показывает сам сайт на первой странице.
    Даты у товаров на сайте нет, поэтому «последние» — это его собственный порядок."""
    db = db_init()
    sent = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        items: list[Item] = []
        seen: set[str] = set()
        for url in SALE_URLS:
            r = await client.get(url, params={"p": 1})
            for it in parse_listing(r.text):
                if it.sku not in seen:
                    seen.add(it.sku)
                    items.append(it)
        for it in items:
            if sent >= limit:
                break
            pr = await client.get(it.url)
            info = parse_product(pr.text)
            if not info["sizes"]:
                continue
            await send(bot, chat_id, it, info, "Сейчас на распродаже")
            db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)",
                       (it.sku, it.price, time.time()))
            sent += 1
            await asyncio.sleep(1)
        db.commit()
    return sent


async def check(bot: Bot, chat_id: int) -> int:
    async with checking:
        return await _check(bot, chat_id)


async def _check(bot: Bot, chat_id: int) -> int:
    db = db_init()
    sent = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        items = await fetch_sale(client)
        log.info("кроссовок со скидкой: %d", len(items))
        first_run = db.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
        for it in items:
            row = db.execute("SELECT price FROM seen WHERE sku=?", (it.sku,)).fetchone()
            if row and it.price >= row[0]:
                continue
            db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)",
                       (it.sku, it.price, time.time()))
            if first_run or it.discount < MIN_DISCOUNT:
                continue
            r = await client.get(it.url)
            info = parse_product(r.text)
            if not info["sizes"]:
                continue  # нет ни одного размера — слать нечего
            reason = "Новая скидка" if not row else f"Цена упала (было {money(row[0])})"
            await send(bot, chat_id, it, info, reason)
            sent += 1
            await asyncio.sleep(1)
        db.commit()
        if first_run:
            await bot.send_message(
                chat_id,
                f"Запомнил {len(items)} кроссовок со скидкой. Дальше приходит только новое "
                f"или подешевевшее — сам проверяю раз в {INTERVAL_MIN} минут.")
    return sent


def load_chat_id() -> int:
    """chat id из .env, иначе из отдельного файла, который бот пишет сам.
    В .env бот не пишет никогда — там лежит токен, и рисковать им нельзя."""
    if CHAT_ID:
        return CHAT_ID
    try:
        with open(CHAT_ID_PATH, encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def save_chat_id(chat_id: int) -> None:
    with open(CHAT_ID_PATH, "w", encoding="utf-8") as f:
        f.write(str(chat_id))


async def loop(bot: Bot):
    while True:
        try:
            await check(bot, CHAT_ID)
        except Exception:
            log.exception("проверка сорвалась")
        await asyncio.sleep(INTERVAL_MIN * 60)


async def run_once():
    bot = Bot(BOT_TOKEN)
    try:
        n = await check(bot, CHAT_ID)
        log.info("отправлено: %d", n)
    finally:
        await bot.session.close()


async def run_forever():
    global CHAT_ID
    CHAT_ID = load_chat_id()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(m: Message):
        global CHAT_ID
        if CHAT_ID and m.chat.id != CHAT_ID:
            return
        first_time = not CHAT_ID
        if first_time:
            CHAT_ID = m.chat.id
            save_chat_id(CHAT_ID)
        await m.answer("Показываю 10 кроссовок с распродажи. Дальше буду присылать новые "
                       "скидки сам, тыкать ничего не надо.")
        n = await send_top(bot, CHAT_ID, 10)
        if not n:
            await m.answer("Не смог достать товары с сайта, загляни в bot_log.txt.")
        if first_time:
            asyncio.create_task(loop(bot))

    if CHAT_ID:
        asyncio.create_task(loop(bot))
    else:
        log.warning("CHAT_ID пуст: напиши боту /start, он сам всё настроит")
    await dp.start_polling(bot)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN. Вставь токен от @BotFather в файл .env и запусти снова.")
    if "--once" in sys.argv:
        globals()["CHAT_ID"] = load_chat_id()
        if not CHAT_ID:
            raise SystemExit("Нет CHAT_ID — режиму --once он обязателен.")
        asyncio.run(run_once())
    else:
        asyncio.run(run_forever())


if __name__ == "__main__":
    main()
