"""Роль: режимы запуска. Собирает бота, выбирает сценарий, закрывает соединение.

Кто вызывает: bot.py (точка входа), флагом из командной строки.
Что править здесь: поведение режимов и список получателей.
Сам обход сайта и отбор скидок — в checker.py.

ГЛАВНОЕ ПРО РОЛИ. Скидки ищет и рассылает Cloudflare Worker: он просыпается
раз в минуту и доводит задержку до нескольких минут. Python здесь остался для
двух вещей — суточной сверки и запасной рассылки, если Worker замолчит.

Четыре режима:
  --audit      суточная сверка индекса с живым сайтом (puma.yml). Ничего не
               рассылает, пока Worker жив. Если молчит — включает --once сам.
  --once       полный обход сайта и рассылка. ЗАПАСНОЙ путь, в обычной жизни
               не работает. Оставлен нетронутым нарочно: это страховка.
  --answer     разобрать команды из getUpdates. Сейчас бесполезен: при активном
               webhook Telegram отдаёт 409. Оставлен на случай снятия webhook.
  (без флага)  живёт постоянно: слушает /start и проверяет сайт раз в
               INTERVAL_MIN. Для запуска на своём компе.

Команды: /start — подписаться и сразу получить витрину; /who — статистика,
отвечает только админу (ADMIN_ID). На /start в бою отвечает Worker.

Ни один обработчик не парсит сайт. Сбор карточек — дело фонового обхода: в
постоянном режиме его крутит loop() ниже, в бою — крон Cloudflare.

Кому уходят скидки: подписка открытая. Любой, кто нажал /start, попадает в
таблицу subs и дальше получает карточки сам. Плюс к ним всегда владелец из
настройки CHAT_ID — его из подписки не выкинуть.

Откуда берутся новые подписчики. На /start отвечает Worker, и человек попадает
сначала в его хранилище. Режимы --audit и --once забирают этот список через
subs_sync. Пока webhook включён, getUpdates отдаёт 409, поэтому сам Python
новых подписчиков не увидит — только через Worker.
"""
import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from . import audit, checker, config, messages, storage, subs_sync
from .checker import check
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
    """Полный обход сайта и рассылка — ЗАПАСНОЙ путь.

    В обычной жизни этот код не работает: скидки ищет Worker, и делает это раз в
    минуту. Сюда управление попадает, только когда Worker замолчал (см.
    run_audit) или когда бот запускают руками.

    Он намеренно оставлен нетронутым. Пока Worker жив, эта ветка — страховка:
    что бы ни случилось на Cloudflare, бот скатывается к прежнему поведению с
    часовой задержкой, а не замолкает совсем.
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
        await bot.session.close()


async def run_audit():
    """Суточная сверка. Ничего не рассылает, пока Worker жив.

    Четыре шага, и каждый следующий не зависит от успеха предыдущего:
      1. забрать подписчиков и память Worker'а к себе в базу;
      2. сверить цены индекса с живым сайтом и закричать при расхождении;
      3. если Worker молчит дольше STALE_HOURS — закричать и включить
         запасную рассылку, чтобы скидки продолжали приходить;
      4. отметиться у внешнего монитора (это делает сам воркфлоу).

    Пункт 3 — причина, по которой смерть Worker'а не оставляет тебя без бота:
    задержка вырастает до суток, но поток скидок не прекращается.
    """
    bot = Bot(config.BOT_TOKEN)
    db = storage.db_init()
    fallback = False
    try:
        try:
            await subs_sync.pull(db)
        except Exception:
            log.exception("подписчиков из Worker забрать не вышло")

        # Память Worker'а к себе: без неё запасная рассылка посчитала бы новыми
        # все скидки разом и завалила чат.
        silence = None
        if config.WORKER_URL and config.SUBS_TOKEN:
            try:
                state = await audit.fetch_worker_state(config.WORKER_URL, config.SUBS_TOKEN)
                audit.sync_seen(db, state.get("seen"))
                # Ноль значит «Worker отвечает, но не обошёл каталог ни разу» —
                # свежеразвёрнутый, с вычищенным KV или со сломанным кроном.
                # Считать это нормой нельзя: снаружи такой бот выглядит живым,
                # а скидок не присылает. Замечено на боевом прогоне 25.09.2026.
                last = float(state.get("last_sweep_ts") or 0)
                silence = (time.time() - last) / 3600 if last else float("inf")
            except Exception:
                log.exception("состояние Worker получить не вышло")
                silence = float("inf")   # не ответил — считаем молчащим
        else:
            log.info("Worker не настроен: работаю как обычный обход")
            fallback = True

        async with new_client() as client:
            try:
                report = await audit.run(client)
                text = audit.verdict(report)
                if text:
                    await checker.warn_once_a_day(bot, recipients(), db, "last_warn_audit", text)
            except Exception:
                log.exception("сверка сорвалась")

        if silence is not None and silence > config.STALE_HOURS:
            log.warning("Worker молчит %.1f ч — включаю запасную рассылку", silence)
            await checker.warn_once_a_day(bot, recipients(), db, "last_warn_stale",
                                          audit.stale_text(silence))
            fallback = True
    finally:
        await bot.session.close()

    if fallback:
        await run_once()


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
    if "--audit" in sys.argv:
        asyncio.run(run_audit())
    elif "--answer" in sys.argv:
        asyncio.run(run_answer())
    elif "--once" in sys.argv:
        asyncio.run(run_once())
    else:
        asyncio.run(run_forever())
