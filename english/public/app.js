/**
 * Фронт кабинета: кнопка → список отчётов → чат с Claude по выбранному.
 *
 * История каждого разбора хранится в localStorage под id отчёта, вместе с
 * текстом отчёта: вернулся к старому отчёту — разговор на месте, и ни Notion,
 * ни Claude повторно не дёргаются.
 */
import { renderMarkdown } from "./markdown.js";

const FIRST_QUESTION = "Разбери ошибки из этого отчёта.";
const PASSWORD_KEY = "ec:password";
const chatKey = (id) => `ec:chat:${id}`;

const $ = (id) => document.getElementById(id);
const ui = {
  heading: $("heading"), back: $("back"),
  reportsView: $("reports-view"), load: $("load"), status: $("reports-status"), reports: $("reports"),
  chatView: $("chat-view"), date: $("report-date"), restart: $("restart"),
  messages: $("messages"), composer: $("composer"), input: $("input"), send: $("send"),
};

let reports = [];   // последний загруженный список
let current = null; // { report: {id, title, date, text}, messages: [{role, content}] }
let busy = false;

// ---------- хранилище: в приватном режиме может падать, живём и без него ----------

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* без памяти */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* без памяти */ } },
};

function loadChat(id) {
  try { return JSON.parse(store.get(chatKey(id))); } catch { return null; }
}
function saveChat() {
  if (current) store.set(chatKey(current.report.id), JSON.stringify(current));
}

// ---------- сеть ----------

async function api(path, init = {}) {
  for (;;) {
    const res = await fetch(path, {
      ...init,
      headers: { ...init.headers, "X-App-Password": store.get(PASSWORD_KEY) ?? "" },
    });
    if (res.status !== 401) return res;
    const password = prompt("Пароль от кабинета:");
    if (password === null) throw new Error("Без пароля кабинет не откроется");
    store.set(PASSWORD_KEY, password);
  }
}

