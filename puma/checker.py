"""Главная логика: обойти сайт, сравнить с базой, разослать новое."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from . import config, messages, storage
from .scraper import fetch_sale, new_client, parse_product
from .sender import send

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("puma")
checking = asyncio.Lock()  # чтобы два обхода не шли внахлёст


async def warn_broken(bot: Bot, chat_id: int, db) -> None:
    """Сайт отдал ноль кроссовок — значит, сломался разбор страницы.
    Молчащий бот выглядит так же, как бот без скидок, поэтому кричим.
    Не чаще раза в сутки, чтобы не превратить это в спам."""
    last = float(storage.get_meta(db, "last_warn", "0"))
    if time.time() - last < 24 * 3600:
        return
    storage.set_meta(db, "last_warn", str(time.time()))
    await bot.send_message(chat_id, messages.BROKEN_TEXT)


async def check(bot: Bot, chat_id: int) -> int:
    async with checking:
        return await _check(bot, chat_id)


async def _check(bot: Bot, chat_id: int) -> int:
    db = storage.db_init()
    sent = 0
    async with new_client() as client:
        items = await fetch_sale(client)
        log.info("кроссовок со скидкой: %d", len(items))
        if not items:
            await warn_broken(bot, chat_id, db)
            return 0
        first_run = storage.is_empty(db)
        for it in items:
            prev = storage.last_price(db, it.sku)
            if prev is not None and it.price >= prev:
                continue
            storage.remember(db, it.sku, it.price)
            if first_run or it.discount < config.MIN_DISCOUNT:
                continue
            r = await client.get(it.url)
            info = parse_product(r.text)
            if not info["sizes"]:
                continue  # нет ни одного размера — слать нечего
            reason = ("Новая скидка" if prev is None
                      else f"Цена упала (было {messages.money(prev)})")
            await send(bot, chat_id, it, info, reason)
            sent += 1
            await asyncio.sleep(1)
        db.commit()
        if first_run:
            await bot.send_message(
                chat_id,
                messages.FIRST_RUN_TEXT.format(n=len(items), minutes=config.INTERVAL_MIN))
    return sent
