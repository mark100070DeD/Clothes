"""Роль: второй источник товаров — каталог через поисковый индекс Пумы (Klevu).

Кто вызывает: audit.py (суточная сверка) и tests. Быстрый путь живёт в Worker,
у него своя копия на JS — worker/src/klevu.js. Правила отбора обязаны совпадать.

Зачем он есть. Страница списка Пумы весит ~950 КБ и отдаёт 36 товаров. Тот же
индекс отдаёт 1000 товаров за 248 КБ — в 100 раз плотнее на товар. Поэтому
весь каталог (5161 позиция) обходится шестью запросами вместо двадцати четырёх,
и обходить его можно хоть каждые три минуты.

Что здесь важно и легко сломать:
  term="*"          перечисляет ВЕСЬ индекс, а не «что нашлось по слову».
                    Поиск по словам неполон по определению — так терялись товары.
  fields=[...]      без него запись весит втрое больше: там 37 полей.
  limit=1000        проверенный потолок; 100 и 500 тоже работают.
  price/salePrice   ОСТОРОЖНО: price — это СТАРАЯ цена (до скидки),
                    salePrice — текущая. Наоборот, чем кажется по названию.

Чего здесь нет: размеров. Индекс отдаёт один вариант на цвет, поэтому размеры
берутся только со страницы товара — см. scraper.parse_product.

Индекс отстаёт. Замер 25.09.2026: из 89 сверенных товаров 2 разошлись с живым
сайтом, и оба раза сайт был ДЕШЕВЛЕ индекса. Поэтому цена из индекса никогда не
попадает в сообщение: она лишь повод открыть страницу товара и взять цену там.
"""
from __future__ import annotations

import json
import logging
import re

from . import config
from .models import Item
from .scraper import is_wanted

log = logging.getLogger("puma")

# Адрес индекса и ключ лежат в HTML любой страницы каталога, в блоке настроек
# Klevu. Забираем их оттуда, а не хардкодим: поменяют — подхватится само.
SEARCH_URL_RE = re.compile(r'searchUrl"\s*:\s*"(.*?)"')
HOST_RE = re.compile(r"([a-z0-9-]+\.ksearchnet\.com)")
TICKET_RE = re.compile(r"(klevu-\d{10,})")

# Артикул бота — это модель+цвет, и он однозначно виден в адресе товара:
# .../mostro-og-prime-sneakers-unisex-403206-08.html -> 403206_08
SKU_RE = re.compile(r"-(\d{6})-(\d{2})\.html")

PAGE_LIMIT = 1000
FIELDS = ["id", "name", "url", "price", "salePrice", "inStock"]
MAX_PAGES = 20  # предохранитель: 5161 товар укладывается в 6 страниц


class KlevuError(RuntimeError):
    """Индекс не ответил или ответил непонятным. Вызывающий решает, падать ли."""


def parse_endpoint(page_html: str) -> tuple[str, str]:
    """Из HTML страницы -> (адрес v2-поиска, ключ). KlevuError, если не нашли.

    В странице лежит адрес старого API (`/cloud-search/n-search/search`), а нам
    нужен v2 (`/cs/v2/search`) — только он умеет term="*" и выбор полей.
    Хост и ключ у них общие, поэтому берём их и собираем адрес сами.
    """
    chunk = ""
    m = SEARCH_URL_RE.search(page_html)
    if m:
        chunk = m.group(1).replace("\\/", "/")
    host = HOST_RE.search(chunk) or HOST_RE.search(page_html)
    ticket = TICKET_RE.search(chunk) or TICKET_RE.search(page_html)
    if not host or not ticket:
        raise KlevuError("в странице не нашёлся адрес или ключ индекса")
    return f"https://{host.group(1)}/cs/v2/search", ticket.group(1)


