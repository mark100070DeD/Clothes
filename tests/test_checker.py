"""Главная логика: что бот шлёт, а что молча запоминает. Запуск: python -m tests.test_checker"""
import asyncio
import logging
import os
import sys
import tempfile

logging.disable(logging.CRITICAL)  # бот кричит в лог о поломках — тесту это шум

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import checker, config, storage  # noqa: E402
from puma.models import Item  # noqa: E402

HEAD = '<html><head><title>X | Колір: Білий | White | Puma</title></head><body>'
PAGE = HEAD + '<li class="size-list__item " data-available="1" data-label="41"></li></body></html>'
SOLD_OUT = HEAD + '</body></html>'  # ни одного размера в наличии


class FakeResponse:
    def __init__(self, text=PAGE):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, page=PAGE):
        self.page = page

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        return FakeResponse(self.page)


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)


def item(sku, price, old=1000):
    return Item(sku, f"Кросівки {sku}", f"https://ua.puma.com/{sku}.html", price, old)


def fresh_db():
    """Своя пустая база на подтест, чтобы подтесты не влияли друг на друга."""
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "sub", "t.db")


def run_check(items, page=PAGE, fail_sku=None, fetch_error=None):
    bot = FakeBot()
    cards = []

    async def fake_fetch(client):
        if fetch_error:
            raise fetch_error
        return items

    async def fake_send(bot_, chat_id, it, info, reason):
        if it.sku == fail_sku:
            raise RuntimeError("телеграм не принял")
        cards.append((it.sku, reason))

    checker.fetch_sale = fake_fetch
    checker.send = fake_send
    checker.new_client = lambda: FakeClient(page)
    n = asyncio.run(checker.check(bot, 1))
    return n, cards, bot


def seed(items):
    """Провести первый (тихий) прогон, чтобы база перестала быть пустой."""
    run_check(items)


def test_basics():
    fresh_db()

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

    # ценник в базе завышен — как в тесте доставки: бот должен прислать «цена упала»
    db = storage.db_init()
    storage.remember(db, "b_2", 900)
    db.commit()
    n, cards, bot = run_check([item("b_2", 600)])
    assert n == 1 and cards[0][1].startswith("Цена упала (было 900")


def test_broken_site():
    fresh_db()
    seed([item("a_1", 500)])

    # сайт отдал пусто: сигнал о поломке, но не чаще раза в сутки
    n, cards, bot = run_check([])
    assert n == 0 and len(bot.messages) == 1 and "0 кроссовок" in bot.messages[0]
    n, cards, bot = run_check([])
    assert bot.messages == []


def test_site_unreachable():
    """Сайт не открылся: бот обязан предупредить в чат и уронить прогон."""
    fresh_db()
    seed([item("a_1", 500)])

    bot = FakeBot()

    async def boom(client):
        raise RuntimeError("HTTP 403")

    checker.fetch_sale = boom
    checker.new_client = lambda: FakeClient()

    crashed = ""
    try:
        asyncio.run(checker.check(bot, 1))
    except RuntimeError as e:
        crashed = str(e)
    assert "403" in crashed, "прогон должен упасть, чтобы в Actions осталась красная отметка"
    assert any("не отвечает" in m for m in bot.messages), bot.messages

    # второй раз в те же сутки про то же молчим
    quiet = FakeBot()
    try:
        asyncio.run(checker.check(quiet, 1))
    except RuntimeError:
        pass
    assert quiet.messages == [], quiet.messages


def test_sold_out_keeps_its_chance():
    """Товар без размеров не должен терять скидку навсегда."""
    fresh_db()
    seed([item("z_9", 500)])

    # распроданный товар: карточки нет
    n, cards, bot = run_check([item("new_1", 300)], page=SOLD_OUT)
    assert n == 0 and cards == []

    # цена в базе НЕ запомнена, иначе скидку уже не вернуть
    db = storage.db_init()
    assert storage.last_price(db, "new_1") is None, "цена распроданного товара попала в базу"

    # размеры вернулись, цена та же — карточка обязана прийти
    n, cards, bot = run_check([item("new_1", 300)])
    assert n == 1 and cards == [("new_1", "Новая скидка")], cards


def test_state_survives_failure():
    """Обрыв на середине не должен приводить к повторной рассылке."""
    fresh_db()
    seed([item("keep_1", 900), item("boom_2", 900)])

    # первая карточка уходит, на второй Телеграм ломается
    n, cards, bot = run_check([item("keep_1", 500), item("boom_2", 500)], fail_sku="boom_2")
    assert n == 1 and [c[0] for c in cards] == ["keep_1"]

    db = storage.db_init()
    assert storage.last_price(db, "keep_1") == 500, "отправленное не сохранилось -> будет дубль"
    assert storage.last_price(db, "boom_2") == 900, "неотправленное запомнилось -> скидка потеряна"

    # следующий прогон: keep_1 молчит, boom_2 приходит
    n, cards, bot = run_check([item("keep_1", 500), item("boom_2", 500)])
    assert n == 1 and [c[0] for c in cards] == ["boom_2"], cards


def test_unreadable_product_page_is_retried():
    """Страница товара не открылась — цену не запоминаем, пробуем позже."""
    fresh_db()
    seed([item("q_1", 900)])

    class Broken(FakeClient):
        async def get(self, url, **kw):
            raise RuntimeError("таймаут")

    bot = FakeBot()

    async def fake_fetch(client):
        return [item("q_1", 500)]

    checker.fetch_sale = fake_fetch
    checker.new_client = lambda: Broken()
    n = asyncio.run(checker.check(bot, 1))
    assert n == 0
    db = storage.db_init()
    assert storage.last_price(db, "q_1") == 900, "цена не должна меняться без отправки"


if __name__ == "__main__":
    test_basics()
    test_broken_site()
    test_site_unreachable()
    test_sold_out_keeps_its_chance()
    test_state_survives_failure()
    test_unreadable_product_page_is_retried()
    print("checker OK")
