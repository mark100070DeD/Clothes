"""Разбор ответа индекса и отбор товаров. Запуск: python -m tests.test_klevu"""
import logging
import os
import sys

logging.disable(logging.CRITICAL)

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import klevu  # noqa: E402

# Так адрес индекса лежит в HTML страницы: со слешами, экранированными для JS.
PAGE = (r'<script>var x = {"searchUrl":"https:\/\/eucs20.ksearchnet.com\/cloud-search'
        r'\/n-search\/search?ticket=klevu-158811194777911465&paginationStartsFrom=0"};</script>')


def rec(url, name, sale, old, stock="yes"):
    return {"url": url, "name": name, "salePrice": sale, "price": old, "inStock": stock}


SNEAKER = rec("https://ua.puma.com/uk/mostro-og-prime-unisex-403206-08.html?size=41",
              "Кросівки Mostro OG Prime Sneakers Unisex", "2590.0", "6490.00")


def test_endpoint():
    url, key = klevu.parse_endpoint(PAGE)
    # Из страницы берём хост и ключ, но адрес собираем на v2: только он умеет
    # term='*' и выбор полей, а в странице прописан старый n-search.
    assert url == "https://eucs20.ksearchnet.com/cs/v2/search", url
    assert key == "klevu-158811194777911465", key
    try:
        klevu.parse_endpoint("<html>без ключа</html>")
    except klevu.KlevuError:
        pass
    else:
        raise AssertionError("страница без ключа должна ронять KlevuError")


def test_query_body():
    body = klevu.query_body("klevu-1", 2000)
    s = body["recordQueries"][0]["settings"]
    assert body["context"]["apiKeys"] == ["klevu-1"]
    assert s["query"]["term"] == "*", "term='*' — это весь индекс, не поиск по слову"
    assert s["limit"] == 1000 and s["offset"] == 2000
    assert "salePrice" in s["fields"] and "name" in s["fields"]


def test_read_page():
    recs, total = klevu.read_page({"queryResults": [
        {"meta": {"totalResultsFound": 5161}, "records": [SNEAKER]}]})
    assert total == 5161 and recs == [SNEAKER]
    try:
        klevu.read_page({"meta": {}})
    except klevu.KlevuError:
        pass
    else:
        raise AssertionError("ответ без queryResults должен ронять KlevuError")


def test_sku_and_item():
    assert klevu.sku_of("https://ua.puma.com/uk/x-y-403206-08.html?size=41") == "403206_08"
    assert klevu.sku_of("https://ua.puma.com/uk/category.html") is None

    it = klevu.to_item(SNEAKER)
    assert it.sku == "403206_08" and it.price == 2590 and it.old_price == 6490
    assert it.discount == 60
    assert it.url.endswith("403206-08.html"), "хвост ?size= должен отваливаться"
    # Картинка собирается из артикула, как и для HTML-источника.
    assert "/global/403206/08/" in it.image


def test_filters():
    # price — это СТАРАЯ цена, salePrice — текущая. Перепутать = слать мусор.
    assert klevu.to_item(rec("https://ua.puma.com/uk/a-1-111111-01.html",
                             "Кросівки X", "6490.0", "6490.0")) is None, "без скидки"
    assert klevu.to_item(rec("https://ua.puma.com/uk/a-1-111111-02.html",
                             "Сандалі X", "100.0", "200.0")) is None, "не кроссовки"
    assert klevu.to_item(rec("https://ua.puma.com/uk/a-1-111111-03.html",
                             "Кросівки X", "100.0", "200.0", stock="no")) is None, "распродан"
    assert klevu.to_item(rec("https://ua.puma.com/uk/a-1-111111-04.html",
                             "Кеди X", "100.0", "200.0")) is not None, "кеди — это тоже наше"
    assert klevu.to_item(rec("https://ua.puma.com/uk/a-1-111111-05.html",
                             "Кросівки X", "", "200.0")) is None, "битая цена"


def test_dedup():
    items = klevu.to_items([SNEAKER, SNEAKER, {"url": "x", "name": "y"}])
    assert len(items) == 1, items


if __name__ == "__main__":
    test_endpoint()
    test_query_body()
    test_read_page()
    test_sku_and_item()
    test_filters()
    test_dedup()
    print("klevu OK")