def query_body(api_key: str, offset: int, limit: int = PAGE_LIMIT) -> dict:
    """Тело запроса к v2. term='*' — это «весь индекс», а не поиск по слову."""
    return {
        "context": {"apiKeys": [api_key]},
        "recordQueries": [{
            "id": "catalog",
            "typeOfRequest": "SEARCH",
            "settings": {
                "query": {"term": "*"},
                "typeOfRecords": ["KLEVU_PRODUCT"],
                "limit": limit,
                "offset": offset,
                "fields": FIELDS,
            },
        }],
    }


def read_page(payload: dict) -> tuple[list[dict], int]:
    """Ответ v2 -> (записи, сколько всего в индексе). KlevuError на мусоре."""
    try:
        result = payload["queryResults"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise KlevuError(f"ответ без queryResults: {str(payload)[:200]}") from e
    return result.get("records") or [], int(result.get("meta", {}).get("totalResultsFound", 0))


def sku_of(url: str) -> str | None:
    m = SKU_RE.search(url or "")
    return f"{m.group(1)}_{m.group(2)}" if m else None


def money(value) -> int:
    """'5240.0' -> 5240. Ноль означает «цены нет», такие записи мы пропускаем."""
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return 0


def to_item(rec: dict) -> Item | None:
    """Одна запись индекса -> Item. None, если это не наш товар.

    Отбор здесь ровно тот же, что в scraper.parse_listing: кроссовки или кеды,
    не детские, цена ниже старой. Плюс наличие — в списке Пумы распроданное не
    показывают, а в индексе оно есть.
    """
    sku = sku_of(rec.get("url", ""))
    if not sku:
        return None
    name = rec.get("name") or ""
    if not is_wanted(name):
        return None
    if str(rec.get("inStock", "yes")).lower() not in ("yes", "true", "1"):
        return None
    price = money(rec.get("salePrice"))     # текущая
    old = money(rec.get("price"))           # до скидки
    if not price or not old or price >= old:
        return None
    return Item(sku, name, rec["url"].split("?")[0], price, old)


def to_items(records: list[dict]) -> list[Item]:
    """Записи индекса -> кроссовки со скидкой, без повторов, порядок сохранён."""
    out: dict[str, Item] = {}
    for rec in records:
        it = to_item(rec)
        if it is not None:
            out.setdefault(it.sku, it)
    return list(out.values())


async def discover(client) -> tuple[str, str]:
    """Узнать адрес и ключ индекса, сходив на страницу каталога.

    Один лишний запрос к Пуме на прогон — плата за то, что ключ не захардкожен.
    Поменяют ключ — бот переживёт это сам, без правки кода и без деплоя.
    """
    r = await client.get(config.SALE_URLS[0])
    r.raise_for_status()
    return parse_endpoint(r.text)


async def fetch_page(client, endpoint: str, api_key: str, offset: int,
                     limit: int = PAGE_LIMIT) -> tuple[list[dict], int]:
    r = await client.post(endpoint, json=query_body(api_key, offset, limit),
                          headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return read_page(r.json())


async def fetch_catalog(client, endpoint: str | None = None,
                        api_key: str | None = None) -> list[dict]:
    """Весь индекс, постранично. Возвращает сырые записи.

    Останавливаемся, когда набрали всё по счётчику индекса или страница пришла
    неполной. MAX_PAGES — предохранитель от бесконечного круга, если индекс
    вдруг начнёт отдавать один и тот же кусок.
    """
    if endpoint is None or api_key is None:
        endpoint, api_key = await discover(client)

    records: list[dict] = []
    total = None
    for page in range(MAX_PAGES):
        chunk, found = await fetch_page(client, endpoint, api_key, len(records))
        if total is None:
            total = found
            log.info("в индексе товаров: %d", total)
        records.extend(chunk)
        if not chunk or len(chunk) < PAGE_LIMIT or len(records) >= total:
            break
    else:
        log.warning("индекс не кончился за %d страниц — остановился", MAX_PAGES)

    log.info("скачал записей: %d из %s", len(records), total)
    return records


async def fetch_sale(client) -> list[Item]:
    """Кроссовки со скидкой из индекса. Тот же контракт, что у scraper.fetch_sale."""
    return to_items(await fetch_catalog(client))
