/* postloom frontend: plain JavaScript, no build step, nothing loaded from the internet. */
"use strict";

const DYES = 8;
const state = {
  status: null,
  articles: [],
  topicFilter: null,
  chats: new Map(), // article id (or "library") -> [{role, text, sources}]
};

// ---------------------------------------------------------------------------- api
async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { "X-Postloom": "1" } };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("postloom isn't running. Start it again with `postloom start`.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

async function refresh() {
  [state.status, { articles: state.articles }] = await Promise.all([
    api("/api/status"),
    api("/api/articles"),
  ]);
  renderSidebar();
}

// ---------------------------------------------------------------------------- dom helpers
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "vars") for (const [k, v] of Object.entries(value)) node.style.setProperty(k, v);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function setMain(...children) {
  const main = document.getElementById("main");
  main.replaceChildren(...children);
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("visible"), 3500);
}

function notice(kind, ...lines) {
  return h("div", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status" },
    lines.map((line) => h("p", {}, line)));
}

function formatDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------- threads (topic colors)
function topicColor(name) {
  const topics = state.status ? state.status.topics : [];
  const index = Math.max(0, topics.indexOf(name));
  return `var(--dye-${(index % DYES) + 1})`;
}

function warp(topics) {
  return h("span", { class: "warp", "aria-hidden": "true" },
    topics.map((t) => h("span", { vars: { "--thread": topicColor(t.name) } })));
}

function weave(topics) {
  // Vertical warp threads in the topic colors, crossed by a faint weft.
  const colors = topics.length ? topics.map((t) => topicColor(t.name)) : ["var(--rule)"];
  // Each topic gets a band of thin threads (3px thread, 1px gap) so it reads as yarn.
  const width = 28;
  const stops = colors.map((c, i) => `${c} ${i * width}px ${(i + 1) * width}px`).join(", ");
  const warpLayer = `repeating-linear-gradient(90deg, ${stops})`;
  const strands = "repeating-linear-gradient(90deg, transparent 0 3px, rgba(247,248,246,.35) 3px 4px)";
  const weftLayer = "repeating-linear-gradient(0deg, rgba(247,248,246,.5) 0 2px, transparent 2px 6px)";
  return h("div", { class: "weave", "aria-hidden": "true", vars: { "--weave": `${weftLayer}, ${strands}, ${warpLayer}` } });
}

function tagList(topics) {
  if (!topics.length) return null;
  return h("ul", { class: "tags", "aria-label": "Topics" },
    topics.map((t) => h("li", { class: "tag", "data-grade": t.grade,
      title: t.grade === "asserted" ? "Suggested by the model" : "Confirmed" },
      h("span", { class: "swatch", vars: { "--thread": topicColor(t.name) } }), t.name)));
}

// ---------------------------------------------------------------------------- markdown
function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function slug(text) {
  return "s-" + text.toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-");
}

function inline(text) {
  // Escape first, then add only the tags we generate ourselves.
  let html = escapeHtml(text);
  const codes = [];
  html = html.replace(/`([^`]+)`/g, (_, code) => `\u0000${codes.push(code) - 1}\u0000`);
  html = html
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`);
}

