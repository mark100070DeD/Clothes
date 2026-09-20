/**
 * Подпись карточки товара. Это перенос puma/messages.py на JS — вывод должен
 * совпадать символ в символ, иначе карточки от Worker и от Python будут выглядеть
 * по-разному. Тест в test/caption.test.js сверяется с фактическим выводом Python.
 *
 * Чистые функции, без обращений к сети: их удобно проверять через node --test.
 */

/** Как html.escape(s, quote=False) в Python: только & < > и ничего больше. */
export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Как money() в Python: разряды через пробел плюс знак гривны. 2590 -> "2 590 ₴" */
export function money(value) {
  const digits = String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${digits} ₴`;
}

/**
 * Карточка товара разметкой HTML для Telegram.
 * @param {{name:string,price:number,old_price:number,discount:number,color:string,sizes:string[],url:string}} item
 * @param {string} reason подпись второй строкой: почему этот товар прислали
 */
export function caption(item, reason) {
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

/**
 * Приветствие к витрине. Отметку времени показываем всегда: расписание GitHub
 * ненадёжное, и данные могут быть многочасовой давности — человек должен это
 * видеть, иначе бот выглядит врущим по ценам.
 */
export function greeting(count, updatedAt) {
  if (!count) {
    return "Скидок пока нет в памяти бота. Он соберёт их на ближайшей проверке и пришлёт сам.";
  }
  return (
    `Показываю ${count} кроссовок с распродажи (данные собраны ${formatTime(updatedAt)}). ` +
    "Дальше буду присылать новые скидки сам, тыкать ничего не надо."
  );
}

/** ISO-время -> «20.09 в 16:33» по Киеву. Не вышло разобрать — отдаём как есть. */
export function formatTime(iso) {
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
