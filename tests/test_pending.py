"""Команды из телеги: /start и /who. Запуск: python -m tests.test_pending

Главное, что здесь проверяется: обработчики отвечают из базы и НЕ ходят в сеть.
"""
import asyncio
import logging
import os
import sys
import tempfile
import types

logging.disable(logging.CRITICAL)  # бот кричит в лог об ошибках — тесту это шум

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import config, messages, sender, storage  # noqa: E402
from puma.models import Item  # noqa: E402

CHAT = 625622586
STRANGER = 999


def upd(uid, text, chat_id=CHAT, username=None, user_id=None, first_name=None):
    """Обновление от телеграма. user_id отличается от chat_id только в группах."""
    chat = types.SimpleNamespace(id=chat_id, username=username,
                                 first_name=first_name, last_name=None, title=None)
    msg = types.SimpleNamespace(text=text, chat=chat,
                                from_user=types.SimpleNamespace(id=user_id or chat_id))
    return types.SimpleNamespace(update_id=uid, message=msg)


class FakeBot:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []
        self.sent = []

    async def get_updates(self, **kw):
        self.calls.append(kw)
        return [] if "offset" in kw else self.updates

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def fresh_db():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.CHAT_ID = CHAT       # владелец задан явно, а не через chat_id.txt
    config.ADMIN_ID = 0         # значит админ = владелец
    config.SEND_PAUSE_SEC = 0   # тесту незачем ждать по-настоящему
    config.PAGE_PAUSE_SEC = 0
    return storage.db_init()


def deal(n, price=1000):
    return (f"s_{n}", f"Кросівки {n}", f"https://ua.puma.com/{n}.html",
            price, price * 2, "білий", "41, 42")


async def run(updates):
    bot = FakeBot(updates)
    answered = []

    async def fake_answer(bot_, chat_id):
        answered.append(chat_id)

    # подмену обязательно возвращаем на место, иначе она течёт в следующие тесты
    original = sender.answer_start
    sender.answer_start = fake_answer
    try:
        result = await sender.handle_pending(bot)
    finally:
        sender.answer_start = original
    return bot, answered, result


def test_start_subscribes():
    fresh_db()

    # пусто: ничего не шлём, offset не трогаем
    bot, answered, new = asyncio.run(run([]))
    assert answered == [] and new == [] and len(bot.calls) == 1

    # /start: отвечаем, подтверждаем приём и записываем в подписчики
    bot, answered, new = asyncio.run(run([upd(10, "привет"), upd(11, "/start")]))
    assert answered == [CHAT] and new == [CHAT] and bot.calls[1]["offset"] == 12

    # /start@имя_бота тоже считается, но подписчик уже не новый
    bot, answered, new = asyncio.run(run([upd(20, "/start@ClothessSalee_bot")]))
    assert answered == [CHAT] and new == []

    # чужой чат: подписка открытая, поэтому его тоже берём
    bot, answered, new = asyncio.run(run([upd(30, "/start", chat_id=STRANGER)]))
    assert answered == [STRANGER] and new == [STRANGER]

    # обычный текст: только подтверждение
    bot, answered, new = asyncio.run(run([upd(40, "как дела")]))
    assert answered == [] and new == [] and bot.calls[1]["offset"] == 41

    # два человека в одной пачке — отвечаем каждому по одному разу
    bot, answered, new = asyncio.run(run(
        [upd(50, "/start", chat_id=777), upd(51, "/start", chat_id=777), upd(52, "/start")]))
    assert answered == [777, CHAT] and new == [777]

    # имя и @username запоминаются и обновляются при повторном /start
    asyncio.run(run([upd(60, "/start", chat_id=555, username="vasya", first_name="Вася")]))
    db = storage.db_init()
    by_id = {c: (n, u) for c, _, n, u in storage.subscribers_recent(db, 99)}
    assert by_id[555] == ("Вася", "@vasya"), by_id[555]
    asyncio.run(run([upd(61, "/start", chat_id=555, username="vasya2", first_name="Вася")]))
    by_id = {c: (n, u) for c, _, n, u in storage.subscribers_recent(db, 99)}
    assert by_id[555] == ("Вася", "@vasya2"), by_id[555]

    assert storage.subscribers_count(db) == 4, storage.subscribers_recent(db, 99)


def test_who_is_admin_only():
    """Админ получает статистику, обычный юзер — отказ, и оба мгновенно."""
    db = fresh_db()
    storage.add_subscriber(db, 4242, "Иван", "@ivan")

    bot, answered, _ = asyncio.run(run([upd(70, "/who")]))
    assert len(bot.sent) == 1, bot.sent
    text = bot.sent[0][1]
    assert "Пользователей в базе: 1" in text and "@ivan" in text and "4242" in text, text
    assert answered == []  # /who не подписывает и не шлёт витрину

    # обычный юзер получает отказ, а не тишину
    bot, answered, _ = asyncio.run(run([upd(71, "/who", chat_id=STRANGER)]))
    assert bot.sent == [(STRANGER, messages.NO_ACCESS)], bot.sent

    # проверка идёт по user_id, а не по chat_id: в группе это разные числа
    bot, answered, _ = asyncio.run(run([upd(72, "/who", chat_id=-100500, user_id=STRANGER)]))
    assert bot.sent == [(-100500, messages.NO_ACCESS)], bot.sent

    # ADMIN_ID перебивает владельца
    config.ADMIN_ID = STRANGER
    bot, answered, _ = asyncio.run(run([upd(73, "/who", chat_id=STRANGER)]))
    assert "Пользователей в базе" in bot.sent[0][1], bot.sent
    bot, answered, _ = asyncio.run(run([upd(74, "/who")]))
    assert bot.sent == [(CHAT, messages.NO_ACCESS)], bot.sent
    config.ADMIN_ID = 0


