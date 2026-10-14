/**
 * Notion: список отчётов из базы и текст одного отчёта.
 *
 * Версию API держим 2022-06-28: в ней ещё живёт POST /databases/{id}/query.
 * В 2025-09-03 Notion переехал на data sources, и тот же запрос пришлось бы
 * делать в два шага. Для базы с одним источником старая версия работает так же.
 */
const API = "https://api.notion.com/v1";
const VERSION = "2022-06-28";

// Больше 300 отчётов в списке листать всё равно никто не будет.
const MAX_REPORT_PAGES = 3;
// Вложенные блоки (тогглы, колонки) читаем, но не бесконечно.
const MAX_DEPTH = 3;

async function notion(env, path, init = {}) {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.NOTION_TOKEN}`,
      "Notion-Version": VERSION,
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.text();
    // 404 от Notion почти всегда значит «интеграцию не пригласили в базу».
    const hint = res.status === 404 ? " (интеграция подключена к базе? Connections → Add connection)" : "";
    throw new Error(`Notion ${res.status}${hint}: ${body.slice(0, 300)}`);
  }
  return res.json();
}

/** Все отчёты базы: id, заголовок, дата. Свежие сверху. */
export async function listReports(env) {
  const reports = [];
  let cursor;
  for (let i = 0; i < MAX_REPORT_PAGES; i++) {
    const page = await notion(env, `/databases/${env.NOTION_DATABASE_ID}/query`, {
      method: "POST",
      body: JSON.stringify({
        page_size: 100,
        start_cursor: cursor,
        sorts: [{ timestamp: "created_time", direction: "descending" }],
      }),
    });
    for (const p of page.results) reports.push(summary(p, env.NOTION_DATE_PROPERTY));
    if (!page.has_more) break;
    cursor = page.next_cursor;
  }
  return reports.sort((a, b) => b.date.localeCompare(a.date));
}

/** Один отчёт целиком: свойства страницы плюс её содержимое обычным текстом. */
export async function getReport(env, id) {
  const page = await notion(env, `/pages/${id}`);
  const head = summary(page, env.NOTION_DATE_PROPERTY);
  const props = propertiesText(page.properties);
  const body = await blocksText(env, id, 0);
  return { ...head, text: [props, body].filter(Boolean).join("\n\n") };
}

/**
 * Заголовок и дата страницы. Дата: свойство из NOTION_DATE_PROPERTY, иначе
 * первое свойство типа date, иначе время создания страницы.
 */
export function summary(page, dateProperty) {
  const props = Object.entries(page.properties ?? {});
  const titleProp = props.find(([, v]) => v.type === "title")?.[1];
  const named = dateProperty && page.properties?.[dateProperty];
  const dateProp = named?.type === "date" ? named : props.find(([, v]) => v.type === "date")?.[1];
  return {
    id: page.id,
    title: plain(titleProp?.title) || "Без названия",
    date: dateProp?.date?.start ?? page.created_time,
  };
}

/** Свойства, кроме заголовка, строками «Имя: значение». Пустые пропускаем. */
export function propertiesText(properties = {}) {
  return Object.entries(properties)
    .filter(([, v]) => v.type !== "title")
    .map(([name, v]) => [name, propertyValue(v)])
    .filter(([, value]) => value)
    .map(([name, value]) => `${name}: ${value}`)
    .join("\n");
}

function propertyValue(p) {
  switch (p.type) {
    case "rich_text": return plain(p.rich_text);
    case "number": return p.number == null ? "" : String(p.number);
    case "select": return p.select?.name ?? "";
    case "status": return p.status?.name ?? "";
    case "multi_select": return p.multi_select.map((o) => o.name).join(", ");
    case "date": return p.date ? [p.date.start, p.date.end].filter(Boolean).join(" — ") : "";
    case "checkbox": return p.checkbox ? "да" : "";
    case "url": return p.url ?? "";
    case "email": return p.email ?? "";
    case "phone_number": return p.phone_number ?? "";
    case "formula": return String(p.formula?.[p.formula.type] ?? "");
    default: return "";
  }
}

async function blocksText(env, id, depth) {
  const lines = [];
  let cursor;
  do {
    const qs = cursor ? `&start_cursor=${cursor}` : "";
    const page = await notion(env, `/blocks/${id}/children?page_size=100${qs}`);
    for (const block of page.results) {
      const line = blockLine(block);
      if (line !== null) lines.push("  ".repeat(depth) + line);
      if (block.has_children && depth < MAX_DEPTH && block.type !== "child_page") {
        const inner = await blocksText(env, block.id, depth + 1);
        if (inner) lines.push(inner);
      }
    }
    cursor = page.has_more ? page.next_cursor : null;
  } while (cursor);
  return lines.join("\n");
}

/** Один блок Notion строкой текста. null — блок без текста (картинка, разделитель). */
export function blockLine(block) {
  const data = block[block.type] ?? {};
  const text = plain(data.rich_text);
  switch (block.type) {
    case "heading_1": return `# ${text}`;
    case "heading_2": return `## ${text}`;
    case "heading_3": return `### ${text}`;
    case "bulleted_list_item": return `- ${text}`;
    case "numbered_list_item": return `1. ${text}`;
    case "to_do": return `[${data.checked ? "x" : " "}] ${text}`;
    case "quote": return `> ${text}`;
    case "code": return "```\n" + text + "\n```";
    case "table_row": return "| " + data.cells.map(plain).join(" | ") + " |";
    case "child_page": return `[страница: ${data.title}]`;
    case "divider": return "---";
    default: return data.rich_text ? text : null;
  }
}

export function plain(richText) {
  return (richText ?? []).map((t) => t.plain_text).join("");
}
