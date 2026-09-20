"""Привести .env в порядок, не показывая токен наружу.

Чинит следы старой ошибки в bat-файлах: голую строку с токеном без
BOT_TOKEN= впереди и мусор вроде INTERVAL_MIN=60).
"""
import re

PATH = ".env"
TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")

token = chat = ""
interval = "60"

try:
    raw = open(PATH, encoding="utf-8", errors="replace").read()
except FileNotFoundError:
    raw = ""

for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    key, sep, value = line.partition("=")
    key, value = key.strip(), value.strip().rstrip(")")
    if sep and key == "BOT_TOKEN" and value:
        token = value
    elif sep and key == "CHAT_ID" and value:
        chat = value
    elif sep and key == "INTERVAL_MIN":
        digits = re.match(r"\d+", value)
        if digits:
            interval = digits.group()
    elif TOKEN_RE.fullmatch(line.rstrip(")")):
        token = line.rstrip(")")  # токен, вставленный без BOT_TOKEN=

with open(PATH, "w", encoding="utf-8") as f:
    f.write(f"BOT_TOKEN={token}\nCHAT_ID={chat}\nINTERVAL_MIN={interval}\n")

print("BOT_TOKEN:", f"на месте, {len(token)} символов" if token else "НЕ НАЙДЕН")
print("CHAT_ID:", chat or "пусто (запишется после /start)")
print("INTERVAL_MIN:", interval)
