"""Суточная сверка: когда молчать, когда кричать. Запуск: python -m tests.test_audit"""
import logging
import os
import sys
import tempfile

logging.disable(logging.CRITICAL)

os.environ["BOT_TOKEN"] = "123:x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puma import audit, config, storage  # noqa: E402
from puma.models import Item  # noqa: E402


def item(sku, price, old=1000):
    return Item(sku, "Кросівки X", f"https://ua.puma.com/uk/x-{sku}.html", price, old)


def fresh_db():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "puma.db")
    return storage.db_init()


def test_agreement():
    """Цены сошлись — молчим."""
    html = [item("a_1", 500), item("b_2", 600)]
    index = [item("a_1", 500), item("b_2", 600), item("c_3", 700)]
    report = audit.compare(html, index)
    assert report["same"] == 2 and not report["diff"] and not report["missing"], report
    # Лишний товар в индексе — это норма: индекс знает весь каталог, а выборка
    # берёт только первые страницы распродажи.
    assert audit.verdict(report) is None


def test_small_lag_is_not_an_alarm():
    """2% расхождения — обычное отставание индекса, а не поломка.

    Замер 25.09.2026 на живом сайте дал ровно такую картину. Если бы порог был
    нулевым, тревога приходила бы каждый день и её перестали бы читать.
    """
    html = [item(f"s_{i}", 500) for i in range(50)]
    index = [item(f"s_{i}", 500 if i else 900) for i in range(50)]
    report = audit.compare(html, index)
    assert report["mismatch_pct"] == 2.0, report["mismatch_pct"]
    assert audit.verdict(report) is None, "2% не повод будить человека"


def test_stuck_index_is_an_alarm():
    """Индекс застрял: половина цен не сходится — кричим."""
    html = [item(f"s_{i}", 500) for i in range(10)]
    index = [item(f"s_{i}", 900 if i % 2 else 500) for i in range(10)]
    report = audit.compare(html, index)
    text = audit.verdict(report)
    assert text and "застрял" in text, text
    assert "сайт 500" in text, "в тревоге должны быть примеры расхождений"


def test_empty_sides_are_different_alarms():
    """Пустой сайт и пустой индекс — разные беды и разные подсказки."""
    dead_site = audit.compare([], [item("a_1", 500)])
    text = audit.verdict(dead_site)
    assert text and "вёрстка" in text, text

    dead_index = audit.compare([item("a_1", 500)], [])
    text = audit.verdict(dead_index)
    assert text and "индекс" in text.lower(), text


def test_missing_coverage_is_an_alarm():
    """Индекс перестал видеть заметную часть витрины."""
    html = [item(f"s_{i}", 500) for i in range(10)]
    index = [item("s_0", 500)]
    report = audit.compare(html, index)
    text = audit.verdict(report)
    assert text and "Покрытие просело" in text, text


def test_seen_sync_prevents_duplicate_blast():
    """Память Worker'а переезжает в базу.

    Без этого запасная рассылка при смерти Worker'а посчитала бы новыми все
    скидки разом — и человек получил бы сотни карточек за раз.
    """
    db = fresh_db()
    assert storage.is_empty(db)

    rows = audit.sync_seen(db, {"a_1": 500, "b_2": "600", "мусор": None})
    assert rows == 2, rows
    assert storage.last_price(db, "a_1") == 500
    assert storage.last_price(db, "b_2") == 600

    # Повторный перенос тех же цен ничего не переписывает.
    assert audit.sync_seen(db, {"a_1": 500, "b_2": 600}) == 0
    # А изменившуюся — переписывает.
    assert audit.sync_seen(db, {"a_1": 450}) == 1
    assert storage.last_price(db, "a_1") == 450


def test_seen_sync_survives_empty():
    db = fresh_db()
    assert audit.sync_seen(db, None) == 0
    assert audit.sync_seen(db, {}) == 0


def test_stale_text_tells_what_to_do():
    text = audit.stale_text(9.5)
    assert "9.5" in text and "wrangler" in text, text


def test_never_swept_is_not_silence():
    """Worker, ни разу не обошедший каталог, — это поломка, а не норма.

    Замечено на боевом прогоне 25.09.2026: при last_sweep_ts = 0 сторож молчал,
    потому что «времени нет — значит и судить не о чем». Снаружи такой бот
    выглядит живым и при этом не присылает ничего.
    """
    text = audit.stale_text(float("inf"))
    assert "ни разу" in text, text
    assert "inf" not in text, "бесконечность нельзя показывать человеку"


if __name__ == "__main__":
    test_agreement()
    test_small_lag_is_not_an_alarm()
    test_stuck_index_is_an_alarm()
    test_empty_sides_are_different_alarms()
    test_missing_coverage_is_an_alarm()
    test_seen_sync_prevents_duplicate_blast()
    test_seen_sync_survives_empty()
    test_stale_text_tells_what_to_do()
    test_never_swept_is_not_silence()
    print("audit OK")
