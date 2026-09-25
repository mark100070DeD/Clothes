/**
 * Состояние бота в KV. Это то, что раньше лежало в data/puma.db и коммитилось
 * в репозиторий после каждого прогона.
 *
 * Что здесь лежит:
 *   seen        {sku: цена}  — по какой цене товар УЖЕ отправлен. Главное.
 *   cursor      где остановился обход индекса и окно свежести
 *   meta        отметки времени и отпечаток каталога — для сторожей
 *   showcase    последние отправленные карточки, из них собирается /start
 *   subs        подписчики (ключи sub:*, как было)
 *
 * Почему seen одним блобом, а не ключ на товар. 589 отдельных ключей — это 589
 * чтений за тик, а бесплатный лимит 100 000 в сутки. Один блоб на ~25 КБ — это
 * одно чтение. Записи только когда что-то изменилось.
 *
 * Про несогласованность KV. Запись расходится по миру до ~60 секунд, так что
 * теоретически соседние тики могут увидеть старое seen и прислать дубль. Тик у
 * нас раз в минуту, а круг индекса — 5 минут, то есть окно расхождения меньше
 * периода повторной встречи с тем же товаром. Плюс seen пишется СРАЗУ после
 * отправки, а не в конце тика. Если дубли всё же появятся — переезжать на D1,
 * там согласованность строгая.
 */

const SEEN_KEY = "state:seen";
const CURSOR_KEY = "state:cursor";
const META_KEY = "state:meta";
const SHOWCASE_KEY = "state:showcase";

/** Сколько карточек держать для витрины /start. */
export const SHOWCASE_KEEP = 20;

async function readJson(env, key, fallback) {
  if (!env.SUBS) return fallback;
  try {
    const value = await env.SUBS.get(key, { type: "json" });
    return value ?? fallback;
  } catch (e) {
    console.log(`не прочитал ${key}: ${e}`);
    return fallback;
  }
}

async function writeJson(env, key, value) {
  if (!env.SUBS) return false;
  try {
    await env.SUBS.put(key, JSON.stringify(value));
    return true;
  } catch (e) {
    console.log(`не записал ${key}: ${e}`);
    return false;
  }
}

export const readSeen = (env) => readJson(env, SEEN_KEY, {});
export const writeSeen = (env, seen) => writeJson(env, SEEN_KEY, seen);

export const readCursor = (env) => readJson(env, CURSOR_KEY, { klevu: 0, listing: 0 });
export const writeCursor = (env, cursor) => writeJson(env, CURSOR_KEY, cursor);

export const readMeta = (env) => readJson(env, META_KEY, {});
export const writeMeta = (env, meta) => writeJson(env, META_KEY, meta);

export const readShowcase = (env) => readJson(env, SHOWCASE_KEY, []);

/**
 * Добавить отправленные карточки в витрину. Новые впереди, хвост обрезаем.
 * Витрина берётся из уже отправленного, поэтому /start не стоит ни одного
 * запроса: цвет и размеры у этих карточек уже добыты.
 */
export async function pushShowcase(env, cards) {
  if (!cards.length) return;
  const old = await readShowcase(env);
  const bySku = new Map();
  // Отметка времени нужна приветствию в /start: человек должен видеть,
  // насколько свежее то, что ему показывают.
  const ts = Math.floor(Date.now() / 1000);
  for (const card of [...cards.map((c) => ({ ...c, ts })), ...old]) {
    if (!bySku.has(card.sku)) bySku.set(card.sku, card);
  }
  await writeJson(env, SHOWCASE_KEY, [...bySku.values()].slice(0, SHOWCASE_KEEP));
}

/**
 * Отпечаток каталога. Нужен единственному сторожу: если по 5161 товару ничего
 * не менялось два часа — индекс замёрз, и молчание бота ничего не значит.
 * Дешёвая сумма, не криптография: тут важна только «изменилось / нет».
 */
export function snapshotHash(items) {
  let h = 2166136261;
  for (const it of items) {
    const s = `${it.sku}:${it.price}`;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
  }
  return (h >>> 0).toString(16);
}

/**
 * Первый запуск: seen пустой, а товаров много.
 *
 * Без этой проверки потеря KV означала бы залп в несколько сотен карточек.
 * Поведение перенесено из checker.py: запомнить молча и написать одну строку.
 */
export function isFirstRun(seen, items) {
  return Object.keys(seen).length === 0 && items.length > 3;
}

/**
 * Кого отправлять: товар новый или цена ниже запомненной.
 * Ровно то же правило, что в checker.py. Менять только вместе с ним.
 */
export function candidates(items, seen) {
  return items.filter((it) => {
    const was = seen[it.sku];
    return was === undefined || it.price < was;
  });
}
