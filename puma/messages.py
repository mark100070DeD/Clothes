"""Тексты сообщений. Хочешь поменять вид карточки — правь здесь."""
import html

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


START_TEXT = ("Показываю 10 кроссовок с распродажи. Дальше буду присылать новые "
              "скидки сам, тыкать ничего не надо.")
START_FAILED = "Не смог достать товары с сайта."
FIRST_RUN_TEXT = ("Запомнил {n} кроссовок со скидкой. Дальше приходит только новое "
                  "или подешевевшее — сам проверяю раз в {minutes} минут.")
BROKEN_TEXT = ("Puma отдала 0 кроссовок со скидкой. Обычно это значит, что на сайте "
               "поменялась вёрстка и бот перестал её понимать — надо чинить разбор.")
