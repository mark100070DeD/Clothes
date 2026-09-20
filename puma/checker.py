"""Роль: дирижёр. Один проход: обойти сайт, сравнить с базой, разослать новое.

Кто вызывает: app.py в режимах --once и «постоянно».
Что править здесь: правила отбора — что считать новостью, а что промолчать.
Про HTML здесь не знают (это scraper.py), про вид сообщений тоже (messages.py).

Правило отбора, по шагам для каждого товара:
  цена не ниже запомненной      -> молчим
  самый первый запуск базы      -> запоминаем молча (иначе залп на сотни сообщений)
  скидка меньше MIN_DISCOUNT    -> запоминаем молча
  страница не открылась         -> НЕ запоминаем, вернёмся на следующем прогоне
  нет ни одного размера         -> НЕ запоминаем, иначе скидка потеряется навсегда
  карточка не дошла ни до кого  -> НЕ запоминаем, вернёмся на следующем прогоне
  иначе                         -> шлём карточку всем и сразу сохраняем базу

Ещё эта же функция наполняет витрину для /start (refresh_deals). Готовые
карточки складываются в таблицу deals, чтобы обработчик команды только читал их
и отвечал мгновенно, а в сеть за товарами ходил этот фоновый обход.

Почему «сохраняем сразу»: запомненная цена — это отметка «уже отправлено».
Если накапливать её до конца прогона, обрыв на середине сотрёт отметки по всем
уже отправленным карточкам, и через час они придут повторно.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from . import config, messages, storage
from .models import Item
from .scraper import fetch_sale, new_client, parse_product
from .sender import broadcast, notify

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("puma")
checking = asyncio.Lock()  # чтобы два обхода не шли внахлёст
WARN_EVERY_SEC = 24 * 3600


async def warn_once_a_day(bot: Bot, chat_ids: list[int], db, key: str, text: str) -> None:
    """Тревога в чат не чаще раза в сутки, чтобы поломка не превратилась в спам.

    Молчащий бот выглядит точно так же, как бот без скидок, поэтому про любую
    поломку надо кричать — сам по вкладке Actions человек не пойдёт.
    Отметку времени ставим ПОСЛЕ удачной отправки: если написать не удалось,
    сутки молчания начинать нельзя.
    """
    last = float(storage.get_meta(db, key, "0"))
    if time.time() - last < WARN_EVERY_SEC:
        return
    if await notify(bot, chat_ids, text):
        storage.set_meta(db, key, str(time.time()))


async def _try_warn(bot: Bot, chat_ids: list[int], db, key: str, text: str) -> None:
    """Тревога, которая сама не может свалить прогон."""
    try:
        await warn_once_a_day(bot, chat_ids, db, key, text)
    except Exception:
        log.exception("не смог отправить предупреждение")


async def refresh_deals(client, db, items: list[Item]) -> None:
    """Держать витрину для /start наполненной и не устаревшей.

    Витрина — это готовые карточки в таблице deals. Обработчик /start их только
    читает, поэтому собирать их должен кто-то заранее, и это место здесь.

    Три шага:
      1. выбрасываем устаревшее — товар ушёл с распродажи или цена изменилась;
      2. если карточек меньше START_ITEMS, добираем из самых крупных скидок.
         За размерами и цветом надо идти на страницу товара, поэтому запросов
         ровно столько, сколько карточек не хватает — обычно ноль;
      3. обрезаем хвост, чтобы таблица не росла без конца.
    """
    current = {it.sku: it for it in items}
    for sku, price in storage.deal_prices(db):
        it = current.get(sku)
        if it is None or it.price != price:
            storage.delete_deal(db, sku)
    db.commit()

    need = config.START_ITEMS - storage.deals_count(db)
    if need > 0:
        have = {sku for sku, _ in storage.deal_prices(db)}
        for it in sorted(items, key=lambda x: -x.discount):
            if need <= 0:
                break
            if it.sku in have:
                continue
            try:
                r = await client.get(it.url)
                r.raise_for_status()
                info = parse_product(r.text)
            except Exception as e:
                log.warning("витрина: страница %s не открылась (%s)", it.sku, e)
                continue
            if not info["sizes"]:
                continue
            storage.save_deal(db, it.sku, it.name, it.url, it.price, it.old_price,
                              info["color"], ", ".join(info["sizes"]))
            db.commit()
            need -= 1
            await asyncio.sleep(config.PAGE_PAUSE_SEC)

    storage.trim_deals(db, config.DEALS_KEEP)
    db.commit()
    log.info("в витрине карточек: %d", storage.deals_count(db))


async def check(bot: Bot, chat_ids: list[int]) -> int:
    async with checking:
        return await _check(bot, chat_ids)


async def _check(bot: Bot, chat_ids: list[int]) -> int:
    db = storage.db_init()
    sent = 0
    async with new_client() as client:
        try:
            items = await fetch_sale(client)
        except Exception as e:
            # Сайт лёг или закрылся от бота. Молча падать нельзя: человек решит,
            # что просто нет скидок. Предупреждаем и роняем прогон дальше,
            # чтобы в Actions осталась красная отметка.
            log.exception("обход распродажи сорвался")
            await _try_warn(bot, chat_ids, db, "last_warn_down",
                            messages.DOWN_TEXT.format(error=e))
            raise

        log.info("кроссовок со скидкой: %d", len(items))
        if not items:
            # Сайт ответил, но кроссовок ноль — почти всегда это сменившаяся вёрстка.
            await _try_warn(bot, chat_ids, db, "last_warn", messages.BROKEN_TEXT)
            return 0

        first_run = storage.is_empty(db)
        for it in items:
            prev = storage.last_price(db, it.sku)
            if prev is not None and it.price >= prev:
                continue

            if first_run or it.discount < config.MIN_DISCOUNT:
                storage.remember(db, it.sku, it.price)
                db.commit()
                continue

            try:
                r = await client.get(it.url)
                r.raise_for_status()
                info = parse_product(r.text)
            except Exception as e:
                log.warning("страница товара %s не открылась (%s) — вернусь позже", it.sku, e)
                continue

            if not info["sizes"]:
                # Распродан. Цену не запоминаем: иначе когда размеры вернутся,
                # цена совпадёт с запомненной и карточка не придёт уже никогда.
                log.info("%s без размеров — вернусь к нему позже", it.sku)
                continue

            reason = ("Новая скидка" if prev is None
                      else f"Цена упала (было {messages.money(prev)})")
            # Не дошло ни до кого — не запоминаем, попробуем на следующем прогоне.
            # Дошло хотя бы до одного — запоминаем, иначе остальные получат дубль.
            if not await broadcast(bot, chat_ids, it, info, reason, db):
                log.warning("карточка %s не дошла ни до кого — вернусь позже", it.sku)
                continue

            # Карточка уже собрана целиком — кладём её и в витрину для /start,
            # это бесплатно: ни одного лишнего запроса.
            storage.save_deal(db, it.sku, it.name, it.url, it.price, it.old_price,
                              info["color"], ", ".join(info["sizes"]))
            storage.remember(db, it.sku, it.price)
            db.commit()
            sent += 1
            await asyncio.sleep(config.SEND_PAUSE_SEC)

        # Витрина для /start: обновляем всегда, даже если рассылать было нечего.
        try:
            await refresh_deals(client, db, items)
        except Exception:
            log.exception("витрину обновить не удалось")

        if first_run:
            await notify(bot, chat_ids, messages.FIRST_RUN_TEXT.format(
                n=len(items), minutes=config.INTERVAL_MIN))
    return sent
