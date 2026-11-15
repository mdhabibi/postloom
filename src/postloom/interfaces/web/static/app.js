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
    throw new Error("postloom isn't running. In your terminal, go to the postloom folder and run `uv run postloom start`, then reload this page.");
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

// ---------------------------------------------------------------------------- icons
// Line icons drawn on a 24px grid; constant markup, never user input.
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  graph: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.5 6.2l7 .5M7.1 8.3l3.8 7.4M16.8 9.3l-3.6 6.5"/>',
  people: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.4 3-5.3 6-5.3s5.4 1.9 6 5.3"/><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.9c1.6.7 2.7 2.4 3 5.1"/>',
  settings: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  ask: '<path d="M4 5h16v11H9l-5 4z"/><path d="M9 10.5h6"/>',
  article: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 10h6M9 14h6M9 18h4"/>',
  person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  reply: '<path d="M9 7 4 12l5 5"/><path d="M4 12h10a6 6 0 0 1 6 6v1"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name];
  return svg;
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

function fill(node, ...children) {
  // replaceChildren() would print "null"; skip empty slots the way h() does.
  node.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function setMain(...children) {
  const main = document.getElementById("main");
  fill(main, vaultBanner(), ...children);
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

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many || `${one}s`}`;
}

// A destructive action asks once more, in place: no browser dialogs.
function confirmBox(label, question, confirmLabel, action) {
  const box = h("div", { class: "confirm" });
  const reset = () => fill(box, h("button", { class: "button button-danger-quiet", type: "button", onclick: ask }, icon("trash"), label));
  function ask() {
    const yes = h("button", { class: "button button-danger", type: "button", onclick: run }, confirmLabel);
    fill(box, h("p", { class: "confirm-text", role: "alert" }, question),
      h("div", { class: "confirm-actions" }, yes, h("button", { class: "button", type: "button", onclick: reset }, "Cancel")));
    box.querySelector(".confirm-actions .button:last-child").focus();
  }
  async function run(event) {
    event.currentTarget.disabled = true;
    try {
      await action();
    } catch (error) {
      toast(error.message);
      reset();
    }
  }
  reset();
  return box;
}

// ---------------------------------------------------------------------------- vault banner
function vaultBanner() {
  const s = state.status;
  if (!s) return null;
  const sync = s.vault_sync;
  const read = async (event) => {
    event.currentTarget.disabled = true;
    try {
      await api("/api/vault/sync", { method: "POST" });
    } catch (error) {
      toast(error.message);
    }
    await refresh();
    route();
  };
  if (sync && !sync.applied && sync.problems.length) {
    return h("div", { class: "notice error banner", role: "alert" },
      h("p", {}, h("strong", {}, `postloom can't read ${plural(sync.problems.length, "note")} in your vault, `),
        "so your recent edits there are not applied yet. Fix the note (or undo the edit), then try again."),
      h("ul", { class: "problem-list" }, sync.problems.map((x) => h("li", {}, h("code", {}, x.path), `: ${x.reason}`))),
      h("button", { class: "button", type: "button", onclick: read }, "Try again"));
  }
  if (s.vault_changes > 0) {
    return h("div", { class: "notice banner" },
      h("p", {}, `${plural(s.vault_changes, "note was", "notes were")} edited outside postloom.`),
      h("button", { class: "button", type: "button", onclick: read }, "Read them now"));
  }
  return null;
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
  renderNav();

  const list = document.getElementById("article-list");
  const current = currentArticleId();
  list.replaceChildren(...(visible.length ? visible.map((a) => h("li", {},
    h("a", { href: `#/article/${encodeURIComponent(a.id)}`, "aria-current": a.id === current ? "page" : null },
      warp(a.topics),
      h("span", {}, h("span", { class: "title" }, a.title), h("span", { class: "meta" },
        [formatDate(a.published_on), a.series && `${a.series}${a.series_part ? `, part ${a.series_part}` : ""}`]
          .filter(Boolean).join(", ") || "Undated")))))
    : [h("li", { class: "empty" }, state.topicFilter ? "No articles in this thread yet." : "No articles yet.")]));
}

const NAV = {
  home: { icon: "home", label: "Home", active: (hash) => hash === "#/" || hash === "" },
  add: { icon: "plus", label: "Add article", active: (hash) => hash === "#/add" },
  graph: { icon: "graph", label: "Graph", active: (hash) => hash === "#/graph" },
  people: { icon: "people", label: "People", active: (hash) => hash.startsWith("#/people") || hash.startsWith("#/person/") },
  settings: { icon: "settings", label: "Settings", active: (hash) => hash === "#/settings" },
};

function renderNav() {
  const hash = location.hash || "#/";
  for (const link of document.querySelectorAll(".main-nav a")) {
    const item = NAV[link.dataset.route];
    const count = link.dataset.route === "people" && state.status && state.status.people
      ? h("span", { class: "nav-count", "aria-label": `${state.status.people} people` }, state.status.people) : null;
    fill(link, icon(item.icon), h("span", {}, item.label), count);
    link.setAttribute("aria-current", item.active(hash) ? "page" : "false");
  }
}

