/**
 * Cloudflare Worker: мгновенный ответ на /start.
 *
 * Зачем он есть. Бот живёт на GitHub Actions и на связи постоянно не висит,
 * поэтому команда ждала ответа до часа. Worker принимает webhook от Telegram и
 * отвечает сразу, потому что ему не нужны ни сайт Пумы, ни база: витрину собрал
 * заранее часовой обход и выложил в data/latest.json.
 *
 * Подписка открытая: карточки получает любой, кто нажал /start. Его чат Worker
 * кладёт в KV, а часовой обход забирает список через GET /subs и переносит в
 * puma.db — иначе новый человек получил бы витрину один раз и больше ничего.
 *
 * Переменные окружения (задаются в настройках Cloudflare, НЕ в коде):
 *   BOT_TOKEN       токен от @BotFather
 *   WEBHOOK_SECRET  тот же секрет, что передан в setWebhook как secret_token
 *   SUBS_TOKEN      пароль к GET /subs; его знает только часовой воркфлоу
 *   CHAT_ID         владелец; на доступ к /start не влияет, нужен для /who
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
    const path = new URL(request.url).pathname;

    // Список подписчиков для часового обхода. Под паролем: это чужие chat id.
    if (path === "/subs") {
      return subsList(request, env);
    }

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
    const chat = message?.chat;
    const text = message?.text ?? "";

    if (!chat?.id) {
      return new Response("ignored", { status: 200 });
    }

    if (text.startsWith("/start")) {
      ctx.waitUntil(handleStart(env, chat));
    }

    return new Response("ok", { status: 200 });
  },
};

/**
 * Какие товары показать. Витрина отдаётся в порядке сайта и меняется редко,
 * поэтому без сдвига человек на каждое нажатие видел бы одну и ту же пятёрку.
 * Начинаем с произвольного места и заворачиваем по кругу.
 */
export function pickItems(items, count, offset) {
  if (!items.length) return [];
  const take = Math.min(count, items.length);
  const start = ((offset % items.length) + items.length) % items.length;
  const out = [];
  for (let i = 0; i < take; i++) {
    out.push(items[(start + i) % items.length]);
  }
  return out;
}

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

/** Кого обслуживаем. Читает только часовой обход, поэтому под паролем. */
async function subsList(request, env) {
  const token = request.headers.get("X-Subs-Token");
  if (!env.SUBS_TOKEN || token !== env.SUBS_TOKEN) {
    return new Response("forbidden", { status: 403 });
  }
  if (!env.SUBS) {
    return json({ ok: false, error: "нет хранилища SUBS" }, 500);
  }

  const subs = [];
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: "sub:", cursor });
    for (const key of page.keys) {
      if (key.metadata) subs.push(key.metadata);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);

  return json({ ok: true, count: subs.length, subs });
}

/**
 * Запомнить, кому потом слать скидки. Запись сама по себе рассылку не включает:
 * её включит часовой обход, когда заберёт список себе в базу.
 */
async function remember(env, chat) {
  if (!env.SUBS) return;
  const record = {
    chat_id: chat.id,
    name: [chat.first_name, chat.last_name].filter(Boolean).join(" "),
    username: chat.username ? `@${chat.username}` : "",
    ts: Math.floor(Date.now() / 1000),
  };
  // Падение записи не должно стоить человеку карточек: он их всё равно увидит,
  // просто не попадёт в рассылку — это видно в логах и чинится следующим /start.
  await env.SUBS.put(`sub:${chat.id}`, JSON.stringify(record), {
    metadata: record,
  }).catch((e) => console.log(`не записал подписчика ${chat.id}: ${e}`));
}

async function handleStart(env, chat) {
  const chatId = chat.id;
  await remember(env, chat);

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

  const all = data.items ?? [];
  const items = pickItems(
    all,
    startItems(env),
    Math.floor(Math.random() * (all.length || 1)),
  );
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: greeting(items.length, data.updated_at),
  });
  if (!items.length) return;

  await sendCards(env, chatId, items);
}

/**
 * Каждая карточка — отдельным сообщением. Альбомом (sendMediaGroup) Telegram
 * показывает плитку фото и прячет подписи под тап, а цену и размеры надо видеть
 * сразу.
 */
async function sendCards(env, chatId, items) {
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
