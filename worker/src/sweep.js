/**
 * Один тик фонового обхода. Это сердце быстрого пути.
 *
 * Крон будит Worker каждую минуту. За тик надо уложиться в 10 мс процессорного
 * времени (бесплатный тариф), поэтому работа раскидана по тикам, а не делается
 * вся сразу. Замеры разбора: страница индекса ~1.5-2 мс, страница списка ~5 мс.
 *
 * Расписание внутри пятиминутки (minute % 5):
 *   0,1,2,3 — окно свежести: по LISTING_PAGES живых страниц списка Пумы.
 *             28 страниц -> полный круг за 18 минут. Длину разделов бот
 *             выясняет сам и запоминает, зашитого числа тут нет.
 *   4       — индекс: по SWEEP_PAGES страниц каталога.
 *             6 страниц -> полный круг тоже за 15 минут.
 *
 * Зачем два источника. Индекс полон (проверено: 591 из 591 товара распродажи),
 * но для свежих уценок бесполезен: 25.09.2026 бот нашёл шесть скидок, и все
 * шесть индекс не знал даже через 40 минут. Живые страницы свежи всегда, но их
 * 24 штуки по мегабайту. Поэтому скорость даёт окно, а индексу оставлена
 * полнота — ему хватает круга раз в 15 минут.
 *
 * Главное правило: РЕШЕНИЕ ВСЕГДА ПО ЦЕНЕ СО СТРАНИЦЫ ТОВАРА. Индекс и список
 * только показывают, куда смотреть. Поэтому прислать неверную цену невозможно.
 */
import * as klevu from "./klevu.js";
import * as puma from "./puma.js";
import * as state from "./state.js";
import { broadcast, recipients, warnOnce } from "./telegram.js";

export const SALE_URLS = [
  "https://ua.puma.com/uk/skidki/muzhchiny/obuv.html",
  "https://ua.puma.com/uk/skidki/zhenschiny/obuv.html",
];
const IMG =
  "https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:fafafa" +
  "/global/{model}/{color}/sv01/fnd/UKR/w/1000/h/1000/fmt/png";

/** Сколько карточек отправить за один тик. Остальные подождут следующего. */
const MAX_CARDS = 5;
/**
 * Через сколько часов неподвижности каталога считать индекс замёрзшим.
 *
 * Было 2 часа — из предположения, что по каталогу в 5183 товара что-то
 * меняется постоянно. Предположение оказалось неверным, и тревога пришла в
 * первый же вечер, 25.09.2026, на здоровом боте.
 *
 * Замер: шесть товаров, уценённых Пумой около 16:20, индекс не знал ни через
 * 40 минут, ни через 3.5 часа — ноль из шести. То есть он переиндексируется
 * раз в несколько часов, и «не менялся 2 часа» это его будни, а не поломка.
 *
 * 12 часов ловит настоящую смерть индекса и молчит при нормальной работе.
 */
const FROZEN_HOURS = 12;
/** Насколько долго верить найденному адресу индекса, прежде чем искать заново. */
const ENDPOINT_TTL_SEC = 24 * 3600;
/** После 403 не трогаем Пуму сутки. Долбить забаненным — худшее, что можно. */
const BAN_PAUSE_SEC = 24 * 3600;
/**
 * Версия схемы состояния. Поднимать, когда прошлая версия могла оставить в KV
 * испорченные данные: тогда наполнение запустится заново, молча.
 *   1 -> 2  круги каталога считались неверно, память заполнялась на треть
 */
const SEED_VERSION = 2;

const REASON_NEW = "Новая скидка";
/** Подпись для первого показа и витрины: это не новость, а «вот что есть». */
const REASON_SHOWCASE = "Сейчас на распродаже";

/** Адрес фото из артикула: '403206_08' -> модель 403206, цвет 08. */
export function imageUrl(sku) {
  const [model, color] = String(sku).split("_");
  return IMG.replace("{model}", model).replace("{color}", color ?? "");
}

/**
 * Что делать на этой минуте. Вынесено отдельно, чтобы проверять тестом.
 *
 * Четыре минуты из пяти уходят на живые страницы, пятая — на индекс. Так было
 * не всегда: сначала соотношение было обратным, пока замер 25.09.2026 не
 * показал, что индекс для свежих уценок бесполезен. Шесть скидок, найденных
 * в тот день, он не знал и через 40 минут — все шесть нашло окно живых страниц.
 *
 * Отсюда и раскладка: скорость даёт окно, индексу остаётся полнота, и для неё
 * хватает круга раз в 15 минут.
 */
