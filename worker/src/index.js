/**
 * Cloudflare Worker: и мгновенный ответ на /start, и сам поиск скидок.
 *
 * Было раньше: Worker только отвечал на /start по готовому data/latest.json,
 * а скидки искал часовой прогон на GitHub Actions. Задержка доходила до часа.
 *
 * Стало: скидки ищет сам Worker, крон будит его каждую минуту (см. sweep.js).
 * GitHub остался на суточной сверке и на запасной рассылке, если Worker умрёт.
 * Ничего никуда не надо дёргать, поэтому и токен GitHub больше не нужен.
 *
 * Переменные окружения (задаются в настройках Cloudflare, НЕ в коде):
 *   BOT_TOKEN       токен от @BotFather
 *   WEBHOOK_SECRET  тот же секрет, что передан в setWebhook как secret_token
 *   SUBS_TOKEN      пароль к GET /subs и GET /state; знает суточная сверка
 *   CHAT_ID         владелец: получает скидки и все тревоги
 *   START_ITEMS     сколько карточек показывать по /start, по умолчанию 5
 *   SWEEP_PAGES     страниц индекса за тик, по умолчанию 2. Ручка на случай,
 *                   если не влезаем в 10 мс CPU: поставить 1, деплой не нужен
 *   MIN_DISCOUNT    не слать скидки меньше N%, по умолчанию 0
 *
 * Почему на webhook отвечаем 200 сразу. Telegram ждёт быстрый ответ и повторяет
 * доставку, если его не получил. Отправку уносим в ctx.waitUntil: она идёт уже
 * после ответа и повторов не вызывает.
 */
import { caption, greeting } from "./caption.js";
import * as state from "./state.js";
import { tick } from "./sweep.js";
import { tg } from "./telegram.js";

const REASON = "Сейчас на распродаже";

export default {
  async fetch(request, env, ctx) {
    const path = new URL(request.url).pathname;

    // Список подписчиков для суточной сверки. Под паролем: это чужие chat id.
    if (path === "/subs") return guarded(request, env, () => subsList(env));
    // Состояние обхода. По нему суточная сверка понимает, жив ли Worker вообще.
    if (path === "/state" && request.method !== "POST") {
      return guarded(request, env, () => stateDump(env));
    }
    // Загрузка памяти из старой базы — разовый перенос при переезде.
    if (path === "/state/seen" && request.method === "POST") {
      return guarded(request, env, () => importSeen(request, env));
    }

    // GET — короткий статус, чтобы проверить деплой в браузере.
    if (request.method !== "POST") return status(env);

    // Проверяем секрет ДО разбора тела: чужой запрос дальше проходить не должен.
    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.WEBHOOK_SECRET || secret !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      // Битое тело повторять смысла нет — 200, чтобы Telegram не долбил.
      return new Response("bad request body", { status: 200 });
    }

    const message = update?.message;
    const chat = message?.chat;
    const text = message?.text ?? "";
    if (!chat?.id) return new Response("ignored", { status: 200 });

    if (text.startsWith("/start")) ctx.waitUntil(handleStart(env, chat));

    return new Response("ok", { status: 200 });
  },

  /**
   * Крон. Одна минута — один тик, вся логика в sweep.js.
   *
   * Ошибку глушим намеренно: если дать ей выпасть, Cloudflare отметит вызов
   * сбойным, но чинить это всё равно некому. Внутри tick() любой отказ уже
   * превращается либо в паузу, либо в сообщение владельцу.
   */
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      tick(env, new Date(event.scheduledTime))
        .then((result) => console.log(`тик: ${JSON.stringify(result)}`))
        .catch((e) => console.log(`тик упал целиком: ${e?.stack ?? e}`)),
    );
  },
};

/**
 * Какие карточки показать. Витрина меняется редко, поэтому без сдвига человек
 * на каждое нажатие видел бы одну и ту же пятёрку. Начинаем с произвольного
 * места и заворачиваем по кругу.
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

/**
 * Общая проверка пароля для служебных адресов.
 *
 * Исход пишем в лог. Иначе разъехавшийся SUBS_TOKEN выглядит точно так же, как
 * «суточная сверка почему-то не приходила»: снаружи 403 не отличить от того,
 * что никто и не стучался. В логе это видно сразу, а значений здесь нет —
 * только сам факт и причина отказа.
 */
async function guarded(request, env, handler) {
  const path = new URL(request.url).pathname;
  const token = request.headers.get("X-Subs-Token");
  if (!env.SUBS_TOKEN) {
    console.log(`${path}: отказ — SUBS_TOKEN не задан в настройках Worker`);
    return new Response("forbidden", { status: 403 });
  }
  if (token !== env.SUBS_TOKEN) {
    console.log(`${path}: отказ — токен ${token ? "не совпал" : "не прислан"}`);
    return new Response("forbidden", { status: 403 });
  }
  console.log(`${path}: доступ разрешён`);
  if (!env.SUBS) return json({ ok: false, error: "нет хранилища SUBS" }, 500);
  return await handler();
}