function markdown(source) {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const isBullet = (l) => /^\s*[-*+]\s+/.test(l);
  const isNumbered = (l) => /^\s*\d+[.)]\s+/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*(```|~~~)\s*([\w+-]*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i += 1;
      out.push(`<pre><code>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(Math.max(heading[1].length, 2), 4);
      const text = heading[2].trim();
      out.push(`<h${level} id="${slug(text)}">${inline(text)}</h${level}>`);
      i += 1;
      continue;
    }
    if (isBullet(line) || isNumbered(line)) {
      const numbered = isNumbered(line);
      const items = [];
      while (i < lines.length && (numbered ? isNumbered(lines[i]) : isBullet(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*+]|\d+[.)])\s+/, ""));
        i += 1;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !isBullet(lines[i]) && !isNumbered(lines[i])) {
          items[items.length - 1] += " " + lines[i].trim();
          i += 1;
        }
      }
      const tag = numbered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`);
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${inline(quote.join(" "))}</blockquote>`);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|~~~|>)/.test(lines[i])
      && !isBullet(lines[i]) && !isNumbered(lines[i])) {
      para.push(lines[i++].trim());
    }
    out.push(`<p>${inline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}

function htmlBlock(className, html) {
  const node = h("div", { class: className });
  node.innerHTML = html; // safe: produced by markdown(), which escapes all input
  return node;
}

// ---------------------------------------------------------------------------- sidebar
function renderSidebar() {
  const counts = new Map();
  for (const article of state.articles) {
    for (const t of article.topics) counts.set(t.name, (counts.get(t.name) || 0) + 1);
  }
  const threadList = document.getElementById("thread-list");
  threadList.replaceChildren(...state.status.topics.map((name) =>
    h("li", {}, h("button", {
      type: "button",
      "aria-pressed": String(state.topicFilter === name),
      onclick: () => { state.topicFilter = state.topicFilter === name ? null : name; renderSidebar(); },
    }, h("span", { class: "swatch", vars: { "--thread": topicColor(name) } }), name,
    h("span", { class: "count" }, counts.get(name) || 0)))));

  const visible = state.articles.filter((a) =>
    !state.topicFilter || a.topics.some((t) => t.name === state.topicFilter));
  const list = document.getElementById("article-list");
  const current = currentArticleId();
  list.replaceChildren(...(visible.length ? visible.map((a) => h("li", {},
    h("a", { href: `#/article/${encodeURIComponent(a.id)}`, "aria-current": a.id === current ? "page" : null },
      warp(a.topics),
      h("span", {}, a.title, h("span", { class: "meta" },
        [formatDate(a.published_on), a.series && `${a.series}${a.series_part ? `, part ${a.series_part}` : ""}`]
          .filter(Boolean).join(", ") || "Undated")))))
    : [h("li", { class: "empty" }, state.topicFilter ? "No articles in this thread yet." : "No articles yet.")]));
}

