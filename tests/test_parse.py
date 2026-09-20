"""Разбор страниц Пумы и вид карточки. Запуск из корня: python -m tests.test_parse"""
import os
import sys

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import messages, scraper  # noqa: E402
from puma.models import Item  # noqa: E402


def card(sku, name, price, old, url):
    return f'''<div class="product-item" data-product-sku="{sku}" data-product-item="1" data-product-name="{name}">
<a href="{url}" class="product-item__img-w"><img class="product-item__img" src="https://img/{sku}.png"></a>
<div class="price-box"><span class="special-price"><span data-price-amount="{price}" data-price-type="finalPrice" class="price-wrapper"><span class="price">x</span></span></span>
<span class="old-price"><span data-price-amount="{old}" data-price-type="oldPrice" class="price-wrapper"><span class="price">y</span></span></span></div></div>'''


def test_listing():
    html = (
        card("311047_01", "Кросівки Magnify NITRO 3 Running Shoes Women", 3390, 6790, "https://ua.puma.com/uk/a.html")
        + card("1_1", "Сандалії Mayu Summer Sandal Women", 1000, 2000, "https://ua.puma.com/uk/b.html")
        + card("2_2", "Кеди Suede Classic Sneakers Unisex", 3990, 4990, "https://ua.puma.com/uk/c.html")
        + card("3_3", "Кросівки Same Price", 3990, 3990, "https://ua.puma.com/uk/d.html")
    )
    items = scraper.parse_listing(html)
    assert [i.sku for i in items] == ["311047_01", "2_2"], items  # сандалии и товар без скидки отсеяны
    assert items[0].discount == 50 and items[1].discount == 20
    assert items[0].image == ("https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:fafafa"
                              "/global/311047/01/sv01/fnd/UKR/w/1000/h/1000/fmt/png")


def test_product():
    prod = '''<html><head><title>Кросівки H-Street Sneakers Unisex | Колір: Білий | Warm White-Alpine Snow | Puma</title></head><body><ul>
<li class="size-list__item " data-available="1" data-label="35.5"><span>35.5</span></li>
<li class="size-list__item unavailable" data-available="0" data-label="40"><span>40</span></li>
<li class="size-list__item " data-available="1" data-label="41"><span>41</span></li></ul></body></html>'''
    info = scraper.parse_product(prod)
    assert info == {"sizes": ["35.5", "41"], "color": "Warm White-Alpine Snow (білий)"}, info


def test_caption():
    it = Item("1_1", "Кросівки <Test> & Co", "https://ua.puma.com/uk/x.html", 3390, 6790)
    text = messages.caption(it, {"sizes": ["41", "42"], "color": "Black (чорний)"}, "Новая скидка")
    assert "&lt;Test&gt; &amp; Co" in text
    assert "3 390 ₴" in text and "6 790 ₴" in text and "-50%" in text
    assert "Размеры: 41, 42" in text


if __name__ == "__main__":
    test_listing()
    test_product()
    test_caption()
    print("parse OK")
