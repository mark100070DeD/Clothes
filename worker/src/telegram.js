/**
 * Отправка в Telegram. Вынесено из index.js, потому что теперь шлёт не только
 * обработчик /start, но и фоновый обход.
 *
 * Здесь же список получателей и тревоги. Правило то же, что в app.py:
 * получают все, кто нажал /start, плюс владелец из CHAT_ID — его из подписки
 * не выкинуть, иначе один сбой оставит хозяина без бота.
 */
import { caption } from "./caption.js";

/** Пауза между карточками: Телеграм пропускает ~1 сообщение в секунду на чат. */
export const SEND_PAUSE_MS = 1500;

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function tg(env, method, payload) {
  const response = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!body.ok) throw new Error(`${method}: ${body.description ?? response.status}`);
  return body.result;
}

/** Все, кому слать. Владелец первым и всегда. */
export async function recipients(env) {
  const owner = Number(env.CHAT_ID) || 0;
  const out = owner ? [owner] : [];
  if (!env.SUBS) return out;
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: "sub:", cursor });
    for (const key of page.keys) {
      const id = Number(key.metadata?.chat_id ?? key.name.slice(4));
      if (id && !out.includes(id)) out.push(id);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

/**
 * Одна карточка всем. Возвращает, до скольких дошла.
 *
 * Ноль означает «не дошла ни до кого» — вызывающий тогда НЕ запоминает цену и
 * вернётся к товару следующим тиком. То же правило, что в sender.broadcast.
 */
export async function broadcast(env, chatIds, item, reason) {
  const text = caption(item, reason);
  let delivered = 0;
  for (const [n, chatId] of chatIds.entries()) {
    if (n) await sleep(SEND_PAUSE_MS);
    try {
      await tg(env, "sendPhoto", {
        chat_id: chatId,
        photo: item.image,
        caption: text,
        parse_mode: "HTML",
      });
      delivered += 1;
    } catch (e) {
      // Фото могло не забраться — тогда хотя бы текст.
      console.log(`фото ${item.sku} не ушло в ${chatId} (${e}), шлю текстом`);
      try {
        await tg(env, "sendMessage", { chat_id: chatId, text, parse_mode: "HTML" });
        delivered += 1;
      } catch (err) {
        console.log(`и текстом не ушло в ${chatId}: ${err}`);
      }
    }
  }
  return delivered;
}

/** Простое сообщение всем. Возвращает, до скольких дошло. */
export async function notify(env, chatIds, text) {
  let delivered = 0;
  for (const chatId of chatIds) {
    try {
      await tg(env, "sendMessage", { chat_id: chatId, text });
      delivered += 1;
    } catch (e) {
      console.log(`не написал в ${chatId}: ${e}`);
    }
  }
  return delivered;
}

/**
 * Тревога не чаще раза в N секунд. Перенос warn_once_a_day из checker.py.
 *
 * Отметку ставим ПОСЛЕ удачной отправки: если написать не удалось, начинать
 * сутки молчания нельзя. Молчащий бот неотличим от бота без скидок.
 */
export async function warnOnce(env, meta, key, text, everySec = 24 * 3600) {
  const now = Math.floor(Date.now() / 1000);
  const last = Number(meta[`warn:${key}`] ?? 0);
  if (now - last < everySec) return false;
  const chatIds = await recipients(env);
  if (!(await notify(env, chatIds, text))) return false;
  meta[`warn:${key}`] = now;
  return true;
}
