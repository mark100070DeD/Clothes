"""Всё, что ходит на сайт Пумы и разбирает его страницы.
Если Пума поменяет вёрстку — чинить надо только этот файл."""
import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from . import config
from .models import Item

log = logging.getLogger("puma")


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


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=config.HEADERS, timeout=30, follow_redirects=True)


async def fetch_sale(client: httpx.AsyncClient) -> list[Item]:
    """Обойти оба раздела распродажи по страницам и собрать все кроссовки со скидкой."""
    found: dict[str, Item] = {}
    for url in config.SALE_URLS:
        seen_skus: set[str] = set()
        for page in range(1, config.MAX_PAGES + 1):
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


async def fetch_first_page(client: httpx.AsyncClient) -> list[Item]:
    """Первая страница каждого раздела — для витрины по /start."""
    items: list[Item] = []
    seen: set[str] = set()
    for url in config.SALE_URLS:
        r = await client.get(url, params={"p": 1})
        for it in parse_listing(r.text):
            if it.sku not in seen:
                seen.add(it.sku)
                items.append(it)
    return items
