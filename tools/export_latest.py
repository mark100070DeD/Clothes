"""Собрать data/latest.json руками, ничего не отправляя в Telegram.

Запуск из корня проекта: python -m tools.export_latest

Этот файл читает Cloudflare Worker, чтобы отвечать на /start мгновенно.
На сервере его пишет часовой обход; здесь — для проверки и отладки.
"""
import asyncio
import json
import logging
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from puma import config, export, scraper  # noqa: E402


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    async with scraper.new_client() as client:
        n = await export.export_latest(client)
    if not n:
        return
    with open(config.LATEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    print()
    print(f"updated_at: {data['updated_at']}, товаров: {data['count']}")
    for it in data["items"][:5]:
        print(f"  {it['name']}")
        print(f"      {it['price']} вместо {it['old_price']} грн (-{it['discount']}%), "
              f"{it['color']}")
        print(f"      размеры: {', '.join(it['sizes'])}")


if __name__ == "__main__":
    asyncio.run(main())