/** Кого обслуживаем. Читает только суточная сверка, поэтому под паролем. */
async function subsList(env) {
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
 * Состояние обхода для стороннего сторожа.
 *
 * Отдаём и `seen` целиком: это копия памяти бота. Суточная сверка кладёт её в
 * data/puma.db, чтобы при смерти Worker'а запасная рассылка на Python знала,
 * что уже отправлено, и не прислала всё заново.
 */
async function stateDump(env) {
  const meta = await state.readMeta(env);
  const seen = await state.readSeen(env);
  return json({
    ok: true,
    last_sweep_ts: meta.lastSweepTs ?? 0,
    last_change_ts: meta.lastChangeTs ?? 0,
    index_total: meta.indexTotal ?? 0,
    seeding: Boolean(meta.seeding),
    puma_pause_until: meta.pumaPauseUntil ?? 0,
    seen_count: Object.keys(seen).length,
    seen,
  });
}

/**
 * Принять память старого бота: {sku: цена} из data/puma.db.
 *
 * Нужно ровно один раз, при переезде. Без этого Worker стартовал бы с пустой
 * памятью: пришлось бы сутки молча запоминать каталог (см. seeding в sweep.js),
 * и всё это время новые скидки не приходили бы вовсе.
 *
 * Сливаем, а не перезаписываем: запомненная цена значит «уже отправлено»,
 * потерять такую строку — значит прислать карточку повторно.
 */
async function importSeen(request, env) {
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, error: "тело не разобралось" }, 400);
  }
  const incoming = payload?.seen;
  if (!incoming || typeof incoming !== "object") {
    return json({ ok: false, error: "нет поля seen" }, 400);
  }

  const seen = await state.readSeen(env);
  let added = 0;
  for (const [sku, price] of Object.entries(incoming)) {
    const value = Math.round(Number(price));
    if (!Number.isFinite(value) || value <= 0) continue;
    if (seen[sku] === value) continue;
    seen[sku] = value;
    added += 1;
  }
  await state.writeSeen(env, seen);

  // Память есть — значит первичное наполнение больше не нужно, и бот может
  // слать новые скидки со следующей же минуты.
  const meta = await state.readMeta(env);
  meta.seeding = false;
  meta.circles = Math.max(1, Number(meta.circles ?? 0));
  await state.writeMeta(env, meta);

  console.log(`память перенесена: добавлено ${added}, всего ${Object.keys(seen).length}`);
  return json({ ok: true, added, total: Object.keys(seen).length });
}

/** Короткий статус для браузера. Секретов здесь нет. */
async function status(env) {
  try {
    const meta = await state.readMeta(env);
    const showcase = await state.readShowcase(env);
    return json({
      ok: true,
      last_sweep_ts: meta.lastSweepTs ?? 0,
      index_total: meta.indexTotal ?? 0,
      showcase: showcase.length,
      start_items: startItems(env),
    });
  } catch (e) {
    return json({ ok: false, error: String(e) }, 502);
  }
}

/**
 * Запомнить, кому слать скидки. Запись сама по себе рассылку не включает:
 * получателей собирает telegram.recipients прямо из этого же хранилища.
 */
async function remember(env, chat) {
  if (!env.SUBS) return;
  const record = {
    chat_id: chat.id,
    name: [chat.first_name, chat.last_name].filter(Boolean).join(" "),
    username: chat.username ? `@${chat.username}` : "",
    ts: Math.floor(Date.now() / 1000),
  };
  // Падение записи не должно стоить человеку карточек: витрину он всё равно
  // увидит, просто не попадёт в рассылку — это видно в логах и чинится /start.
  await env.SUBS.put(`sub:${chat.id}`, JSON.stringify(record), { metadata: record })
    .catch((e) => console.log(`не записал подписчика ${chat.id}: ${e}`));
}

/**
 * Ответ на /start. Витрина берётся из УЖЕ ОТПРАВЛЕННЫХ карточек в KV:
 * там готовы и цвет, и размеры, поэтому ни одного запроса в сеть не нужно.
 */
async function handleStart(env, chat) {
  const chatId = chat.id;
  await remember(env, chat);

  const showcase = await state.readShowcase(env);
  const items = pickItems(
    showcase,
    startItems(env),
    Math.floor(Math.random() * (showcase.length || 1)),
  );
  // Свежесть показываем по самой новой карточке витрины, а не по выбранным:
  // человеку важно, когда бот в последний раз что-то находил.
  const newest = showcase[0]?.ts;
  const updatedAt = newest ? new Date(newest * 1000).toISOString() : "";

  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: greeting(items.length, updatedAt),
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
