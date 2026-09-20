"""Кто подписан на бота. Запуск из корня: python -m tools.subscribers
(или двойным кликом scripts\subscribers.bat)

Читает data/puma.db — ту же базу, которую бот коммитит с сервера. Чтобы список
был свежим, сначала сделай git pull.
"""
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from puma import config, storage  # noqa: E402

db = storage.db_init()
rows = storage.subscribers_full(db)
owner = config.load_chat_id()

print(f"База: {config.DB_PATH}")
print(f"Подписчиков: {len(rows)}")
print()
for chat_id, ts, name in rows:
    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))
    who = name or "имя неизвестно (появится при следующем /start)"
    mine = "  <-- это ты" if chat_id == owner else ""
    print(f"  {who}{mine}")
    print(f"      id {chat_id}, подписался {when}")

if owner and not any(r[0] == owner for r in rows):
    print(f"  Ты сам: id {owner} — владелец, в рассылке всегда")

print()
print(f"Итого получателей карточек: {len(set(r[0] for r in rows) | ({owner} if owner else set()))}")
