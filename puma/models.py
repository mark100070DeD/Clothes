"""Структуры данных."""
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
        model, _, color = self.sku.partition("_")
        return config.IMG.format(model=model, color=color)
