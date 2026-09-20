"""Роль: что такое «товар» для бота. Одна структура — Item.

Кто создаёт: scraper.py, разбирая страницу списка.
Кто читает: checker.py (решает, слать ли), messages.py (рисует карточку).
Что править здесь: новые поля товара и правила, выводимые из полей
(процент скидки, адрес картинки).
"""
from dataclasses import dataclass

from . import config


@dataclass
class Item:
    sku: str
    name: str
    url: str
    price: int
    old_price: int

    @property
    def discount(self) -> int:
        return round((1 - self.price / self.old_price) * 100) if self.old_price else 0

    @property
    def image(self) -> str:
        """Адрес фото собирается из артикула: '403206_08' -> модель 403206, цвет 08."""
        model, _, color = self.sku.partition("_")
        return config.IMG.format(model=model, color=color)
