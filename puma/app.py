"""Роль: режимы запуска. Собирает бота, выбирает сценарий, закрывает соединение.

Кто вызывает: bot.py (точка входа), флагом из командной строки.
Что править здесь: поведение режимов и список получателей.
Сам обход сайта и отбор скидок — в checker.py.

Три режима:
  (без флага)  живёт постоянно: слушает /start и проверяет сайт раз в INTERVAL_MIN.
               Для запуска на своём компе — нужен включённый компьютер.
  --once       обойти сайт и выйти. Это главный режим, раз в час (puma.yml).
               Команды из чата он НЕ разбирает — этим занят --answer.
  --answer     только разобрать команды, без обхода сайта. Быстрый, раз в минуту
               (start.yml): ответ на /start занимает ~31 секунду.

Команды: /start — подписаться и получить витрину; /who — список подписчиков,
отвечает только владельцу.

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
from .sender import answer_start, chat_name, handle_pending, send_text

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

    В getUpdates этот режим намеренно не лезет: команды забирает --answer, и
    делает это раз в минуту. Если бы оба прогона читали чат, они могли бы
    вытащить один и тот же /start и ответить витриной дважды.
    """
    chat_ids = recipients()
    if not chat_ids:
        log.warning("некому слать: ни CHAT_ID, ни подписчиков. Напиши боту /start.")
        return
    bot = Bot(config.BOT_TOKEN)
    try:
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
        name = chat_name(m.chat)
        if storage.add_subscriber(db, m.chat.id, name):
            log.info("новый подписчик: %s (%s)", m.chat.id, name or "имя неизвестно")
        await answer_start(bot, m.chat.id)

    @dp.message(Command("who"))
    async def who(m: Message):
        # Список получателей показываем только владельцу.
        owner = config.load_chat_id()
        if m.chat.id != owner:
            return
        await send_text(bot, m.chat.id, messages.subs_list(
            storage.subscribers_full(db), owner))

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
