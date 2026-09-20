"""Роль: выгрузка витрины в data/latest.json — этот файл читает Cloudflare Worker.

Кто вызывает: app.py в режиме --once, то есть часовой обход на GitHub Actions.
Что править здесь: состав полей и правила отбора товаров для витрины.

Зачем файл вообще. Telegram-бот на GitHub Actions не висит на связи, поэтому
ответ на /start приходил с задержкой до часа. Теперь на /start отвечает Worker на
Cloudflare: он получает webhook и мгновенно отдаёт карточки, читая ГОТОВЫЙ JSON
из репозитория. Ни сайт Пумы, ни база ему для этого не нужны.

Порядок товаров — как на сайте: первые страницы разделов, мужской за женским.
Не по размеру скидки: витрина должна выглядеть так же, как сама распродажа.

Почему не берём все товары. Размеры в наличии видны только на странице товара,
а их около 450. Ходить за каждым — это лишние минуты на каждый обход, поэтому
кандидатов ищем только на первых страницах и открываем не больше
LATEST_MAX_CHECKS страниц.
"""
import json
import logging
import os
from datetime import datetime, timezone

from . import config
from .models import Item
from .scraper import fetch_pages, parse_product

log = logging.getLogger("puma")


def item_json(it: Item, info: dict) -> dict:
    """Один товар в том виде, в котором его ждёт Worker."""
    return {
        "sku": it.sku,
        "name": it.name,
        "url": it.url,
        "price": it.price,
        "old_price": it.old_price,
        "discount": it.discount,
        "image": it.image,
        "color": info["color"],
        "sizes": info["sizes"],
    }


async def collect_latest(client, limit: int | None = None,
                         pages: int | None = None,
                         max_checks: int | None = None) -> list[dict]:
    """Собрать до `limit` товаров, у которых есть размеры в наличии.

    Открываем страницы товаров по порядку витрины и останавливаемся, как только
    набрали нужное количество либо исчерпали потолок запросов.
    """
    limit = config.LATEST_ITEMS if limit is None else limit
    pages = config.LATEST_PAGES if pages is None else pages
    max_checks = config.LATEST_MAX_CHECKS if max_checks is None else max_checks

    candidates = await fetch_pages(client, pages)
    log.info("кандидатов на первых страницах: %d", len(candidates))

    out: list[dict] = []
    checked = 0
    for it in candidates:
        if len(out) >= limit or checked >= max_checks:
            break
        checked += 1
        try:
            r = await client.get(it.url)
            r.raise_for_status()
            info = parse_product(r.text)
        except Exception as e:
            log.warning("latest: страница %s не открылась (%s)", it.sku, e)
            continue
        if not info["sizes"]:
            continue  # распродан — в витрину не берём
        out.append(item_json(it, info))

    log.info("в latest.json пойдёт товаров: %d (открыто страниц: %d)", len(out), checked)
    return out


def write_latest(items: list[dict], path: str | None = None) -> str:
    """Записать выгрузку. Возвращает путь к файлу.

    updated_at обязателен: расписание GitHub ненадёжное, и Worker должен уметь
    сказать человеку, насколько данные свежие.
    """
    path = config.LATEST_PATH if path is None else path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items),
        "items": items,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path


async def export_latest(client) -> int:
    """Собрать и записать выгрузку. Возвращает число товаров в ней."""
    items = await collect_latest(client)
    if not items:
        # Пустой файл сделал бы /start бесполезным, а старый хотя бы покажет
        # что-то с честной отметкой времени.
        log.warning("latest.json не обновляю: подходящих товаров не нашлось")
        return 0
    path = write_latest(items)
    log.info("записал %s: товаров %d", path, len(items))
    return len(items)