function currentArticleId() {
  const match = location.hash.match(/^#\/article\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

// ---------------------------------------------------------------------------- views
function homeView() {
  if (!state.articles.length) {
    return setMain(h("section", { class: "page" },
      h("h1", {}, "Your articles, woven together"),
      h("p", { class: "lede" }, "Paste a LinkedIn article and its announcement post. postloom restores the formatting, files it under your topics and makes it searchable, so you can ask questions about everything you've written."),
      keyNotice(),
      h("a", { class: "button button-primary", href: "#/add" }, "Add your first article")));
  }
  setMain(h("section", { class: "page" },
    h("h1", {}, "Your articles"),
    h("p", { class: "lede" }, `${state.articles.length} ${state.articles.length === 1 ? "article" : "articles"} in your vault. Open one to read it and ask about it, or search across all of them.`),
    keyNotice(),
    h("div", { class: "home-grid" }, state.articles.map((a) =>
      h("a", { class: "home-row", href: `#/article/${encodeURIComponent(a.id)}` }, warp(a.topics),
        h("div", {}, h("h2", {}, a.title), h("p", {}, a.summary || formatDate(a.published_on) || "")))))));
}

function keyNotice() {
  if (!state.status || state.status.api_key !== "missing") return null;
  return notice("", "Add your Gemini API key in settings to add articles, search by meaning and chat.",
    h("a", { href: "#/settings" }, "Open settings"));
}

function addView() {
  const form = h("form", { class: "page", onsubmit: submitArticle },
    h("h1", {}, "Add an article"),
    h("p", { class: "lede" }, "Copy the article from LinkedIn and paste it below, then do the same with the post you announced it in. The text can look messy; postloom restores the headings, lists and code."),
    keyNotice(),
    h("div", { id: "add-result" }),
    field("article_text", "Article", h("textarea", { id: "article_text", name: "article_text", required: true, rows: 12 })),
    field("post_text", "Announcement post", h("textarea", { id: "post_text", name: "post_text", required: true, rows: 6 })),
    h("div", { class: "field-row" },
      field("article_url", "Article link (optional)", h("input", { id: "article_url", name: "article_url", type: "url", placeholder: "https://www.linkedin.com/pulse/..." })),
      field("published_on", "Published on (optional)", h("input", { id: "published_on", name: "published_on", type: "date" }))),
    field("post_url", "Post link (optional)", h("input", { id: "post_url", name: "post_url", type: "url", placeholder: "https://www.linkedin.com/posts/..." })),
    h("button", { class: "button button-primary", type: "submit", id: "add-submit" }, "Add article"));
  setMain(form);
}

function field(id, label, control, hint) {
  return h("div", { class: "field" }, h("label", { for: id }, label), control,
    hint ? h("p", { class: "hint" }, hint) : null);
}

async function submitArticle(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const body = {
    article_text: data.article_text,
    post_text: data.post_text,
    article_url: data.article_url || null,
    post_url: data.post_url || null,
    published_on: data.published_on || null,
  };
  const button = document.getElementById("add-submit");
  const result = document.getElementById("add-result");
  button.disabled = true;
  button.textContent = "Restoring the article, this can take a minute...";
  result.replaceChildren();
  try {
    const added = await api("/api/articles", { method: "POST", body });
    await refresh();
    const lines = [`${added.is_update ? "Updated" : "Added"} "${added.title}".`];
    if (added.topics.length) lines.push(`Topics: ${added.topics.join(", ")}.`);
    for (const warning of added.warnings) lines.push(warning);
    if (added.index_error) lines.push(`Saved, but not indexed for search: ${added.index_error}`);
    result.replaceChildren(notice(added.warnings.length || added.index_error ? "" : "", ...lines,
      h("a", { href: `#/article/${encodeURIComponent(added.id)}` }, "Open the article")));
    form.reset();
    toast(added.is_update ? "Article updated" : "Article added");
  } catch (error) {
    result.replaceChildren(notice("error", error.message));
  } finally {
    button.disabled = false;
    button.textContent = "Add article";
    result.scrollIntoView({ block: "nearest" });
  }
}

async function articleView(id) {
  let article;
  try {
    article = await api(`/api/article?id=${encodeURIComponent(id)}`);
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Article not found"),
      notice("error", error.message), h("a", { href: "#/" }, "Back to your articles")));
  }
  const series = article.series ? `${article.series}${article.series_part ? `, part ${article.series_part}` : ""}` : null;
  const byline = [formatDate(article.published_on), series].filter(Boolean).join(". ");
  const reader = h("article", { class: "reader" },
    weave(article.topics),
    h("h1", {}, article.title),
    h("p", { class: "byline" }, byline || "Undated",
      article.url ? [" ", h("a", { href: article.url, target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn")] : null),
    tagList(article.topics),
    article.summary ? h("p", { class: "summary" }, article.summary) : null,
    htmlBlock("prose", markdown(article.body_markdown)),
    article.posts.map((post) => h("section", { class: "post", "aria-label": "Announcement post" },
      h("h2", {}, "Announcement post"), h("p", {}, post.text))));
  setMain(h("div", { class: "article-layout" }, reader,
    chatPanel(article.id, "Ask about this article", "Answers come only from this article and its post.", [
      "Summarize the key takeaways",
      "What are the main trade-offs?",
      "Explain the code step by step",
    ])));
  renderSidebar();
}

async function searchView(query) {
  document.getElementById("search-input").value = query;
  const page = h("section", { class: "page library-ask" },
    h("h1", {}, `Results for "${query}"`), h("div", { id: "search-results" }, h("p", { class: "lede" }, "Searching...")));
  setMain(page);
  try {
    const found = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const list = found.results.length
      ? h("ul", { class: "results" }, found.results.map((r) => h("li", { class: "result" },
          h("h2", {}, h("a", { href: `#/article/${encodeURIComponent(r.id)}` }, r.title)),
          r.passages.map((p) => h("p", { class: "passage" }, h("span", { class: "where" }, p.heading || "Introduction"), p.excerpt)))))
      : h("p", { class: "lede" }, "No articles match. Try other words, or ask below.");
    document.getElementById("search-results").replaceChildren(
      ...found.warnings.map((w) => notice("", w)), list,
      chatPanel("library", "Ask across all your articles", "Answers use only passages that clearly match your question.", [], query));
  } catch (error) {
    document.getElementById("search-results").replaceChildren(notice("error", error.message));
  }
}

async function settingsView() {
  await refresh();
  const s = state.status;
  const fromEnv = s.api_key === "environment";
  const form = h("form", { class: "page", onsubmit: saveKey },
    h("h1", {}, "Settings"),
    h("p", { class: "lede" }, "postloom runs on your computer. Your articles, the people you talk to and your API key never leave it, except for the text sent to Gemini when you add, search or ask."),
    h("ul", { class: "status-list" },
      h("li", { "data-on": String(s.features.ingest) }, "Adding articles"),
      h("li", { "data-on": String(s.features.semantic_search) }, "Search by meaning"),
      h("li", { "data-on": String(s.features.chat) }, "Chat")),
    fromEnv
      ? notice("", "Your Gemini API key comes from the GEMINI_API_KEY environment variable. Change it there.")
      : field("gemini_api_key", "Gemini API key",
          h("input", { id: "gemini_api_key", name: "gemini_api_key", type: "password", autocomplete: "off",
            placeholder: s.api_key === "config" ? "A key is saved. Paste a new one to replace it." : "Paste your key" }),
          h("span", {}, "Create a free key at ",
            h("a", { href: "https://aistudio.google.com/apikey", target: "_blank", rel: "noopener noreferrer" }, "aistudio.google.com"),
            ". It's stored only in your Postloom folder.")),
    fromEnv ? null : h("div", {}, h("button", { class: "button button-primary", type: "submit" }, "Save key"), " ",
      s.api_key === "config" ? h("button", { class: "button", type: "button", onclick: removeKey }, "Remove saved key") : null),
    h("h2", { class: "settings-heading" }, "Where your data lives"),
    h("p", { class: "path" }, s.vault),
    h("p", { class: "hint" }, "Open this folder in Obsidian to browse your articles as a graph."),
    h("h2", { class: "settings-heading" }, "Models"),
    h("p", {}, `Restoring articles: ${s.models.extraction}. Search: ${s.models.embedding}. Chat: ${s.models.chat}.`),
    h("p", { class: "hint" }, `postloom ${s.version}`));
  setMain(form);
}

async function saveKey(event) {
  event.preventDefault();
  const key = new FormData(event.currentTarget).get("gemini_api_key");
  if (!key) return toast("Paste a key first");
  try {
    await api("/api/settings", { method: "PUT", body: { gemini_api_key: key } });
    toast("Key saved");
    settingsView();
  } catch (error) {
    toast(error.message);
  }
}

async function removeKey() {
  await api("/api/settings", { method: "PUT", body: { gemini_api_key: null } });
  toast("Saved key removed");
  settingsView();
}

// ---------------------------------------------------------------------------- chat
function chatPanel(scope, title, subtitle, suggestions, initialQuestion) {
  const messages = h("div", { class: "messages", "aria-live": "polite" });
  const input = h("textarea", { "aria-label": "Your question", placeholder: "Ask a question", rows: 1 });
  const submit = h("button", { class: "button button-primary", type: "submit" }, "Ask");
  const panel = h("section", { class: "chat", "aria-label": title },
    h("div", { class: "chat-head" }, h("h2", {}, title), h("p", {}, subtitle)),
    messages,
    h("form", { class: "ask-form", onsubmit: (e) => { e.preventDefault(); send(); } }, input, submit));

  const history = state.chats.get(scope) || [];
  state.chats.set(scope, history);

  function render() {
    if (!history.length) {
      const empty = [h("p", { class: "empty" }, "No questions yet.")];
      if (suggestions.length) {
        empty.push(h("div", { class: "suggestions" }, suggestions.map((s) =>
          h("button", { type: "button", onclick: () => { input.value = s; send(); } }, s))));
      }
      messages.replaceChildren(...empty);
      return;
    }
    messages.replaceChildren(...history.map(renderMessage));
    messages.scrollTop = messages.scrollHeight;
  }

  async function send() {
    const question = input.value.trim();
    if (!question || submit.disabled) return;
    const previous = history.filter((m) => m.role !== "error" && !m.pending)
      .map((m) => ({ role: m.role, text: m.text }));
    history.push({ role: "user", text: question });
    const pending = { role: "assistant", text: "Reading your articles...", pending: true };
    history.push(pending);
    input.value = "";
    submit.disabled = true;
    render();
    try {
      const answer = await api("/api/ask", { method: "POST", body: {
        question, article_id: scope === "library" ? null : scope, history: previous } });
      Object.assign(pending, { text: answer.text, sources: answer.sources, pending: false });
    } catch (error) {
      Object.assign(pending, { role: "error", text: error.message, pending: false });
    } finally {
      submit.disabled = false;
      render();
      input.focus();
    }
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  render();
  if (initialQuestion && !history.length) input.value = initialQuestion;
  return panel;
}

function renderMessage(message) {
  if (message.role === "user") return h("div", { class: "message user" }, message.text);
  if (message.role === "error") return h("div", { class: "message error", role: "alert" }, message.text);
  if (message.pending) return h("div", { class: "message assistant pending" }, message.text);
  const body = htmlBlock("message assistant", markdown(message.text)
    .replace(/\[(\d{1,2})\]/g, '<button type="button" class="cite" data-n="$1" aria-label="Source $1">$1</button>'));
  const sources = message.sources || [];
  const here = currentArticleId();
  if (sources.length) {
    body.append(h("div", { class: "sources" }, sources.map((s) =>
      h("details", { "data-n": s.number },
        h("summary", {}, h("strong", {}, `[${s.number}] `),
          s.article_id === here ? s.section : `${s.title}: ${s.section}`),
        h("p", { class: "source-text" }, s.text)))));
  }
  body.addEventListener("click", (event) => {
    const cite = event.target.closest(".cite");
    if (!cite) return;
    const source = sources.find((s) => String(s.number) === cite.dataset.n);
    const details = body.querySelector(`details[data-n="${cite.dataset.n}"]`);
    if (details) details.open = true;
    if (source) revealSection(source);
  });
  return body;
}

function revealSection(source) {
  if (currentArticleId() !== source.article_id) {
    location.hash = `#/article/${encodeURIComponent(source.article_id)}`;
    return;
  }
  const target = document.getElementById(slug(source.section));
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  target.classList.remove("flash");
  void target.offsetWidth; // restart the highlight animation
  target.classList.add("flash");
}

// ---------------------------------------------------------------------------- routing
async function route() {
  const hash = location.hash || "#/";
  try {
    if (!state.status) await refresh();
    if (hash.startsWith("#/article/")) return await articleView(decodeURIComponent(hash.slice(10)));
    if (hash.startsWith("#/search")) {
      const query = new URLSearchParams(hash.split("?")[1] || "").get("q") || "";
      return await searchView(query);
    }
    if (hash === "#/add") return addView();
    if (hash === "#/settings") return await settingsView();
    renderSidebar();
    return homeView();
  } catch (error) {
    setMain(h("section", { class: "page" }, h("h1", {}, "Something went wrong"), notice("error", error.message)));
  }
}

document.getElementById("browse-toggle").addEventListener("click", (event) => {
  const sidebar = document.querySelector(".sidebar");
  const open = sidebar.classList.toggle("browsing");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});
window.addEventListener("hashchange", () => {
  document.querySelector(".sidebar").classList.remove("browsing");
  document.getElementById("browse-toggle").setAttribute("aria-expanded", "false");
});

document.getElementById("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = document.getElementById("search-input").value.trim();
  if (query) location.hash = `#/search?q=${encodeURIComponent(query)}`;
});
window.addEventListener("hashchange", route);
route();
