"""Наполнить витрину для /start, ничего не отправляя в Telegram.

Запуск из корня проекта: python -m tools.fill_showcase

Обходит распродажу и складывает готовые карточки в таблицу deals — ту самую,
из которой обработчик /start потом читает мгновенно. Ни одного сообщения в чат
не уходит, так что запускать можно спокойно и сколько угодно раз.

Нужен, когда витрина пуста: сразу после чистой базы или после миграции, пока
фоновый обход до неё не дошёл.
"""
import asyncio
import logging
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from puma import checker, config, scraper, storage  # noqa: E402


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    db = storage.db_init()
    print(f"База: {config.DB_PATH}")
    print(f"Карточек в витрине сейчас: {storage.deals_count(db)}")
    print("Обхожу распродажу, это займёт пару минут...")

    async with scraper.new_client() as client:
        items = await scraper.fetch_sale(client)
        print(f"Кроссовок со скидкой на сайте: {len(items)}")
        await checker.refresh_deals(client, db, items)

    print()
    print(f"Карточек в витрине стало: {storage.deals_count(db)}")
    for sku, name, url, price, old_price, color, sizes in storage.recent_deals(db, 10):
        print(f"  {name}")
        print(f"      {price} вместо {old_price} грн, {color}, размеры: {sizes}")


if __name__ == "__main__":
    asyncio.run(main())
