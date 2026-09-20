/**
 * Запуск: cd worker && node --test
 *
 * Смысл теста: подпись карточки в Worker обязана совпадать с puma/messages.py
 * символ в символ. Ожидаемые строки ниже — это ФАКТИЧЕСКИЙ вывод Python на тех же
 * данных, снятый командой:
 *
 *   python -c "from puma import messages; from puma.models import Item; ..."
 *
 * Если правишь messages.py — снимай вывод заново и правь здесь.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { caption, escapeHtml, greeting, money } from "../src/caption.js";

const ITEM = {
  sku: "403206_08",
  name: "Кросівки A&B <Prime> Unisex",
  url: "https://ua.puma.com/uk/a-403206-08.html",
  price: 2590,
  old_price: 6490,
  discount: 60,
  color: "Warm & White <Snow> (білий)",
  sizes: ["35.5", "36", "41"],
};

test("подпись совпадает с выводом puma/messages.py", () => {
  const expected = [
    "<b>Кросівки A&amp;B &lt;Prime&gt; Unisex</b>",
    "Сейчас на распродаже",
    "Цена: <b>2 590 ₴</b> <s>6 490 ₴</s> (-60%)",
    "Цвет: Warm &amp; White &lt;Snow&gt; (білий)",
    "Размеры: 35.5, 36, 41",
    '<a href="https://ua.puma.com/uk/a-403206-08.html">Открыть на puma.com</a>',
  ].join("\n");

  assert.equal(caption(ITEM, "Сейчас на распродаже"), expected);
});

test("разряды и знак гривны как в money() Python", () => {
  assert.equal(money(999), "999 ₴");
  assert.equal(money(1000), "1 000 ₴");
  assert.equal(money(2590), "2 590 ₴");
  assert.equal(money(6490), "6 490 ₴");
  assert.equal(money(1234567), "1 234 567 ₴");
});

test("экранируются только & < > — как html.escape(quote=False)", () => {
  assert.equal(escapeHtml('a & b < c > d "e"'), 'a &amp; b &lt; c &gt; d "e"');
});

test("нет размеров — так и написано", () => {
  const line = caption({ ...ITEM, sizes: [] }, "r").split("\n")[4];
  assert.equal(line, "Размеры: нет в наличии");
});

test("подпись не ломается на пустых полях", () => {
  const bare = { name: "", url: "", price: 0, old_price: 0, discount: 0, color: "", sizes: null };
  const text = caption(bare, "r");
  assert.equal(text.split("\n").length, 6);
  assert.ok(text.includes("Размеры: нет в наличии"));
});

test("приветствие показывает свежесть данных", () => {
  const text = greeting(5, "2026-09-20T13:33:34Z");
  assert.ok(text.includes("5 кроссовок"), text);
  assert.ok(text.includes("20.09"), text);
});

test("пустая витрина — честное сообщение", () => {
  assert.ok(greeting(0, "2026-09-20T13:33:34Z").includes("Скидок пока нет"));
});

test("битая дата не роняет приветствие", () => {
  assert.ok(greeting(3, "не дата").includes("3 кроссовок"));
});