function currentArticleId() {
  const match = location.hash.match(/^#\/article\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

// ---------------------------------------------------------------------------- views
async function homeView() {
  if (!state.articles.length) {
    const configured = state.status.provider && state.status.provider.configured;
    return setMain(h("section", { class: "dashboard" },
      h("div", { class: "dash-head" }, weaveAll(),
        h("h1", {}, "Your writing, woven together"),
        h("p", {}, "Paste a LinkedIn article and the post that announced it. postloom restores the formatting, files it under your topics, links it to related articles and the people who discuss it, and lets you ask about everything you've written.")),
      keyNotice(),
      h("div", { class: "empty-state" },
        h("h2", {}, configured ? "Add your first article" : "Connect a model, then add an article"),
        h("p", {}, configured
          ? "Copy an article from LinkedIn and paste it in. It takes about half a minute."
          : "postloom works with Gemini, Claude, OpenAI, OpenRouter, or free local models with Ollama. Bring your own key; it stays on this computer."),
        h("div", { class: "actions" },
          configured ? null : h("a", { class: "button button-primary", href: "#/settings" }, "Connect a provider"),
          h("a", { class: configured ? "button button-primary" : "button", href: "#/add" }, icon("plus"), "Add article")))));
  }

  setMain(h("section", { class: "dashboard" }, h("p", { class: "hint" }, "Loading...")));
  let overview;
  try {
    overview = await api("/api/overview");
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Home"), notice("error", error.message)));
  }
  const s = state.status;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const spent = s.budget.spent_usd;
  const cost = spent > 0 && spent < 0.01 ? `$${spent.toFixed(4)}` : `$${spent.toFixed(2)}`;
  const budget = s.budget.monthly_usd;

  const waiting = overview.waiting.length
    ? h("ul", { class: "waiting-list" }, overview.waiting.map((w) => h("li", { class: "waiting-item" },
        h("p", { class: "who" }, h("strong", {}, w.author_name), ` on ${w.article_title}${w.posted_label ? `, ${w.posted_label}` : ""}`),
        h("q", {}, w.text),
        h("a", { class: "link-button", href: `#/article/${encodeURIComponent(w.article_id)}?comment=${encodeURIComponent(w.comment_id)}&reply=1` },
          icon("reply"), "Draft reply"))))
    : h("p", { class: "hint" }, overview.messages
      ? "You've answered everyone. Paste new comments from an article's page when there are more."
      : "No comments saved yet. Open an article and paste its comment section to see who's talking.");

  setMain(h("section", { class: "dashboard" },
    h("div", { class: "dash-head" }, weaveAll(),
      h("h1", {}, "Home"),
      h("p", {}, `${plural(overview.articles, "article", "articles")}, ${plural(overview.messages, "message", "messages")} from ${plural(overview.people, "person", "people")}.`)),
    keyNotice(),
    h("div", { class: "attention" },
      h("a", { href: "#waiting", class: overview.waiting_total ? "needs" : null },
        h("strong", {}, overview.waiting_total), h("span", {}, overview.waiting_total === 1 ? "message waiting for your reply" : "messages waiting for your reply")),
      h("a", { href: "#/graph", class: overview.pending_links ? "needs" : null },
        h("strong", {}, overview.pending_links), h("span", {}, overview.pending_links === 1 ? "suggested link to review" : "suggested links to review")),
      h("a", { href: "#/settings" },
        h("strong", {}, cost), h("span", {}, budget === null ? "spent on models this month" : `of your $${budget} monthly budget`))),
    h("div", { class: "dash-grid" },
      h("div", {},
        h("section", { class: "dash-section", id: "waiting", "aria-labelledby": "waiting-heading" },
          h("h2", { id: "waiting-heading" }, "Waiting for your reply"), waiting),
        h("section", { class: "dash-section", "aria-labelledby": "articles-heading" },
          h("h2", { id: "articles-heading" }, "Your articles", h("a", { href: "#/add" }, "Add article")),
          h("ul", { class: "article-rows" }, state.articles.slice(0, 8).map((a) => h("li", {},
            h("a", { class: "article-row", href: `#/article/${encodeURIComponent(a.id)}` }, warp(a.topics),
              h("div", {}, h("h3", {}, a.title), h("p", {}, a.summary || formatDate(a.published_on) || "")))))))),
      h("aside", {},
        h("section", { class: "dash-section", "aria-labelledby": "people-heading" },
          h("h2", { id: "people-heading" }, "Most engaged", overview.top_people.length ? h("a", { href: "#/people" }, "Everyone") : null),
          overview.top_people.length
            ? h("ul", { class: "people-mini" }, overview.top_people.map((p) => h("li", {},
                h("a", { href: `#/person/${encodeURIComponent(p.id)}` }, avatar(p.name),
                  h("span", { class: "name" }, p.name), h("span", { class: "count" }, plural(p.messages, "message", "messages"))))))
            : h("p", { class: "hint" }, "People appear here once you save comments."))))));
  const anchor = document.getElementById("waiting");
  document.querySelector('.attention a[href="#waiting"]').addEventListener("click", (event) => {
    event.preventDefault();
    anchor.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function weaveAll() {
  // Every thread in the vault, side by side: the loom at rest.
  const colors = state.status.topics.map((name) => topicColor(name));
  const stops = colors.map((c, i) => `${c} ${(i / colors.length) * 100}% ${((i + 1) / colors.length) * 100}%`);
  return h("div", { class: "weave", "aria-hidden": "true", vars: { "--weave": `linear-gradient(90deg, ${stops.join(", ")})` } });
}

function keyNotice() {
  const s = state.status;
  if (!s) return null;
  if (!s.provider || !s.provider.configured) {
    return notice("", s.provider
      ? `Finish setting up ${s.provider.label} to add articles, chat and draft replies.`
      : "Connect a model provider to add articles, chat and draft replies. Gemini, Claude, OpenAI, OpenRouter, or free local models with Ollama.",
      h("a", { href: "#/settings" }, "Open settings"));
  }
  if (s.embeddings.needs_reindex) {
    return notice("", "Your search model changed. Rebuild the search index so search by meaning works again.",
      h("a", { href: "#/settings" }, "Open settings"));
  }
  return null;
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
    if (added.suggested_links) lines.push(`${added.suggested_links} related ${added.suggested_links === 1 ? "article" : "articles"} suggested. Review them on the article's page.`);
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

async function articleView(id, focus = {}) {
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
    articleActions(article),
    article.summary ? h("p", { class: "summary" }, article.summary) : null,
    htmlBlock("prose", markdown(article.body_markdown)),
    article.posts.map((post) => h("section", { class: "post", "aria-label": "Announcement post" },
      h("h2", {}, "Announcement post"), h("p", {}, post.text))),
    relatedSection(article),
    article.posts.length ? discussionSection(article) : null);
  const suggestions = article.discussion.length
    ? ["What did people ask in the comments?", "Summarize the key takeaways", "Which questions did I not answer yet?"]
    : ["Summarize the key takeaways", "What are the main trade-offs?", "Explain the code step by step"];
  setMain(h("div", { class: "article-layout" }, reader,
    chatPanel(article.id, "Ask about this article",
      "Answers come only from this article, its post and its comments.", suggestions)));
  renderSidebar();
  if (focus.comment) focusComment(focus.comment, focus.reply);
}

// ---------------------------------------------------------------------------- edit / delete an article
function articleActions(article) {
  const panel = h("div", { class: "article-edit" });
  const comments = article.discussion.length;
  const remove = confirmBox("Delete",
    `Delete "${article.title}", its post${comments ? ` and ${plural(comments, "comment")}` : ""}? People you talked to are kept. This can't be undone.`,
    "Delete article", async () => {
      await api(`/api/article?id=${encodeURIComponent(article.id)}`, { method: "DELETE" });
      state.chats.delete(article.id);
      await refresh();
      toast("Article deleted");
      location.hash = "#/";
    });
  const edit = h("button", { class: "button", type: "button", "aria-expanded": "false",
    onclick: () => {
      const open = panel.childElementCount > 0;
      edit.setAttribute("aria-expanded", String(!open));
      if (open) panel.replaceChildren();
      else articleEditor(article, panel, () => { panel.replaceChildren(); edit.setAttribute("aria-expanded", "false"); });
    } }, icon("edit"), "Edit details");
  return h("div", { class: "article-tools" }, h("div", { class: "article-actions" }, edit, remove), panel);
}

async function articleEditor(article, panel, close) {
  fill(panel, h("p", { class: "hint" }, "Loading your topics…"));
  let topics;
  try {
    ({ topics } = await api("/api/topics"));
  } catch (error) {
    return fill(panel, notice("error", error.message));
  }
  const chosen = new Set(article.topics.map((t) => t.name));
  const input = (id, attrs) => h("input", { id, ...attrs });
  const title = input("edit_title", { value: article.title, required: true, maxlength: 300 });
  const summary = h("textarea", { id: "edit_summary", rows: 3, maxlength: 2000 }, article.summary || "");
  const series = input("edit_series", { value: article.series || "", maxlength: 200, placeholder: "None" });
  const part = input("edit_part", { type: "number", min: 1, max: 999, value: article.series_part || "", placeholder: "None" });
  const date = input("edit_date", { type: "date", value: article.published_on || "" });
  const url = input("edit_url", { type: "url", value: article.url || "", maxlength: 2000, placeholder: "https://www.linkedin.com/pulse/..." });
  const picker = h("fieldset", { class: "topic-picker" },
    h("legend", {}, "Topics"),
    topics.map((t) => h("label", { class: "chip" },
      h("input", { type: "checkbox", value: t.name, checked: chosen.has(t.name) }),
      h("span", { class: "swatch", vars: { "--thread": topicColor(t.name) } }), t.name)),
    h("p", { class: "hint" }, "Add, rename or remove topics in ", h("a", { href: "#/settings" }, "Settings"), "."));
  const status = h("p", { class: "hint", role: "status" });
  const save = h("button", { class: "button button-primary", type: "submit" }, "Save changes");

  const form = h("form", { class: "editor", "aria-label": "Edit article details",
    onsubmit: async (event) => {
      event.preventDefault();
      save.disabled = true;
      status.textContent = "Saving…";
      const body = {
        id: article.id,
        title: title.value.trim(),
        summary: summary.value.trim(),
        topics: [...picker.querySelectorAll("input:checked")].map((box) => box.value),
        series: series.value.trim() || null,
        series_part: part.value ? Number(part.value) : null,
        published_on: date.value || null,
        url: url.value.trim() || null,
      };
      try {
        await api("/api/article", { method: "PUT", body });
        await refresh();
        toast("Article updated");
        articleView(article.id);
      } catch (error) {
        save.disabled = false;
        fill(status, notice("error", error.message));
      }
    } },
    field("edit_title", "Title", title),
    field("edit_summary", "Summary", summary, "One or two sentences. Shown in search results and used by chat."),
    picker,
    h("div", { class: "field-row" },
      field("edit_series", "Series", series, "Leave empty if it isn't part of one."),
      field("edit_part", "Part", part),
      field("edit_date", "Published", date)),
    field("edit_url", "LinkedIn link", url, "postloom uses the link to recognise this article if you add it again."),
    h("div", { class: "editor-actions" }, save,
      h("button", { class: "button", type: "button", onclick: close }, "Cancel")),
    status,
    h("p", { class: "hint" }, "To change the article's text, edit its note in your vault; postloom reads the change."));
  fill(panel, form);
  title.focus();
}

function focusComment(commentId, openDraft) {
  const row = [...document.querySelectorAll(".comment")].find((li) => li.dataset.id === commentId);
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("flash");
  if (openDraft) {
    const button = row.querySelector(".comment-actions .link-button");
    if (button) button.click();
  }
}

// ---------------------------------------------------------------------------- related articles
function relatedSection(article) {
  const section = h("section", { class: "related", "aria-label": "Related articles" });
  fillRelated(section, article);
  return section;
}

function fillRelated(section, article) {
  const others = state.articles.filter((a) => a.id !== article.id);
  if (!others.length) return section.replaceChildren();
  const linked = new Set(article.related.map((r) => r.id));

  const decide = async (other, decision, button) => {
    button.disabled = true;
    try {
      await api("/api/links", { method: "POST", body: { article_id: article.id, other_id: other, decision } });
      article = await api(`/api/article?id=${encodeURIComponent(article.id)}`);
      fillRelated(section, article);
    } catch (error) {
      button.disabled = false;
      toast(error.message);
    }
  };
  const rows = article.related.map((link) => {
    const suggested = link.grade === "asserted";
    const title = h("a", { href: `#/article/${encodeURIComponent(link.id)}` }, link.title);
    const meta = suggested
      ? `Suggested${link.similarity ? `, ${Math.round(link.similarity * 100)}% similar` : ""}`
      : "Linked";
    const actions = suggested
      ? [h("button", { class: "button", type: "button", onclick: (e) => decide(link.id, "accept", e.currentTarget) }, "Accept"),
         h("button", { class: "button", type: "button", onclick: (e) => decide(link.id, "reject", e.currentTarget) }, "Dismiss")]
      : [h("button", { class: "link-button", type: "button", onclick: (e) => decide(link.id, "reject", e.currentTarget) }, "Remove")];
    return h("li", { class: `related-item${suggested ? " suggested" : ""}` },
      h("div", {}, title, h("p", { class: "hint" }, meta)), h("div", { class: "related-actions" }, actions));
  });

  const choices = others.filter((a) => !linked.has(a.id));
  const select = h("select", { id: "link-other" },
    h("option", { value: "" }, "Choose an article..."),
    choices.map((a) => h("option", { value: a.id }, a.title)));
  const linkButton = h("button", { class: "button", type: "button", onclick: (e) => {
    if (select.value) decide(select.value, "accept", e.currentTarget);
  } }, "Link");

  fill(section,
    h("h2", {}, "Related articles"),
    rows.length ? h("ul", { class: "related-list" }, rows)
      : h("p", { class: "hint" }, "No related articles yet. postloom suggests links when articles are similar in meaning, or you can link one yourself."),
    choices.length ? h("div", { class: "link-by-hand" },
      h("label", { class: "visually-hidden", for: "link-other" }, "Link another article"), select, linkButton) : null);
}

// ---------------------------------------------------------------------------- discussion
function discussionSection(article) {
  const comments = article.discussion;
  const people = new Set(comments.filter((c) => !c.is_own).map((c) => c.author_name));
  const summary = comments.length
    ? `${comments.length} ${comments.length === 1 ? "message" : "messages"} from ${people.size} ${people.size === 1 ? "person" : "people"}`
    : "No comments saved yet.";
  const editor = h("div", { class: "comment-editor" });
  const addButton = h("button", { class: "button", type: "button", onclick: () => {
    addButton.hidden = true;
    openPasteStep(article, editor, () => { addButton.hidden = false; });
  } }, comments.length ? "Add more comments" : "Add comments");

  return h("section", { class: "discussion", "aria-label": "Discussion" },
    h("div", { class: "discussion-head" },
      h("div", {}, h("h2", {}, "Discussion"), h("p", { class: "hint" }, summary)), addButton),
    editor,
    threadsOf(comments).map((thread) => h("ol", { class: "thread" },
      thread.map((c) => commentRow(c, comments)))));
}

function threadsOf(comments) {
  const threads = [];
  for (const comment of comments) {
    if (!comment.thread || !threads.length) threads.push([comment]);
    else threads[threads.length - 1].push(comment);
  }
  return threads;
}

function commentRow(comment, all) {
  const depth = Math.min(comment.depth, 4);
  const target = all.find((c) => c.id === comment.reply_to);
  const answering = target ? (target.is_own ? "you" : target.author_name) : null;
  return h("li", { class: `comment${comment.is_own ? " own" : ""}`, "data-depth": depth, "data-id": comment.id },
    h("p", { class: "comment-meta" },
      h("strong", {}, comment.is_own ? "You"
        : h("a", { href: `#/person/${encodeURIComponent(comment.author)}` }, comment.author_name)),
      answering ? h("span", { class: "replying" }, ` replying to ${answering}`) : null,
      comment.posted_label ? h("span", { class: "age" }, `, ${comment.posted_label}`) : null),
    comment.author_headline && !comment.is_own ? h("p", { class: "comment-headline" }, comment.author_headline) : null,
    h("p", { class: "comment-text" }, comment.text),
    !comment.is_own && state.status?.features?.reply_drafts ? replyDrafter(comment) : null);
}

// ---------------------------------------------------------------------------- reply drafts
function replyDrafter(comment) {
  const box = h("div", { class: "reply-draft" });
  const open = h("button", { class: "link-button", type: "button", onclick: () => {
    open.hidden = true;
    draftReply(comment, box, "", () => { open.hidden = false; });
  } }, "Draft reply");
  return h("div", { class: "comment-actions" }, open, box);
}

async function draftReply(comment, box, guidance, onClose) {
  const first = comment.author_name.split(/\s+/)[0];
  box.replaceChildren(h("p", { class: "hint" }, `Writing a reply to ${first}...`));
  let draft;
  try {
    draft = await api("/api/reply-draft", { method: "POST", body: { comment_id: comment.id, guidance } });
  } catch (error) {
    box.replaceChildren(h("p", { class: "notice error" }, error.message),
      h("div", { class: "actions" },
        h("button", { class: "button", type: "button", onclick: () => draftReply(comment, box, guidance, onClose) }, "Try again"),
        h("button", { class: "button", type: "button", onclick: () => { box.replaceChildren(); onClose(); } }, "Close")));
    return;
  }
  const id = `draft-${comment.id.replace(/[^a-z0-9]/gi, "-")}`;
  const text = h("textarea", { id, rows: Math.min(12, Math.max(4, Math.ceil(draft.text.length / 70))) });
  text.value = draft.text;
  const steer = h("input", { type: "text", id: `${id}-steer`, value: guidance,
    placeholder: "Optional: shorter, more technical, mention part 4..." });
  const copy = h("button", { class: "button button-primary", type: "button", onclick: async () => {
    await copyText(text);
    copy.textContent = "Copied";
    setTimeout(() => { copy.textContent = "Copy reply"; }, 1600);
  } }, "Copy reply");
  fill(box,
    h("label", { for: id }, `Draft reply to ${first}`),
    draft.already_answered ? h("p", { class: "hint" }, "You've already replied to this message.") : null,
    text,
    h("label", { class: "visually-hidden", for: steer.id }, "How should the next draft change?"),
    steer,
    h("div", { class: "actions" },
      copy,
      h("button", { class: "button", type: "button", onclick: () => draftReply(comment, box, steer.value.trim(), onClose) }, "Redraft"),
      h("button", { class: "button", type: "button", onclick: () => { box.replaceChildren(); onClose(); } }, "Close")),
    h("p", { class: "hint" },
      "postloom never posts anything. Edit, copy and reply on LinkedIn, then paste the comments again to save your reply."));
  text.focus();
}

async function copyText(textarea) {
  try {
    await navigator.clipboard.writeText(textarea.value);
  } catch {
    textarea.select();
    document.execCommand("copy");
  }
}

function openPasteStep(article, container, onClose) {
  const textarea = h("textarea", { id: "comments-paste", rows: 10, required: true,
    placeholder: "Open your post on LinkedIn, expand all comments and replies, select the whole comment section, copy and paste it here." });
  const read = h("button", { class: "button button-primary", type: "submit" }, "Read comments");
  const status = h("div", {});
  const form = h("form", { class: "paste-step", onsubmit: async (event) => {
    event.preventDefault();
    read.disabled = true;
    read.textContent = "Reading the comments...";
    status.replaceChildren();
    try {
      const preview = await api("/api/comments/preview", { method: "POST",
        body: { article_id: article.id, text: textarea.value } });
      openReviewStep(article, container, preview, onClose);
    } catch (error) {
      status.replaceChildren(notice("error", error.message));
      read.disabled = false;
      read.textContent = "Read comments";
    }
  } },
    field("comments-paste", "Paste the comment section", textarea,
      "Include your own replies. Pasting a section you added before only adds the new messages."),
    status,
    h("div", { class: "actions" }, read,
      h("button", { class: "button", type: "button", onclick: () => { container.replaceChildren(); onClose(); } }, "Cancel")));
  container.replaceChildren(form);
  textarea.focus();
}

function openReviewStep(article, container, preview, onClose) {
  const drafts = preview.messages.map((m) => ({ ...m }));
  const list = h("ol", { class: "review-list" });
  const saveButton = h("button", { class: "button button-primary", type: "button" }, "Save comments");
  const status = h("div", {});

  function label(index) {
    const d = drafts[index];
    const who = d.is_own ? "You" : d.author_name || `Message ${index + 1}`;
    const text = d.text.length > 60 ? `${d.text.slice(0, 60)}...` : d.text;
    return `${index + 1}. ${who}: ${text}`;
  }

  function render() {
    list.replaceChildren(...drafts.map((d, i) => {
      const replySelect = h("select", { "aria-label": `Where message ${i + 1} belongs`,
        onchange: (e) => { setParent(i, e.target.value === "" ? null : Number(e.target.value)); render(); } },
        h("option", { value: "", selected: d.reply_to === null }, "Starts a new thread"),
        drafts.slice(0, i).map((_, j) => h("option", { value: j, selected: d.reply_to === j }, `Replies to ${label(j)}`)));
      return h("li", { class: `review-item${d.is_own ? " own" : ""}${d.already_saved ? " saved" : ""}` },
        h("div", { class: "review-row" },
          h("label", {}, "Name", h("input", { value: d.author_name, oninput: (e) => { d.author_name = e.target.value; } })),
          h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.is_own,
            onchange: (e) => { d.is_own = e.target.checked; render(); } }), "This is me")),
        d.is_own ? null : h("div", { class: "review-row" },
          h("label", {}, "Headline", h("input", { value: d.author_headline, oninput: (e) => { d.author_headline = e.target.value; } })),
          h("label", {}, d.known_person ? "Profile link (known)" : "Profile link (optional)",
            h("input", { type: "url", value: d.profile_url || "", placeholder: "https://www.linkedin.com/in/...",
              oninput: (e) => { d.profile_url = e.target.value; } }))),
        h("label", { class: "review-text" }, "Message",
          h("textarea", { rows: 3, oninput: (e) => { d.text = e.target.value; } }, d.text)),
        h("div", { class: "review-row" }, replySelect,
          d.already_saved ? h("span", { class: "saved-badge" }, "Already saved, will be skipped") : null));
    }));
  }

  function setParent(index, target) {
    const d = drafts[index];
    if (target === null) { d.thread = null; d.reply_to = null; }
    else { d.reply_to = target; d.thread = drafts[target].thread ?? target; }
    // Messages that pointed into a thread that just changed shape keep their own choice.
  }

  saveButton.addEventListener("click", async () => {
    saveButton.disabled = true;
    status.replaceChildren();
    try {
      const messages = drafts.map(({ already_saved, known_person, ...m }) => ({ ...m, profile_url: m.profile_url || null }));
      const saved = await api("/api/comments", { method: "POST", body: { article_id: article.id, messages } });
      toast(saved.added ? `Saved ${saved.added} ${saved.added === 1 ? "message" : "messages"}` : "Nothing new to save");
      await refresh();
      articleView(article.id);
    } catch (error) {
      status.replaceChildren(notice("error", error.message));
      saveButton.disabled = false;
    }
  });

  const newCount = drafts.filter((d) => !d.already_saved).length;
  container.replaceChildren(h("div", { class: "review-step" },
    h("h3", {}, `Check ${drafts.length} ${drafts.length === 1 ? "message" : "messages"} before saving`),
    h("p", { class: "hint" }, `${newCount} new. Fix names or where a reply belongs, and add profile links so postloom recognises people next time.`),
    ...preview.warnings.map((w) => notice("", w)),
    list, status,
    h("div", { class: "actions" }, saveButton,
      h("button", { class: "button", type: "button", onclick: () => { container.replaceChildren(); onClose(); } }, "Cancel"))));
  render();
}

async function searchView(query, ask = false) {
  const page = h("section", { class: "page library-ask" },
    h("h1", {}, ask ? query : `Results for "${query}"`), h("div", { id: "search-results" }, h("p", { class: "lede" }, "Searching...")));
  setMain(page);
  try {
    const found = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const list = found.results.length
      ? h("ul", { class: "results" }, found.results.map((r) => h("li", { class: "result" },
          h("h2", {}, h("a", { href: `#/article/${encodeURIComponent(r.id)}` }, r.title)),
          r.passages.map((p) => h("p", { class: "passage" }, h("span", { class: "where" }, p.heading || "Introduction"), p.excerpt)))))
      : h("p", { class: "lede" }, "Nothing matches in your articles, posts or comments. Try other words, or ask below.");
    document.getElementById("search-results").replaceChildren(
      ...found.warnings.map((w) => notice("", w)), list,
      chatPanel("library", "Ask across your library", "Answers use only your articles, posts and comments, and what postloom knows about the people in them.", [], query, ask));
  } catch (error) {
    document.getElementById("search-results").replaceChildren(notice("error", error.message));
  }
}

async function settingsView() {
  await refresh();
  const s = state.status;
  const page = h("div", { class: "page settings" },
    h("h1", {}, "Settings"),
    h("p", { class: "lede" }, "postloom runs on your computer. Your articles, the people you talk to and your API keys stay here. Only the text a feature needs is sent to the model provider you choose, when you use that feature."),
    h("ul", { class: "status-list" },
      h("li", { "data-on": String(s.features.ingest) }, "Adding articles"),
      h("li", { "data-on": String(s.features.semantic_search) }, "Search by meaning"),
      h("li", { "data-on": String(s.features.chat) }, "Chat"),
      h("li", { "data-on": String(s.features.comments) }, "Reading comments"),
      h("li", { "data-on": String(s.features.reply_drafts) }, "Reply drafts")),
    providerSection(s),
    embeddingsSection(s),
    usageSection(s),
    h("section", { class: "settings-section" },
      h("h2", { class: "settings-heading" }, "Your name on LinkedIn"),
      h("div", { class: "inline-field" },
        h("label", { class: "visually-hidden", for: "owner_name" }, "Your name on LinkedIn"),
        h("input", { id: "owner_name", value: s.owner_name || "", placeholder: "e.g. Alex Author", autocomplete: "name",
          disabled: s.locked.includes("owner_name") }),
        h("button", { class: "button", type: "button", onclick: saveOwnerName, disabled: s.locked.includes("owner_name") }, "Save name")),
      h("p", { class: "hint" }, "Used to recognise your own replies when you paste comments.")),
    topicsSection(),
    vaultSection(s));
  setMain(page);
}

// ---------------------------------------------------------------------------- settings: topics
function topicsSection() {
  const section = h("section", { class: "settings-section", "aria-labelledby": "topics-heading" });
  const list = h("ul", { class: "topic-rows" });
  const status = h("div", { role: "status" });

  async function change(request, message) {
    try {
      const { topics } = await request;
      await refresh();
      render(topics);
      fill(status);
      toast(message);
    } catch (error) {
      fill(status, notice("error", error.message));
    }
  }

  function row(topic) {
    const item = h("li", {});
    const show = () => fill(item,
      h("span", { class: "swatch", vars: { "--thread": topicColor(topic.name) } }),
      h("div", { class: "topic-text" }, h("strong", {}, topic.name),
        topic.description ? h("p", {}, topic.description) : null),
      h("span", { class: "count" }, plural(topic.articles, "article")),
      h("div", { class: "topic-actions" },
        h("button", { class: "button", type: "button", onclick: edit }, "Edit"),
        confirmBox("Remove",
          `Remove "${topic.name}"? ${topic.articles ? `${plural(topic.articles, "article")} will no longer belong to it. ` : ""}Articles are never deleted.`,
          "Remove topic",
          () => change(api(`/api/topics?id=${encodeURIComponent(topic.id)}`, { method: "DELETE" }), "Topic removed"))));
    function edit() {
      const name = h("input", { value: topic.name, maxlength: 60, required: true, "aria-label": "Topic name" });
      const description = h("input", { value: topic.description, maxlength: 500, "aria-label": "Description", placeholder: "What belongs in this topic" });
      fill(item, h("form", { class: "topic-form",
        onsubmit: (event) => {
          event.preventDefault();
          change(api("/api/topics", { method: "PUT", body: { id: topic.id, name: name.value.trim(), description: description.value.trim() } }), "Topic saved");
        } }, name, description,
        h("button", { class: "button button-primary", type: "submit" }, "Save"),
        h("button", { class: "button", type: "button", onclick: show }, "Cancel")),
        h("p", { class: "hint" }, "Renaming it to the name of another topic merges the two."));
      name.focus();
    }
    show();
    return item;
  }

  function render(topics) {
    fill(list, topics.map(row));
  }

  const newName = h("input", { id: "new_topic", maxlength: 60, required: true, placeholder: "e.g. Vector databases" });
  const newDescription = h("input", { id: "new_topic_description", maxlength: 500, placeholder: "What belongs in this topic (helps the model choose)" });
  section.append(
    h("h2", { class: "settings-heading", id: "topics-heading" }, "Topics"),
    h("p", { class: "hint" }, "The threads your writing is sorted into. When you add an article, the model picks from this list and nothing else."),
    list, status,
    h("form", { class: "topic-form topic-add",
      onsubmit: async (event) => {
        event.preventDefault();
        await change(api("/api/topics", { method: "POST", body: { name: newName.value.trim(), description: newDescription.value.trim() } }), "Topic added");
        newName.value = "";
        newDescription.value = "";
      } },
      h("label", { class: "visually-hidden", for: "new_topic" }, "New topic name"), newName,
      h("label", { class: "visually-hidden", for: "new_topic_description" }, "New topic description"), newDescription,
      h("button", { class: "button", type: "submit" }, "Add topic")));
  api("/api/topics").then(({ topics }) => render(topics))
    .catch((error) => fill(status, notice("error", error.message)));
  return section;
}

// ---------------------------------------------------------------------------- settings: vault
function syncSummary(sync) {
  if (!sync.applied) {
    return notice("error", `${plural(sync.problems.length, "note")} can't be read, so nothing was changed:`,
      ...sync.problems.map((x) => `${x.path}: ${x.reason}`));
  }
  const lines = [`Your vault holds ${plural(sync.articles, "article")}, ${plural(sync.comments, "comment")} and ${plural(sync.people, "person", "people")}. postloom matches it.`];
  if (sync.changed) lines.push(`${plural(sync.changed, "edited note was", "edited notes were")} read.`);
  for (const x of sync.problems) lines.push(`Skipped ${x.path}: ${x.reason}`);
  if (sync.trashed.length) lines.push(`${plural(sync.trashed.length, "note")} that matched nothing moved to .postloom/trash in your vault.`);
  if (sync.index_error) lines.push(`Search by meaning is incomplete: ${sync.index_error}`);
  return notice("ok", ...lines);
}

function vaultSection(s) {
  const result = h("div", { role: "status" });
  const button = h("button", { class: "button", type: "button",
    onclick: async () => {
      button.disabled = true;
      fill(result, h("p", { class: "hint" }, "Reading your vault…"));
      try {
        const sync = await api("/api/vault/sync", { method: "POST" });
        await refresh();
        fill(result, syncSummary(sync));
      } catch (error) {
        fill(result, notice("error", error.message));
      }
      button.disabled = false;
    } }, "Read the vault again");
  return h("section", { class: "settings-section" },
    h("h2", { class: "settings-heading" }, "Your vault"),
    h("p", { class: "path" }, s.vault),
    h("p", { class: "hint" }, "Every article, post, comment and person is a Markdown note in this folder. Open it in Obsidian to browse it as a graph, and edit the notes there if you like: postloom reads your changes. If postloom's index is ever lost, it rebuilds itself from this folder, so backing up this folder backs up everything."),
    button, result,
    h("p", { class: "hint" }, `postloom ${s.version}`));
}

const TASK_LABELS = {
  extraction: "Restoring articles",
  comments: "Reading comments",
  chat: "Chat",
  reply: "Reply drafts",
};

function providerSection(s) {
  const section = h("section", { class: "settings-section", "aria-labelledby": "provider-heading" });
  let selected = s.provider ? s.provider.id : null;
  let found = [];
  let tested = null; // the last "Test connection" result, kept across re-renders
  const render = () => {
    const spec = s.providers.find((p) => p.id === selected);
    const locked = s.locked.includes("provider");
    fill(section,
      h("h2", { class: "settings-heading", id: "provider-heading" }, "Model provider"),
      h("p", { class: "hint" }, "Bring your own key. Cheap models do the routine work, so most people spend a few cents a month."),
      h("div", { class: "provider-grid", role: "radiogroup", "aria-label": "Model provider" },
        s.providers.map((p) => h("label", { class: `provider-card${p.id === selected ? " selected" : ""}` },
          h("input", { type: "radio", name: "provider", value: p.id, checked: p.id === selected, disabled: locked,
            onchange: () => { selected = p.id; found = []; tested = null; render(); } }),
          h("span", { class: "provider-name" }, p.label, p.local ? h("span", { class: "badge free" }, "Free") : null),
          h("span", { class: "provider-description" }, p.description)))),
      locked ? notice("", "The provider is set by the POSTLOOM_PROVIDER environment variable.") : null,
      spec ? providerForm(s, spec, found, tested, (models, outcome) => { found = models; tested = outcome; render(); }) : null);
  };
  render();
  return section;
}

function providerForm(s, spec, found, tested, onTested) {
  const current = s.provider && s.provider.id === spec.id ? s.provider : null;
  const keyFromEnv = current && current.key === "environment";
  const keySaved = current && current.key === "config";
  const id = (name) => `${spec.id}-${name}`;
  const result = h("div", { class: "test-result", role: "status", "aria-live": "polite" },
    tested ? notice(tested.ok ? "ok" : "error", tested.message) : null);
  const keyInput = spec.key === "none" || keyFromEnv ? null
    : h("input", { id: id("key"), type: "password", autocomplete: "off",
        placeholder: keySaved ? "A key is saved. Paste a new one to replace it." : spec.key === "optional" ? "Optional" : "Paste your key" });
  const urlInput = spec.base_url_editable
    ? h("input", { id: id("url"), type: "url", value: (current && current.base_url) || spec.base_url || "", placeholder: spec.base_url || "" })
    : null;
  const listId = id("models");
  const modelInputs = Object.entries(TASK_LABELS).map(([task, label]) => {
    const saved = current ? s.models[task] : "";
    const fallback = spec.models[task];
    return field(id(task), label,
      h("input", { id: id(task), list: listId, value: saved && saved !== fallback ? saved : "",
        placeholder: fallback || "Required: choose a model", disabled: s.locked.includes(`model:${task}`), "data-task": task }),
      task === "reply" ? "What people read. Worth your strongest model." : null);
  });
  const values = () => ({
    provider: spec.id,
    ...(keyInput && keyInput.value.trim() ? { api_key: keyInput.value.trim() } : {}),
    ...(urlInput ? { base_url: urlInput.value.trim() || null } : {}),
  });

  const test = h("button", { class: "button", type: "button", onclick: async () => {
    test.disabled = true;
    result.replaceChildren(h("span", { class: "hint" }, "Connecting..."));
    try {
      const reply = await api("/api/settings/test", { method: "POST", body: values() });
      onTested(reply.ok ? reply.models : found, { ok: reply.ok, message: reply.message });
    } catch (error) {
      test.disabled = false;
      result.replaceChildren(notice("error", error.message));
    }
  } }, "Test connection");

  const save = h("button", { class: "button button-primary", type: "submit" }, "Save");
  const form = h("form", { class: "provider-form", onsubmit: async (event) => {
    event.preventDefault();
    const models = {};
    for (const input of form.querySelectorAll("input[data-task]")) {
      if (!input.disabled) models[input.dataset.task] = input.value.trim() || null;
    }
    // Providers without defaults (Ollama, custom servers): one model can do every task.
    const first = Object.values(models).find(Boolean);
    if (!spec.models.chat && first) {
      for (const task of Object.keys(models)) models[task] = models[task] || first;
    }
    save.disabled = true;
    try {
      await api("/api/settings", { method: "PUT", body: { ...values(), models } });
      toast(`${spec.label} saved`);
      settingsView();
    } catch (error) {
      save.disabled = false;
      result.replaceChildren(notice("error", error.message));
    }
  } },
    keyFromEnv ? notice("", `Your key comes from the ${spec.key_envs[0] || "POSTLOOM_API_KEY"} environment variable. Change it there.`) : null,
    keyInput ? field(id("key"), `${spec.label} API key`, keyInput,
      spec.key_url ? h("span", {}, "Create one at ",
        h("a", { href: spec.key_url, target: "_blank", rel: "noopener noreferrer" }, new URL(spec.key_url).host),
        ". It's stored only in your Postloom folder, readable only by you.") : "Only if your server needs one.") : null,
    urlInput ? field(id("url"), "Server address", urlInput, spec.local ? "Where Ollama listens. The default is right unless you changed it." : "The server's OpenAI-compatible base URL, usually ending in /v1.") : null,
    spec.notes.map((note) => h("p", { class: "hint" }, note)),
    h("details", { class: "models", open: !spec.models.chat || (current && Object.keys(TASK_LABELS).some((t) => s.models[t] !== spec.models[t])) },
      h("summary", {}, "Models"),
      h("p", { class: "hint" }, spec.models.chat ? "Leave a field empty to use the default shown." : "Choose a model for each task, or fill in one and it's used for all. Test the connection to see what's available."),
      h("datalist", { id: listId }, found.map((m) => h("option", { value: m }))),
      h("div", { class: "field-row" }, modelInputs)),
    h("div", { class: "actions" }, save, test,
      keySaved ? h("button", { class: "button", type: "button", onclick: async () => {
        await api("/api/settings", { method: "PUT", body: { provider: spec.id, api_key: null } });
        toast("Saved key removed");
        settingsView();
      } }, "Remove saved key") : null),
    result);
  return form;
}

function embeddingsSection(s) {
  const e = s.embeddings;
  const spec = s.provider ? s.providers.find((p) => p.id === s.provider.id) : null;
  const choices = [
    ["local", "On this computer", `Free and private. Uses ${e.local_model}, downloaded once (about 70 MB).`],
    ...(spec && spec.offers_embeddings ? [["provider", `${spec.label}`, `Uses ${spec.models.embedding}; costs a fraction of a cent per article.`]] : []),
    ["off", "Off", "Keyword search only. Related-article suggestions need embeddings."],
  ];
  const rebuild = h("button", { class: "button button-primary", type: "button", onclick: async () => {
    rebuild.disabled = true;
    rebuild.textContent = "Rebuilding...";
    try {
      const done = await api("/api/reindex", { method: "POST", body: {} });
      toast(`Rebuilt ${done.articles} ${done.articles === 1 ? "article" : "articles"}`);
      settingsView();
    } catch (error) {
      rebuild.disabled = false;
      rebuild.textContent = "Rebuild search index";
      toast(error.message);
    }
  } }, "Rebuild search index");
  return h("section", { class: "settings-section" },
    h("h2", { class: "settings-heading" }, "Search by meaning"),
    h("div", { class: "choice-list", role: "radiogroup", "aria-label": "Embeddings" },
      choices.map(([value, label, hint]) => h("label", { class: "choice" },
        h("input", { type: "radio", name: "embeddings", value, checked: e.mode === value || (value === "local" && e.mode === "provider" && !(spec && spec.offers_embeddings)),
          onchange: async () => {
            try {
              await api("/api/settings", { method: "PUT", body: { embeddings: value } });
              toast("Search setting saved");
              settingsView();
            } catch (error) {
              toast(error.message);
            }
          } }),
        h("span", {}, h("strong", {}, label), h("span", { class: "hint" }, ` ${hint}`))))),
    e.needs_reindex ? notice("", "Your search index was built with a different model, so search by meaning can't use it yet.", rebuild) : null,
    !e.available && e.mode !== "off" ? notice("error", "Embeddings aren't available right now, so search uses keywords only.") : null);
}

function usageSection(s) {
  const section = h("section", { class: "settings-section", "aria-labelledby": "usage-heading" },
    h("h2", { class: "settings-heading", id: "usage-heading" }, "Usage this month"),
    h("p", { class: "hint" }, "Loading..."));
  api("/api/usage").then((usage) => {
    const money = (n) => n > 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
    const tokens = (n) => n.toLocaleString();
    const labels = { ...TASK_LABELS, embeddings: "Search embeddings", test: "Connection tests" };
    const budgetInput = h("input", { id: "monthly_budget", type: "number", min: "0", step: "0.5", inputmode: "decimal",
      value: s.budget.monthly_usd ?? "", placeholder: "No limit" });
    const saveBudget = async (value) => {
      try {
        await api("/api/settings", { method: "PUT", body: { monthly_budget_usd: value } });
        toast(value === null ? "Budget removed" : "Budget saved");
        settingsView();
      } catch (error) {
        toast(error.message);
      }
    };
    fill(section,
      h("h2", { class: "settings-heading", id: "usage-heading" }, `Usage this month: ${money(usage.cost_usd)}`),
      usage.by_task.length
        ? h("table", { class: "usage" },
            h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Task"), h("th", { scope: "col" }, "Calls"),
              h("th", { scope: "col" }, "Tokens in / out"), h("th", { scope: "col" }, "Cost"))),
            h("tbody", {}, usage.by_task.map((t) => h("tr", {},
              h("th", { scope: "row" }, labels[t.task] || t.task), h("td", {}, t.calls),
              h("td", {}, `${tokens(t.input_tokens)} / ${tokens(t.output_tokens)}`),
              h("td", {}, t.unpriced_calls === t.calls && t.cost_usd === 0 ? "unknown" : money(t.cost_usd))))))
        : h("p", { class: "hint" }, "No model calls yet this month."),
      usage.unpriced_calls ? h("p", { class: "hint" }, `${usage.unpriced_calls} ${usage.unpriced_calls === 1 ? "call" : "calls"} used a model without a known price and ${usage.unpriced_calls === 1 ? "isn't" : "aren't"} counted. Add its price to config.json under "prices".`) : null,
      h("p", { class: "hint" }, "Costs are estimated from list prices (OpenRouter reports exact ones). Models on your computer are free."),
      h("h3", { class: "settings-subheading" }, "Monthly budget"),
      h("div", { class: "inline-field" },
        h("label", { class: "visually-hidden", for: "monthly_budget" }, "Monthly budget in US dollars"),
        h("span", { class: "currency", "aria-hidden": "true" }, "$"), budgetInput,
        h("button", { class: "button", type: "button", onclick: () => {
          const value = budgetInput.value.trim();
          saveBudget(value === "" ? null : Number(value));
        } }, "Save budget"),
        s.budget.monthly_usd !== null ? h("button", { class: "button", type: "button", onclick: () => saveBudget(null) }, "Remove") : null),
      h("p", { class: "hint" }, s.budget.monthly_usd !== null
        ? `${money(Math.max(s.budget.monthly_usd - usage.cost_usd, 0))} left. When it's spent, postloom pauses paid model calls until next month or until you raise it.`
        : "Optional. postloom pauses paid model calls once this month's spending reaches it."));
  }).catch((error) => section.replaceChildren(notice("error", error.message)));
  return section;
}

