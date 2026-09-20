"""Роль: всё, что говорит с Telegram — отправка карточек и разбор входящих команд.

Кто вызывает: checker.py (шлёт найденные скидки), app.py (режимы запуска).
Что править здесь: как именно уходит сообщение, что делать при ошибке Телеграма,
как отвечать на /start. Тексты лежат не здесь, а в messages.py.

Про флуд-лимит: Телеграм пропускает примерно одно сообщение в секунду на чат,
а на превышение отвечает ошибкой 429 с просьбой подождать. Мы эту просьбу
выполняем и повторяем отправку, иначе большая партия скидок обрывалась бы
на середине.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramRetryAfter

from . import config, messages, storage
from .models import Item
from .scraper import fetch_first_page, new_client, parse_product

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("puma")


async def send_text(bot: Bot, chat_id: int, text: str) -> None:
    """Текстом, с одной попыткой переждать флуд-лимит."""
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except TelegramRetryAfter as e:
        log.warning("флуд-лимит на тексте, жду %s с", e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def send(bot: Bot, chat_id: int, it: Item, info: dict, reason: str) -> None:
    """Карточка: фото с подписью. Не вышло фото — то же самое текстом."""
    text = messages.caption(it, info, reason)
    for _ in range(2):
        try:
            await bot.send_photo(chat_id, it.image, caption=text, parse_mode="HTML")
            return
        except TelegramRetryAfter as e:
            log.warning("флуд-лимит на фото, жду %s с", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:  # телега не смогла забрать картинку
            log.warning("фото не ушло (%s), шлю текстом", e)
            break
    await send_text(bot, chat_id, text)


async def send_top(bot: Bot, chat_id: int, limit: int | None = None) -> int:
    """Прислать первые скидки так, как их показывает сам сайт на первой странице.
    Даты у товаров на сайте нет, поэтому «последние» — это его собственный порядок.

    Сколько именно — берём из config.START_ITEMS."""
    limit = config.START_ITEMS if limit is None else limit
    db = storage.db_init()
    sent = 0
    async with new_client() as client:
        for it in await fetch_first_page(client):
            if sent >= limit:
                break
            try:
                pr = await client.get(it.url)
                pr.raise_for_status()
                info = parse_product(pr.text)
            except Exception as e:  # одна битая страница не должна ломать витрину
                log.warning("страница товара %s не открылась (%s)", it.sku, e)
                continue
            if not info["sizes"]:
                continue
            await send(bot, chat_id, it, info, "Сейчас на распродаже")
            # Витрину помним, чтобы часовой обход не прислал те же товары
            # ещё раз как «новую скидку». Сохраняем сразу же.
            storage.remember(db, it.sku, it.price)
            db.commit()
            sent += 1
            await asyncio.sleep(config.SEND_PAUSE_SEC)
    return sent


async def answer_start(bot: Bot, chat_id: int) -> None:
    """Ответ на /start: приветствие + витрина из config.START_ITEMS карточек."""
    await bot.send_message(chat_id, messages.START_TEXT.format(n=config.START_ITEMS))
    if not await send_top(bot, chat_id):
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
        log.info("пришёл /start — шлю до %d карточек", config.START_ITEMS)
        # Витрина не должна уводить за собой весь прогон: за ней в режиме
        # --once идёт проверка скидок, и она важнее.
        try:
            await answer_start(bot, chat_id)
        except Exception:
            log.exception("витрина по /start не удалась")