def test_who_survives_broken_ack():
    """Ответ уходит ДО подтверждения приёма: иначе прерванный прогон съедал бы
    команду навсегда."""
    db = fresh_db()
    storage.add_subscriber(db, 4242, "Иван", "@ivan")

    class AckBroken(FakeBot):
        async def get_updates(self, **kw):
            self.calls.append(kw)
            if "offset" in kw:
                raise RuntimeError("телеграм не принял подтверждение")
            return self.updates

    async def go():
        bot = AckBroken([upd(80, "/who")])
        await sender.handle_pending(bot)
        return bot

    bot = asyncio.run(go())
    assert len(bot.sent) == 1 and "@ivan" in bot.sent[0][1], bot.sent


def test_who_falls_back_to_plain_text():
    """Если Телеграм не принял разметку, ответ уходит без неё, а не теряется."""
    db = fresh_db()
    storage.add_subscriber(db, 4242, "Иван", "@ivan")
    tries = []

    class PickyBot(FakeBot):
        async def send_message(self, chat_id, text, **kw):
            tries.append(kw.get("parse_mode"))
            if kw.get("parse_mode") == "HTML":
                raise RuntimeError("can't parse entities")
            self.sent.append((chat_id, text))

    async def go():
        bot = PickyBot()
        await sender.show_users(bot, CHAT, db, CHAT)
        return bot

    bot = asyncio.run(go())
    assert tries == ["HTML", None], tries
    assert len(bot.sent) == 1, bot.sent
    assert "@ivan" in bot.sent[0][1] and "<" not in bot.sent[0][1], bot.sent[0][1]


def test_showcase_reads_db_only():
    """Витрина берёт готовые карточки из базы и не ходит в сеть."""
    db = fresh_db()
    for n in range(9):
        storage.save_deal(db, *deal(n))
    db.commit()

    shown = []

    async def fake_send(bot, chat_id, it, info, reason):
        shown.append((it.sku, info["sizes"], info["color"], reason))

    sender.send = fake_send
    config.START_ITEMS = 5

    n = asyncio.run(sender.send_top(FakeBot(), CHAT))
    assert n == 5 and len(shown) == 5, (n, shown)
    assert shown[0][1] == ["41", "42"] and shown[0][2] == "білий", shown[0]
    assert shown[0][3] == "Сейчас на распродаже", shown[0]

    # сеть недоступна в принципе: модуль отправки не знает про парсер
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "puma", "sender.py"), encoding="utf-8").read()
    assert "scraper" not in src, "sender.py снова тянет парсер — /start станет медленным"


def test_start_when_showcase_empty():
    """Пустая витрина: честное сообщение вместо тишины."""
    fresh_db()

    async def go():
        bot = FakeBot()
        await sender.answer_start(bot, CHAT)
        return bot

    bot = asyncio.run(go())
    assert bot.sent == [(CHAT, messages.DEALS_EMPTY)], bot.sent


def test_broadcast_to_many():
    """Одна карточка уходит всем; кто заблокировал бота — выпадает из подписки."""
    from aiogram.exceptions import TelegramForbiddenError

    db = fresh_db()
    for cid in (111, 222, 333):
        storage.add_subscriber(db, cid)

    got = []

    async def fake_send(bot, chat_id, it, info, reason):
        if chat_id == 222:
            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")
        got.append(chat_id)

    sender.send = fake_send
    it = Item("x_1", "Кросівки X", "https://ua.puma.com/x.html", 100, 200)

    n = asyncio.run(sender.broadcast(None, [111, 222, 333], it, {"sizes": ["41"]}, "повод", db))
    assert n == 2 and got == [111, 333], (n, got)
    assert storage.subscribers(db) == [111, 333], storage.subscribers(db)

    # до кого не дошло вообще — ноль, checker по нему не станет запоминать цену
    async def all_fail(bot, chat_id, it_, info, reason):
        raise RuntimeError("телеграм лежит")

    sender.send = all_fail
    assert asyncio.run(sender.broadcast(None, [111, 333], it, {"sizes": ["41"]}, "повод", db)) == 0


if __name__ == "__main__":
    test_start_subscribes()
    test_who_is_admin_only()
    test_who_survives_broken_ack()
    test_who_falls_back_to_plain_text()
    test_showcase_reads_db_only()
    test_start_when_showcase_empty()
    test_broadcast_to_many()
    print("pending OK")
