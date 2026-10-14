import assert from "node:assert/strict";
import { test } from "node:test";
import { blockLine, propertiesText, summary } from "../src/notion.js";

const rt = (text) => [{ plain_text: text }];

test("заголовок и дата: берём свойство типа date", () => {
  const page = {
    id: "p1",
    created_time: "2026-10-01T10:00:00.000Z",
    properties: {
      Name: { type: "title", title: rt("Отчёт за неделю") },
      Когда: { type: "date", date: { start: "2026-10-10" } },
    },
  };
  assert.deepEqual(summary(page), { id: "p1", title: "Отчёт за неделю", date: "2026-10-10" });
});

test("дата: явное свойство важнее первого попавшегося, без дат — время создания", () => {
  const page = {
    id: "p2",
    created_time: "2026-10-01T10:00:00.000Z",
    properties: {
      Name: { type: "title", title: [] },
      Создано: { type: "date", date: { start: "2026-01-01" } },
      Урок: { type: "date", date: { start: "2026-10-12" } },
    },
  };
  assert.equal(summary(page, "Урок").date, "2026-10-12");
  assert.equal(summary(page).title, "Без названия");
  assert.equal(summary({ id: "x", created_time: "T", properties: {} }).date, "T");
});

test("свойства превращаются в строки, пустые и заголовок пропускаются", () => {
  const text = propertiesText({
    Name: { type: "title", title: rt("X") },
    Ошибки: { type: "rich_text", rich_text: rt("I goed home") },
    Теги: { type: "multi_select", multi_select: [{ name: "past simple" }, { name: "articles" }] },
    Пусто: { type: "rich_text", rich_text: [] },
    Оценка: { type: "number", number: 0 },
  });
  assert.equal(text, "Ошибки: I goed home\nТеги: past simple, articles\nОценка: 0");
});

test("блоки Notion в текст", () => {
  assert.equal(blockLine({ type: "heading_2", heading_2: { rich_text: rt("Errors") } }), "## Errors");
  assert.equal(blockLine({ type: "bulleted_list_item", bulleted_list_item: { rich_text: rt("a") } }), "- a");
  assert.equal(blockLine({ type: "to_do", to_do: { rich_text: rt("b"), checked: true } }), "[x] b");
  assert.equal(
    blockLine({ type: "table_row", table_row: { cells: [rt("was"), rt("should be")] } }),
    "| was | should be |",
  );
  assert.equal(blockLine({ type: "image", image: {} }), null);
});
