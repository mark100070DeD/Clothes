"""Точка входа. Вся логика лежит в пакете puma/.

    python bot.py           — живёт постоянно (слушает /start, проверяет раз в час)
    python bot.py --once    — обход сайта + разбор команд и выход (GitHub Actions, раз в час)
    python bot.py --answer  — только ответ на команды (GitHub Actions, раз в 5 минут)
"""
from puma.app import main

if __name__ == "__main__":
    main()