async function saveOwnerName() {
  const name = document.getElementById("owner_name").value.trim();
  try {
    await api("/api/settings", { method: "PUT", body: { owner_name: name || null } });
    toast(name ? "Name saved" : "Name removed");
  } catch (error) {
    toast(error.message);
  }
}

// ---------------------------------------------------------------------------- people
function initials(name) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function avatar(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return h("span", { class: "initials", "aria-hidden": "true", vars: { "--thread": `var(--dye-${(hash % DYES) + 1})` } },
    initials(name));
}

async function peopleView() {
  const [{ people }] = await Promise.all([api("/api/people"), refresh()]);
  const page = h("section", { class: "page" },
    h("h1", {}, "People"),
    h("p", { class: "lede" }, people.length
      ? "Everyone who has commented on your posts, most engaged first."
      : "No one yet. Open an article and add its comments to see who engages with your writing."));
  if (people.length) {
    page.append(h("ul", { class: "people-list" }, people.map((p) => h("li", {},
      h("a", { class: "person-row", href: `#/person/${encodeURIComponent(p.id)}` }, avatar(p.name),
        h("div", {}, h("h2", {}, p.name, p.profile_url ? null : h("span", { class: "badge" }, "no profile link")),
          p.headline ? h("p", {}, p.headline) : null),
        h("span", { class: "count" }, `${p.messages} ${p.messages === 1 ? "message" : "messages"}`,
          h("br"), `${p.articles} ${p.articles === 1 ? "article" : "articles"}`))))));
  }
  setMain(page);
  renderSidebar();
}

