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


def users_list(rows: list[tuple[int, float, str, str]], total: int, admin: int) -> str:
    """Ответ на /who: сколько пользователей и кто пришёл последним.

    Строки приходят готовыми из базы, считать тут нечего — обработчик должен
    отвечать мгновенно.
    """
    out = [f"<b>Пользователей в базе: {total}</b>"]
    if not rows:
        out.append("Пока никто не нажимал /start.")
        return "\n".join(out)
    out.append("")
    out.append("<b>Последние:</b>")
    for user_id, ts, name, username in rows:
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))
        who = html.escape(name, quote=False) if name else "имя неизвестно"
        tag = html.escape(username, quote=False) if username else "без username"
        me = " — это ты" if user_id == admin else ""
        out.append(f"• {who}{me}\n  {tag} · id <code>{user_id}</code>\n  вошёл {when}")
    return "\n".join(out)


START_TEXT = ("Показываю пару кроссовок с распродажи ({n} шт). Дальше буду присылать "
              "новые скидки сам, тыкать ничего не надо.")
START_FAILED = "Не смог достать товары с сайта."
FIRST_RUN_TEXT = ("Запомнил {n} кроссовок со скидкой. Дальше приходит только новое "
                  "или подешевевшее — сам проверяю раз в {minutes} минут.")
NO_ACCESS = "У вас нет доступа к этой команде"
DEALS_EMPTY = ("Скидок пока нет в памяти бота. Он соберёт их на ближайшей проверке "
               "и пришлёт сам — нажимать ничего не нужно.")
BROKEN_TEXT = ("Puma отдала 0 кроссовок со скидкой. Обычно это значит, что на сайте "
               "поменялась вёрстка и бот перестал её понимать — надо чинить разбор.")
DOWN_TEXT = ("Не смог обойти распродажу: сайт Puma не отвечает или закрылся от бота.\n"
             "Причина: {error}\n"
             "Если это повторится несколько часов — надо смотреть, не забанили ли нас.")
