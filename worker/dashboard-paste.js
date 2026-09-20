/**
 * Cloudflare Worker: мгновенный ответ на /start.
 *
 * Это src/index.js и src/caption.js, склеенные в один файл — для вставки через
 * веб-редактор Cloudflare (Quick Edit понимает только один файл). Логика та же,
 * что проверена тестами в worker/test/caption.test.js. Если правишь код — правь
 * оригиналы в src/, а сюда переноси копией перед следующей вставкой на сайте.
 *
 * Переменные окружения (задаются в настройках Cloudflare, НЕ в коде):
 *   BOT_TOKEN       токен от @BotFather
 *   CHAT_ID         чей чат обслуживаем; остальные молча игнорируем
 *   WEBHOOK_SECRET  тот же секрет, что передан в setWebhook как secret_token
 *   START_ITEMS     сколько карточек показывать, по умолчанию 5
 */

// ---- caption.js ----

/** Как html.escape(s, quote=False) в Python: только & < > и ничего больше. */
function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Как money() в Python: разряды через пробел плюс знак гривны. 2590 -> "2 590 ₴" */
function money(value) {
  const digits = String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${digits} ₴`;
}

/** Карточка товара разметкой HTML для Telegram. */
function caption(item, reason) {
  const sizes = item.sizes && item.sizes.length ? item.sizes.join(", ") : "нет в наличии";
  return [
    `<b>${escapeHtml(item.name)}</b>`,
    reason,
    `Цена: <b>${money(item.price)}</b> <s>${money(item.old_price)}</s> (-${item.discount}%)`,
    `Цвет: ${escapeHtml(item.color)}`,
    `Размеры: ${sizes}`,
    `<a href="${escapeHtml(item.url)}">Открыть на puma.com</a>`,
  ].join("\n");
}

/** Приветствие к витрине. Отметку времени показываем всегда — данные могут быть многочасовой давности. */
function greeting(count, updatedAt) {
  if (!count) {
    return "Скидок пока нет в памяти бота. Он соберёт их на ближайшей проверке и пришлёт сам.";
  }
  return (
    `Показываю ${count} кроссовок с распродажи (данные собраны ${formatTime(updatedAt)}). ` +
    "Дальше буду присылать новые скидки сам, тыкать ничего не надо."
  );
}

/** ISO-время -> «20.09 в 16:33» по Киеву. Не вышло разобрать — отдаём как есть. */
function formatTime(iso) {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const parts = new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Kyiv",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(d);
    const get = (type) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("day")}.${get("month")} в ${get("hour")}:${get("minute")}`;
  } catch {
    return String(iso);
  }
}

// ---- index.js ----

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