async function personView(id) {
  let person;
  try {
    person = await api(`/api/person?id=${encodeURIComponent(id)}`);
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Person not found"),
      notice("error", error.message), h("a", { href: "#/people" }, "Back to people")));
  }
  const earlier = person.headlines.filter((x) => !x.current);
  const profileField = h("input", { id: "profile_url", type: "url", value: person.profile_url || "",
    placeholder: "https://www.linkedin.com/in/..." });
  const notesField = h("textarea", { id: "person_notes", rows: 4 }, person.notes);

  async function save(changes, message) {
    try {
      const { id: newId } = await api("/api/person", { method: "PUT", body: { id: person.id, ...changes } });
      toast(message);
      if (newId !== person.id) location.hash = `#/person/${encodeURIComponent(newId)}`;
      else personView(newId);
    } catch (error) {
      toast(error.message);
    }
  }

  const firstName = person.name.split(/\s+/)[0];
  const profile = h("section", { class: "page" },
    h("div", { class: "person-head" }, avatar(person.name),
      h("div", {}, h("h1", {}, person.name), person.headline ? h("p", {}, person.headline) : null)),
    earlier.length ? h("ul", { class: "history", "aria-label": "Earlier headlines" },
      earlier.map((x) => h("li", {}, `Earlier: ${x.headline}`))) : null,
    h("p", { class: "byline" }, `${person.messages} ${person.messages === 1 ? "message" : "messages"} on ${person.articles} ${person.articles === 1 ? "article" : "articles"}. `,
      person.profile_url ? h("a", { href: person.profile_url, target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn") : null),

    h("div", { class: "person-section" },
      h("h2", {}, "Profile link"),
      person.profile_url ? null : h("p", { class: "hint" },
        "Add their LinkedIn profile link so postloom recognises them on every post, even if their name is written differently."),
      h("div", { class: "inline-field" },
        h("label", { class: "visually-hidden", for: "profile_url" }, "LinkedIn profile link"), profileField,
        h("button", { class: "button", type: "button",
          onclick: () => save({ profile_url: profileField.value.trim() }, "Profile link saved") }, "Save link"))),

    h("div", { class: "person-section" },
      h("h2", {}, "Notes"),
      field("person_notes", "Private notes about this person", notesField, "Only you see these. They're saved in your vault."),
      h("button", { class: "button", type: "button",
        onclick: () => save({ notes: notesField.value }, "Notes saved") }, "Save notes")),

    h("div", { class: "person-section" },
      h("h2", {}, "Conversations"),
      person.conversations.map((c) => h("div", {},
        h("h3", {}, h("a", { href: `#/article/${encodeURIComponent(c.article_id)}` }, c.article_title)),
        threadsOf(c.messages).map((thread) => h("ol", { class: "thread" },
          thread.map((m) => commentRow(m, c.messages))))))),

    h("div", { class: "person-section danger-zone" },
      h("h2", {}, "Delete this person"),
      h("p", { class: "hint" }, "Erases their profile, your notes about them and every message they wrote, from postloom and from your vault. Use this when someone asks you to remove their data. Your own replies stay as you wrote them."),
      confirmBox("Delete person",
        `Delete ${person.name} and ${plural(person.messages, "message")} they wrote? This can't be undone.`,
        "Delete person", async () => {
          const gone = await api(`/api/person?id=${encodeURIComponent(person.id)}`, { method: "DELETE" });
          await refresh();
          state.chats.delete(person.id);
          toast(`${gone.name} deleted`);
          location.hash = "#/people";
        })));
  setMain(person.messages ? h("div", { class: "article-layout" }, profile,
    chatPanel(person.id, `Ask about ${firstName}`,
      "Answers come only from your notes about them and the conversations you had.",
      [`What does ${firstName} care about?`, "Summarize our conversations", "Is there anything I haven't answered?"]))
    : profile);
  renderSidebar();
}

// ---------------------------------------------------------------------------- chat
function chatPanel(scope, title, subtitle, suggestions, initialQuestion, autoAsk = false) {
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
        empty.push(h("div", { class: "prompts" }, suggestions.map((s) =>
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
    const pending = { role: "assistant", text: "Reading your library...", pending: true };
    history.push(pending);
    input.value = "";
    submit.disabled = true;
    render();
    try {
      const answer = await api("/api/ask", { method: "POST", body: {
        question,
        article_id: scope.startsWith("article:") ? scope : null,
        person_id: scope.startsWith("person:") ? scope : null,
        history: previous } });
      Object.assign(pending, { text: answer.text, sources: answer.sources, uncited: answer.uncited, pending: false });
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
  if (initialQuestion && !history.length) {
    input.value = initialQuestion;
    if (autoAsk) queueMicrotask(send);
  }
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
          s.article_id && s.article_id === here ? s.section : `${s.title}: ${s.section}`),
        h("p", { class: "source-text" }, s.text)))));
  }
  if (message.uncited) {
    body.append(h("p", { class: "uncited" }, "This answer points to none of your sources, so it can't be checked. Treat it with care."));
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
  if (!source.article_id) {
    // Facts about a person open their page; library facts have nowhere to go.
    if (source.person_id) location.hash = `#/person/${encodeURIComponent(source.person_id)}`;
    return;
  }
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
// ---------------------------------------------------------------------------- graph
const GRAPH_LENGTHS = { belongs_to: 95, part_of: 60, related_to: 120, discussed: 55 };
const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "css") for (const [k, v] of Object.entries(value)) node.style.setProperty(k, v); // CSSOM, allowed by the CSP
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function graphView() {
  let graph;
  try {
    [graph] = await Promise.all([api("/api/graph"), refresh()]);
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Graph"), notice("error", error.message)));
  }
  const options = { people: true, suggested: true };
  const canvas = h("div", { class: "graph-canvas" });
  const toggle = (key, label) => h("label", { class: "check" },
    h("input", { type: "checkbox", checked: true, onchange: (e) => { options[key] = e.target.checked; draw(); } }), label);
  const draw = () => canvas.replaceChildren(graphSvg(graph, options));

  const articles = graph.nodes.filter((n) => n.kind === "article");
  setMain(h("section", { class: "graph-page" },
    h("h1", {}, "Graph"),
    h("p", { class: "lede" }, articles.length
      ? "Your articles, their topics and series, and the people who discussed them. Drag to move around, scroll to zoom, select a node to open it."
      : "Add an article and its topics, links and commenters will appear here."),
    h("div", { class: "graph-controls" },
      toggle("people", "People"), toggle("suggested", "Suggested links"),
      h("ul", { class: "graph-legend", "aria-label": "Legend" },
        h("li", {}, h("span", { class: "key key-topic" }), "Topic"),
        h("li", {}, h("span", { class: "key key-article" }), "Article"),
        h("li", {}, svgEl("svg", { class: "key-person", viewBox: "-11 -11 22 22", "aria-hidden": "true" }, personGlyph(10)), "Person"),
        h("li", {}, h("span", { class: "key key-linked" }), "Linked"),
        h("li", {}, h("span", { class: "key key-suggested" }), "Suggested"))),
    canvas,
    suggestionList(graph)));
  draw();
}

function suggestionList(graph) {
  const titles = new Map(graph.nodes.map((n) => [n.id, n.label]));
  const pending = graph.links.filter((l) => l.kind === "related_to" && l.grade === "asserted");
  if (!pending.length) return null;
  const decide = async (link, decision, button) => {
    button.disabled = true;
    try {
      await api("/api/links", { method: "POST", body: { article_id: link.source, other_id: link.target, decision } });
      await graphView();
    } catch (error) {
      button.disabled = false;
      toast(error.message);
    }
  };
  return h("section", { class: "link-review", "aria-label": "Suggested links" },
    h("h2", {}, `${pending.length} suggested ${pending.length === 1 ? "link" : "links"} to review`),
    h("p", { class: "hint" }, "Accepted links are added to both articles' notes in your vault. Dismissed ones are never suggested again."),
    h("ul", { class: "related-list" }, pending.map((link) => h("li", { class: "related-item suggested" },
      h("div", {},
        h("a", { href: `#/article/${encodeURIComponent(link.source)}` }, titles.get(link.source)),
        h("span", { class: "pair-sep" }, " and "),
        h("a", { href: `#/article/${encodeURIComponent(link.target)}` }, titles.get(link.target)),
        h("p", { class: "hint" }, link.weight ? `${Math.round(link.weight * 100)}% similar` : "Suggested")),
      h("div", { class: "related-actions" },
        h("button", { class: "button", type: "button", onclick: (e) => decide(link, "accept", e.currentTarget) }, "Accept"),
        h("button", { class: "button", type: "button", onclick: (e) => decide(link, "reject", e.currentTarget) }, "Dismiss"))))));
}

function graphSvg(graph, options) {
  const nodes = graph.nodes
    .filter((n) => options.people || n.kind !== "person")
    .map((n) => ({ ...n, r: nodeRadius(n) }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = graph.links.filter((l) => byId.has(l.source) && byId.has(l.target)
    && (options.suggested || l.grade !== "asserted" || l.kind !== "related_to"));
  if (!nodes.length) return h("p", { class: "hint graph-empty" }, "Nothing to show yet.");
  layout(nodes, links, byId);

  const neighbours = new Map(nodes.map((n) => [n.id, new Set([n.id])]));
  for (const l of links) { neighbours.get(l.source).add(l.target); neighbours.get(l.target).add(l.source); }

  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
  const pad = 70;
  let view = { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad,
    w: Math.max(...xs) - Math.min(...xs) + 2 * pad, h: Math.max(...ys) - Math.min(...ys) + 2 * pad };
  view.w = Math.max(view.w, 320); view.h = Math.max(view.h, 240);
  const svg = svgEl("svg", { class: "graph", role: "img", "aria-label": `Graph of ${nodes.length} nodes and ${links.length} links` });
  const setView = () => svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  setView();

  const edgeLayer = svgEl("g", { class: "edges" }, links.map((l) => {
    const a = byId.get(l.source), b = byId.get(l.target);
    const topic = l.kind === "belongs_to" ? b : null;
    return svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, "data-a": l.source, "data-b": l.target,
      class: `edge edge-${l.kind}${l.grade === "asserted" && l.kind === "related_to" ? " suggested" : ""}`,
      css: topic ? { stroke: topicColor(topic.label) } : null });
  }));
  const nodeLayer = svgEl("g", { class: "nodes" }, nodes.map((n) => {
    const href = n.kind === "article" ? `#/article/${encodeURIComponent(n.id)}`
      : n.kind === "person" ? `#/person/${encodeURIComponent(n.id)}` : null;
    const shape = n.kind === "person"
      ? personGlyph(n.r, { transform: `translate(${n.x} ${n.y})` })
      : svgEl("circle", { cx: n.x, cy: n.y, r: n.r, class: `node node-${n.kind}`,
          css: n.kind === "topic" ? { fill: topicColor(n.label) } : null });
    const label = svgEl("text", { x: n.x, y: n.y + n.r + 12, class: `label label-${n.kind}` },
      clip(n.label, n.kind === "person" ? 22 : 30));
    const group = svgEl(href ? "a" : "g", { class: "graph-node", "data-id": n.id, href,
      onclick: n.kind === "topic" ? () => { state.topicFilter = n.label; location.hash = "#/"; } : null,
      onmouseenter: () => focusNode(svg, n.id, neighbours), onmouseleave: () => focusNode(svg, null),
      onfocus: () => focusNode(svg, n.id, neighbours), onblur: () => focusNode(svg, null) },
      svgEl("title", {}, nodeTitle(n)), shape, label);
    return group;
  }));
  svg.append(edgeLayer, nodeLayer);
  panAndZoom(svg, () => view, (v) => { view = v; setView(); });
  return svg;
}

function personGlyph(r, attrs = {}) {
  // A head and shoulders drawn in a 20-unit box, scaled to the node's radius. The faint
  // circle behind it keeps the whole node easy to hover and click.
  const k = r / 10;
  return svgEl("g", { class: "node node-person", ...attrs },
    svgEl("circle", { class: "person-hit", r: r + 2 }),
    svgEl("g", { transform: `scale(${k})` },
      svgEl("circle", { cx: 0, cy: -4.2, r: 4 }),
      svgEl("path", { d: "M-8.5 9.5c0-5.2 3.8-8.2 8.5-8.2s8.5 3 8.5 8.2z" })));
}

function nodeRadius(n) {
  if (n.kind === "topic") return 10 + Math.min(Math.sqrt(n.weight) * 2.5, 12);
  if (n.kind === "series") return 8;
  if (n.kind === "article") return 7 + Math.min(Math.sqrt(n.weight), 5);
  return 7 + Math.min(Math.sqrt(n.weight) * 1.5, 5);
}

function nodeTitle(n) {
  const count = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  if (n.kind === "topic" || n.kind === "series") return `${n.label}: ${count(n.weight, "article", "articles")}`;
  if (n.kind === "article") return n.weight ? `${n.label}: ${count(n.weight, "comment", "comments")}` : n.label;
  return `${n.label}: ${count(n.weight, "message", "messages")}`;
}

function clip(text, width) {
  return text.length <= width ? text : `${text.slice(0, width - 1).trimEnd()}…`;
}

function focusNode(svg, id, neighbours) {
  svg.classList.toggle("focused", id !== null);
  const near = id === null ? null : neighbours.get(id);
  for (const g of svg.querySelectorAll(".graph-node")) g.classList.toggle("near", !!near && near.has(g.dataset.id));
  for (const line of svg.querySelectorAll(".edge")) {
    line.classList.toggle("near", !!near && (line.dataset.a === id || line.dataset.b === id));
  }
}

function layout(nodes, links, byId) {
  // A small force simulation, run to completion before drawing. Starting positions come
  // from each id's hash, so the same library always gets the same picture.
  nodes.forEach((n, i) => {
    let hash = 0;
    for (const ch of n.id) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    const angle = (hash % 3600) / 3600 * 2 * Math.PI;
    const radius = 40 + (i % 7) * 15 + (n.kind === "topic" ? 0 : 40);
    n.x = Math.cos(angle) * radius; n.y = Math.sin(angle) * radius; n.vx = 0; n.vy = 0;
  });
  const steps = nodes.length > 400 ? 120 : 300;
  for (let step = 0; step < steps; step++) {
    const alpha = 1 - step / steps;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        if (d2 > 90000) continue; // beyond ~300 units, nodes ignore each other
        const force = (1400 * (0.3 + 0.7 * alpha)) / d2;
        a.vx += dx * force; a.vy += dy * force; b.vx -= dx * force; b.vy -= dy * force;
      }
    }
    for (const l of links) {
      const a = byId.get(l.source), b = byId.get(l.target);
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = ((d - (GRAPH_LENGTHS[l.kind] || 80)) / d) * 0.06 * alpha;
      a.vx += dx * force; a.vy += dy * force; b.vx -= dx * force; b.vy -= dy * force;
    }
    for (const n of nodes) {
      n.vx -= n.x * 0.025; n.vy -= n.y * 0.025; // gravity keeps separate clusters close
      n.vx *= 0.82; n.vy *= 0.82;
      n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy));
    }
  }
}

