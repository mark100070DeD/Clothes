"""Роль: режимы запуска. Собирает бота, выбирает сценарий, закрывает соединение.

Кто вызывает: bot.py (точка входа), флагом из командной строки.
Что править здесь: поведение режимов и список получателей.
Сам обход сайта и отбор скидок — в checker.py.

Три режима:
  (без флага)  живёт постоянно: слушает /start и проверяет сайт раз в INTERVAL_MIN.
               Для запуска на своём компе — нужен включённый компьютер.
  --once       обойти сайт, выгрузить data/latest.json и выйти (puma.yml).
               Чат не читает.
  --answer     только разобрать команды, без обхода сайта (start.yml).

Чат читает ТОЛЬКО --answer. Если бы в getUpdates лез и часовой обход, два
прогона могли бы вытащить одно и то же обновление и ответить витриной дважды.
Поэтому у воркфлоу разные очереди concurrency и разные обязанности.

Быстрее всего команды отрабатывают в постоянном режиме (без флага): бот висит на
связи и отвечает за секунду. На GitHub ответ приходит тогда, когда случится
прогон, а его расписание ненадёжно — см. комментарий в start.yml.

Команды: /start — подписаться и мгновенно получить витрину из базы;
/who — статистика пользователей, отвечает только админу (ADMIN_ID).

Ни один обработчик не парсит сайт. Сбор карточек — дело фонового обхода: в этом
режиме его крутит loop() ниже, на GitHub — часовой воркфлоу.

Кому уходят скидки: подписка открытая. Любой, кто нажал /start, попадает в
таблицу subs и дальше получает карточки сам. Плюс к ним всегда владелец из
настройки CHAT_ID — его из подписки не выкинуть.

Откуда берутся новые подписчики. На /start отвечает Worker на Cloudflare, и
человек попадает сначала в его хранилище. Режим --once забирает этот список
через subs_sync и переносит в базу. Пока webhook включён, getUpdates отдаёт 409,
поэтому сам Python новых подписчиков не увидит — только через Worker.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from . import config, messages, storage, subs_sync
from .checker import check
from .export import export_latest
from .scraper import new_client
from .sender import (answer_start, chat_person, handle_pending,
                     send_with_fallback, show_users)

log = logging.getLogger("puma")


def recipients() -> list[int]:
    """Кому слать: владелец из CHAT_ID плюс все, кто нажал /start.

    Владелец идёт первым и присутствует даже если его нет в subs — иначе
    достаточно было бы одного случайного сбоя, чтобы бот замолчал для хозяина.
    """
    db = storage.db_init()
    out = storage.subscribers(db)
    owner = config.load_chat_id()
    if owner and owner not in out:
        out.insert(0, owner)
    return out


async def loop(bot: Bot):
    while True:
        try:
            chat_ids = recipients()
            if chat_ids:
                await check(bot, chat_ids)
            else:
                log.warning("некому слать: напиши боту /start")
        except Exception:
            log.exception("проверка сорвалась")
        await asyncio.sleep(config.INTERVAL_MIN * 60)


async def run_answer():
    bot = Bot(config.BOT_TOKEN)
    try:
        await handle_pending(bot)
    finally:
        await bot.session.close()


async def run_once():
    """Только обход сайта.

    В getUpdates не лезем намеренно: чат читает --answer, и делает это в своей
    очереди. Если бы оба прогона читали чат, они могли бы вытащить одно и то же
    обновление и ответить витриной дважды.
    """
    bot = Bot(config.BOT_TOKEN)
    try:
        # Сначала забрать тех, кто нажал /start у Worker'а: они появляются в его
        # хранилище, а не в базе. Сбой на этом шаге рассылку не отменяет —
        # старые подписчики своё получат.
        try:
            await subs_sync.pull(storage.db_init())
        except Exception:
            log.exception("подписчиков из Worker забрать не вышло")

        chat_ids = recipients()
        if chat_ids:
            log.info("получателей: %d", len(chat_ids))
            n = await check(bot, chat_ids)
            log.info("отправлено: %d", n)
        else:
            log.warning("некому слать: ни CHAT_ID, ни подписчиков. Напиши боту /start.")
    finally:
        # Выгрузка для Cloudflare Worker нужна даже если рассылка сорвалась:
        # именно на ней держится мгновенный ответ на /start.
        try:
            async with new_client() as client:
                await export_latest(client)
        except Exception:
            log.exception("выгрузка latest.json сорвалась")
        await bot.session.close()


async def run_forever():
    bot = Bot(config.BOT_TOKEN)
    dp = Dispatcher()
    db = storage.db_init()

    @dp.message(Command("start"))
    async def start(m: Message):
        """Мгновенно: записать пользователя и отдать готовые карточки из базы."""
        name, username = chat_person(m.chat)
        if storage.add_subscriber(db, m.chat.id, name, username):
            log.info("новый подписчик: %s %s %s", m.chat.id, name or "?", username or "")
        await answer_start(bot, m.chat.id)

    @dp.message(Command("who"))
    async def who(m: Message):
        """Мгновенно: COUNT и последние пользователи из базы. Только админу."""
        admin = config.admin_id()
        user_id = m.from_user.id if m.from_user else m.chat.id
        if user_id != admin:
            log.info("/who от %s — доступа нет", user_id)
            await send_with_fallback(bot, m.chat.id, messages.NO_ACCESS)
            return
        await show_users(bot, m.chat.id, db, admin)

    asyncio.create_task(loop(bot))
    await dp.start_polling(bot)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN. Вставь токен от @BotFather в файл .env и запусти снова.")
    if "--answer" in sys.argv:
        asyncio.run(run_answer())
    elif "--once" in sys.argv:
        asyncio.run(run_once())
    else:
        asyncio.run(run_forever())
