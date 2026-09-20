/**
 * Cloudflare Worker: мгновенный ответ на /start.
 *
 * Зачем он есть. Бот живёт на GitHub Actions и на связи постоянно не висит,
 * поэтому команда ждала ответа до часа. Worker принимает webhook от Telegram и
 * отвечает сразу, потому что ему не нужны ни сайт Пумы, ни база: витрину собрал
 * заранее часовой обход и выложил в data/latest.json.
 *
 * Переменные окружения (задаются в настройках Cloudflare, НЕ в коде):
 *   BOT_TOKEN       токен от @BotFather
 *   CHAT_ID         чей чат обслуживаем; остальные молча игнорируем
 *   WEBHOOK_SECRET  тот же секрет, что передан в setWebhook как secret_token
 *   START_ITEMS     сколько карточек показывать, по умолчанию 5
 *
 * Почему отвечаем 200 сразу. Telegram ждёт быстрый ответ и повторяет доставку,
 * если его не получил. Отправку карточек уносим в ctx.waitUntil: она идёт уже
 * после ответа и повторов не вызывает.
 */
import { caption, greeting } from "./caption.js";

const DATA_URL =
  "https://raw.githubusercontent.com/mark100070DeD/Clothes/main/data/latest.json";

/** Кэш выгрузки. Обход обновляет её раз в час, чаще ходить незачем. */
const CACHE_TTL_SEC = 300;

const REASON = "Сейчас на распродаже";

export default {
  async fetch(request, env, ctx) {
    // GET — короткий статус, чтобы можно было проверить деплой в браузере.
    if (request.method !== "POST") {
      return status(env);
    }

    // Проверяем секрет ДО разбора тела: чужой запрос дальше проходить не должен.
    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.WEBHOOK_SECRET || secret !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      // Битое тело повторять смысла нет — отвечаем 200, чтобы Telegram не долбил.
      return new Response("bad request body", { status: 200 });
    }

    const message = update?.message;
    const text = message?.text ?? "";
    const chatId = message?.chat?.id;

    // Обслуживаем только свой чат. Остальным не отвечаем вообще.
    if (chatId === undefined || String(chatId) !== String(env.CHAT_ID)) {
      return new Response("ignored", { status: 200 });
    }

    if (text.startsWith("/start")) {
      ctx.waitUntil(handleStart(env, chatId));
    }

    return new Response("ok", { status: 200 });
  },
};

/** Короткий статус для браузера: свежесть выгрузки. Секретов здесь нет. */
async function status(env) {
  try {
    const data = await loadLatest();
    return json({
      ok: true,
      updated_at: data.updated_at,
      items: data.items?.length ?? 0,
      start_items: startItems(env),
    });
  } catch (e) {
    return json({ ok: false, error: String(e) }, 502);
  }
}

async function handleStart(env, chatId) {
  let data;
  try {
    data = await loadLatest();
  } catch (e) {
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: "Не смог прочитать витрину. Попробуй ещё раз через минуту.",
    }).catch(() => {});
    throw e;
  }

  const items = (data.items ?? []).slice(0, startItems(env));
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: greeting(items.length, data.updated_at),
  });
  if (!items.length) return;

  await sendCards(env, chatId, items);
}

/**
 * Карточки одним запросом. sendMediaGroup принимает от 2 до 10 элементов, и
 * падает целиком, если Telegram не смог забрать хотя бы одно фото — поэтому на
 * такой случай шлём по одной.
 */
async function sendCards(env, chatId, items) {
  const media = items.map((item) => ({
    type: "photo",
    media: item.image,
    caption: caption(item, REASON),
    parse_mode: "HTML",
  }));

  if (media.length >= 2) {
    try {
      await tg(env, "sendMediaGroup", { chat_id: chatId, media });
      return;
    } catch (e) {
      console.log(`sendMediaGroup не прошёл (${e}), шлю по одной`);
    }
  }

  for (const item of items) {
    try {
      await tg(env, "sendPhoto", {
        chat_id: chatId,
        photo: item.image,
        caption: caption(item, REASON),
        parse_mode: "HTML",
      });
    } catch (e) {
      // Фото могло не забраться — тогда хотя бы текст.
      console.log(`фото ${item.sku} не ушло (${e}), шлю текстом`);
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: caption(item, REASON),
        parse_mode: "HTML",
      }).catch((err) => console.log(`и текстом не ушло: ${err}`));
    }
  }
}

async function loadLatest() {
  const response = await fetch(DATA_URL, {
    cf: { cacheTtl: CACHE_TTL_SEC, cacheEverything: true },
  });
  if (!response.ok) {
    throw new Error(`latest.json: HTTP ${response.status}`);
  }
  return await response.json();
}

async function tg(env, method, payload) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!body.ok) {
    throw new Error(`${method}: ${body.description ?? response.status}`);
  }
  return body.result;
}

function startItems(env) {
  const n = Number(env.START_ITEMS);
  return Number.isFinite(n) && n > 0 ? Math.min(n, 10) : 5;
}

function json(body, code = 200) {
  return new Response(JSON.stringify(body, null, 1), {
    status: code,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