function panAndZoom(svg, getView, setView) {
  let drag = null;
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".graph-node")) return;
    drag = { x: event.clientX, y: event.clientY, view: getView() };
    svg.setPointerCapture(event.pointerId);
    svg.classList.add("dragging");
  });
  svg.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const scale = drag.view.w / svg.clientWidth;
    setView({ ...drag.view, x: drag.view.x - (event.clientX - drag.x) * scale, y: drag.view.y - (event.clientY - drag.y) * scale });
  });
  const stop = () => { drag = null; svg.classList.remove("dragging"); };
  svg.addEventListener("pointerup", stop);
  svg.addEventListener("pointercancel", stop);
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const view = getView();
    const factor = Math.min(4, Math.max(0.25, Math.exp(event.deltaY * 0.0015)));
    const box = svg.getBoundingClientRect();
    const px = view.x + ((event.clientX - box.left) / box.width) * view.w;
    const py = view.y + ((event.clientY - box.top) / box.height) * view.h;
    setView({ x: px - (px - view.x) * factor, y: py - (py - view.y) * factor, w: view.w * factor, h: view.h * factor });
  }, { passive: false });
}

async function route() {
  const hash = location.hash || "#/";
  const [path, queryString] = hash.split("?");
  const params = new URLSearchParams(queryString || "");
  try {
    if (!state.status) await refresh();
    else state.status = await api("/api/status");  // notes may have been edited meanwhile
    renderNav();
    if (path.startsWith("#/article/")) {
      return await articleView(decodeURIComponent(path.slice(10)),
        { comment: params.get("comment"), reply: params.get("reply") === "1" });
    }
    if (path === "#/search") return await searchView(params.get("q") || "", params.get("ask") === "1");
    if (path === "#/add") return addView();
    if (path === "#/settings") return await settingsView();
    if (path === "#/people") return await peopleView();
    if (path === "#/graph") return await graphView();
    if (path.startsWith("#/person/")) return await personView(decodeURIComponent(path.slice(9)));
    renderSidebar();
    return await homeView();
  } catch (error) {
    setMain(h("section", { class: "page" }, h("h1", {}, "Something went wrong"), notice("error", error.message)));
  }
}

