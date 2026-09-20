"""Роль: единственное место со настройками — токены, адреса сайта, лимиты.

Кто читает: все остальные модули (`from . import config`).
Что править здесь: разделы сайта, шаблон картинки, пороги и паузы.
Чего здесь нет: логики. Только значения и две функции про chat id.

Секреты сюда не пишутся руками: токен приходит из .env (локально)
или из Secrets репозитория (на GitHub).
"""
import os
import re

from dotenv import load_dotenv

load_dotenv()


def env_int(name: str, default: int) -> int:
    """Число из .env, терпимое к мусору вокруг значения."""
    digits = re.match(r"-?\d+", (os.getenv(name) or "").strip())
    return int(digits.group()) if digits else default


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = env_int("CHAT_ID", 0)
INTERVAL_MIN = env_int("INTERVAL_MIN", 60)
MIN_DISCOUNT = env_int("MIN_DISCOUNT", 0)  # шлём только от N% скидки
# Сколько карточек показать в витрине по /start. Придёт не больше этого числа,
# а может и меньше: товары без размеров в наличии витрина пропускает.
START_ITEMS = env_int("START_ITEMS", 5)
# Кому отвечает /who. По умолчанию — владелец из CHAT_ID.
ADMIN_ID = env_int("ADMIN_ID", 0)
# Сколько последних пользователей показывать в /who.
USERS_SHOWN = env_int("USERS_SHOWN", 10)
# Сколько готовых карточек держать в витрине про запас.
DEALS_KEEP = env_int("DEALS_KEEP", 50)
DB_PATH = os.getenv("DB_PATH") or "data/puma.db"
CHAT_ID_PATH = "chat_id.txt"

BASE = "https://ua.puma.com"
# Распродажа, разрезанная по обуви — намного короче, чем общая /uk/skidki.html
SALE_URLS = [
    BASE + "/uk/skidki/muzhchiny/obuv.html",
    BASE + "/uk/skidki/zhenschiny/obuv.html",
]
IMG = ("https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:fafafa"
       "/global/{model}/{color}/sv01/fnd/UKR/w/1000/h/1000/fmt/png")
MAX_PAGES = 40
# Пауза между карточками. Телеграм пропускает примерно одно сообщение в секунду
# на чат, поэтому ровно 1.0 — по границе; 1.5 держит запас от ошибки 429.
SEND_PAUSE_SEC = 1.5
# Пауза между запросами к сайту, чтобы не долбить Пуму очередями.
PAGE_PAUSE_SEC = 0.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9",
}


def load_chat_id() -> int:
    """chat id владельца: из .env, иначе из отдельного файла chat_id.txt.
    В .env бот не пишет никогда — там лежит токен, и рисковать им нельзя.
    Остальные получатели живут в базе, см. storage.subscribers."""
    if CHAT_ID:
        return CHAT_ID
    try:
        with open(CHAT_ID_PATH, encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def admin_id() -> int:
    """Кому можно /who: ADMIN_ID, иначе владелец из CHAT_ID."""
    return ADMIN_ID or load_chat_id()
