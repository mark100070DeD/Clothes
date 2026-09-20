"""Тест доставки: завышаем в базе сохранённые цены нескольких кроссовок.

Бот на следующем прогоне увидит, что цена на сайте ниже запомненной,
и пришлёт карточки «цена упала» — сам, без единой команды.
Товары и текущие цены настоящие, липовая только зачёркнутая старая цена.
"""
import sqlite3

N = 8
db = sqlite3.connect("puma.db")
rows = db.execute("SELECT sku, price FROM seen ORDER BY RANDOM() LIMIT ?", (N,)).fetchall()
for sku, price in rows:
    fake = int(price * 1.5)
    db.execute("UPDATE seen SET price=? WHERE sku=?", (fake, sku))
    print(f"{sku}: {price} -> {fake}")
db.commit()
print(f"подменено строк: {len(rows)}")