// ---------------------------------------------------------------------------- command palette
const palette = {
  root: document.getElementById("palette"),
  input: document.getElementById("palette-input"),
  list: document.getElementById("palette-list"),
  options: [],
  active: 0,
  returnFocus: null,
  people: null,
};

function openPalette() {
  if (!palette.root.hidden) return;
  palette.returnFocus = document.activeElement;
  palette.root.hidden = false;
  palette.input.value = "";
  palette.active = 0;
  renderPalette();
  palette.input.focus();
  if (palette.people === null) {
    palette.people = [];
    api("/api/people").then(({ people }) => { palette.people = people; renderPalette(); }).catch(() => {});
  }
}

function closePalette() {
  if (palette.root.hidden) return;
  palette.root.hidden = true;
  if (palette.returnFocus && document.contains(palette.returnFocus)) palette.returnFocus.focus();
}

function paletteOptions(query) {
  const q = query.trim().toLowerCase();
  const matches = (text) => !q || text.toLowerCase().includes(q);
  const go = (hash) => () => { location.hash = hash; };
  const groups = [];
  if (q) {
    groups.push(["Search and ask", [
      { icon: "search", label: `Search for "${query.trim()}"`, run: go(`#/search?q=${encodeURIComponent(query.trim())}`) },
      { icon: "ask", label: `Ask your articles: "${query.trim()}"`, run: go(`#/search?q=${encodeURIComponent(query.trim())}&ask=1`) },
    ]]);
  }
  const articles = state.articles.filter((a) => matches(a.title)).slice(0, q ? 6 : 4).map((a) => ({
    icon: "article", label: a.title, sub: a.topics.map((t) => t.name).join(", "),
    run: go(`#/article/${encodeURIComponent(a.id)}`),
  }));
  if (articles.length) groups.push(["Articles", articles]);
  const people = (palette.people || []).filter((p) => matches(p.name)).slice(0, q ? 5 : 3).map((p) => ({
    icon: "person", label: p.name, sub: p.headline || "", run: go(`#/person/${encodeURIComponent(p.id)}`),
  }));
  if (people.length) groups.push(["People", people]);
  const dark = document.documentElement.dataset.theme !== "light";
  const pages = [
    ...Object.entries(NAV).map(([route, item]) => ({
      icon: item.icon, label: item.label, run: go(route === "home" ? "#/" : `#/${route}`),
    })),
    { icon: dark ? "sun" : "moon", label: dark ? "Switch to light theme" : "Switch to dark theme", run: toggleTheme },
  ].filter((o) => matches(o.label));
  if (pages.length) groups.push(["Go to", pages]);
  return groups;
}

