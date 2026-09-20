"""Разбор команд из телеги в режиме GitHub Actions. Запуск: python -m tests.test_pending"""
import asyncio
import logging
import os
import sys
import tempfile
import types

logging.disable(logging.CRITICAL)  # бот кричит в лог об ошибках — тесту это шум

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import config, sender, storage  # noqa: E402
from puma.models import Item  # noqa: E402

CHAT = 625622586


def upd(uid, text, chat_id=CHAT, username=None):
    chat = types.SimpleNamespace(id=chat_id, username=username,
                                 first_name=None, last_name=None, title=None)
    return types.SimpleNamespace(update_id=uid, message=types.SimpleNamespace(text=text, chat=chat))


class FakeBot:
    def __init__(self, updates):
        self.updates = updates
        self.calls = []
        self.sent = []

    async def get_updates(self, **kw):
        self.calls.append(kw)
        return [] if "offset" in kw else self.updates

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


async def run(updates):
    bot = FakeBot(updates)
    answered = []

    async def fake_answer(bot_, chat_id):
        answered.append(chat_id)

    sender.answer_start = fake_answer
    fresh = await sender.handle_pending(bot)
    return bot, answered, fresh


def test_all():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")  # своя пустая база
    config.CHAT_ID = CHAT  # владелец задан явно, а не через chat_id.txt

    # пусто: ничего не шлём, offset не трогаем
    bot, answered, fresh = asyncio.run(run([]))
    assert answered == [] and fresh == [] and len(bot.calls) == 1

    # /start: отвечаем, подтверждаем приём и записываем в подписчики
    bot, answered, fresh = asyncio.run(run([upd(10, "привет"), upd(11, "/start")]))
    assert answered == [CHAT] and fresh == [CHAT] and bot.calls[1]["offset"] == 12

    # /start@имя_бота тоже считается, но подписчик уже не новый
    bot, answered, fresh = asyncio.run(run([upd(20, "/start@ClothessSalee_bot")]))
    assert answered == [CHAT] and fresh == []

    # чужой чат: подписка открытая, поэтому его тоже берём
    bot, answered, fresh = asyncio.run(run([upd(30, "/start", chat_id=999)]))
    assert answered == [999] and fresh == [999] and bot.calls[1]["offset"] == 31

    # обычный текст: только подтверждение
    bot, answered, fresh = asyncio.run(run([upd(40, "как дела")]))
    assert answered == [] and fresh == [] and bot.calls[1]["offset"] == 41

    # два разных человека в одной пачке — отвечаем каждому по одному разу
    bot, answered, fresh = asyncio.run(run(
        [upd(50, "/start", chat_id=777), upd(51, "/start", chat_id=777), upd(52, "/start")]))
    assert answered == [777, CHAT] and fresh == [777]

    db = storage.db_init()
    assert sorted(storage.subscribers(db)) == sorted([CHAT, 999, 777]), storage.subscribers(db)

    # имя запоминается и обновляется при повторном /start
    asyncio.run(run([upd(60, "/start", chat_id=555, username="vasya")]))
    assert dict((c, n) for c, _, n in storage.subscribers_full(db))[555] == "@vasya"
    asyncio.run(run([upd(61, "/start", chat_id=555, username="vasya_new")]))
    assert dict((c, n) for c, _, n in storage.subscribers_full(db))[555] == "@vasya_new"


def test_showcase_limit():
    """Витрина по /start шлёт не больше config.START_ITEMS карточек."""
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.START_ITEMS = 5
    config.SEND_PAUSE_SEC = 0  # тесту незачем ждать по-настоящему

    page = ('<html><head><title>X | Колір: Білий | White | Puma</title></head><body>'
            '<li class="size-list__item " data-available="1" data-label="41"></li></body></html>')

    class Resp:
        text = page

        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return Resp()

    shown = []

    async def fake_first_page(client):
        # сайт отдал девять товаров — заметно больше лимита
        return [Item(f"s_{i}", f"Кросівки {i}", f"https://ua.puma.com/{i}.html", 100, 200)
                for i in range(9)]

    async def fake_send(bot, chat_id, it, info, reason):
        shown.append(it.sku)

    sender.fetch_first_page = fake_first_page
    sender.new_client = lambda: Client()
    sender.send = fake_send

    n = asyncio.run(sender.send_top(FakeBot([]), CHAT))
    assert n == 5 and len(shown) == 5, (n, shown)

    # показанное запомнено, чтобы часовой обход не прислал это как «новую скидку»
    db = storage.db_init()
    assert all(storage.last_price(db, s) == 100 for s in shown), shown


def test_broadcast_to_many():
    """Одна карточка уходит всем; кто заблокировал бота — выпадает из подписки."""
    from aiogram.exceptions import TelegramForbiddenError

    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.SEND_PAUSE_SEC = 0
    db = storage.db_init()
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


def test_who_only_for_owner():
    """/who показывает список подписчиков, и только владельцу."""
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.CHAT_ID = CHAT
    db = storage.db_init()
    storage.add_subscriber(db, 4242, "@friend")

    bot, answered, fresh = asyncio.run(run([upd(70, "/who")]))
    assert len(bot.sent) == 1, bot.sent
    text = bot.sent[0][1]
    assert "Подписчиков: 1" in text and "@friend" in text and "4242" in text, text
    assert answered == [] and fresh == []  # /who не подписывает и не шлёт витрину

    # чужой чат списка не получает
    bot, answered, fresh = asyncio.run(run([upd(71, "/who", chat_id=999)]))
    assert bot.sent == [], bot.sent


def test_who_survives_broken_ack():
    """Ответ на /who уходит ДО подтверждения приёма: иначе прерванный прогон
    съедал бы команду навсегда."""
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.CHAT_ID = CHAT
    storage.add_subscriber(storage.db_init(), 4242, "@friend")

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
    assert len(bot.sent) == 1 and "@friend" in bot.sent[0][1], bot.sent


def test_who_falls_back_to_plain_text():
    """Если Телеграм не принял разметку, список уходит без неё, а не теряется."""
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    config.CHAT_ID = CHAT
    db = storage.db_init()
    storage.add_subscriber(db, 4242, "@friend")

    tries = []

    class PickyBot(FakeBot):
        async def send_message(self, chat_id, text, **kw):
            tries.append(kw.get("parse_mode"))
            if kw.get("parse_mode") == "HTML":
                raise RuntimeError("can't parse entities")
            self.sent.append((chat_id, text))

    async def go():
        bot = PickyBot([])
        await sender.show_subs(bot, CHAT, db, CHAT)
        return bot

    bot = asyncio.run(go())
    assert tries == ["HTML", None], tries
    assert len(bot.sent) == 1, bot.sent
    text = bot.sent[0][1]
    assert "@friend" in text and "<" not in text, text  # разметка вычищена


if __name__ == "__main__":
    test_all()
    test_showcase_limit()
    test_broadcast_to_many()
    test_who_only_for_owner()
    test_who_survives_broken_ack()
    test_who_falls_back_to_plain_text()
    print("pending OK")
