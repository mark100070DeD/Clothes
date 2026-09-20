"""Роль: всё, что говорит с Telegram — отправка карточек и разбор входящих команд.

Кто вызывает: checker.py (шлёт найденные скидки), app.py (режимы запуска).
Что править здесь: как именно уходит сообщение, что делать при ошибке Телеграма,
как отвечать на команды. Тексты лежат не здесь, а в messages.py.

ГЛАВНОЕ ПРАВИЛО ЭТОГО ФАЙЛА: обработчики команд не ходят в сеть за товарами.
Ни /start, ни /who не парсят сайт — они только читают готовое из базы и отвечают.
Раньше /start запускал обход сайта прямо в обработчике, и человек ждал полминуты.
Сбором карточек занят фоновый обход (checker.refresh_deals): он кладёт их в
таблицу deals целиком, вместе с цветом и размерами.

Получателей может быть несколько: подписка открытая, любой, кто нажал /start,
попадает в таблицу subs и дальше получает скидки. Одна карточка уходит всем по
очереди (broadcast), и кто заблокировал бота — из подписки выпадает.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from . import config, messages, storage
from .models import Item

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("puma")


def chat_person(chat) -> tuple[str, str]:
    """(имя, @username) — как показать человека в списке пользователей.

    Пишем через getattr: у разных видов чатов набор полей разный, и падать
    из-за отсутствующего поля на приёме команды нельзя.
    """
    username = getattr(chat, "username", None)
    parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
    name = " ".join(p for p in parts if p) or getattr(chat, "title", None) or ""
    return name, ("@" + username if username else "")


async def send_text(bot: Bot, chat_id: int, text: str) -> None:
    """Текстом, с одной попыткой переждать флуд-лимит."""
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except TelegramRetryAfter as e:
        log.warning("флуд-лимит на тексте, жду %s с", e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def send_with_fallback(bot: Bot, chat_id: int, text: str) -> None:
    """Сообщение, которое дойдёт даже если Телеграм не принял разметку.

    Остаться совсем без ответа хуже, чем получить текст без жирного шрифта.
    """
    try:
        await send_text(bot, chat_id, text)
        return
    except Exception:
        log.exception("сообщение с разметкой не ушло, пробую без неё")
    try:
        await bot.send_message(chat_id, re.sub(r"<[^>]+>", "", text))
    except Exception:
        log.exception("сообщение не ушло совсем")


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


async def broadcast(bot: Bot, chat_ids: list[int], it: Item, info: dict,
                    reason: str, db=None) -> int:
    """Одна карточка всем получателям. Возвращает, до скольких она дошла.

    Ноль означает «не дошла ни до кого» — тогда checker.py не станет запоминать
    цену и вернётся к товару на следующем прогоне.

    Кто заблокировал бота, выпадает из подписки: мёртвый чат незачем держать и
    незачем тормозить на нём каждую рассылку.
    """
    delivered = 0
    for n, chat_id in enumerate(chat_ids):
        if n:
            await asyncio.sleep(config.SEND_PAUSE_SEC)
        try:
            await send(bot, chat_id, it, info, reason)
            delivered += 1
        except TelegramForbiddenError:
            log.warning("чат %s заблокировал бота — убираю из подписки", chat_id)
            if db is not None:
                storage.remove_subscriber(db, chat_id)
        except Exception:
            log.exception("карточка %s не дошла в чат %s", it.sku, chat_id)
    return delivered


async def notify(bot: Bot, chat_ids: list[int], text: str) -> int:
    """Простое сообщение всем получателям. Возвращает, до скольких дошло."""
    delivered = 0
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, text)
            delivered += 1
        except Exception:
            log.exception("не смог написать в чат %s", chat_id)
    return delivered


def deal_card(row: tuple) -> tuple[Item, dict]:
    """Строка таблицы deals -> то, из чего messages.caption рисует карточку."""
    sku, name, url, price, old_price, color, sizes = row
    info = {"sizes": [s for s in (sizes or "").split(", ") if s], "color": color or "—"}
    return Item(sku, name, url, price, old_price), info


async def send_cards(bot: Bot, chat_id: int, rows: list[tuple], reason: str) -> int:
    """Отправить готовые карточки. В сеть за товарами не ходим — всё уже в rows."""
    sent = 0
    for n, row in enumerate(rows):
        if n:
            await asyncio.sleep(config.SEND_PAUSE_SEC)  # лимит Телеграма на чат
        it, info = deal_card(row)
        try:
            await send(bot, chat_id, it, info, reason)
            sent += 1
        except Exception:
            log.exception("карточка витрины %s не ушла", it.sku)
    return sent


async def send_top(bot: Bot, chat_id: int, limit: int | None = None) -> int:
    """Витрина из готовых карточек. Только чтение базы, ни одного запроса на сайт."""
    limit = config.START_ITEMS if limit is None else limit
    db = storage.db_init()
    return await send_cards(bot, chat_id, storage.recent_deals(db, limit),
                            "Сейчас на распродаже")


async def answer_start(bot: Bot, chat_id: int) -> None:
    """Ответ на /start: приветствие и готовые карточки из базы.

    Мгновенно: чтение базы занимает миллисекунды, первое сообщение уходит сразу.
    Если витрина пуста — честно говорим, что бот ещё не собрал скидки.
    """
    db = storage.db_init()
    rows = storage.recent_deals(db, config.START_ITEMS)
    if not rows:
        await bot.send_message(chat_id, messages.DEALS_EMPTY)
        return
    await bot.send_message(chat_id, messages.START_TEXT.format(n=len(rows)))
    await send_cards(bot, chat_id, rows, "Сейчас на распродаже")


async def show_users(bot: Bot, chat_id: int, db, admin: int) -> None:
    """Статистика пользователей админу: быстрый COUNT и последние подписавшиеся."""
    text = messages.users_list(storage.subscribers_recent(db, config.USERS_SHOWN),
                               storage.subscribers_count(db), admin)
    await send_with_fallback(bot, chat_id, text)


async def handle_pending(bot: Bot) -> list[int]:
    """Разобрать сообщения, накопившиеся с прошлого запуска. Отвечает на /start
    и /who, записывает нажавших /start в подписчики. Возвращает новых подписчиков.

    В режиме GitHub Actions бот не висит на связи, поэтому команда не доходит
    сама: её надо забрать через getUpdates. Телега держит непрочитанное сутки,
    так что команда не теряется — просто отвечаем с задержкой.
    """
    try:
        updates = await bot.get_updates(timeout=0, limit=100, allowed_updates=["message"])
    except Exception:
        log.exception("не смог забрать сообщения")
        return []
    if not updates:
        return []

    starters: dict[int, tuple[str, str]] = {}   # chat id -> (имя, username)
    wants_list: list[tuple[int, int]] = []      # (chat id, user id) для /who
    for u in updates:
        if not u.message:
            continue
        text = u.message.text or ""
        chat = u.message.chat
        if text.startswith("/start"):
            starters.setdefault(chat.id, chat_person(chat))
        elif text.startswith("/who"):
            user = getattr(u.message, "from_user", None)
            user_id = getattr(user, "id", None) or chat.id
            if (chat.id, user_id) not in wants_list:
                wants_list.append((chat.id, user_id))

    admin = config.admin_id()

    # /who отвечаем ДО подтверждения приёма. Ответ не страшно прислать дважды,
    # а вот потерять команду из-за прерванного прогона обидно: подтверждённое
    # обновление Телеграм больше не отдаст.
    if wants_list:
        db = storage.db_init()
        for chat_id, user_id in wants_list:
            if user_id != admin:
                log.info("/who от %s — доступа нет", user_id)
                await send_with_fallback(bot, chat_id, messages.NO_ACCESS)
                continue
            log.info("/who от админа %s — шлю статистику", user_id)
            await show_users(bot, chat_id, db, admin)

    # Подтверждаем приём: иначе те же сообщения вернутся на следующем запуске
    # и бот пришлёт витрину повторно.
    last_id = max(u.update_id for u in updates)
    try:
        await bot.get_updates(offset=last_id + 1, timeout=0, limit=1)
    except Exception:
        log.exception("не смог подтвердить сообщения")

    if not starters:
        return []

    db = storage.db_init()
    fresh: list[int] = []
    for chat_id, person in starters.items():
        name, username = person
        if storage.add_subscriber(db, chat_id, name, username):
            fresh.append(chat_id)
            log.info("новый подписчик: %s %s %s", chat_id, name or "?", username or "")
        log.info("/start от %s — шлю витрину из базы", chat_id)
        # Ответ одному не должен ломать ответ остальным.
        try:
            await answer_start(bot, chat_id)
        except Exception:
            log.exception("витрина для %s не удалась", chat_id)
    return fresh