function renderPalette() {
  const groups = paletteOptions(palette.input.value);
  palette.options = groups.flatMap(([, options]) => options);
  palette.active = Math.min(palette.active, Math.max(palette.options.length - 1, 0));
  let index = 0;
  const items = groups.flatMap(([name, options]) => [
    h("li", { class: "palette-group", role: "presentation" }, name),
    ...options.map((option) => {
      const i = index++;
      return h("li", { class: "palette-option", role: "option", id: `palette-option-${i}`,
        "aria-selected": String(i === palette.active),
        onmousemove: () => { if (palette.active !== i) { palette.active = i; markActive(); } },
        onclick: () => runOption(i) },
        icon(option.icon), h("span", { class: "label-text" }, option.label),
        option.sub ? h("span", { class: "sub" }, option.sub) : null);
    }),
  ]);
  fill(palette.list, items.length ? items : h("li", { class: "palette-empty" }, "Nothing matches. Press Enter to search instead."));
  markActive();
}

function markActive() {
  for (const el of palette.list.querySelectorAll(".palette-option")) {
    const on = el.id === `palette-option-${palette.active}`;
    el.setAttribute("aria-selected", String(on));
    if (on) el.scrollIntoView({ block: "nearest" });
  }
  palette.input.setAttribute("aria-activedescendant", palette.options.length ? `palette-option-${palette.active}` : "");
}

