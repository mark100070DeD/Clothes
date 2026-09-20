"""Слить память бота: наши строки в свежую серверную базу, не потеряв чужих.

Запуск: python .github/merge-state.py <серверная.db> <наша.db>

Зачем: два прогона на GitHub могут идти параллельно, и тогда тот, кто
сохраняется вторым, держит в руках базу, выложенную ДО первого. Если просто
положить свой файл сверху, строки первого прогона исчезнут, а исчезнувшая
строка означает «товар не отправляли» — и карточка уйдёт повторно.

Правило слияния: по каждому товару выживает запись с более поздним ts.
Для служебных отметок (meta) — большее значение, там лежат метки времени.
"""
import sqlite3
import sys

server, mine = sys.argv[1], sys.argv[2]

db = sqlite3.connect(server)
db.execute("CREATE TABLE IF NOT EXISTS seen (sku TEXT PRIMARY KEY, price INTEGER, ts REAL)")
db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS subs (chat_id INTEGER PRIMARY KEY, ts REAL)")
db.execute("""CREATE TABLE IF NOT EXISTS deals (
    sku TEXT PRIMARY KEY, name TEXT, url TEXT, price INTEGER,
    old_price INTEGER, color TEXT, sizes TEXT, ts REAL)""")
have = {r[1] for r in db.execute("PRAGMA table_info(subs)")}
if "name" not in have:
    db.execute("ALTER TABLE subs ADD COLUMN name TEXT")
if "username" not in have:
    db.execute("ALTER TABLE subs ADD COLUMN username TEXT")
db.execute("ATTACH DATABASE ? AS mine", (mine,))

before = db.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

db.execute("""
    INSERT INTO seen (sku, price, ts)
    SELECT sku, price, ts FROM mine.seen WHERE true
    ON CONFLICT(sku) DO UPDATE SET price = excluded.price, ts = excluded.ts
    WHERE excluded.ts > seen.ts
""")
db.execute("""
    INSERT INTO meta (k, v)
    SELECT k, v FROM mine.meta WHERE true
    ON CONFLICT(k) DO UPDATE SET v = excluded.v
    WHERE CAST(excluded.v AS REAL) > CAST(meta.v AS REAL)
""")
# Подписчики объединяются: человек, нажавший /start на одном прогоне, не должен
# исчезнуть из-за другого прогона, который его ещё не видел.
db.execute("""
    INSERT INTO subs (chat_id, ts, name, username)
    SELECT chat_id, ts, name, username FROM mine.subs WHERE true
    ON CONFLICT(chat_id) DO UPDATE SET name = excluded.name, username = excluded.username
    WHERE excluded.name <> '' AND excluded.name IS NOT NULL
""")

# Витрина для /start: карточки тоже надо сливать, иначе сохранение состояния
# выбросило бы только что собранные и /start снова оказался бы пустым.
db.execute("""
    INSERT INTO deals (sku, name, url, price, old_price, color, sizes, ts)
    SELECT sku, name, url, price, old_price, color, sizes, ts FROM mine.deals WHERE true
    ON CONFLICT(sku) DO UPDATE SET
        name = excluded.name, url = excluded.url, price = excluded.price,
        old_price = excluded.old_price, color = excluded.color,
        sizes = excluded.sizes, ts = excluded.ts
    WHERE excluded.ts > deals.ts
""")
db.commit()

after = db.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
subs = db.execute("SELECT COUNT(*) FROM subs").fetchone()[0]
deals = db.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
print(f"слито: товаров было {before}, стало {after}; подписчиков {subs}; карточек {deals}")
