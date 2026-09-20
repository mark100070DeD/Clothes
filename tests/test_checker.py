"""Главная логика: что бот шлёт, а что молча запоминает. Запуск: python -m tests.test_checker"""
import asyncio
import os
import sys
import tempfile

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import checker, config, storage  # noqa: E402
from puma.models import Item  # noqa: E402

PAGE = '<html><head><title>X | Колір: Білий | White | Puma</title></head><body>' \
       '<li class="size-list__item " data-available="1" data-label="41"></li></body></html>'


class FakeResponse:
    text = PAGE


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        return FakeResponse()


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)


def item(sku, price, old=1000):
    return Item(sku, f"Кросівки {sku}", f"https://ua.puma.com/{sku}.html", price, old)


def run_check(items):
    bot = FakeBot()
    cards = []

    async def fake_fetch(client):
        return items

    async def fake_send(bot_, chat_id, it, info, reason):
        cards.append((it.sku, reason))

    checker.fetch_sale = fake_fetch
    checker.send = fake_send
    checker.new_client = lambda: FakeClient()
    n = asyncio.run(checker.check(bot, 1))
    return n, cards, bot


def test_all():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "sub", "t.db")  # папка создаётся сама

    # первый запуск: всё запоминаем молча, шлём только сводку
    n, cards, bot = run_check([item("a_1", 500), item("b_2", 600)])
    assert n == 0 and cards == [] and "Запомнил 2" in bot.messages[0]

    # те же товары по тем же ценам: тишина
    n, cards, bot = run_check([item("a_1", 500), item("b_2", 600)])
    assert n == 0 and cards == [] and bot.messages == []

    # новый товар и подешевевший старый
    n, cards, bot = run_check([item("a_1", 400), item("b_2", 600), item("c_3", 300)])
    assert n == 2
    reasons = dict(cards)
    assert reasons["c_3"] == "Новая скидка"
    assert reasons["a_1"].startswith("Цена упала (было 500")

    # подорожание не шлётся
    n, cards, bot = run_check([item("a_1", 450)])
    assert n == 0

    # сайт отдал пусто: сигнал о поломке, но не чаще раза в сутки
    n, cards, bot = run_check([])
    assert n == 0 and len(bot.messages) == 1 and "0 кроссовок" in bot.messages[0]
    n, cards, bot = run_check([])
    assert bot.messages == []

    # ценник в базе завышен — как в тесте доставки: бот должен прислать «цена упала»
    db = storage.db_init()
    storage.remember(db, "b_2", 900)
    db.commit()
    n, cards, bot = run_check([item("b_2", 600)])
    assert n == 1 and cards[0][1].startswith("Цена упала (было 900")


if __name__ == "__main__":
    test_all()
    print("checker OK")
