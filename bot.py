"""Точка входа. Здесь только запуск — весь код бота лежит в пакете puma/.

    python bot.py           — живёт постоянно (слушает /start, проверяет раз в час)
    python bot.py --once    — команды + обход сайта и выход (GitHub Actions)
    python bot.py --answer  — только ответ на команды (GitHub Actions, быстрый)

КАРТА ПРОЕКТА. Один прогон идёт сверху вниз:

    bot.py  ->  puma/app.py        выбирает режим, создаёт бота
                     |
                puma/checker.py    ДИРИЖЁР: что новое, что подешевело
                     |
      +--------------+--------------+--------------+
      |              |              |              |
  scraper.py     storage.py     messages.py     sender.py
  ходит на       помнит, что     тексты и        говорит с
  сайт Пумы      уже послали     вид карточки    Telegram
      |              |
  (HTML сайта)   data/puma.db

Куда идти с проблемой:

  не видит товары, пропали размеры или цвет   puma/scraper.py
  не нравится текст или вид карточки          puma/messages.py
  «что считать новостью» — правила отбора     puma/checker.py
  адреса разделов, пороги, паузы              puma/config.py
  приходят дубли или наоборот тишина          puma/checker.py + puma/storage.py
  /start отвечает «скидок пока нет»            puma/checker.py (refresh_deals)
  кто получает /who                           puma/config.py (ADMIN_ID)
  как часто запускается, где секреты          .github/workflows/
  проверить без Telegram                      scripts/check-site.bat
  посмотреть, кто подписан                    scripts/subscribers.bat
  залить изменения на GitHub                  scripts/publish.bat

В каждом файле puma/ сверху написано, за что он отвечает и что в нём править.
"""
from puma.app import main

if __name__ == "__main__":
    main()
