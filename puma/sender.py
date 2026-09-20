"""Всё, что отправляет сообщения в телеграм и разбирает входящие команды."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from . import messages, storage
from .models import Item
from .scraper import fetch_first_page, new_client, parse_product

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("puma")


async def send(bot: Bot, chat_id: int, it: Item, info: dict, reason: str) -> None:
    text = messages.caption(it, info, reason)
    try:
        await bot.send_photo(chat_id, it.image, caption=text, parse_mode="HTML")
    except Exception as e:  # телега не смогла забрать картинку — шлём текстом
        log.warning("фото не ушло (%s), шлю текстом", e)
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def send_top(bot: Bot, chat_id: int, limit: int = 10) -> int:
    """Прислать первые скидки так, как их показывает сам сайт на первой странице.
    Даты у товаров на сайте нет, поэтому «последние» — это его собственный порядок."""
    db = storage.db_init()
    sent = 0
    async with new_client() as client:
        for it in await fetch_first_page(client):
            if sent >= limit:
                break
            pr = await client.get(it.url)
            info = parse_product(pr.text)
            if not info["sizes"]:
                continue
            await send(bot, chat_id, it, info, "Сейчас на распродаже")
            storage.remember(db, it.sku, it.price)
            sent += 1
            await asyncio.sleep(1)
        db.commit()
    return sent


async def answer_start(bot: Bot, chat_id: int) -> None:
    """Ответ на /start: приветствие + витрина из 10 карточек."""
    await bot.send_message(chat_id, messages.START_TEXT)
    if not await send_top(bot, chat_id, 10):
        await bot.send_message(chat_id, messages.START_FAILED)


async def handle_pending(bot: Bot, chat_id: int) -> None:
    """Разобрать сообщения, накопившиеся с прошлого запуска.

    В режиме GitHub Actions бот не висит на связи, поэтому /start не доходит сам:
    его надо забрать вручную через getUpdates. Телега держит непрочитанное
    сутки, так что команда не теряется — просто отвечаем с задержкой.
    """
    try:
        updates = await bot.get_updates(timeout=0, limit=100, allowed_updates=["message"])
    except Exception:
        log.exception("не смог забрать сообщения")
        return
    if not updates:
        return

    wants_start = any(
        u.message and (u.message.text or "").startswith("/start") and u.message.chat.id == chat_id
        for u in updates
    )
    # Подтверждаем приём: иначе те же сообщения вернутся на следующем запуске
    # и бот пришлёт карточки повторно.
    last_id = max(u.update_id for u in updates)
    try:
        await bot.get_updates(offset=last_id + 1, timeout=0, limit=1)
    except Exception:
        log.exception("не смог подтвердить сообщения")

    if wants_start:
        log.info("пришёл /start — шлю 10 карточек")
        await answer_start(bot, chat_id)
