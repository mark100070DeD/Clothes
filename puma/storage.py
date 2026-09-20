"""Роль: память бота. SQLite-файл data/puma.db — что уже показывали и когда.

Кто вызывает: checker.py (основной сценарий) и sender.py (витрина по /start).
Что править здесь: структуру таблиц и запросы к ним.

Четыре таблицы:
  seen (sku, price, ts)     последняя цена, по которой товар уже отправлен
  meta (k, v)               служебные отметки, например время последней тревоги
  subs (chat_id, ts, name, username)  кому слать: все, кто нажал /start
  deals (...)               ГОТОВЫЕ карточки скидок для мгновенной витрины

Зачем нужна deals. Раньше /start парсил сайт прямо в обработчике и человек ждал
полминуты. Теперь карточки собирает фоновый обход и складывает сюда целиком —
с названием, ценами, цветом и размерами. Обработчик /start только читает готовое,
в сеть за ними не ходит и ничего не ждёт.

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
    db.execute("""CREATE TABLE IF NOT EXISTS deals (
        sku TEXT PRIMARY KEY, name TEXT, url TEXT, price INTEGER,
        old_price INTEGER, color TEXT, sizes TEXT, ts REAL)""")
    # Эти столбцы добавлены позже: в уже существующих базах их нет.
    have = {r[1] for r in db.execute("PRAGMA table_info(subs)")}
    if "name" not in have:
        db.execute("ALTER TABLE subs ADD COLUMN name TEXT")
    if "username" not in have:
        db.execute("ALTER TABLE subs ADD COLUMN username TEXT")
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


def add_subscriber(db: sqlite3.Connection, chat_id: int, name: str = "",
                   username: str = "") -> bool:
    """Записать подписчика. True — если он новый, а не жал /start раньше.

    Имя и @username при повторном /start обновляем: человек мог их сменить.
    """
    cur = db.execute(
        "INSERT OR IGNORE INTO subs (chat_id, ts, name, username) VALUES (?,?,?,?)",
        (chat_id, time.time(), name, username))
    fresh = cur.rowcount > 0
    if not fresh and (name or username):
        db.execute("UPDATE subs SET name=?, username=? WHERE chat_id=?",
                   (name, username, chat_id))
    db.commit()
    return fresh


def remove_subscriber(db: sqlite3.Connection, chat_id: int) -> None:
    """Убрать подписчика — например, если он заблокировал бота."""
    db.execute("DELETE FROM subs WHERE chat_id=?", (chat_id,))
    db.commit()


def subscribers(db: sqlite3.Connection) -> list[int]:
    """Все, кто нажал /start, в порядке подписки."""
    return [r[0] for r in db.execute("SELECT chat_id FROM subs ORDER BY ts")]


def subscribers_count(db: sqlite3.Connection) -> int:
    """Сколько всего подписчиков. Быстрый COUNT, без выборки строк."""
    return db.execute("SELECT COUNT(*) FROM subs").fetchone()[0]


def subscribers_recent(db: sqlite3.Connection, limit: int = 10
                       ) -> list[tuple[int, float, str, str]]:
    """Последние подписавшиеся: (user_id, дата входа, имя, username)."""
    return [(r[0], r[1], r[2] or "", r[3] or "")
            for r in db.execute(
                "SELECT chat_id, ts, name, username FROM subs ORDER BY ts DESC LIMIT ?",
                (limit,))]


def save_deal(db: sqlite3.Connection, sku: str, name: str, url: str, price: int,
              old_price: int, color: str, sizes: str) -> None:
    """Сложить готовую карточку в витрину. Вызывает только фоновый обход."""
    db.execute("INSERT OR REPLACE INTO deals VALUES (?,?,?,?,?,?,?,?)",
               (sku, name, url, price, old_price, color, sizes, time.time()))


def recent_deals(db: sqlite3.Connection, limit: int) -> list[tuple]:
    """Последние карточки: (sku, name, url, price, old_price, color, sizes)."""
    return db.execute(
        "SELECT sku, name, url, price, old_price, color, sizes FROM deals "
        "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def deals_count(db: sqlite3.Connection) -> int:
    return db.execute("SELECT COUNT(*) FROM deals").fetchone()[0]


def deal_prices(db: sqlite3.Connection) -> list[tuple[str, int]]:
    """Что лежит в витрине: (sku, цена). Нужно, чтобы выбросить устаревшее."""
    return db.execute("SELECT sku, price FROM deals").fetchall()


def delete_deal(db: sqlite3.Connection, sku: str) -> None:
    db.execute("DELETE FROM deals WHERE sku=?", (sku,))


def trim_deals(db: sqlite3.Connection, keep: int) -> None:
    """Витрина не должна расти без конца — оставляем только свежие карточки."""
    db.execute("DELETE FROM deals WHERE sku NOT IN "
               "(SELECT sku FROM deals ORDER BY ts DESC LIMIT ?)", (keep,))


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    db.commit()
