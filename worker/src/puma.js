import { isWanted } from "./klevu.js";

/**
 * Живой сайт Пумы: страница товара и страница списка.
 *
 * Роль в схеме. Индекс (klevu.js) говорит «посмотри сюда», а ИСТИНУ про цену,
 * размеры и наличие бот берёт здесь. Причина замерена 25.09.2026: из 89 товаров
 * индекс разошёлся с сайтом на двух, и оба раза сайт был ДЕШЕВЛЕ. Если верить
 * индексу, в карточке окажется неправильная цена.
 *
 * Поэтому: цена в сообщении — всегда отсюда, никогда из индекса.
 *
 * Опорные точки вёрстки, которые могут отвалиться (и больше никаких):
 *   страница товара: .size-list__item[data-label][data-available]   размеры
 *                    data-price-amount + data-price-type            цены
 *                    <title> ... | Колір: Білий | Warm White | ...  цвет
 *   страница списка: data-product-sku + data-product-item           связка
 *                    id="product-price-N" / id="old-price-N"        цены
 *
 * Про CPU. Страница товара весит ~625 КБ, страница списка ~950 КБ. Гонять
 * регулярки по всему тексту дорого, а у бесплатного тарифа 10 мс на вызов,
 * поэтому везде сначала вырезаем нужный кусок через indexOf и работаем с ним.
 */

/** Сайт закрылся от бота. Ловится отдельно: долбить дальше нельзя. */
export class BannedError extends Error {}
/** Временный отказ — можно повторить позже. Несёт задержку из Retry-After. */
export class RetryableError extends Error {
  constructor(message, retryAfterSec) {
    super(message);
    this.retryAfterSec = retryAfterSec;
  }
}

/** Реальный Chrome шлёт это всё. Один только User-Agent выглядит как робот. */
export const HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "uk-UA,uk;q=0.9",
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
};

/**
 * Запрос к Пуме с разбором отказов.
 * 403 — бан, поднимаем BannedError и выше по стеку останавливаем обход.
 * 429/503 — перегрузка, RetryableError с задержкой: вернёмся следующим тиком.
 */
export async function fetchPuma(url, fetchFn = fetch, referer = "") {
  const headers = { ...HEADERS };
  if (referer) headers.Referer = referer;
  const response = await fetchFn(url, { headers });
  if (response.status === 403) {
    throw new BannedError(`Puma ответила 403 на ${url}`);
  }
  if (response.status === 429 || response.status === 503) {
    const after = Number(response.headers.get("Retry-After")) || 60;
    throw new RetryableError(`Puma ответила ${response.status}`, after);
  }
  if (!response.ok) throw new Error(`Puma: HTTP ${response.status} на ${url}`);
  return await response.text();
}

/** Кусок текста вокруг первого и последнего совпадения метки. "" — если нет. */
function slice(html, marker, pad = 400) {
  const from = html.indexOf(marker);
  if (from < 0) return "";
  const to = html.lastIndexOf(marker);
  return html.slice(Math.max(0, from - pad), Math.min(html.length, to + pad + marker.length));
}

/** Размеры в наличии, в порядке страницы, без повторов. */
export function parseSizes(html) {
  const zone = slice(html, "size-list__item", 600);
  const sizes = [];
  const re = /size-list__item([^>]*)>/g;
  let m;
  while ((m = re.exec(zone)) !== null) {
    const attrs = m[1];
    if (!/data-available="1"/.test(attrs)) continue;
    if (/\bunavailable\b/.test(attrs)) continue;
    const label = /data-label="([^"]+)"/.exec(attrs);
    if (label && !sizes.includes(label[1])) sizes.push(label[1]);
  }
  return sizes;
}

/**
 * Цены со страницы товара: { price, oldPrice }. Нули, если не нашлись.
 * Атрибуты идут как data-price-amount перед data-price-type — но порядок
 * на сайте уже менялся, поэтому ловим оба варианта.
 */
export function parsePrices(html) {
  const zone = slice(html, "data-price-type=", 300);
  const grab = (type) => {
    // [0-9.] вместо \d нарочно: в шаблонной строке обратный слеш пришлось бы
    // удваивать, и это уже один раз ломало разбор цен молча.
    const a = new RegExp(`data-price-amount="([0-9.]+)"[^>]*data-price-type="${type}"`).exec(zone);
    if (a) return Math.round(Number(a[1]));
    const b = new RegExp(`data-price-type="${type}"[^>]*data-price-amount="([0-9.]+)"`).exec(zone);
    return b ? Math.round(Number(b[1])) : 0;
  };
  return { price: grab("finalPrice"), oldPrice: grab("oldPrice") };
}

/** Цвет из <title>: "... | Колір: Білий | Warm White-Alpine Snow | ..." */
export function parseColor(html) {
  const t = /<title>([^<]*)<\/title>/.exec(html);
  const title = t ? t[1] : "";
  const m = /Колір:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|/.exec(title);
  if (m) return `${m[2]} (${m[1].toLowerCase()})`;
  const j = /"color"\s*:\s*"([^"]+)"/.exec(html);
  return j ? j[1] : "—";
}

/** Страница товара -> всё, что нужно карточке. Цена здесь — истина. */
export function parseProduct(html) {
  return { sizes: parseSizes(html), color: parseColor(html), ...parsePrices(html) };
}

/**
 * Страница списка -> Map(sku -> {name, url, price, oldPrice}), только взрослые
 * кроссовки со скидкой. Это «окно свежести»: цены здесь настоящие, в отличие от индекса.
 *
 * Цена и артикул лежат в разных местах разметки, связывает их data-product-item:
 *   data-product-sku="403206_08" data-product-item="1601041"
 *   <span id="product-price-1601041" data-price-amount="2590" ...>
 */
export function parseListing(html) {
  const byId = new Map();
  const cards = /data-product-sku="([^"]+)" data-product-item="(\d+)"([^>]*)>/g;
  let m;
  while ((m = cards.exec(html)) !== null) {
    const nameMatch = /data-product-name="([^"]*)"/.exec(m[3]);
    byId.set(m[2], { sku: m[1], name: nameMatch ? nameMatch[1] : "" });
  }
  const price = new Map();
  const oldPrice = new Map();
  for (const [re, target] of [
    [/id="product-price-(\d+)"\s+data-price-amount="([\d.]+)"/g, price],
    [/id="old-price-(\d+)"\s+data-price-amount="([\d.]+)"/g, oldPrice],
  ]) {
    let p;
    while ((p = re.exec(html)) !== null) target.set(p[1], Math.round(Number(p[2])));
  }

  const out = new Map();
  for (const [id, card] of byId) {
    // Тот же фильтр, что в klevu.js и scraper.py: бутсы, сандалии, щитки и
    // детское тоже лежат в разделе распродажи обуви, но боту они не нужны.
    if (!isWanted(card.name)) continue;
    const now = price.get(id);
    const was = oldPrice.get(id);
    if (!now || !was || now >= was) continue;
    const link = new RegExp(
      `href="(https://ua[.]puma[.]com/uk/[^"]*-${card.sku.replace("_", "-")}[.]html)"`,
    ).exec(html);
    out.set(card.sku, {
      sku: card.sku,
      name: card.name,
      url: link ? link[1] : "",
      price: now,
      oldPrice: was,
    });
  }
  return out;
}