export function plan(minute, sweepPages = 2, listingPages = 2) {
  return minute % 5 < 4
    ? { kind: "listing", pages: listingPages }
    : { kind: "index", pages: sweepPages };
}

const num = (value, fallback) => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
};

/** Адрес и ключ индекса: из памяти, иначе со страницы Пумы. */
async function endpoint(env, meta, fetchFn) {
  const now = Math.floor(Date.now() / 1000);
  if (meta.endpoint && meta.apiKey && now - Number(meta.endpointTs ?? 0) < ENDPOINT_TTL_SEC) {
    return { endpoint: meta.endpoint, apiKey: meta.apiKey };
  }
  const html = await puma.fetchPuma(SALE_URLS[0], fetchFn);
  const found = klevu.parseEndpoint(html);
  meta.endpoint = found.endpoint;
  meta.apiKey = found.apiKey;
  meta.endpointTs = now;
  console.log(`адрес индекса обновлён: ${found.endpoint}`);
  return found;
}

/**
 * Страницы индекса начиная с курсора. Заодно двигает курсор и отмечает,
 * менялось ли содержимое — на этом держится сторож замёрзшего индекса.
 */
async function sweepIndex(env, meta, cursor, pages, fetchFn) {
  const { endpoint: url, apiKey } = await endpoint(env, meta, fetchFn);
  const hashes = meta.pageHashes ?? {};
  const items = [];
  let changed = false;
  let total = Number(meta.indexTotal ?? klevu.PAGE_LIMIT);

  for (let i = 0; i < pages; i++) {
    const page = (Number(cursor.klevu ?? 0) + i) % klevu.pageCount(total);
    const result = await klevu.fetchPage(url, apiKey, page * klevu.PAGE_LIMIT, fetchFn);
    total = result.total || total;
    const found = klevu.toItems(result.records).map((it) => ({ ...it, source: "индекс" }));
    const hash = state.snapshotHash(found);
    if (hashes[page] !== hash) {
      hashes[page] = hash;
      changed = true;
    }
    items.push(...found);
  }

  // Круг замкнулся, когда увидены ВСЕ страницы каталога — считаем по реально
  // прочитанным, а не по номеру страницы.
  //
  // Раньше здесь стояло `page === count - 1`, и на первом же тике это было
  // верно: размер каталога ещё неизвестен, pageCount по умолчанию давал 1,
  // то есть 0 === 0. Круг объявлялся пройденным после ОДНОЙ страницы из шести,
  // первичное наполнение обрывалось на трети, и остальные две сотни товаров
  // уходили в чат как «новые». Проверено на живом деплое 25.09.2026.
  const count = klevu.pageCount(total);
  if (Object.keys(hashes).length >= count) {
    meta.circles = Number(meta.circles ?? 0) + 1;
  }

  cursor.klevu = (Number(cursor.klevu ?? 0) + pages) % count;
  meta.indexTotal = total;
  meta.pageHashes = hashes;
  if (changed) meta.lastChangeTs = Math.floor(Date.now() / 1000);
  return items;
}

/**
 * Живые страницы списка, начиная с курсора. Курсор идёт по разделам подряд.
 *
 * Это единственное место, которое даёт скорость: индекс про свежие уценки не
 * знает. 24 страницы, по две за тик, четыре тика из пяти — полный круг за
 * 15 минут.
 */
