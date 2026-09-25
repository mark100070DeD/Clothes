/**
 * Проверки фонового обхода. Запуск: cd worker && node --test
 *
 * Главное, что здесь проверяется, — что цена в карточке берётся СО СТРАНИЦЫ
 * ТОВАРА, а не из поискового индекса. Индекс отстаёт (замер 25.09.2026: 2
 * расхождения из 89, оба раза сайт дешевле), и если довериться ему, человек
 * получит неправильную цену. Тест `цена берётся со страницы` держит это свойство.
 */
import assert from "node:assert/strict";
import test from "node:test";

import * as klevu from "../src/klevu.js";
import * as puma from "../src/puma.js";
import * as state from "../src/state.js";
import { imageUrl, plan, tick } from "../src/sweep.js";

/** Память вместо KV: хватает, чтобы прогнать тик целиком. */
function fakeKv(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    store,
    async get(key, opts) {
      const raw = store.get(key);
      if (raw === undefined) return null;
      return opts?.type === "json" ? JSON.parse(raw) : raw;
    },
    async put(key, value) {
      store.set(key, value);
    },
    async list() {
      return { keys: [{ name: "sub:777", metadata: { chat_id: 777 } }], list_complete: true };
    },
  };
}

const PRODUCT_HTML = `<html><head><title>Кросівки X | Колір: Білий | Warm White | Puma</title></head>
<body><span id="product-price-1" data-price-amount="1490" data-price-type="finalPrice"></span>
<span id="old-price-1" data-price-amount="2990" data-price-type="oldPrice"></span>
<li class="size-list__item " data-available="1" data-label="41"></li>
<li class="size-list__item unavailable" data-available="0" data-label="42"></li></body></html>`;

const SOLD_OUT_HTML = PRODUCT_HTML.replace('data-available="1"', 'data-available="0"');

/** Индекс утверждает 2090, а страница товара показывает 1490. Сайт дешевле. */
function indexRecord(sku = "404843_01", salePrice = "2090.00") {
  return {
    url: `https://ua.puma.com/uk/krosivky-${sku.replace("_", "-")}.html?size=41`,
    name: "Кросівки Velocity",
    salePrice,
    price: "2990.00",
    inStock: "yes",
  };
}

/** Подменённый fetch: индекс, страница товара и Telegram. */
function fakeFetch({ records = [], total = 1, product = PRODUCT_HTML, sent = [] } = {}) {
  return async (url, init) => {
    const target = String(url);
    if (target.includes("ksearchnet.com")) {
      return jsonResponse({
        queryResults: [{ meta: { totalResultsFound: total }, records }],
      });
    }
    if (target.includes("api.telegram.org")) {
      sent.push(JSON.parse(init.body));
      return jsonResponse({ ok: true, result: {} });
    }
    return textResponse(product);
  };
}

const jsonResponse = (body, status = 200) => ({
  ok: status < 400,
  status,
  headers: new Map(),
  json: async () => body,
  text: async () => JSON.stringify(body),
});

const textResponse = (text, status = 200) => ({
  ok: status < 400,
  status,
  headers: { get: () => null },
  json: async () => ({}),
  text: async () => text,
});

const envWith = (kv) => ({
  SUBS: kv,
  BOT_TOKEN: "1:x",
  CHAT_ID: "42",
  SWEEP_PAGES: "1",
  LISTING_PAGES: "1",
});

const atMinute = (m) => new Date(Date.UTC(2026, 8, 25, 12, m, 0));

/** Готовое состояние: адрес индекса уже найден, каталог уже обойдён кругом. */
const READY_META = JSON.stringify({
  endpoint: "https://eucs20.ksearchnet.com/cs/v2/search",
  apiKey: "klevu-158811194777911465",
  endpointTs: Math.floor(Date.now() / 1000),
  circles: 1,
  firstShowDone: true,
  seedVersion: 2,
});

