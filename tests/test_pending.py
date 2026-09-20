"""Разбор команд из телеги в режиме GitHub Actions. Запуск: python -m tests.test_pending"""
import asyncio
import os
import sys
import types

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import sender  # noqa: E402

CHAT = 625622586


def upd(uid, text, chat_id=CHAT):
    msg = types.SimpleNamespace(text=text, chat=types.SimpleNamespace(id=chat_id))
    return types.SimpleNamespace(update_id=uid, message=msg)


class FakeBot:
    def __init__(self, updates):
        self.updates = updates
        self.calls = []

    async def get_updates(self, **kw):
        self.calls.append(kw)
        return [] if "offset" in kw else self.updates


async def run(updates):
    bot = FakeBot(updates)
    answered = []

    async def fake_answer(bot_, chat_id):
        answered.append(chat_id)

    sender.answer_start = fake_answer
    await sender.handle_pending(bot, CHAT)
    return bot, answered


def test_all():
    # пусто: ничего не шлём, offset не трогаем
    bot, answered = asyncio.run(run([]))
    assert answered == [] and len(bot.calls) == 1

    # /start от своего чата: отвечаем и подтверждаем приём
    bot, answered = asyncio.run(run([upd(10, "привет"), upd(11, "/start")]))
    assert answered == [CHAT] and bot.calls[1]["offset"] == 12

    # /start@имя_бота тоже считается
    bot, answered = asyncio.run(run([upd(20, "/start@ClothessSalee_bot")]))
    assert answered == [CHAT]

    # чужой чат: игнор, но приём подтверждаем
    bot, answered = asyncio.run(run([upd(30, "/start", chat_id=999)]))
    assert answered == [] and bot.calls[1]["offset"] == 31

    # обычный текст: только подтверждение
    bot, answered = asyncio.run(run([upd(40, "как дела")]))
    assert answered == [] and bot.calls[1]["offset"] == 41


if __name__ == "__main__":
    test_all()
    print("pending OK")