async function sweepListing(env, meta, cursor, pages, fetchFn) {
  const lengths = meta.sectionPages ?? {};
  const found = [];

  for (let i = 0; i < pages; i++) {
    const section = Number(cursor.section ?? 0) % SALE_URLS.length;
    const page = Math.max(1, Number(cursor.page ?? 1));
    const url = `${SALE_URLS[section]}?p=${page}`;

    // Пауза перед второй страницей: две подряд без задержки — маленькая, но
    // очередь, а именно всплески и выглядят роботом. Разброс тоже нарочно.
    if (i) await new Promise((r) => setTimeout(r, 400 + Math.random() * 600));

    const html = await puma.fetchPuma(url, fetchFn, SALE_URLS[section]);

    // Пустая страница = раздел кончился. Запоминаем его длину и идём в
    // следующий. Раньше длина была зашита числом 12, и это стоило дорого:
    // замер 25.09.2026 показал 13 страниц в мужском разделе и 15 в женском,
    // то есть 109 товаров окно свежести не видело вовсе. Теперь длина
    // выясняется сама и переживает любые изменения распродажи.
    if (!puma.hasProducts(html)) {
      lengths[section] = Math.max(1, page - 1);
      console.log(`окно свежести: ${url} пуста — в разделе ${lengths[section]} стр.`);
      nextSection(cursor, section);
      continue;
    }

    const items = [...puma.parseListing(html).values()]
      .map((it) => ({ ...it, source: "живая страница" }));
    console.log(`окно свежести: ${url} -> кроссовок со скидкой ${items.length}`);
    found.push(...items);

    // Длину знаем — на пустую страницу больше не тратимся.
    if (lengths[section] && page >= lengths[section]) {
      nextSection(cursor, section);
    } else {
      // Раздел пишем явно: на первом тике его в курсоре ещё нет, и без этой
      // строки он так и оставался бы неопределённым.
      cursor.section = section;
      cursor.page = page + 1;
    }
  }

  meta.sectionPages = lengths;
  return found;
}

/** Перейти к началу следующего раздела. */
function nextSection(cursor, section) {
  cursor.section = (section + 1) % SALE_URLS.length;
  cursor.page = 1;
}

/**
 * Проверить кандидата на живой странице и отправить, если скидка настоящая.
 * Возвращает готовую карточку или null.
 *
 * Три причины промолчать, и все три НЕ запоминают цену — иначе скидка
 * потеряется навсегда: страница не открылась, размеров нет, карточка не дошла.
 */
async function confirmAndSend(env, item, seen, chatIds, minDiscount, fetchFn, forcedReason = "") {
  if (!item.url) return null;
  const html = await puma.fetchPuma(item.url, fetchFn);
  const info = puma.parseProduct(html);

  // Цена ТОЛЬКО отсюда. Индекс мог отстать — и отстаёт, это замерено.
  const price = info.price || 0;
  const oldPrice = info.oldPrice || 0;
  if (!price || !oldPrice || price >= oldPrice) {
    console.log(`${item.sku}: на странице скидки нет (${price} из ${oldPrice}) — источник отстал`);
    return null;
  }
  const was = seen[item.sku];
  // В обычном режиме молчим, если дешевле не стало. Но для первого показа это
  // правило пришлось бы обойти: память только что перенесена из старой базы,
  // цены совпадают, и по обычному правилу не ушло бы ни одной карточки.
  if (!forcedReason && was !== undefined && price >= was) return null;
  if (!info.sizes.length) {
    console.log(`${item.sku}: размеров нет — вернусь позже`);
    return null;
  }
  const discount = Math.round((1 - price / oldPrice) * 100);
  if (discount < minDiscount) {
    seen[item.sku] = price; // запомнить молча, как MIN_DISCOUNT в checker.py
    return null;
  }

  const card = {
    sku: item.sku,
    name: item.name,
    url: item.url,
    price,
    old_price: oldPrice,
    discount,
    color: info.color,
    sizes: info.sizes,
    image: imageUrl(item.sku),
  };
  const reason = forcedReason || (was === undefined ? REASON_NEW : `Цена упала (было ${was} ₴)`);
  const delivered = await broadcast(env, chatIds, card, reason);
  if (!delivered) {
    console.log(`${item.sku}: не дошло ни до кого — вернусь позже`);
    return null;
  }
  // Повод и число получателей кладём в саму карточку: она уходит в витрину, а
  // оттуда — в статус Worker'а. Без этого на вопрос «почему бот это прислал и
  // всем ли дошло?» можно ответить только живым логом, который уже утёк.
  card.reason = reason;
  card.delivered = delivered;
  card.of = chatIds.length;
  // Кто нашёл и что бот помнил до этого. По этим двум полям видно, настоящая
  // это свежая уценка (нашла живая страница) или индекс догоняет то, что уже
  // давно на сайте. Без них отличить одно от другого нечем.
  card.source = item.source ?? "—";
  card.was = was ?? null;
  console.log(`${item.sku}: отправлено ${delivered} из ${chatIds.length}`
    + ` — ${reason}, нашёл: ${card.source}`);
  seen[item.sku] = price;
  return card;
}