/** То же, но первый показ ещё не состоялся — как сразу после переезда. */
const FRESH_META = JSON.stringify({
  endpoint: "https://eucs20.ksearchnet.com/cs/v2/search",
  apiKey: "klevu-158811194777911465",
  endpointTs: Math.floor(Date.now() / 1000),
  circles: 1,
  seedVersion: 2,
});

/** Состояние, оставленное прошлой версией: seedVersion ещё нет. */
const OLD_META = JSON.stringify({
  endpoint: "https://eucs20.ksearchnet.com/cs/v2/search",
  apiKey: "klevu-158811194777911465",
  endpointTs: Math.floor(Date.now() / 1000),
  circles: 1,
  firstShowDone: true,
});

/** Адрес индекса известен, но каталог ещё ни разу не обойдён. */
const SEEDING_META = JSON.stringify({
  endpoint: "https://eucs20.ksearchnet.com/cs/v2/search",
  apiKey: "klevu-158811194777911465",
  endpointTs: Math.floor(Date.now() / 1000),
  circles: 0,
  seedVersion: 2,
});

/**
 * Прогнать тик на подменённой сети.
 *
 * globalThis.fetch подменяем тоже: отправка в Telegram идёт через него, а не
 * через аргумент. Без этого тест молча стучался бы в настоящий api.telegram.org.
 */
async function run(env, minute, fetchFn) {
  const real = globalThis.fetch;
  globalThis.fetch = fetchFn;
  try {
    return await tick(env, atMinute(minute), fetchFn);
  } finally {
    globalThis.fetch = real;
  }
}

test("расписание тиков: четыре минуты живым страницам, пятая индексу", () => {
  // Скорость даёт окно живых страниц, а не индекс: замер 25.09.2026 показал,
  // что шесть найденных скидок индекс не знал и через 40 минут. Поэтому четыре
  // тика из пяти уходят на страницы — 24 страницы по две за тик, круг 15 минут.
  for (const m of [0, 1, 2, 3]) {
    assert.deepEqual(plan(m), { kind: "listing", pages: 2 }, `минута ${m}`);
  }
  assert.deepEqual(plan(4, 2), { kind: "index", pages: 2 });
  assert.deepEqual(plan(9, 3), { kind: "index", pages: 3 });
  assert.deepEqual(plan(0, 2, 1), { kind: "listing", pages: 1 }, "ручка LISTING_PAGES");
});

test("за тик берутся две живые страницы, курсор идёт дальше", async () => {
  // Круг по 24 страницам и есть вся скорость бота. По одной странице за тик он
  // занимал час; по две — пятнадцать минут. Стало возможно после того, как
  // разбор страницы подешевел с 5 мс до 1 мс и перестал упираться в лимит CPU.
  const asked = [];
  const kv = fakeKv({ "state:meta": READY_META, "state:seen": JSON.stringify({ x: 1 }) });
  const fetchFn = async (url, init) => {
    const target = String(url);
    if (target.includes("skidki")) asked.push(target);
    if (target.includes("api.telegram.org")) return jsonResponse({ ok: true, result: {} });
    return textResponse("<html></html>");
  };
  // Без LISTING_PAGES в окружении — значит берётся значение по умолчанию.
  const env = { SUBS: kv, BOT_TOKEN: "1:x", CHAT_ID: "42" };
  await run(env, 0, fetchFn);

  assert.equal(asked.length, 2, "две страницы за тик");
  assert.match(asked[0], /muzhchiny\/obuv\.html\?p=1/);
  assert.match(asked[1], /muzhchiny\/obuv\.html\?p=2/);
  assert.equal(JSON.parse(kv.store.get("state:cursor")).listing, 2, "курсор сдвинут на две");
});

