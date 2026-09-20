"""Подписчики из Worker попадают в базу. Запуск: python -m tests.test_subs_sync"""
import asyncio
import logging
import os
import sys
import tempfile

logging.disable(logging.CRITICAL)

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import config, storage, subs_sync  # noqa: E402


def fresh_db():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    return storage.db_init()


def test_new_subscribers_land_in_db():
    db = fresh_db()
    fresh = subs_sync.merge(db, [
        {"chat_id": 111, "name": "Марк", "username": "@mark", "ts": 1},
        {"chat_id": 222, "name": "Аня", "username": "", "ts": 2},
    ])
    assert fresh == 2, fresh
    assert storage.subscribers(db) == [111, 222], storage.subscribers(db)


def test_repeat_start_is_not_a_new_subscriber():
    db = fresh_db()
    subs_sync.merge(db, [{"chat_id": 111, "name": "Марк", "username": "@mark"}])
    fresh = subs_sync.merge(db, [{"chat_id": 111, "name": "Марк", "username": "@mark"}])
    assert fresh == 0, fresh
    assert storage.subscribers(db) == [111]


def test_renamed_person_is_updated_not_duplicated():
    db = fresh_db()
    subs_sync.merge(db, [{"chat_id": 111, "name": "Марк", "username": "@old"}])
    subs_sync.merge(db, [{"chat_id": 111, "name": "Марк Аброскин", "username": "@new"}])
    rows = list(db.execute("SELECT chat_id, name, username FROM subs"))
    assert rows == [(111, "Марк Аброскин", "@new")], rows


def test_broken_record_does_not_lose_the_rest():
    """Одна кривая запись в KV не должна стоить подписки остальным."""
    db = fresh_db()
    fresh = subs_sync.merge(db, [
        {"name": "без chat_id"},
        {"chat_id": "не число"},
        {"chat_id": 0},
        {"chat_id": 333, "name": "Живой"},
    ])
    assert fresh == 1, fresh
    assert storage.subscribers(db) == [333]


def test_chat_id_as_text_is_accepted():
    """KV отдаёт JSON, и число могло приехать строкой."""
    db = fresh_db()
    assert subs_sync.merge(db, [{"chat_id": "444"}]) == 1
    assert storage.subscribers(db) == [444]


def test_silent_when_worker_not_configured():
    """Локальный запуск без Worker'а не должен падать."""
    db = fresh_db()
    url, token = config.WORKER_URL, config.SUBS_TOKEN
    config.WORKER_URL, config.SUBS_TOKEN = "", ""
    try:
        assert asyncio.run(subs_sync.pull(db)) == 0
    finally:
        config.WORKER_URL, config.SUBS_TOKEN = url, token


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("все тесты прошли")


if __name__ == "__main__":
    run()
