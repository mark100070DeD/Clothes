"""Роль: память бота. SQLite-файл data/puma.db — что уже показывали и когда.

Кто вызывает: checker.py (основной сценарий) и sender.py (витрина по /start).
Что править здесь: структуру таблиц и запросы к ним.

Три таблицы:
  seen (sku, price, ts)  последняя цена, по которой товар уже отправлен
  meta (k, v)            служебные отметки, например время последней тревоги
  subs (chat_id, ts)     кому слать: все, кто нажал /start

Про seen и подписчиков: отметка «уже отправлено» общая для всех, не у каждого
своя. То есть товар уходит один раз всем сразу, а кто подписался позже — прошлые
скидки не получит, только будущие. Ему вместо этого сразу приходит витрина.

Важно про сохранность: remember() только пишет в открытую транзакцию, сам не
сохраняет. Вызывающий обязан сделать db.commit() — без него при обрыве
пропадёт всё, что накопилось с прошлого commit. Поэтому checker.py
сохраняет после каждой отправленной карточки, а не одним разом в конце.

На GitHub этот файл живёт между запусками только потому, что воркфлоу
коммитит его в репозиторий после каждого прогона.
"""
import os
import sqlite3
import time

from . import config


def db_init() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(config.DB_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS seen (sku TEXT PRIMARY KEY, price INTEGER, ts REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS subs (chat_id INTEGER PRIMARY KEY, ts REAL)")
    db.commit()
    return db


def is_empty(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0


def last_price(db: sqlite3.Connection, sku: str) -> int | None:
    row = db.execute("SELECT price FROM seen WHERE sku=?", (sku,)).fetchone()
    return row[0] if row else None


def remember(db: sqlite3.Connection, sku: str, price: int) -> None:
    """Запомнить цену. Не сохраняет — нужен db.commit() у вызывающего."""
    db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)", (sku, price, time.time()))


def add_subscriber(db: sqlite3.Connection, chat_id: int) -> bool:
    """Записать подписчика. True — если он новый, а не жал /start раньше."""
    cur = db.execute("INSERT OR IGNORE INTO subs VALUES (?,?)", (chat_id, time.time()))
    db.commit()
    return cur.rowcount > 0


def remove_subscriber(db: sqlite3.Connection, chat_id: int) -> None:
    """Убрать подписчика — например, если он заблокировал бота."""
    db.execute("DELETE FROM subs WHERE chat_id=?", (chat_id,))
    db.commit()


def subscribers(db: sqlite3.Connection) -> list[int]:
    """Все, кто нажал /start, в порядке подписки."""
    return [r[0] for r in db.execute("SELECT chat_id FROM subs ORDER BY ts")]


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    db.commit()
