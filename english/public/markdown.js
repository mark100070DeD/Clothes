/**
 * Маленький Markdown → HTML для ответов Claude. Сначала экранируем весь текст,
 * потом расставляем свои теги — так ничего из ответа не станет живым HTML.
 * Поддержано то, что Claude реально пишет в разборе: заголовки, списки,
 * цитаты, код, таблицы, жирный, курсив.
 */
export function renderMarkdown(src) {
  const lines = escapeHtml(src).split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      const code = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) code.push(lines[i]);
      i++;
      out.push(`<pre><code>${code.join("\n")}</code></pre>`);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 4);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }

    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      out.push("<hr>");
      i++;
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const marker = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
      const items = [];
      while (i < lines.length && marker.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(marker, ""))}</li>`);
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.join("")}</${tag}>`);
      continue;
    }

    if (line.startsWith("&gt;")) {
      const quote = [];
      for (; i < lines.length && lines[i].startsWith("&gt;"); i++) quote.push(lines[i].replace(/^&gt;\s?/, ""));
      out.push(`<blockquote>${inline(quote.join("<br>"))}</blockquote>`);
      continue;
    }

    if (line.trim().startsWith("|") && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(cells(lines[i]));
      out.push(
        "<table><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>",
      );
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const para = [];
    for (; i < lines.length && lines[i].trim() && !startsBlock(lines[i]); i++) para.push(lines[i]);
    out.push(`<p>${inline(para.join("<br>"))}</p>`);
  }

  return out.join("\n");
}

function startsBlock(line) {
  return /^(```|#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|&gt;|\s*\|)/.test(line);
}

function cells(row) {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function inline(text) {
  // Код прячем, чтобы звёздочки внутри него не стали курсивом.
  const codes = [];
  text = text.replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  text = text
    .replace(/\*\*([^*\s](?:.*?[^*\s])?)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\s](?:.*?[^_\s])?)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?![*\w])/g, "$1<em>$2</em>")
    // Пропуски в упражнениях «I ___ home» курсивом стать не должны.
    .replace(/(^|[^_\w])_([^_\s][^_]*?)_(?![_\w])/g, "$1<em>$2</em>")
    .replace(/~~(.+?)~~/g, "<del>$1</del>");
  return text.replace(/\u0000(\d+)\u0000/g, (_, n) => `<code>${codes[n]}</code>`);
}

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
