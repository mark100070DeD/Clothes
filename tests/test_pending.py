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


def upd(uid, text, chat_id=CHAT):
    msg = types.SimpleNamespace(text=text, chat=types.SimpleNamespace(id=chat_id))
    return types.SimpleNamespace(update_id=uid, message=msg)


class FakeBot:
    def __init__(self, updates):
        self.updates = updates
        self.calls = []

    async def get_updates(self, **kw):
        self.calls.append(kw)
        return [] if "offset" in kw else self.updates


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


if __name__ == "__main__":
    test_all()
    test_showcase_limit()
    test_broadcast_to_many()
    print("pending OK")
