"""Роль: режимы запуска. Собирает бота, выбирает сценарий, закрывает соединение.

Кто вызывает: bot.py (точка входа), флагом из командной строки.
Что править здесь: поведение режимов и обработку /start при живом боте.
Сам обход сайта и отбор скидок — в checker.py.

Три режима:
  (без флага)  живёт постоянно: слушает /start и проверяет сайт раз в INTERVAL_MIN.
               Для запуска на своём компе — нужен включённый компьютер.
  --once       разобрать накопившиеся команды, обойти сайт, выйти.
               Это главный режим: его раз в час запускает puma.yml.
  --answer     только разобрать команды, без обхода сайта. Быстрый, раз в 5 минут
               (start.yml), потому что /start иначе ждал бы ответа до часа.

Важно: в режимах --once и --answer chat id берётся из настроек (секрет CHAT_ID),
а не из сообщения. Рассылка скидок НЕ зависит от того, писал ли кто-то /start.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from . import config
from .checker import check
from .sender import answer_start, handle_pending

log = logging.getLogger("puma")


async def loop(bot: Bot, chat_id: int):
    while True:
        try:
            await check(bot, chat_id)
        except Exception:
            log.exception("проверка сорвалась")
        await asyncio.sleep(config.INTERVAL_MIN * 60)


async def run_answer(chat_id: int):
    bot = Bot(config.BOT_TOKEN)
    try:
        await handle_pending(bot, chat_id)
    finally:
        await bot.session.close()


async def run_once(chat_id: int):
    bot = Bot(config.BOT_TOKEN)
    try:
        # Сначала команды, потом обход. Ошибка в витрине по /start не отменяет
        # проверку скидок — handle_pending гасит её внутри себя.
        await handle_pending(bot, chat_id)
        n = await check(bot, chat_id)
        log.info("отправлено: %d", n)
    finally:
        await bot.session.close()


async def run_forever():
    chat_id = config.load_chat_id()
    bot = Bot(config.BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(m: Message):
        nonlocal chat_id
        if chat_id and m.chat.id != chat_id:
            return
        first_time = not chat_id
        if first_time:
            chat_id = m.chat.id
            config.save_chat_id(chat_id)
        await answer_start(bot, chat_id)
        if first_time:
            asyncio.create_task(loop(bot, chat_id))

    if chat_id:
        asyncio.create_task(loop(bot, chat_id))
    else:
        log.warning("CHAT_ID пуст: напиши боту /start, он сам всё настроит")
    await dp.start_polling(bot)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN. Вставь токен от @BotFather в файл .env и запусти снова.")
    if "--once" in sys.argv or "--answer" in sys.argv:
        chat_id = config.load_chat_id()
        if not chat_id:
            raise SystemExit("Нет CHAT_ID — этому режиму он обязателен.")
        asyncio.run(run_answer(chat_id) if "--answer" in sys.argv else run_once(chat_id))
    else:
        asyncio.run(run_forever())
