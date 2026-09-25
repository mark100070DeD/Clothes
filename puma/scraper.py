"""Роль: единственный файл, который знает, как устроены страницы Puma.

Кто вызывает: checker.py (полный обход) и sender.py (первая страница для витрины).
Что править здесь: если Пума поменяла вёрстку и бот перестал видеть товары,
размеры или цвет — чинить надо ТОЛЬКО этот файл, остальные не знают про HTML.

За что отвечает каждая функция:
  parse_listing   страница списка -> список Item (кроссовки, не детские, со скидкой)
  parse_product   страница товара -> размеры в наличии и цвет
  fetch_sale      обойти оба раздела по страницам (полный проход, раз в час)
  fetch_pages     первые страницы разделов в порядке сайта (выборка для сверки)

Кто ещё сюда ходит: audit.py — за выборкой живых цен для суточной сверки.

Опорные точки вёрстки, которые могут отвалиться:
  .product-item[data-product-sku]        карточка в списке
  [data-price-type="finalPrice"|"oldPrice"] + data-price-amount   цены
  .size-list__item[data-label][data-available]                    размеры
  <title> вида 'Кросівки X | Колір: Білий | Warm White | Puma'    цвет
"""
import asyncio
import logging
import random
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from . import config
from .models import Item

log = logging.getLogger("puma")

# Сколько раз повторить запрос, если Пума попросила подождать, и максимум
# ожидания. Больше трёх попыток нет смысла: прогон всё равно суточный,
# вернёмся завтра, а держать воркфлоу часами — только жечь минуты.
RETRIES = 3
RETRY_BASE_SEC = 5.0
RETRY_MAX_SEC = 120.0


def amount(el, price_type: str) -> int:
    p = el.select_one(f'[data-price-type="{price_type}"]')
    try:
        return round(float(p["data-price-amount"])) if p else 0
    except (KeyError, ValueError):
        return 0


def is_sneakers(name: str) -> bool:
    n = name.lower()
    return "кросівки" in n or "кеди" in n


# Детское. Проверено на живом каталоге 25.09.2026: из 586 кроссовок со скидкой
# 109 детских (toddler и infant по классификации Пумы), и это выражение ловит
# все 109, не задев ни одного взрослого.
#
# Границы слова для латиницы обязательны: без них под фильтр попадала
# коллаборация «PUMA x KIDSUPER» — взрослая обувь, в названии которой сидит
# «kids». С \b «kidsuper» не совпадает, потому что дальше идёт буква.
KIDS_RE = re.compile(r"дитяч|\b(kids?|babies|baby|toddler|infant|junior|jr)\b", re.I)


def is_kids(name: str) -> bool:
    return bool(KIDS_RE.search(name or ""))


def is_wanted(name: str) -> bool:
    """Берём ли мы этот товар вообще. Единственное место с этим правилом.

    Его двойник на JS — isWanted в worker/src/klevu.js. Расходиться им нельзя:
    суточная сверка сравнивает выборки обеих сторон и будет ругаться.
    """
    return is_sneakers(name) and not is_kids(name)


def parse_listing(page_html: str) -> list[Item]:
    soup = BeautifulSoup(page_html, "html.parser")
    items = []
    for el in soup.select(".product-item[data-product-sku]"):
        name = el.get("data-product-name", "")
        if not is_wanted(name):
            continue
        price = amount(el, "finalPrice")
        old = amount(el, "oldPrice")
        if not price or not old or price >= old:
            continue
        link = el.select_one("a.product-item__img-w") or el.select_one("a")
        if not link:
            continue
        # Сейчас Пума отдаёт полные адреса, но относительный href нас бы сломал.
        url = urljoin(config.BASE, link["href"])
        items.append(Item(el["data-product-sku"], name, url, price, old))
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


class BannedError(RuntimeError):
    """Сайт закрылся от бота (403). Обход надо прекратить, а не повторять."""


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=config.HEADERS, timeout=30, follow_redirects=True)


async def pause() -> None:
    """Пауза между запросами со случайной добавкой.

    Ровно 0.5 с между запросами — подпись автомата: живой человек так не ходит.
    Разброс стоит ноль и убирает самый очевидный признак.
    """
    await asyncio.sleep(config.PAGE_PAUSE_SEC + random.random() * config.PAGE_JITTER_SEC)


async def get(client: httpx.AsyncClient, url: str, **kw):
    """GET с разбором отказов. Единственная дверь к Пуме в этом файле.

    403  — бан. Поднимаем BannedError: продолжать долбить забаненным клиентом
           хуже, чем остановиться. Наверху это превратится в тревогу владельцу.
    429  — перегрузка. Ждём столько, сколько просят в Retry-After, и пробуем
           ещё раз. Три попытки, потом сдаёмся до следующего прогона.
    503  — то же самое: сайт жив, но сейчас не отвечает.
    """
    for attempt in range(RETRIES):
        r = await client.get(url, **kw)
        if r.status_code == 403:
            raise BannedError(f"Puma ответила 403 на {url}")
        if r.status_code in (429, 503):
            wait = _retry_after(r) or RETRY_BASE_SEC * (attempt + 1)
            log.warning("Puma ответила %d, жду %.0f с (попытка %d из %d)",
                        r.status_code, wait, attempt + 1, RETRIES)
            await asyncio.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Puma не ответила за {RETRIES} попыток: {url}")


def _retry_after(response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", "")), RETRY_MAX_SEC)
    except ValueError:
        return 0.0


async def fetch_sale(client: httpx.AsyncClient) -> list[Item]:
    """Обойти оба раздела распродажи по страницам и собрать все кроссовки со скидкой.

    Конец списка ищем по всем товарам страницы, а не только по кроссовкам:
    страница из одних сандалий — не повод считать, что раздел закончился.
    За последней страницей Пума отдаёт пустую сетку, на ней и останавливаемся.
    """
    found: dict[str, Item] = {}
    for url in config.SALE_URLS:
        seen_skus: set[str] = set()
        for page in range(1, config.MAX_PAGES + 1):
            r = await get(client, url, params={"p": page})
            page_skus = set(re.findall(r'data-product-sku="([^"]+)"[^>]*data-product-item', r.text))
            if not page_skus - seen_skus:  # пусто или повтор последней страницы — конец
                break
            seen_skus |= page_skus
            for it in parse_listing(r.text):
                found.setdefault(it.sku, it)
            log.info("%s p%d: всего кроссовок со скидкой %d",
                     url.rsplit("/", 2)[-2], page, len(found))
            await pause()
    return list(found.values())


async def fetch_pages(client: httpx.AsyncClient, pages: int = 1) -> list[Item]:
    """Первые `pages` страниц каждого раздела, в том порядке, как отдаёт сайт.

    Нужна суточной сверке: чтобы проверить, не застрял ли поисковый индекс,
    хватает выборки с первых страниц. Полный обход для этого слишком тяжёлый.
    """
    items: list[Item] = []
    seen: set[str] = set()
    for url in config.SALE_URLS:
        for page in range(1, pages + 1):
            r = await get(client, url, params={"p": page})
            found = parse_listing(r.text)
            new = [it for it in found if it.sku not in seen]
            if not new and page > 1:
                break  # страницы кончились или пошли повторы
            for it in new:
                seen.add(it.sku)
                items.append(it)
            await pause()
    return items
