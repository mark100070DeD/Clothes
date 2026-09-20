"""Роль: перенести подписчиков из Cloudflare Worker в базу бота.

Кто вызывает: app.py в режиме --once, перед тем как считать получателей.
Что править здесь: разбор ответа Worker'а.

Зачем это нужно. На /start отвечает Worker, поэтому новый человек появляется в
его хранилище KV, а не в puma.db. Рассылку же ведёт Python по базе. Без этого
шага нажавший /start получил бы витрину один раз и больше ничего.

Почему не наоборот (Worker пишет прямо в репозиторий): для этого ему нужен был
бы токен с правом записи в GitHub. Читать список безопаснее, чем давать право
коммитить.
"""
import logging

import httpx

from . import config, storage

log = logging.getLogger("puma")

TIMEOUT_SEC = 20


def _row(rec: dict) -> tuple[int, str, str] | None:
    """Одна запись из KV -> (chat_id, имя, @username). None, если мусор."""
    try:
        chat_id = int(rec["chat_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if not chat_id:
        return None
    return chat_id, str(rec.get("name") or ""), str(rec.get("username") or "")


async def fetch_subs(url: str, token: str) -> list[dict]:
    """Спросить Worker, кто нажал /start."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        r = await client.get(f"{url}/subs", headers={"X-Subs-Token": token})
        r.raise_for_status()
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Worker ответил отказом: {data}")
    return data.get("subs") or []


def merge(db, records: list[dict]) -> int:
    """Записать подписчиков в базу. Возвращает число новых."""
    fresh = 0
    for rec in records:
        row = _row(rec)
        if row is None:
            log.warning("подписчик пропущен, непонятная запись: %r", rec)
            continue
        chat_id, name, username = row
        if storage.add_subscriber(db, chat_id, name, username):
            fresh += 1
            log.info("новый подписчик: %s %s %s", chat_id, name or "?", username or "")
    return fresh


async def pull(db) -> int:
    """Забрать подписчиков из Worker. Возвращает число новых.

    Молчаливо ничего не делает, если Worker не настроен: локальный запуск и
    старые прогоны должны работать без него.
    """
    if not (config.WORKER_URL and config.SUBS_TOKEN):
        log.info("подписчиков из Worker не беру: не задан WORKER_URL или SUBS_TOKEN")
        return 0
    records = await fetch_subs(config.WORKER_URL, config.SUBS_TOKEN)
    fresh = merge(db, records)
    log.info("подписчиков у Worker: %d, из них новых: %d", len(records), fresh)
    return fresh
