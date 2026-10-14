import assert from "node:assert/strict";
import { test } from "node:test";
import { systemPrompt, validate } from "../src/chat.js";

const report = { title: "Неделя", date: "2026-10-10", text: "I goed home" };
const u = (content) => ({ role: "user", content });
const a = (content) => ({ role: "assistant", content });

test("нормальная история проходит", () => {
  assert.equal(validate({ report, messages: [u("Разбери")] }), null);
  assert.equal(validate({ report, messages: [u("1"), a("2"), u("3")] }), null);
});

test("плохая история отклоняется", () => {
  assert.match(validate({ messages: [u("x")] }), /отчёта/);
  assert.match(validate({ report, messages: [] }), /нет сообщений/);
  assert.match(validate({ report, messages: [a("x")] }), /чередоваться/);
  assert.match(validate({ report, messages: [u("1"), u("2")] }), /чередоваться/);
  assert.match(validate({ report, messages: [u("1"), a("2")] }), /последнее/);
  assert.match(validate({ report, messages: [u("  ")] }), /пустое/);
  assert.match(validate(null), /отчёта/);
});

test("отчёт попадает в системный промпт, кавычки в заголовке экранированы", () => {
  const prompt = systemPrompt({ ...report, title: 'Урок "5"' });
  assert.ok(prompt.includes("I goed home"));
  assert.ok(prompt.includes('title="Урок &quot;5&quot;"'));
});