/**
 * Тик целиком.
 * @param {object} env окружение Worker
 * @param {Date} now подменяется в тестах
 * @param {Function} fetchFn подменяется в тестах
 */
export async function tick(env, now = new Date(), fetchFn = fetch) {
  const meta = await state.readMeta(env);
  resetIfStale(meta);
  const nowSec = Math.floor(now.getTime() / 1000);
  const paused = nowSec < Number(meta.pumaPauseUntil ?? 0);

  const cursor = await state.readCursor(env);
  const seen = await state.readSeen(env);
  const sweepPages = num(env.SWEEP_PAGES, 2);
  const listingPages = num(env.LISTING_PAGES, 2);
  const minDiscount = num(env.MIN_DISCOUNT, 0) || 0;
  const step = plan(now.getUTCMinutes(), sweepPages, listingPages);

  let items = [];
  try {
    if (step.kind === "index") {
      items = await sweepIndex(env, meta, cursor, step.pages, fetchFn);
    } else if (!paused) {
      items = await sweepListing(env, meta, cursor, step.pages, fetchFn);
    } else {
      console.log("Пума на паузе — окно свежести пропускаю");
    }
  } catch (e) {
    return await handleFailure(env, meta, e, nowSec);
  }

  meta.lastSweepTs = nowSec;

  // Первый запуск или потеря KV: запоминаем молча, иначе прилетит залп на
  // несколько сотен карточек. Пока каталог не обойдён целиком — не шлём ничего.
  if (state.isFirstRun(seen, items) || meta.seeding) {
    for (const it of items) seen[it.sku] = it.price;
    meta.seeding = Number(meta.circles ?? 0) < 1;
    await state.writeSeen(env, seen);
    await state.writeCursor(env, cursor);
    if (!meta.seeding) {
      await warnOnce(env, meta, "seeded",
        `Запомнил ${Object.keys(seen).length} кроссовок со скидкой. ` +
        "Дальше приходит только новое или подешевевшее — проверяю каждую минуту.", 3600);
    }
    await state.writeMeta(env, meta);
    return { kind: step.kind, seeding: true, seen: Object.keys(seen).length };
  }

  // Первый показ после переезда: человек должен сразу увидеть, что бот живой,
  // а не ждать первой уценки. Шлём самые крупные скидки из того, что уже есть,
  // и этим же наполняем витрину для /start — иначе она пуста до первой находки.
  if (!meta.firstShowDone && items.length && !paused) {
    await firstShow(env, meta, items, seen, minDiscount, fetchFn);
    await state.writeSeen(env, seen);
    await state.writeCursor(env, cursor);
    await state.writeMeta(env, meta);
    return { kind: step.kind, firstShow: true };
  }

  const wanted = state.candidates(items, seen).slice(0, MAX_CARDS);
  const sent = [];
  if (wanted.length && !paused) {
    const chatIds = await recipients(env);
    for (const item of wanted) {
      try {
        const card = await confirmAndSend(env, item, seen, chatIds, minDiscount, fetchFn);
        if (card) sent.push(card);
      } catch (e) {
        if (e instanceof puma.BannedError || e instanceof puma.RetryableError) {
          await handleFailure(env, meta, e, nowSec);
          break;
        }
        console.log(`${item.sku}: не проверил (${e}) — вернусь позже`);
      }
    }
  }

  if (sent.length) {
    await state.writeSeen(env, seen);
    await state.pushShowcase(env, sent);
  }
  await state.writeCursor(env, cursor);
  await checkFrozen(env, meta, nowSec);
  await state.writeMeta(env, meta);

  return { kind: step.kind, found: items.length, candidates: wanted.length, sent: sent.length };
}

/**
 * Починка состояния, испорченного прошлой версией.
 *
 * Считать круги каталога бот раньше умел неправильно, и в KV осталась отметка
 * «наполнение закончено» при памяти, заполненной на треть. Просто выложить
 * исправленный код мало: отметка-то уже стоит, и остаток каталога снова уехал
 * бы в чат как двести «новых» скидок.
 *
 * Поэтому — разовый сброс по версии схемы. Наполнение запускается заново и
 * проходит молча, как и задумано.
 */