test("адрес индекса достаётся из HTML страницы", () => {
  // Этот путь не был покрыт, и в нём жил баг: регулярка с экранированным
  // слешем распалась на деление, обход падал с «g is not defined» на каждом
  // тике, а все 26 тестов при этом были зелёными — в них адрес брался из KV.
  const html = String.raw`<script>var x = {"searchUrl":"https:\/\/eucs20.ksearchnet.com\/cloud-search\/n-search\/search?ticket=klevu-158811194777911465&paginationStartsFrom=0"};</script>`;
  const found = klevu.parseEndpoint(html);
  assert.equal(found.endpoint, "https://eucs20.ksearchnet.com/cs/v2/search",
    "из страницы берём хост, но адрес собираем на v2");
  assert.equal(found.apiKey, "klevu-158811194777911465");

  assert.throws(() => klevu.parseEndpoint("<html>без ключа</html>"));
});

test("адрес фото собирается из артикула", () => {
  assert.match(imageUrl("403206_08"), /\/global\/403206\/08\//);
});

test("отбор в индексе совпадает с правилом бота", () => {
  const ok = klevu.toItem(indexRecord());
  assert.equal(ok.sku, "404843_01");
  assert.equal(ok.price, 2090, "salePrice — текущая цена");
  assert.equal(ok.oldPrice, 2990, "price — цена до скидки");
  assert.equal(ok.url.includes("?"), false, "хвост ?size= отваливается");

  assert.equal(klevu.toItem({ ...indexRecord(), name: "Сандалі" }), null);
  assert.equal(klevu.toItem({ ...indexRecord(), inStock: "no" }), null);
  assert.equal(klevu.toItem(indexRecord("111111_01", "2990.00")), null, "скидки нет");
});

test("детская обувь отсеивается, взрослая с «kids» в бренде — нет", () => {
  // Имена настоящие, из каталога. Проверено на живых данных 25.09.2026:
  // из 586 кроссовок со скидкой 109 детских, фильтр ловит все и не задевает
  // ни одного взрослого. Правило обязано совпадать с KIDS_RE в scraper.py.
  const kids = [
    "Дитячі кеди Karmen II IDOL Sneakers Kids",
    "Дитячі кросівки Anzarun Lite Kids’ Trainers",
    "Дитячі кеди Shuffle V Babies' Trainers",
    "Кросівки RS-X Kids Sneakers",           // «Дитячі» в названии нет
  ];
  for (const name of kids) {
    assert.equal(klevu.isWanted(name), false, name);
  }

  const adults = [
    "Кросівки Mostro OG Prime Sneakers Unisex",
    // Бренд коллаборации содержит «kids» — но это взрослая обувь. Без границы
    // слова фильтр выбрасывал её вместе с детской.
    "Кеди PUMA x KIDSUPER Brasil Panels Sneakers Unisex",
  ];
  for (const name of adults) {
    assert.equal(klevu.isWanted(name), true, name);
  }

  assert.equal(klevu.isWanted("Сандалі Leadcat"), false, "не кроссовки — тоже мимо");
});

test("детский товар не проходит отбор в индексе", () => {
  const rec = { ...indexRecord(), name: "Дитячі кросівки Anzarun Lite Kids" };
  assert.equal(klevu.toItem(rec), null);
});

test("страница товара отдаёт цену, размеры и цвет", () => {
  const info = puma.parseProduct(PRODUCT_HTML);
  assert.equal(info.price, 1490);
  assert.equal(info.oldPrice, 2990);
  assert.deepEqual(info.sizes, ["41"], "распроданные размеры не берём");
  assert.equal(info.color, "Warm White (білий)");
});

test("403 и 429 разбираются по-разному", async () => {
  const banned = async () => ({ ok: false, status: 403, headers: { get: () => null } });
  await assert.rejects(() => puma.fetchPuma("https://ua.puma.com/x", banned), puma.BannedError);

  const busy = async () => ({ ok: false, status: 429, headers: { get: () => "30" } });
  await assert.rejects(
    () => puma.fetchPuma("https://ua.puma.com/x", busy),
    (e) => e instanceof puma.RetryableError && e.retryAfterSec === 30,
  );
});

test("первый запуск запоминает молча, карточек не шлёт", async () => {
  const sent = [];
  const kv = fakeKv({ "state:meta": READY_META });
  const records = ["111111_01", "222222_02", "333333_03", "444444_04"]
    .map((s) => indexRecord(s));
  await run(envWith(kv), 4, fakeFetch({ records, total: 1, sent }));

  const seen = JSON.parse(kv.store.get("state:seen"));
  assert.equal(Object.keys(seen).length, 4, "все цены запомнены");
  assert.equal(sent.some((m) => m.photo), false, "ни одной карточки не ушло");
});

test("цена берётся со страницы товара, а не из индекса", async () => {
  const sent = [];
  const kv = fakeKv({
    // 2200 — то, что бот отправлял раньше. Индекс говорит 2090, страница 1490.
    "state:seen": JSON.stringify({ "404843_01": 2200 }),
    "state:meta": READY_META,
  });
  await run(envWith(kv), 4, fakeFetch({ records: [indexRecord()], total: 1, sent }));

  const card = sent.find((m) => m.caption);
  assert.ok(card, "карточка должна уйти");
  assert.match(card.caption, /1 490/, "в карточке цена со страницы товара");
  assert.equal(/2 090/.test(card.caption), false, "цена из индекса в карточку не попадает");

  const seen = JSON.parse(kv.store.get("state:seen"));
  assert.equal(seen["404843_01"], 1490, "запоминаем именно отправленную цену");
});

test("карточка уходит ВСЕМ: и владельцу, и подписчикам", async () => {
  // Владелец задан через CHAT_ID (42), подписчик лежит в KV (777). Оба должны
  // получить одну и ту же карточку. Раньше это нигде не проверялось, а вопрос
  // «а всем ли дошло?» — первое, что спрашивают про рассылку.
  const sent = [];
  const kv = fakeKv({
    "state:seen": JSON.stringify({ "404843_01": 2200 }),
    "state:meta": READY_META,
  });
  await run(envWith(kv), 4, fakeFetch({ records: [indexRecord()], total: 1, sent }));

  const cards = sent.filter((m) => m.caption);
  const gotIt = cards.map((m) => m.chat_id).sort();
  assert.deepEqual(gotIt, [42, 777], "карточку получили владелец и подписчик");

  // Число получателей записано в самой карточке — оно видно в статусе Worker'а.
  const showcase = JSON.parse(kv.store.get("state:showcase"));
  assert.equal(showcase[0].delivered, 2);
  assert.equal(showcase[0].of, 2);
  assert.match(showcase[0].reason, /Цена упала/);
});

test("распроданный товар не запоминается — вернётся, когда размеры появятся", async () => {
  const sent = [];
  const kv = fakeKv({
    "state:seen": JSON.stringify({ "404843_01": 2200 }),
    "state:meta": READY_META,
  });
  await run(envWith(kv), 4,
    fakeFetch({ records: [indexRecord()], total: 1, product: SOLD_OUT_HTML, sent }));

  assert.equal(sent.some((m) => m.caption), false, "карточки нет");
  const seen = JSON.parse(kv.store.get("state:seen"));
  assert.equal(seen["404843_01"], 2200, "старая цена осталась — скидка не потеряна");
});

test("на странице скидки уже нет — молчим, индекс просто отстал", async () => {
  const sent = [];
  const kv = fakeKv({
    "state:seen": JSON.stringify({ "404843_01": 2200 }),
    "state:meta": READY_META,
  });
  const noDiscount = PRODUCT_HTML.replace('data-price-amount="1490"', 'data-price-amount="2990"');
  await run(envWith(kv), 4,
    fakeFetch({ records: [indexRecord()], total: 1, product: noDiscount, sent }));
  assert.equal(sent.some((m) => m.caption), false, "ложную скидку не шлём");
});

test("403 останавливает обход на сутки и пишет владельцу", async () => {
  const sent = [];
  const kv = fakeKv({ "state:meta": READY_META });
  const fetchFn = async (url, init) => {
    if (String(url).includes("api.telegram.org")) {
      sent.push(JSON.parse(init.body));
      return jsonResponse({ ok: true, result: {} });
    }
    return { ok: false, status: 403, headers: { get: () => null } };
  };
  const result = await run(envWith(kv), 0, fetchFn);

  assert.equal(result.kind, "banned");
  const meta = JSON.parse(kv.store.get("state:meta"));
  assert.ok(meta.pumaPauseUntil > Date.now() / 1000 + 3600, "пауза не меньше часа");
  assert.equal(sent.some((m) => /403/.test(m.text ?? "")), true, "тревога ушла");
});

test("после переезда бот сразу показывает крупнейшие скидки", async () => {
  const sent = [];
  // Память перенесена из старой базы: 555 цен уже известны, новых скидок нет.
  // Без первого показа человек не увидел бы ни одного сообщения до первой
  // уценки — может, несколько часов. Это и проверяем.
  const kv = fakeKv({
    "state:seen": JSON.stringify({ "404843_01": 1490, "555555_05": 1000 }),
    "state:meta": FRESH_META,
  });
  const records = [indexRecord(), indexRecord("555555_05", "1000.00")];
  const result = await run(envWith(kv), 4, fakeFetch({ records, total: 1, sent }));

  assert.equal(result.firstShow, true);
  const cards = sent.filter((m) => m.caption);
  assert.ok(cards.length >= 1, "карточки должны уйти сразу");
  assert.match(cards[0].caption, /Сейчас на распродаже/, "подпись витрины, не «новая скидка»");

  const meta = JSON.parse(kv.store.get("state:meta"));
  assert.equal(meta.firstShowDone, true, "показ разовый, второй раз не повторится");
  assert.ok(JSON.parse(kv.store.get("state:showcase")).length >= 1, "витрина наполнена");
});

test("наполнение не заканчивается, пока каталог не прочитан целиком", async () => {
  // Баг с живого деплоя 25.09.2026. Размер каталога на первом тике неизвестен,
  // по умолчанию считался одной страницей — и круг объявлялся пройденным после
  // ОДНОЙ страницы из шести. Наполнение обрывалось на трети, а оставшиеся
  // двести товаров уходили в чат как «новые». Тесты это пропустили, потому что
  // в них total всегда был равен 1.
  const sent = [];
  const kv = fakeKv({ "state:meta": SEEDING_META });
  const records = ["111111_01", "222222_02", "333333_03", "444444_04"]
    .map((s) => indexRecord(s));
  // total 5183 -> шесть страниц по 1000. Одного тика на круг не хватит.
  const result = await run(envWith(kv), 4, fakeFetch({ records, total: 5183, sent }));

  assert.equal(result.seeding, true, "после одной страницы наполнение не закончено");
  const meta = JSON.parse(kv.store.get("state:meta"));
  assert.equal(meta.seeding, true, "флаг наполнения должен остаться поднятым");
  assert.equal(Number(meta.circles ?? 0), 0, "круг не пройден");
  assert.equal(sent.some((m) => m.photo), false, "во время наполнения молчим");
});

test("состояние старой версии сбрасывается и наполняется заново", async () => {
  // Выложить исправленный код мало: в KV осталась отметка «наполнение
  // закончено» при памяти, заполненной на треть.
  const sent = [];
  const kv = fakeKv({
    "state:seen": JSON.stringify({ "404843_01": 2200 }),
    "state:meta": OLD_META,   // без seedVersion — то есть от старой версии
  });
  const result = await run(envWith(kv), 4,
    fakeFetch({ records: [indexRecord()], total: 5183, sent }));

  assert.equal(result.seeding, true, "испорченное состояние уходит в наполнение");
  const meta = JSON.parse(kv.store.get("state:meta"));
  assert.equal(meta.seedVersion, 2);
  assert.equal(sent.some((m) => m.photo), false, "и делает это молча");
});

test("отпечаток каталога меняется вместе с ценой", () => {
  const a = state.snapshotHash([{ sku: "1_1", price: 100 }]);
  assert.equal(a, state.snapshotHash([{ sku: "1_1", price: 100 }]));
  assert.notEqual(a, state.snapshotHash([{ sku: "1_1", price: 99 }]));
});