function runOption(i) {
  const option = palette.options[i];
  closePalette();
  if (option) option.run();
}

palette.input.addEventListener("input", () => { palette.active = 0; renderPalette(); });
palette.input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const n = palette.options.length;
    if (n) palette.active = (palette.active + (event.key === "ArrowDown" ? 1 : n - 1)) % n;
    markActive();
  } else if (event.key === "Enter") {
    event.preventDefault();
    const query = palette.input.value.trim();
    if (palette.options.length) runOption(palette.active);
    else if (query) { closePalette(); location.hash = `#/search?q=${encodeURIComponent(query)}`; }
  } else if (event.key === "Escape") {
    event.preventDefault();
    closePalette();
  } else if (event.key === "Tab") {
    event.preventDefault(); // focus stays in the dialog
  }
});
palette.root.addEventListener("mousedown", (event) => { if (event.target === palette.root) closePalette(); });

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
document.getElementById("shortcut-hint").textContent = isMac ? "⌘K" : "Ctrl K";
document.getElementById("search-trigger").prepend(icon("search"));
document.getElementById("search-trigger").addEventListener("click", openPalette);
document.addEventListener("keydown", (event) => {
  const typing = event.target.closest && event.target.closest("input, textarea, select, [contenteditable]");
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (palette.root.hidden) openPalette(); else closePalette();
  } else if (event.key === "/" && !typing && palette.root.hidden) {
    event.preventDefault();
    openPalette();
  }
});

// ---------------------------------------------------------------------------- theme and menu
function renderThemeToggle() {
  const dark = document.documentElement.dataset.theme !== "light";
  fill(document.getElementById("theme-toggle"), icon(dark ? "sun" : "moon"), h("span", {}, dark ? "Light theme" : "Dark theme"));
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("postloom-theme", next);
  } catch {
    // Not saved (private window); the choice still applies until the page closes.
  }
  renderThemeToggle();
}

document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
renderThemeToggle();

const menuToggle = document.getElementById("menu-toggle");
function setMenu(open) {
  document.getElementById("sidebar").classList.toggle("open", open);
  menuToggle.setAttribute("aria-expanded", String(open));
  fill(menuToggle, icon(open ? "close" : "menu"));
}
menuToggle.addEventListener("click", () => setMenu(menuToggle.getAttribute("aria-expanded") !== "true"));
setMenu(false);

window.addEventListener("hashchange", () => { setMenu(false); route(); });
route();
