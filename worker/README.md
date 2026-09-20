# Мгновенный `/start` на Cloudflare Worker

## Зачем

Бот живёт на GitHub Actions и на связи постоянно не висит, поэтому `/start` ждал
ответа до часа. Worker принимает webhook от Telegram и отвечает сразу: сайт Пумы
и база ему не нужны, витрину заранее собрал часовой обход и выложил в
`data/latest.json`.

```
Telegram  --webhook-->  Cloudflare Worker  --читает-->  data/latest.json
                              |                         (собирает puma.yml раз в час)
                              +--отвечает--> 5 карточек, каждая отдельным сообщением
```

## Что внутри

| Файл | Что делает |
|---|---|
| `src/index.js` | принимает webhook, проверяет секрет и чат, отправляет карточки |
| `src/caption.js` | подпись карточки — перенос `puma/messages.py` на JS |
| `test/caption.test.js` | сверяет подпись с фактическим выводом Python |
| `wrangler.toml` | настройки деплоя. **Секретов здесь нет и быть не должно** |

## Переменные окружения

Задаются **только в Cloudflare**, в коде их нет — репозиторий публичный.

| Переменная | Что это |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `CHAT_ID` | твой chat id; остальным Worker не отвечает |
| `WEBHOOK_SECRET` | любая длинная случайная строка, придумываешь сам |
| `START_ITEMS` | сколько карточек показывать, по умолчанию 5 |

## Развёртывание

Нужен Node.js — он же нужен для Wrangler.

```
cd worker
node --test            # прогнать тест подписи
npx wrangler login     # откроет браузер, войдёшь в аккаунт Cloudflare
npx wrangler deploy    # выложит Worker и напечатает его адрес
```

Затем секреты (каждая команда спросит значение и не покажет его в консоли):

```
npx wrangler secret put BOT_TOKEN
npx wrangler secret put CHAT_ID
npx wrangler secret put WEBHOOK_SECRET
```

И один раз зарегистрировать webhook — открыть в браузере:

```
https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=<АДРЕС_WORKER>&secret_token=<СЕКРЕТ>&allowed_updates=["message"]
```

Проверить, что всё встало: открыть адрес Worker в браузере обычным GET — он
отдаст JSON со свежестью витрины. И `getWebhookInfo`:

```
https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo
```

## Важно: webhook и polling несовместимы

Пока webhook включён, `getUpdates` не работает — Telegram отдаёт ошибку 409.
Это значит:

- запуск бота на компе через polling (`scripts/run-local.bat`) **не будет
  получать команды**, пока webhook не снят;
- чтобы вернуться к polling, надо один раз открыть
  `https://api.telegram.org/bot<ТОКЕН>/deleteWebhook`;
- обратно на Worker — снова `setWebhook` по ссылке выше.

## Свежесть данных

Worker показывает то, что собрал последний обход, и пишет в приветствии, когда
это было. Расписание GitHub ненадёжное: замерено 6 прогонов за 17 часов вместо 17,
с провалами до 5 часов. Значит цены в витрине могут быть многочасовой давности —
поэтому отметка времени в ответе обязательна.

Сама выгрузка кэшируется на стороне Worker 5 минут, чтобы не ходить в GitHub на
каждое нажатие.