function resetIfStale(meta) {
  if (Number(meta.seedVersion ?? 0) >= SEED_VERSION) return;
  console.log("состояние от старой версии — запускаю наполнение заново");
  meta.seedVersion = SEED_VERSION;
  meta.seeding = true;
  meta.circles = 0;
  meta.pageHashes = {};
  meta.firstShowDone = false;
}

/**
 * Разовый первый показ: самые крупные скидки из первой же выборки.
 *
 * Зачем. После переезда память уже перенесена, поэтому обычное правило «шлём
 * только то, что подешевело» означало бы тишину до первой новой уценки — может,
 * несколько часов. Человеку в этот момент нужно увидеть, что бот работает.
 *
 * Отправленное сразу попадает в seen, так что повторно эти карточки не придут.
 * Отметку firstShowDone ставим в любом случае: показ разовый, и если он не
 * удался, повторять его на каждом тике нельзя.
 */
async function firstShow(env, meta, items, seen, minDiscount, fetchFn) {
  meta.firstShowDone = true;
  const best = [...items]
    .filter((it) => it.url)
    .sort((a, b) => (1 - a.price / a.oldPrice) < (1 - b.price / b.oldPrice) ? 1 : -1)
    .slice(0, MAX_CARDS);
  if (!best.length) return;

  const chatIds = await recipients(env);
  const sent = [];
  for (const item of best) {
    try {
      const card = await confirmAndSend(env, item, seen, chatIds, minDiscount, fetchFn,
                                        REASON_SHOWCASE);
      if (card) sent.push(card);
    } catch (e) {
      console.log(`первый показ, ${item.sku}: ${e}`);
    }
  }
  await state.pushShowcase(env, sent);
  console.log(`первый показ: отправлено ${sent.length} карточек`);
}

/** Отказ Пумы: 403 — пауза на сутки и крик, 429 — короткая пауза молча. */
async function handleFailure(env, meta, error, nowSec) {
  if (error instanceof puma.BannedError) {
    meta.pumaPauseUntil = nowSec + BAN_PAUSE_SEC;
    await warnOnce(env, meta, "banned",
      "Puma ответила 403 — похоже, закрылась от бота.\n" +
      "Останавливаю запросы к сайту на сутки: долбить сейчас только хуже.\n" +
      "Скидки пока приходить не будут.");
    await state.writeMeta(env, meta);
    return { kind: "banned" };
  }
  if (error instanceof puma.RetryableError) {
    meta.pumaPauseUntil = nowSec + error.retryAfterSec;
    console.log(`Пума просит подождать ${error.retryAfterSec} с`);
    await state.writeMeta(env, meta);
    return { kind: "retry", after: error.retryAfterSec };
  }
  console.log(`тик сорвался: ${error}`);
  await warnOnce(env, meta, "sweep", `Обход сорвался: ${error}`);
  await state.writeMeta(env, meta);
  return { kind: "error", error: String(error) };
}

/**
 * Сторож замёрзшего индекса. По каталогу из 5161 товара что-то меняется
 * постоянно; если отпечаток стоит два часа — индекс встал, и молчание бота
 * больше ничего не значит. Без этого поломка выглядит как «нет скидок».
 */
async function checkFrozen(env, meta, nowSec) {
  const last = Number(meta.lastChangeTs ?? 0);
  if (!last) {
    meta.lastChangeTs = nowSec;
    return;
  }
  const hours = (nowSec - last) / 3600;
  if (hours >= FROZEN_HOURS) {
    // Текст нарочно спокойный. Скидки ищет окно живых страниц, а индекс нужен
    // только для полноты — чтобы не потерять товары, которых нет в двух
    // разделах распродажи. Прежняя формулировка пугала «медленнее обычного»,
    // хотя окно как раз и есть быстрый путь.
    await warnOnce(env, meta, "frozen",
      `Поисковый индекс Puma не обновлялся ${hours.toFixed(0)} ч.\n` +
      "Скидки приходят как обычно — их находит обход живых страниц, он не зависит "
      + "от индекса.\nПод вопросом только полнота: товары вне разделов распродажи "
      + "бот сейчас может не видеть. Если это повторится — стоит проверить индекс.");
  }
}
