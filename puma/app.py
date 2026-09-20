"""Роль: режимы запуска. Собирает бота, выбирает сценарий, закрывает соединение.

Кто вызывает: bot.py (точка входа), флагом из командной строки.
Что править здесь: поведение режимов и список получателей.
Сам обход сайта и отбор скидок — в checker.py.

Три режима:
  (без флага)  живёт постоянно: слушает /start и проверяет сайт раз в INTERVAL_MIN.
               Для запуска на своём компе — нужен включённый компьютер.
  --once       разобрать команды и обойти сайт (puma.yml).
  --answer     только разобрать команды, без обхода сайта (start.yml) — быстрый
               ответ на /start, ~31 секунду вместо двух минут.

Команды разбирают ОБА режима, и это сделано намеренно: GitHub выполняет
расписание start.yml крайне ненадёжно (см. комментарий в start.yml), поэтому
полагаться только на него нельзя. Чтобы два прогона не вытащили одну и ту же
команду и не ответили дважды, оба воркфлоу стоят в одной очереди concurrency.

Команды: /start — подписаться и мгновенно получить витрину из базы;
/who — статистика пользователей, отвечает только админу (ADMIN_ID).

Ни один обработчик не парсит сайт. Сбор карточек — дело фонового обхода: в этом
режиме его крутит loop() ниже, на GitHub — часовой воркфлоу.

Кому уходят скидки: подписка открытая. Любой, кто нажал /start, попадает в
таблицу subs и дальше получает карточки сам. Плюс к ним всегда владелец из
настройки CHAT_ID — его из подписки не выкинуть.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from . import config, messages, storage
from .checker import check
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
    """Команды из чата, затем обход сайта.

    Команды разбираем и здесь, а не только в --answer: расписание start.yml
    GitHub не выполняет вовсе, а расписание этого воркфлоу выполняет — пусть
    и с провалами по несколько часов. Иначе команда ждала бы пуша.
    """
    bot = Bot(config.BOT_TOKEN)
    try:
        # Ошибка в разборе команд не должна отменять проверку скидок.
        try:
            await handle_pending(bot)
        except Exception:
            log.exception("разбор команд сорвался")

        chat_ids = recipients()   # список уже с учётом только что подписавшихся
        if not chat_ids:
            log.warning("некому слать: ни CHAT_ID, ни подписчиков. Напиши боту /start.")
            return
        log.info("получателей: %d", len(chat_ids))
        n = await check(bot, chat_ids)
        log.info("отправлено: %d", n)
    finally:
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
