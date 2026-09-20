"""Проверка без Telegram: доступен ли сайт и что находит парсер."""
import asyncio
import logging
import re

import httpx

import bot


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    bot.MAX_PAGES = 2  # это проверка, а не полный обход
    async with httpx.AsyncClient(headers=bot.HEADERS, timeout=30, follow_redirects=True) as c:
        r = await c.get(bot.SALE_URLS[0])
        print(f"{bot.SALE_URLS[0]} -> HTTP {r.status_code}, {len(r.text)} байт")
        if r.status_code != 200:
            print("Сайт не отдал страницу. Скорее всего защита или блокировка.")
            return
        items = await bot.fetch_sale(c)
        print(f"\nКроссовок со скидкой найдено: {len(items)} (лимит 2 страницы на раздел)\n")
        for it in items[:5]:
            pr = await c.get(it.url)
            info = bot.parse_product(pr.text)
            print(plain(bot.caption(it, info, "пример")))
            print(f"фото: {it.image}\n")


if __name__ == "__main__":
    asyncio.run(main())
