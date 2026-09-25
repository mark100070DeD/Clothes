"""Перенести память бота из data/puma.db в хранилище Worker'а. Делается ОДИН раз.

Запуск из корня проекта:  python -m tools.push_seen

Зачем. Скидки теперь ищет Worker, и отметки «уже отправлено» должны лежать у
него. Без переноса он стартовал бы с пустой памятью: пришлось бы сутки молча
запоминать каталог, и всё это время новые скидки не приходили бы вовсе. А если
бы защиту от залпа отключить — прилетело бы разом 500+ карточек.

Что делает: читает таблицу seen (sku -> цена) и отправляет её в POST /state/seen
под паролем SUBS_TOKEN. Worker сливает, а не перезаписывает: потерять строку
значит прислать карточку повторно.

Повторный запуск безопасен: одинаковые цены Worker просто не считает новыми.

Нужны переменные окружения (берутся из .env): WORKER_URL и SUBS_TOKEN.
"""
import asyncio
import sqlite3
import sys

import httpx

from puma import config

TIMEOUT_SEC = 60


def read_seen(path: str) -> dict[str, int]:
    """Таблица seen целиком. Битые строки пропускаем молча — их единицы."""
    db = sqlite3.connect(path)
    out: dict[str, int] = {}
    for sku, price in db.execute("SELECT sku, price FROM seen"):
        try:
            value = int(price)
        except (TypeError, ValueError):
            continue
        if sku and value > 0:
            out[str(sku)] = value
    db.close()
    return out


async def push(url: str, token: str, seen: dict[str, int]) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        r = await client.post(f"{url}/state/seen",
                              headers={"X-Subs-Token": token},
                              json={"seen": seen})
        r.raise_for_status()
        return r.json()


async def main() -> int:
    if not (config.WORKER_URL and config.SUBS_TOKEN):
        print("Не задан WORKER_URL или SUBS_TOKEN — добавь их в .env и запусти снова.")
        return 1

    seen = read_seen(config.DB_PATH)
    if not seen:
        print(f"В {config.DB_PATH} нечего переносить: таблица seen пуста.")
        return 1

    print(f"Переношу {len(seen)} запомненных цен в {config.WORKER_URL} ...")
    answer = await push(config.WORKER_URL, config.SUBS_TOKEN, seen)
    if not answer.get("ok"):
        print(f"Worker отказал: {answer}")
        return 1

    print(f"Готово. Добавлено новых: {answer['added']}, всего в памяти: {answer['total']}.")
    print("Worker начнёт работать со следующей минуты и сразу пришлёт первые карточки.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
