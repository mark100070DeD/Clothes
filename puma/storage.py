"""Роль: память бота. SQLite-файл data/puma.db — что уже показывали и когда.

Кто вызывает: checker.py (основной сценарий) и sender.py (витрина по /start).
Что править здесь: структуру таблиц и запросы к ним.

Две таблицы:
  seen (sku, price, ts)  последняя цена, по которой товар уже отправлен
  meta (k, v)            служебные отметки, например время последней тревоги

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


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    db.commit()
