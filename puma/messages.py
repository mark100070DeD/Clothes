"""Роль: все тексты, которые видит человек в Telegram, и вид карточки товара.

Кто вызывает: sender.py (карточки), checker.py (сводки и тревоги).
Что править здесь: формулировки, порядок строк в карточке, эмодзи.
Ходить в сеть и в базу здесь нечем — это самый безопасный файл для правок.

Разметка карточки — HTML Telegram: <b>, <s>, <a href>. Названия товаров
и цвета приходят с сайта, поэтому прогоняются через html.escape.
"""
import html
import time

from .models import Item


def money(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₴"


def caption(it: Item, info: dict, reason: str) -> str:
    sizes = ", ".join(info["sizes"]) if info["sizes"] else "нет в наличии"
    return (
        f"<b>{html.escape(it.name, quote=False)}</b>\n"
        f"{reason}\n"
        f"Цена: <b>{money(it.price)}</b> <s>{money(it.old_price)}</s> (-{it.discount}%)\n"
        f"Цвет: {html.escape(info['color'], quote=False)}\n"
        f"Размеры: {sizes}\n"
        f'<a href="{it.url}">Открыть на puma.com</a>'
    )


def subs_list(rows: list[tuple[int, float, str]], owner: int) -> str:
    """Ответ на /who: кто подписан на рассылку.

    Имя есть не у всех: у подписавшихся до того, как бот начал его запоминать,
    оно появится при следующем /start.
    """
    if not rows:
        return "Подписчиков пока нет. Ты получаешь скидки как владелец."
    out = [f"<b>Подписчиков: {len(rows)}</b>"]
    for chat_id, ts, name in rows:
        when = time.strftime("%d.%m в %H:%M", time.localtime(ts))
        who = html.escape(name, quote=False) if name else "имя неизвестно"
        mine = " — это ты" if chat_id == owner else ""
        out.append(f"• {who}{mine}\n  id <code>{chat_id}</code>, подписался {when}")
    if owner and not any(r[0] == owner for r in rows):
        out.append(f"\nПлюс ты сам (id <code>{owner}</code>) — владелец, в рассылке всегда.")
    return "\n".join(out)


START_TEXT = ("Показываю пару кроссовок с распродажи ({n} шт). Дальше буду присылать "
              "новые скидки сам, тыкать ничего не надо.")
START_FAILED = "Не смог достать товары с сайта."
FIRST_RUN_TEXT = ("Запомнил {n} кроссовок со скидкой. Дальше приходит только новое "
                  "или подешевевшее — сам проверяю раз в {minutes} минут.")
BROKEN_TEXT = ("Puma отдала 0 кроссовок со скидкой. Обычно это значит, что на сайте "
               "поменялась вёрстка и бот перестал её понимать — надо чинить разбор.")
DOWN_TEXT = ("Не смог обойти распродажу: сайт Puma не отвечает или закрылся от бота.\n"
             "Причина: {error}\n"
             "Если это повторится несколько часов — надо смотреть, не забанили ли нас.")
