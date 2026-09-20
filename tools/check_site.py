"""Проверка без Telegram: доступен ли сайт и что находит парсер.
Запуск из корня проекта: python -m tools.check_site  (или scripts\\check-site.bat)"""
import asyncio
import logging
import re

from puma import config, messages, scraper


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config.MAX_PAGES = 2  # это проверка, а не полный обход
    async with scraper.new_client() as c:
        url = config.SALE_URLS[0]
        r = await c.get(url)
        print(f"{url} -> HTTP {r.status_code}, {len(r.text)} байт")
        if r.status_code != 200:
            print("Сайт не отдал страницу. Скорее всего защита или блокировка.")
            return
        items = await scraper.fetch_sale(c)
        print(f"\nКроссовок со скидкой найдено: {len(items)} (лимит 2 страницы на раздел)\n")
        for it in items[:5]:
            pr = await c.get(it.url)
            info = scraper.parse_product(pr.text)
            print(plain(messages.caption(it, info, "пример")))
            print(f"фото: {it.image}\n")


if __name__ == "__main__":
    asyncio.run(main())
