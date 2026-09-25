"""Роль: суточная сверка индекса с живым сайтом. Ничего не рассылает.

Кто вызывает: bot.py --audit, то есть суточный воркфлоу puma.yml.
Что править здесь: пороги тревог и размер выборки.

Зачем. Быстрый путь живёт в Worker и опирается на поисковый индекс Пумы. Индекс
может застрять и начать отдавать вчерашние цены: ошибок нет, формат правильный,
новых скидок «просто нет». Со стороны это неотличимо от спокойного дня, и бот
замолчит навсегда, а человек ничего не заметит.

Отличить одно от другого можно только посмотрев на настоящий сайт. Это и есть
единственная задача файла: взять небольшую выборку живых страниц, сравнить цены
с тем, что утверждает индекс, и закричать при расхождении.

Почему выборка, а не полный обход: полный стоит 24 запроса и 23 МБ, а для ответа
на вопрос «индекс ещё живой?» хватает четырёх страниц.

Замер 25.09.2026 (до всех правок): из 89 товаров разошлись 2, и оба раза живой
сайт был ДЕШЕВЛЕ индекса. То есть пара процентов расхождения — норма, а не
поломка. Порог поэтому не нулевой.
"""
from __future__ import annotations

import logging

from . import config, klevu
from .models import Item

log = logging.getLogger("puma")


def compare(html_items: list[Item], index_items: list[Item]) -> dict:
    """Сверить цены по общим артикулам. Возвращает готовый отчёт.

    Сравниваем только пересечение: индекс знает весь каталог, а выборка — лишь
    первые страницы распродажи, так что «нет в выборке» ничего не значит.
    А вот «есть в выборке, нет в индексе» — уже симптом.
    """
    index = {it.sku: it for it in index_items}
    same, diff, missing = 0, [], []
    for it in html_items:
        other = index.get(it.sku)
        if other is None:
            missing.append(it.sku)
        elif (other.price, other.old_price) == (it.price, it.old_price):
            same += 1
        else:
            diff.append((it.sku, (it.price, it.old_price), (other.price, other.old_price)))
    checked = same + len(diff)
    return {
        "checked": checked,
        "same": same,
        "diff": diff,
        "missing": missing,
        "sample": len(html_items),
        "index_total": len(index_items),
        "mismatch_pct": round(len(diff) / checked * 100, 1) if checked else 0.0,
        "missing_pct": round(len(missing) / len(html_items) * 100, 1) if html_items else 0.0,
    }


def verdict(report: dict) -> str | None:
    """Текст тревоги или None, если всё в порядке.

    Три разных беды, и лечатся они по-разному, поэтому и формулировки разные:
      выборка пустая        — сломался разбор HTML или сайт закрылся
      индекс пустой         — сломался разбор индекса или индекс лёг
      цены разошлись сильно — индекс застрял, быстрый путь больше не свежий
    """
    if not report["sample"]:
        return ("Сверка: живой сайт не отдал ни одного товара со скидкой. "
                "Либо поменялась вёрстка списка, либо Puma закрылась от бота.")
    if not report["index_total"]:
        return ("Сверка: поисковый индекс не отдал ни одного товара. "
                "Быстрый путь сейчас слеп — скидки идут только суточным обходом.")
    if report["mismatch_pct"] > config.AUDIT_MISMATCH_PCT:
        first = ", ".join(f"{s}: сайт {h[0]}, индекс {k[0]}" for s, h, k in report["diff"][:3])
        return (f"Сверка: индекс разошёлся с сайтом на {report['mismatch_pct']}% "
                f"({len(report['diff'])} из {report['checked']}). Похоже, он застрял.\n{first}")
    if report["missing_pct"] > config.AUDIT_MISSING_PCT:
        return (f"Сверка: индекс не знает {report['missing_pct']}% товаров с витрины "
                f"({len(report['missing'])} из {report['sample']}). Покрытие просело.")
    return None


def stale_text(hours: float) -> str:
    """Текст тревоги. Бесконечность значит «не обошёл каталог ни разу»."""
    if hours == float("inf"):
        return ("Worker отвечает, но каталог не обходил ни разу: KV пуст или крон "
                "не срабатывает. Скидки сейчас идут только суточным обходом.\n"
                "Проверить: cd worker && npx wrangler tail")
    return (f"Быстрый путь молчит {hours:.1f} ч: Worker не обновлял состояние. "
            "Скидки сейчас идут только суточным обходом, с задержкой до суток.\n"
            "Проверить: cd worker && npx wrangler deploy --keep-vars")


async def run(client) -> dict:
    """Сверка целиком: выборка живых страниц против индекса.

    Порядок важен: сначала HTML, потом индекс. Если индекс ляжет, мы всё равно
    успеем увидеть, жив ли сам сайт, и тревога будет точнее.
    """
    from .scraper import fetch_pages  # локально: audit не должен тянуть bs4 в тестах

    html_items = await fetch_pages(client, config.AUDIT_PAGES)
    log.info("сверка: с живого сайта взято товаров: %d", len(html_items))

    try:
        index_items = await klevu.fetch_sale(client)
    except Exception as e:
        log.exception("сверка: индекс не ответил")
        return {"checked": 0, "same": 0, "diff": [], "missing": [],
                "sample": len(html_items), "index_total": 0,
                "mismatch_pct": 0.0, "missing_pct": 0.0, "error": str(e)}

    report = compare(html_items, index_items)
    log.info("сверка: совпало %d, разошлось %d (%.1f%%), нет в индексе %d",
             report["same"], len(report["diff"]), report["mismatch_pct"], len(report["missing"]))
    return report


async def fetch_worker_state(url: str, token: str) -> dict:
    """Спросить Worker, когда он последний раз обходил индекс.

    Отдельный сторож от сверки цен: там мы проверяем, врёт ли индекс, а здесь —
    жив ли вообще тот, кто его читает. Worker сам про свою смерть не напишет.
    """
    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{url}/state", headers={"X-Subs-Token": token})
        r.raise_for_status()
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Worker ответил отказом: {data}")
    return data


async def worker_silence_hours() -> float | None:
    """Сколько часов Worker молчит. None — если спросить не у кого или не вышло.

    Молча возвращаем None, когда Worker не настроен: локальный запуск и старые
    прогоны должны работать без него, как и в subs_sync.
    """
    import time

    if not (config.WORKER_URL and config.SUBS_TOKEN):
        log.info("состояние Worker не проверяю: нет WORKER_URL или SUBS_TOKEN")
        return None
    state = await fetch_worker_state(config.WORKER_URL, config.SUBS_TOKEN)
    last = float(state.get("last_sweep_ts") or 0)
    if not last:
        return None
    return max(0.0, (time.time() - last) / 3600)


def sync_seen(db, seen: dict | None) -> int:
    """Скопировать память Worker'а (sku -> цена) в базу. Возвращает число строк.

    Зачем. Рассылку ведёт Worker, и отметки «уже отправлено» живут у него в KV.
    Если Worker умрёт, включится запасная рассылка на Python — и без этой копии
    она посчитала бы новыми все 589 скидок и завалила бы чат.

    Тот же приём, что в subs_sync для подписчиков: читать у Worker безопаснее,
    чем давать ему право писать сюда.
    """
    if not seen:
        return 0
    from . import storage

    rows = 0
    for sku, price in seen.items():
        try:
            value = int(price)
        except (TypeError, ValueError):
            continue
        if storage.last_price(db, sku) != value:
            storage.remember(db, sku, value)
            rows += 1
    db.commit()
    if rows:
        log.info("память Worker'а перенесена в базу: строк обновлено %d", rows)
    return rows
