"""SQLite: что бот уже показывал и служебные отметки."""
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
    db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)", (sku, price, time.time()))


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    db.commit()
