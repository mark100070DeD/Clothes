import assert from "node:assert/strict";
import { test } from "node:test";
import { renderMarkdown } from "../public/markdown.js";

test("HTML из ответа не оживает", () => {
  const html = renderMarkdown('<img src=x onerror="alert(1)">');
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});

test("заголовки, списки, жирный и код", () => {
  assert.equal(renderMarkdown("## Ошибка 1"), "<h3>Ошибка 1</h3>");
  assert.equal(renderMarkdown("- a\n- **b**"), "<ul><li>a</li><li><strong>b</strong></li></ul>");
  assert.equal(renderMarkdown("1. one\n2. two"), "<ol><li>one</li><li>two</li></ol>");
  assert.equal(renderMarkdown("`a*b*c`"), "<p><code>a*b*c</code></p>");
  assert.equal(renderMarkdown("I *went* home"), "<p>I <em>went</em> home</p>");
  assert.equal(renderMarkdown("fill_in_the_gap"), "<p>fill_in_the_gap</p>");
  assert.equal(renderMarkdown("Yesterday I ___ (go) home, _really_."), "<p>Yesterday I ___ (go) home, <em>really</em>.</p>");
  assert.equal(renderMarkdown("I ***** it"), "<p>I ***** it</p>");
});

test("таблица и цитата", () => {
  const table = renderMarkdown("| было | стало |\n|---|---|\n| goed | went |");
  assert.ok(table.includes("<th>было</th>") && table.includes("<td>went</td>"));
  assert.equal(renderMarkdown("> I goed"), "<blockquote>I goed</blockquote>");
});
