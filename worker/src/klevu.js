/**
 * Каталог Пумы через её поисковый индекс (Klevu). Перенос puma/klevu.py на JS.
 *
 * Правила отбора обязаны совпадать с Python символ в символ: иначе суточная
 * сверка будет ругаться на расхождение, которого на самом деле нет.
 *
 * Зачем индекс вместо страниц. Страница списка весит ~950 КБ и отдаёт 36 товаров.
 * Индекс отдаёт 1000 товаров за 248 КБ — в 100 раз плотнее на товар. Весь
 * каталог (5161 позиция) обходится шестью запросами, поэтому его можно
 * перечитывать каждые три минуты, не трогая сайт Пумы вообще.
 *
 * Что здесь легко сломать:
 *   term="*"       перечисляет ВЕСЬ индекс. Поиск по словам неполон по
 *                  определению — на нём терялось 4% товаров.
 *   fields         без него запись весит втрое больше: полей там 37.
 *   price          ОСТОРОЖНО: это СТАРАЯ цена. Текущая — salePrice.
 *
 * Размеров в индексе нет: он отдаёт один вариант на цвет. За ними и за
 * настоящей ценой ходим на страницу товара — см. puma.js.
 */

export const PAGE_LIMIT = 1000;
export const FIELDS = ["id", "name", "url", "price", "salePrice", "inStock"];
const MAX_PAGES = 20; // предохранитель: каталог укладывается в 6 страниц

const SKU_RE = /-(\d{6})-(\d{2})\.html/;
const HOST_RE = /([a-z0-9-]+\.ksearchnet\.com)/;
const TICKET_RE = /(klevu-\d{10,})/;

/** Артикул из адреса: .../x-403206-08.html -> "403206_08". null, если не товар. */
export function skuOf(url) {
  const m = SKU_RE.exec(String(url ?? ""));
  return m ? `${m[1]}_${m[2]}` : null;
}

/** "5240.0" -> 5240. Ноль значит «цены нет» — такие записи пропускаем. */
export function money(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

/** Как is_sneakers в scraper.py: берём только кроссовки и кеды. */
export function isSneakers(name) {
  const n = String(name ?? "").toLowerCase();
  return n.includes("кросівки") || n.includes("кеди");
}

/** Адрес и ключ индекса из HTML страницы. Не хардкодим: поменяют — подхватим. */
export function parseEndpoint(html) {
  const text = String(html ?? "").replace(/\\//g, "/");
  const host = HOST_RE.exec(text);
  const ticket = TICKET_RE.exec(text);
  if (!host || !ticket) throw new Error("в странице не нашёлся адрес или ключ индекса");
  // В странице прописан старый n-search; v2 умеет term="*" и выбор полей.
  return { endpoint: `https://${host[1]}/cs/v2/search`, apiKey: ticket[1] };
}

export function queryBody(apiKey, offset, limit = PAGE_LIMIT) {
  return {
    context: { apiKeys: [apiKey] },
    recordQueries: [{
      id: "catalog",
      typeOfRequest: "SEARCH",
      settings: {
        query: { term: "*" },
        typeOfRecords: ["KLEVU_PRODUCT"],
        limit,
        offset,
        fields: FIELDS,
      },
    }],
  };
}

/** Ответ v2 -> { records, total }. Бросает, если пришёл не тот формат. */
export function readPage(payload) {
  const result = payload?.queryResults?.[0];
  if (!result) throw new Error(`ответ без queryResults: ${JSON.stringify(payload).slice(0, 200)}`);
  return {
    records: result.records ?? [],
    total: Number(result.meta?.totalResultsFound ?? 0),
  };
}

/**
 * Одна запись индекса -> товар или null.
 * Отбор тот же, что в parse_listing: кроссовки, есть скидка, есть в наличии.
 */
export function toItem(rec) {
  const sku = skuOf(rec?.url);
  if (!sku) return null;
  const name = rec.name ?? "";
  if (!isSneakers(name)) return null;
  if (!["yes", "true", "1"].includes(String(rec.inStock ?? "yes").toLowerCase())) return null;
  const price = money(rec.salePrice); // текущая
  const oldPrice = money(rec.price); // до скидки
  if (!price || !oldPrice || price >= oldPrice) return null;
  return { sku, name, url: String(rec.url).split("?")[0], price, oldPrice };
}

/** Записи -> кроссовки со скидкой, без повторов, в порядке индекса. */
export function toItems(records) {
  const out = new Map();
  for (const rec of records ?? []) {
    const it = toItem(rec);
    if (it && !out.has(it.sku)) out.set(it.sku, it);
  }
  return [...out.values()];
}

/** Номер страницы каталога -> смещение. Круг считаем по числу страниц. */
export function pageCount(total) {
  return Math.max(1, Math.min(MAX_PAGES, Math.ceil((total || PAGE_LIMIT) / PAGE_LIMIT)));
}

/** Одна страница индекса. fetchFn подменяется в тестах. */
export async function fetchPage(endpoint, apiKey, offset, fetchFn = fetch) {
  const response = await fetchFn(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(queryBody(apiKey, offset)),
  });
  if (!response.ok) throw new Error(`индекс: HTTP ${response.status}`);
  return readPage(await response.json());
}