async function apiJson(path) {
  const res = await api(path);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Ошибка ${res.status}`);
  return data;
}

// ---------- экран отчётов ----------

ui.load.addEventListener("click", async () => {
  ui.load.disabled = true;
  setStatus("Загружаю отчёты из Notion…");
  ui.reports.replaceChildren();
  try {
    ({ reports } = await apiJson("/api/reports"));
    if (!reports.length) return setStatus("В базе пока нет ни одного отчёта.");
    setStatus(`Отчётов: ${reports.length}. Выбери, какой разобрать.`);
    ui.reports.append(...reports.map(reportItem));
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    ui.load.disabled = false;
  }
});

function reportItem(report) {
  const li = document.createElement("li");
  const button = document.createElement("button");
  const title = document.createElement("span");
  const date = document.createElement("span");
  title.className = "title";
  title.textContent = report.title;
  if (loadChat(report.id)) title.classList.add("seen");
  date.className = "date";
  date.textContent = formatDate(report.date);
  button.append(title, date);
  button.addEventListener("click", () => openReport(report, button));
  li.append(button);
  return li;
}

async function openReport(summary, button) {
  const saved = loadChat(summary.id);
  if (saved?.messages?.length) {
    showChat(saved);
    return;
  }
  button.disabled = true;
  setStatus(`Читаю «${summary.title}»…`);
  try {
    const { report } = await apiJson(`/api/reports/${summary.id}`);
    if (!report.text.trim()) throw new Error("Отчёт пустой — разбирать нечего.");
    setStatus("");
    showChat({ report, messages: [] });
    ask(FIRST_QUESTION);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    button.disabled = false;
  }
}

function setStatus(text, isError = false) {
  ui.status.textContent = text;
  ui.status.classList.toggle("error", isError);
}

// ---------- экран чата ----------

function showChat(chat) {
  current = chat;
  ui.reportsView.hidden = true;
  ui.chatView.hidden = false;
  ui.back.hidden = false;
  ui.heading.textContent = chat.report.title;
  ui.date.textContent = formatDate(chat.report.date);
  ui.messages.replaceChildren(...chat.messages.map((m) => bubble(m.role, m.content)));
  ui.input.focus();
  scrollDown();
}

ui.back.addEventListener("click", () => {
  if (busy) return;
  current = null;
  ui.chatView.hidden = true;
  ui.reportsView.hidden = false;
  ui.back.hidden = true;
  ui.heading.textContent = "Кабинет разбора ошибок";
  // Перерисовываем без похода в Notion: могли измениться пометки «есть разбор».
  ui.reports.replaceChildren(...reports.map(reportItem));
});

ui.restart.addEventListener("click", () => {
  if (busy || !confirm("Стереть этот разбор и начать заново?")) return;
  store.del(chatKey(current.report.id));
  current.messages = [];
  ui.messages.replaceChildren();
  ask(FIRST_QUESTION);
});

ui.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = ui.input.value.trim();
  if (!text || busy) return;
  ui.input.value = "";
  ask(text);
});

// Enter — отправить, Shift+Enter — новая строка.
ui.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    ui.composer.requestSubmit();
  }
});

async function ask(text) {
  const chat = current;
  chat.messages.push({ role: "user", content: text });
  ui.messages.append(bubble("user", text));
  const answer = bubble("assistant", "");
  answer.classList.add("pending");
  ui.messages.append(answer);
  scrollDown();
  setBusy(true);

  let reply = "";
  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report: chat.report, messages: chat.messages }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Ошибка ${res.status}`);
    }

    let stop = null;
    for await (const event of ndjson(res.body)) {
      if (event.type === "text") {
        reply += event.text;
        answer.innerHTML = renderMarkdown(reply);
        scrollDown(true);
      } else if (event.type === "error") {
        throw new Error(event.message);
      } else if (event.type === "done") {
        stop = event.stop_reason;
      }
    }
    if (stop === null) throw new Error("Ответ оборвался на полуслове. Попробуй ещё раз.");
    if (stop === "refusal") throw new Error("Claude отказался отвечать на этот запрос.");
    if (stop === "max_tokens") reply += "\n\n_Ответ упёрся в лимит длины. Напиши «продолжай»._";
    if (!reply.trim()) throw new Error("Claude прислал пустой ответ.");

    answer.classList.remove("pending");
    answer.innerHTML = renderMarkdown(reply);
    chat.messages.push({ role: "assistant", content: reply });
    if (chat === current) saveChat();
  } catch (err) {
    // Неудачный вопрос убираем из истории: иначе следующий запрос пойдёт
    // с двумя сообщениями пользователя подряд.
    chat.messages.pop();
    answer.remove();
    ui.messages.lastElementChild?.remove();
    showError(err.message, text);
  } finally {
    setBusy(false);
  }
}

function showError(message, text) {
  const box = bubble("assistant", "");
  box.classList.add("error");
  box.textContent = message;
  if (text === FIRST_QUESTION && current.messages.length === 0) {
    const retry = document.createElement("button");
    retry.className = "ghost retry";
    retry.textContent = "Повторить разбор";
    retry.addEventListener("click", () => { box.remove(); ask(FIRST_QUESTION); });
    box.append(document.createElement("br"), retry);
  } else {
    ui.input.value = text; // вернём текст, чтобы не набирать заново
  }
  ui.messages.append(box);
  scrollDown();
}

function bubble(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (role === "user") div.textContent = content;
  else div.innerHTML = renderMarkdown(content);
  return div;
}

function setBusy(value) {
  busy = value;
  ui.send.disabled = value;
  ui.restart.disabled = value;
  ui.back.disabled = value;
}

/** Автопрокрутка вниз, но не мешаем, если человек сам ушёл читать выше. */
function scrollDown(onlyIfNearBottom = false) {
  const gap = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
  if (!onlyIfNearBottom || gap < 160) window.scrollTo({ top: document.documentElement.scrollHeight });
}

async function* ndjson(body) {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let nl;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer);
}

function formatDate(value) {
  if (!value) return "";
  // «2026-10-10» без времени — это день, а не полночь по UTC.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const date = day ? new Date(+day[1], day[2] - 1, +day[3]) : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}
