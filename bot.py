"""Точка входа. Здесь только запуск — весь код бота лежит в пакете puma/.

    python bot.py --audit   — суточная сверка (это крутится на GitHub)
    python bot.py --once    — полный обход и рассылка: ЗАПАСНОЙ путь
    python bot.py           — живёт постоянно (для запуска на своём компе)
    python bot.py --answer  — только ответ на команды; при webhook бесполезен

ГДЕ ТЕПЕРЬ ГЛАВНОЕ. Скидки ищет и рассылает Cloudflare Worker (папка worker/):
крон будит его раз в минуту, задержка — несколько минут вместо часа. Код здесь
остался для суточной сверки и на случай, если Worker замолчит.

КАРТА ПРОЕКТА:

    worker/src/sweep.js    БОЕВОЙ ПУТЬ: тик обхода, отбор, отправка
         |                 klevu.js — индекс, puma.js — живые страницы,
         |                 state.js — память в KV
         |
    bot.py  ->  puma/app.py        выбирает режим, создаёт бота
                     |
         +-----------+------------+
         |                        |
    puma/audit.py            puma/checker.py
    сверка + сторож          ДИРИЖЁР запасного пути
         |                        |
    puma/klevu.py      +----------+----------+-----------+
    индекс             |          |          |           |
                   scraper.py storage.py messages.py sender.py
                   ходит на   помнит,   тексты и    говорит с
                   сайт Пумы  что послали вид карточки Telegram
                       |          |
                   (HTML сайта) data/puma.db

Куда идти с проблемой:

  бот молчит / не шлёт скидки                 worker/README.md, раздел «когда сломалось»
  не видит товары, пропали размеры или цвет   worker/src/puma.js (бой), puma/scraper.py (запас)
  не нравится текст или вид карточки          puma/messages.py + worker/src/caption.js
  «что считать новостью» — правила отбора     worker/src/sweep.js + puma/checker.py
  адреса разделов, пороги, паузы              puma/config.py
  приходят дубли или наоборот тишина          puma/checker.py + puma/storage.py
  /start отвечает «скидок пока нет»            витрина в KV пуста, см. worker/src/state.js
  кто получает /who                           puma/config.py (ADMIN_ID)
  как часто запускается, где секреты          worker/wrangler.toml + .github/workflows/
  проверить без Telegram                      scripts/check-site.bat
  посмотреть, кто подписан                    scripts/subscribers.bat
  залить изменения на GitHub                  scripts/publish.bat

В каждом файле puma/ сверху написано, за что он отвечает и что в нём править.
"""
from puma.app import main

if __name__ == "__main__":
    main()
