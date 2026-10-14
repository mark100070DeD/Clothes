/**
 * Кабинет разбора английских ошибок.
 *
 * Статика (public/) отдаётся Cloudflare сама, сюда приходят только /api/*:
 *   GET  /api/reports      список отчётов из базы Notion
 *   GET  /api/reports/:id  один отчёт текстом
 *   POST /api/chat         разбор отчёта и чат с Claude, ответ потоком
 *
 * Переменные окружения (задаются в Cloudflare или `wrangler secret put`, НЕ в коде):
 *   NOTION_TOKEN          секрет внутренней интеграции Notion (ntn_… / secret_…)
 *   NOTION_DATABASE_ID    id базы с отчётами: 32 символа из её ссылки
 *   ANTHROPIC_API_KEY     ключ Claude API
 *   APP_PASSWORD          пароль на вход. Без него кабинет открыт всем, кто
 *                         знает адрес, и любой сможет тратить твой ключ Claude
 *   NOTION_DATE_PROPERTY  необязательно: имя свойства с датой отчёта
 *   CLAUDE_MODEL          необязательно, по умолчанию claude-opus-5-5
 *   CLAUDE_EFFORT         необязательно: low | medium | high, по умолчанию medium
 */
import { chatStream, validate } from "./chat.js";
import { getReport, listReports } from "./notion.js";

const REQUIRED = ["NOTION_TOKEN", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);

    const missing = REQUIRED.filter((name) => !env[name]);
    if (missing.length) return json({ error: `Не заданы переменные: ${missing.join(", ")}` }, 500);
    if (!authorized(request, env)) return json({ error: "Неверный пароль", auth: true }, 401);

    try {
      if (url.pathname === "/api/reports" && request.method === "GET") {
        return json({ reports: await listReports(env) });
      }
      const one = url.pathname.match(/^\/api\/reports\/([0-9a-f-]{32,36})$/i);
      if (one && request.method === "GET") {
        return json({ report: await getReport(env, one[1]) });
      }
      if (url.pathname === "/api/chat" && request.method === "POST") {
        const body = await request.json().catch(() => null);
        const problem = validate(body);
        if (problem) return json({ error: problem }, 400);
        return chatStream(env, body);
      }
      return json({ error: "Нет такого адреса" }, 404);
    } catch (err) {
      console.error(url.pathname, err);
      return json({ error: err.message }, 502);
    }
  },
};

export function authorized(request, env) {
  if (!env.APP_PASSWORD) return true;
  return request.headers.get("X-App-Password") === env.APP_PASSWORD;
}

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}
