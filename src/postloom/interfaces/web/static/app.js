/* postloom frontend: plain JavaScript, no build step, nothing loaded from the internet. */
"use strict";

const DYES = 8;
const state = {
  status: null,
  articles: [],
  topicFilter: null,
  allTopics: false,
  libraryVersion: null,
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
    // The last status said how postloom was started here (installed, or from a checkout).
    const start = (state.status && state.status.start_command) || "postloom start";
    throw new Error(`postloom isn't running. Start it again in your terminal with \`${start}\`, then reload this page.`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

async function refresh() {
  // The article list is the biggest answer; fetch it again only once the library changed.
  const status = await api("/api/status");
  const version = status.library_version;
  if (version === null || version === undefined || version !== state.libraryVersion) {
    ({ articles: state.articles } = await api("/api/articles"));
    state.libraryVersion = version;
  }
  state.status = status;
  renderSidebar();
}

// ---------------------------------------------------------------------------- icons
// Line icons drawn on a 24px grid; constant markup, never user input.
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  power: '<path d="M12 3v8"/><path d="M6.4 7a8 8 0 1 0 11.2 0"/>',
  graph: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.5 6.2l7 .5M7.1 8.3l3.8 7.4M16.8 9.3l-3.6 6.5"/>',
  people: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.4 3-5.3 6-5.3s5.4 1.9 6 5.3"/><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.9c1.6.7 2.7 2.4 3 5.1"/>',
  settings: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  tag: '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.7 7.7a1 1 0 0 1-1.4 0z"/><circle cx="8" cy="8" r="1.4"/>',
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

// ---------------------------------------------------------------------------- long lists
// A library grows to hundreds of articles and thousands of people. Lists show a page at a
// time and grow on request, so a screen stays quick and readable at any size.
const PAGE_SIZE = 50;

function pagedList(items, renderItem, { pageSize = PAGE_SIZE, listClass = "", tag = "ul", what = "more" } = {}) {
  const list = h(tag, { class: listClass });
  const more = h("button", { class: "button show-more", type: "button" });
  let shown = 0;
  function grow() {
    const next = items.slice(shown, shown + pageSize);
    list.append(...next.map(renderItem));
    shown += next.length;
    const left = items.length - shown;
    more.hidden = left <= 0;
    more.textContent = `Show ${Math.min(pageSize, left)} more ${what}`;
    more.setAttribute("aria-label", `Show more ${what}: ${left} not shown yet`);
  }
  more.addEventListener("click", () => { grow(); more.blur(); });
  grow();
  return h("div", { class: "paged" }, list, items.length > pageSize ? h("p", { class: "paged-foot" },
    more, h("span", { class: "hint" }, ` ${items.length} in all`)) : null);
}

// Search box and choices above a list. ``choices`` are [name, label, [[value, text]...]];
// ``onChange`` receives {query, name: value...} and the URL keeps them for Back and reload.
function listControls(label, choices, onChange, initial = {}) {
  const values = { query: initial.query || "" };
  const search = h("input", { type: "search", value: values.query, placeholder: label, "aria-label": label });
  const selects = choices.map(([name, text, options]) => {
    values[name] = initial[name] || options[0][0];
    const select = h("select", { "aria-label": text },
      options.map(([value, optionText]) => h("option", { value, selected: value === values[name] }, optionText)));
    select.addEventListener("change", () => { values[name] = select.value; changed(); });
    return h("label", { class: "list-choice" }, h("span", { class: "visually-hidden" }, text), select);
  });
  let timer;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { values.query = search.value.trim(); changed(); }, 120);
  });
  function changed() {
    onChange({ ...values });
    const [path] = location.hash.split("?");
    const params = new URLSearchParams(Object.entries(values).filter(([, v]) => v));
    history.replaceState(null, "", `${path}${params.toString() ? `?${params}` : ""}`);
  }
  return { node: h("div", { class: "list-controls", role: "search" }, search, selects), values };
}

const matches = (query, ...texts) => !query || texts.some((t) => t && t.toLowerCase().includes(query.toLowerCase()));

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
      out.push(`<h${level} id="${slug(text)}" dir="auto">${inline(text)}</h${level}>`);
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
      out.push(`<${tag} dir="auto">${items.map((it) => `<li dir="auto">${inline(it)}</li>`).join("")}</${tag}>`);
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote dir="auto">${inline(quote.join(" "))}</blockquote>`);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|~~~|>)/.test(lines[i])
      && !isBullet(lines[i]) && !isNumbered(lines[i])) {
      para.push(lines[i++].trim());
    }
    out.push(`<p dir="auto">${inline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}

// Links from stored data are only rendered when they are web addresses.
function webLink(url) {
  return typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url) ? url : null;
}

// Turn "[2]" in an answer into a button, in text only: never inside a link, code or an
// attribute, which a string replacement over the HTML could not guarantee.
function addCitations(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement.closest("a, code, pre") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) {
    const parts = text.nodeValue.split(/\[(\d{1,2})\]/);
    if (parts.length === 1) continue;
    const pieces = parts.map((part, index) => (index % 2
      ? h("button", { type: "button", class: "cite", "data-n": part, "aria-label": `Source ${part}` }, part)
      : document.createTextNode(part)));
    text.replaceWith(...pieces);
  }
  return root;
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
  // The busiest threads first; the rest one click away, so the sidebar stays short.
  const topics = [...state.status.topics].sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0));
  let shownTopics = topics;
  if (!state.allTopics && topics.length > SIDEBAR_TOPICS) {
    shownTopics = topics.slice(0, SIDEBAR_TOPICS);
    if (state.topicFilter && !shownTopics.includes(state.topicFilter)) shownTopics.push(state.topicFilter);
  }
  fill(document.getElementById("thread-list"), shownTopics.map((name) =>
    h("li", {}, h("button", {
      type: "button",
      "aria-pressed": String(state.topicFilter === name),
      onclick: () => { state.topicFilter = state.topicFilter === name ? null : name; renderSidebar(); },
    }, h("span", { class: "swatch", vars: { "--thread": topicColor(name) } }), name,
    h("span", { class: "count" }, counts.get(name) || 0)))),
  topics.length > SIDEBAR_TOPICS ? h("li", { class: "see-all" }, h("button", {
    type: "button", "aria-expanded": String(Boolean(state.allTopics)),
    onclick: () => { state.allTopics = !state.allTopics; renderSidebar(); },
  }, state.allTopics ? "Show fewer topics" : `Show all ${topics.length} topics`)) : null);

  const visible = state.articles.filter((a) =>
    !state.topicFilter || a.topics.some((t) => t.name === state.topicFilter));
  renderNav();

  const list = document.getElementById("article-list");
  const current = currentArticleId();
  // The newest few, and the article open now if it's older; the Library page has the rest.
  const recent = visible.slice(0, SIDEBAR_ITEMS);
  const open = visible.find((a) => a.id === current);
  if (open && !recent.includes(open)) recent.push(open);
  const allHref = `#/library${state.topicFilter ? `?topic=${encodeURIComponent(state.topicFilter)}` : ""}`;
  const seeAll = visible.length > recent.length || state.articles.length > SIDEBAR_ITEMS
    ? h("li", { class: "see-all" }, h("a", { href: allHref },
      state.topicFilter ? `All ${visible.length} in ${state.topicFilter}` : `All writing (${visible.length})`)) : null;
  fill(list, (recent.length ? recent.map((a) => h("li", {},
    h("a", { href: `#/article/${encodeURIComponent(a.id)}`, "aria-current": a.id === current ? "page" : null },
      warp(a.topics),
      h("span", {}, h("span", { class: "title", dir: "auto" }, a.title), h("span", { class: "meta" },
        [a.kind === "post" ? "Post" : null, formatDate(a.published_on),
          a.series && `${a.series}${a.series_part ? `, part ${a.series_part}` : ""}`]
          .filter(Boolean).join(", ") || "Undated")))))
    : [h("li", { class: "empty" }, state.topicFilter ? "Nothing in this thread yet." : "No articles or posts yet.")]), seeAll);
}

const SIDEBAR_TOPICS = 12;
const SIDEBAR_ITEMS = 25;

const NAV = {
  home: { icon: "home", label: "Home", active: (hash) => hash === "#/" || hash === "" },
  library: { icon: "article", label: "Library", active: (hash) => hash.startsWith("#/library") || hash.startsWith("#/article/") },
  add: { icon: "plus", label: "Add", active: (hash) => hash.startsWith("#/add") },
  graph: { icon: "graph", label: "Graph", active: (hash) => hash === "#/graph" },
  people: { icon: "people", label: "People", active: (hash) => hash.startsWith("#/people") || hash.startsWith("#/person/") },
  mentions: { icon: "tag", label: "Mentions", active: (hash) => hash.startsWith("#/mentions") || hash.startsWith("#/entity/") },
  settings: { icon: "settings", label: "Settings", active: (hash) => hash === "#/settings" },
};

function renderNav() {
  const hash = location.hash || "#/";
  document.getElementById("quit").hidden = !(state.status && state.status.can_quit);
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
        h("p", {}, "Paste your LinkedIn articles and posts. postloom restores the formatting, files them under your topics, links them to the people who discuss them, and lets you ask about everything you've written.")),
      keyNotice(),
      h("div", { class: "empty-state" },
        h("h2", {}, configured ? "Add your first article or post" : "Connect a model, then add your writing"),
        h("p", {}, configured
          ? "Copy an article or a post from LinkedIn and paste it in. An article takes about half a minute; a post a few seconds."
          : "postloom works with Gemini, Claude, OpenAI, OpenRouter, or free local models with Ollama. Bring your own key; it stays on this computer."),
        h("div", { class: "actions" },
          configured ? null : h("a", { class: "button button-primary", href: "#/settings" }, "Connect a provider"),
          h("a", { class: configured ? "button button-primary" : "button", href: "#/add" }, icon("plus"), "Add an article"),
          h("a", { class: "button", href: "#/add/post" }, icon("plus"), "Add a post")))));
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
        h("q", { dir: "auto" }, w.text),
        h("a", { class: "link-button", href: `#/article/${encodeURIComponent(w.article_id)}?comment=${encodeURIComponent(w.comment_id)}&reply=1` },
          icon("reply"), "Draft reply"))))
    : h("p", { class: "hint" }, overview.messages
      ? "You've answered everyone. Paste new comments from an article's page when there are more."
      : "No comments saved yet. Open an article or post and paste its comment section to see who's talking.");

  setMain(h("section", { class: "dashboard" },
    h("div", { class: "dash-head" }, weaveAll(),
      h("h1", {}, "Home"),
      h("p", {}, `${plural(overview.articles, "article", "articles")}${overview.posts ? `, ${plural(overview.posts, "post", "posts")}` : ""}, ${plural(overview.messages, "message", "messages")} from ${plural(overview.people, "person", "people")}.`)),
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
          h("h2", { id: "articles-heading" }, "Your writing",
            state.articles.length > HOME_ITEMS ? h("a", { href: "#/library" }, `See all ${state.articles.length}`) : h("a", { href: "#/add" }, "Add")),
          h("ul", { class: "article-rows" }, state.articles.slice(0, HOME_ITEMS).map(articleRow)))),
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

const HOME_ITEMS = 8;

function articleRow(a) {
  return h("li", {},
    h("a", { class: "article-row", href: `#/article/${encodeURIComponent(a.id)}` }, warp(a.topics),
      h("div", {}, h("h3", { dir: "auto" }, a.title), a.summary ? h("p", { dir: "auto" }, a.summary) : null,
        h("p", { class: "row-meta" }, [a.kind === "post" ? "Post" : "Article", formatDate(a.published_on),
          a.topics.map((t) => t.name).join(", ")].filter(Boolean).join(" \u00b7 ")))));
}

// Everything written, findable: search, narrow by kind and topic, sort, a page at a time.
function libraryView(initial) {
  const topics = [...new Set(state.articles.flatMap((a) => a.topics.map((t) => t.name)))]
    .sort((a, b) => a.localeCompare(b));
  const results = h("div", { class: "library-results" });
  const summary = h("p", { class: "hint", role: "status" });
  const controls = listControls("Search titles and summaries", [
    ["kind", "Kind", [["", "Articles and posts"], ["article", "Articles"], ["post", "Posts"]]],
    ["topic", "Topic", [["", "Every topic"], ...topics.map((t) => [t, t])]],
    ["sort", "Sort", [["", "Newest first"], ["oldest", "Oldest first"], ["title", "By title"]]],
  ], draw, initial);
  function draw({ query, kind, topic, sort }) {
    let shown = state.articles.filter((a) => (!kind || (a.kind || "article") === kind)
      && (!topic || a.topics.some((t) => t.name === topic))
      && matches(query, a.title, a.summary, a.series));
    if (sort === "oldest") shown = [...shown].reverse();
    if (sort === "title") shown = [...shown].sort((a, b) => a.title.localeCompare(b.title));
    summary.textContent = shown.length === state.articles.length ? `${plural(shown.length, "item")}`
      : `${shown.length} of ${state.articles.length}`;
    fill(results, shown.length
      ? pagedList(shown, articleRow, { listClass: "article-rows", what: "items" })
      : h("p", { class: "hint" }, state.articles.length ? "Nothing matches. Try fewer words or another topic." : "Nothing here yet."));
  }
  draw(controls.values);
  setMain(h("section", { class: "page library-page" },
    h("div", { class: "section-head" }, h("h1", {}, "Library"),
      h("a", { class: "button", href: "#/add" }, icon("plus"), "Add")),
    h("p", { class: "lede" }, "Every article and post you saved."),
    controls.node, summary, results));
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
      : "Connect a model provider to add articles, chat and draft replies. Posts can be added without one. Gemini, Claude, OpenAI, OpenRouter, or free local models with Ollama.",
      h("a", { href: "#/settings" }, "Open settings"));
  }
  if (s.embeddings.needs_reindex) {
    return notice("", "Your search model changed. Rebuild the search index so search by meaning works again.",
      h("a", { href: "#/settings" }, "Open settings"));
  }
  return null;
}

function addKinds(current) {
  const link = (kind, href, label) => h("a", { href, "aria-current": kind === current ? "page" : null }, label);
  return h("nav", { class: "add-kinds", "aria-label": "What to add" },
    link("article", "#/add", "Article"), link("post", "#/add/post", "Post"));
}

function addPostView() {
  const form = h("form", { class: "page", onsubmit: submitPost },
    addKinds("post"),
    h("h1", {}, "Add a post"),
    h("p", { class: "lede" }, "For a post that stands on its own. If the post shares one of your articles, add both together under Article instead."),
    h("div", { id: "add-result" }),
    field("text", "The post", h("textarea", { id: "text", name: "text", required: true, rows: 10, dir: "auto",
      placeholder: "Paste the post here, with its hashtags.\n\ne.g.\nThree things I learned shipping our first AI agent...\n\n#AI #Agents" }),
    "On LinkedIn, open your post, click \u2026see more so the whole text shows, then copy it and paste it here. Bold or fancy letters are fine. Adding the same post again later updates it."),
    optionalDetails("They let you jump back to LinkedIn and sort your writing by date.",
      h("div", { class: "field-row" },
        field("url", "Link to the post", h("input", { id: "url", name: "url", type: "url", placeholder: "https://www.linkedin.com/posts/..." }),
          "Copy it from your browser's address bar while the post is open."),
        field("published_on", "Published on", h("input", { id: "published_on", name: "published_on", type: "date" }),
          "The day you posted it."))),
    h("div", { class: "form-submit" },
      h("button", { class: "button button-primary", type: "submit", id: "add-submit" }, "Add post"),
      nextSteps("Next, postloom picks its topics and shows the people, organisations and links it names, for you to confirm.")));
  setMain(form);
}

async function submitPost(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const body = { text: data.text, url: data.url || null, published_on: data.published_on || null };
  const button = document.getElementById("add-submit");
  const result = document.getElementById("add-result");
  button.disabled = true;
  button.textContent = "Saving the post...";
  result.replaceChildren();
  try {
    const added = await api("/api/posts", { method: "POST", body });
    await refresh();
    const lines = [`${added.is_update ? "Updated" : "Added"} "${added.title}".`];
    if (added.topics.length) lines.push(`Topics: ${added.topics.join(", ")}.`);
    for (const warning of added.warnings) lines.push(warning);
    if (added.index_error) lines.push(`Saved, but not indexed for search: ${added.index_error}`);
    result.replaceChildren(notice("", ...lines,
      lookForMentions(added.id, "post"),
      h("a", { href: `#/article/${encodeURIComponent(added.id)}` }, "Open the post")));
    form.reset();
    toast(added.is_update ? "Post updated" : "Post added");
  } catch (error) {
    result.replaceChildren(notice("error", error.message));
  } finally {
    button.disabled = false;
    button.textContent = "Add post";
    result.scrollIntoView({ block: "nearest" });
  }
}

// Right after adding, look for what the text names; the user reviews it on the item's page.
function lookForMentions(id, what) {
  const line = h("p", { class: "hint", role: "status" }, "Looking for people, organisations, links and more...");
  api("/api/mentions/find", { method: "POST", body: { id } }).then((found) => {
    const n = found.suggestions.length + found.topics.length;
    line.textContent = n
      ? `Found ${plural(n, "thing")} to review: open the ${what} to choose what goes into your graph.`
      : "Nothing to review in it.";
  }).catch((error) => {
    line.textContent = `Couldn't look for mentions: ${error.message} You can try again on the ${what}'s page.`;
  });
  return line;
}

function addView() {
  const form = h("form", { class: "page", onsubmit: submitArticle },
    addKinds("article"),
    h("h1", {}, "Add an article"),
    h("p", { class: "lede" }, "An article is the long piece you published on LinkedIn; it comes with the short post you shared it in. Paste both, in two steps."),
    keyNotice(),
    h("div", { id: "add-result" }),
    field("article_text", "The article", h("textarea", { id: "article_text", name: "article_text", required: true, rows: 12, dir: "auto",
      placeholder: "Paste the whole article here: its title first, then everything under it." }),
    `On LinkedIn, open the article, click anywhere in its text, press ${selectAllKeys()} to select it all, copy and paste it here. It may look messy: postloom restores the headings, lists and code.`,
    { step: 1 }),
    field("post_text", "The post that shared it", h("textarea", { id: "post_text", name: "post_text", required: true, rows: 6, dir: "auto",
      placeholder: "e.g.\nNew article: how we cut our LLM bill in half without losing quality.\n\n#LLM #RAG" }),
    "The short post on your feed that links to the article. Copy its text with the hashtags: its comments will be read from there.",
    { step: 2 }),
    optionalDetails("They let you jump back to LinkedIn and sort your writing by date. Copy a link from your browser's address bar while the page is open.",
      h("div", { class: "field-row" },
        field("article_url", "Link to the article", h("input", { id: "article_url", name: "article_url", type: "url", placeholder: "https://www.linkedin.com/pulse/..." })),
        field("post_url", "Link to the post", h("input", { id: "post_url", name: "post_url", type: "url", placeholder: "https://www.linkedin.com/posts/..." }))),
      field("published_on", "Published on", h("input", { id: "published_on", name: "published_on", type: "date" }))),
    h("div", { class: "form-submit" },
      h("button", { class: "button button-primary", type: "submit", id: "add-submit" }, "Add article"),
      nextSteps("Next, postloom restores the formatting, picks its topics and shows the people, organisations and links it names, for you to confirm. It can take a minute.")));
  setMain(form);
}

function field(id, label, control, hint, { step = null, optional = false } = {}) {
  // What to write comes before the box, where it is read first.
  if (hint) control.setAttribute("aria-describedby", `${id}-hint`);
  return h("div", { class: `field${step ? " step" : ""}` },
    h("label", { for: id }, step ? h("span", { class: "step-number", "aria-hidden": "true" }, step) : null, label,
      optional ? h("span", { class: "optional" }, "optional") : null),
    hint ? h("p", { class: "hint", id: `${id}-hint` }, hint) : null,
    control);
}

const selectAllKeys = () => (/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "\u2318A" : "Ctrl+A");

// Fields that help but aren't needed, folded under one heading.
function optionalDetails(summary, ...fields) {
  return h("fieldset", { class: "details-group" },
    h("legend", {}, "Details ", h("span", { class: "optional" }, "optional")),
    h("p", { class: "hint" }, summary), ...fields);
}

function nextSteps(text) {
  return h("p", { class: "hint next-steps" }, text);
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
      lookForMentions(added.id, "article"),
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
  if (article.kind === "post") return postView(article, focus);
  const series = article.series ? `${article.series}${article.series_part ? `, part ${article.series_part}` : ""}` : null;
  const byline = [formatDate(article.published_on), series].filter(Boolean).join(". ");
  const reader = h("article", { class: "reader" },
    weave(article.topics),
    h("h1", { dir: "auto" }, article.title),
    h("p", { class: "byline" }, byline || "Undated",
      webLink(article.url) ? [" ", h("a", { href: webLink(article.url), target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn")] : null),
    tagList(article.topics),
    articleActions(article),
    article.summary ? h("p", { class: "summary", dir: "auto" }, article.summary) : null,
    htmlBlock("prose", markdown(article.body_markdown)),
    article.posts.map((post) => h("section", { class: "post", "aria-label": "Announcement post" },
      h("h2", {}, "Announcement post"), h("p", { dir: "auto", class: "post-text" }, post.text))),
    relatedSection(article),
    mentionsSection(article),
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

function postView(post, focus) {
  const reader = h("article", { class: "reader" },
    weave(post.topics),
    h("p", { class: "eyebrow" }, "Post"),
    h("h1", { dir: "auto" }, post.title),
    h("p", { class: "byline" }, formatDate(post.published_on) || "Undated",
      webLink(post.url) ? [" ", h("a", { href: webLink(post.url), target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn")] : null),
    tagList(post.topics),
    articleActions(post),
    h("section", { class: "post standalone", "aria-label": "Post" },
      h("p", { dir: "auto", class: "post-text" }, withoutTitle(post.body_markdown, post.title))),
    mentionsSection(post),
    discussionSection(post));
  const suggestions = post.discussion.length
    ? ["What did people ask in the comments?", "Which questions did I not answer yet?", "What did people disagree with?"]
    : ["Summarize this post", "What is the main claim?", "Suggest a follow-up post"];
  setMain(h("div", { class: "article-layout" }, reader,
    chatPanel(post.id, "Ask about this post",
      "Answers come only from this post and its comments.", suggestions)));
  renderSidebar();
  if (focus.comment) focusComment(focus.comment, focus.reply);
}

function withoutTitle(text, title) {
  // The title is the post's first line, so don't show that line twice.
  const lines = text.split("\n");
  const first = lines.findIndex((line) => line.trim());
  const shown = title.replace(/\.\.\.$/, "");
  if (first < 0 || title.endsWith("...") || !lines[first].includes(shown)) return text;
  return lines.slice(first + 1).join("\n").replace(/^\s*\n/, "");
}

// ---------------------------------------------------------------------------- mentions
const CATEGORIES = [
  ["person", "People", "Person"],
  ["organisation", "Organisations", "Organisation"],
  ["place", "Places", "Place"],
  ["event", "Events", "Event"],
  ["project", "Projects and products", "Project or product"],
  ["dataset", "Datasets", "Dataset"],
  ["method", "Methods and techniques", "Method or technique"],
  ["link", "Links", "Link"],
  ["other", "Other", "Other"],
];
const categoryName = (key, plural = false) => (CATEGORIES.find((c) => c[0] === key) || [key, key, key])[plural ? 1 : 2];
const mentionHref = (id) => id.startsWith("person:") ? `#/person/${encodeURIComponent(id)}` : `#/entity/${encodeURIComponent(id)}`;

function categorySelect(value, id) {
  return h("select", { id, "aria-label": "Category" },
    CATEGORIES.map(([key, , one]) => h("option", { value: key, selected: key === value }, one)));
}

function byCategory(rows, keyOf) {
  return CATEGORIES.map(([key, plural]) => [key, plural, rows.filter((r) => keyOf(r) === key)])
    .filter(([, , group]) => group.length);
}

// What an article or post names: confirmed mentions, and anything found waiting for review.
function mentionsSection(item) {
  const what = item.kind === "post" ? "post" : "article";
  const section = h("section", { class: "mentions", "aria-labelledby": "mentions-heading" },
    h("h2", { id: "mentions-heading" }, "Mentioned"), h("p", { class: "hint" }, "Loading..."));
  async function load() {
    let data;
    try {
      data = await api(`/api/mentions?id=${encodeURIComponent(item.id)}`);
    } catch (error) {
      return fill(section, h("h2", { id: "mentions-heading" }, "Mentioned"), notice("error", error.message));
    }
    const review = data.review && (data.review.suggestions.length || data.review.topics.length) ? data.review : null;
    const find = h("button", { class: "button", type: "button", onclick: async () => {
      find.disabled = true;
      find.textContent = data.can_find ? "Reading the text..." : "Looking for links...";
      try {
        const found = await api("/api/mentions/find", { method: "POST", body: { id: item.id } });
        if (!found.suggestions.length && !found.topics.length) toast("Nothing new found");
        load();
      } catch (error) {
        find.disabled = false;
        find.textContent = "Try again";
        toast(error.message);
      }
    } }, icon("search"), data.mentions.length || data.review ? "Find again" : "Find people, organisations and more");
    const confirmed = data.mentions.length
      ? byCategory(data.mentions, (m) => m.category).map(([, plural, group]) =>
        h("div", { class: "mention-group" }, h("h3", {}, plural),
          h("ul", { class: "mention-chips" }, group.map((m) => h("li", {},
            h("a", { href: mentionHref(m.target), title: m.evidence || "", dir: "auto" }, m.name),
            h("button", { class: "chip-remove", type: "button", "aria-label": `Remove ${m.name} from this ${what}`,
              title: `Not mentioned in this ${what}`,
              onclick: async () => {
                try {
                  await api(`/api/mention?item=${encodeURIComponent(item.id)}&target=${encodeURIComponent(m.target)}`, { method: "DELETE" });
                  load();
                } catch (error) {
                  toast(error.message);
                }
              } }, "\u00d7"))))))
      : review ? null : h("p", { class: "hint" }, `People, organisations, places, events, datasets and links named in this ${what} appear here once you confirm them.`);
    fill(section,
      h("div", { class: "section-head" }, h("h2", { id: "mentions-heading" }, "Mentioned"), review ? null : find),
      review ? reviewPanel(item, review, data.can_find, load) : null,
      confirmed,
      !data.can_find && !review ? h("p", { class: "hint" }, "Without a model, postloom finds links only. Connect one in Settings to find people and organisations too.") : null);
  }
  load();
  return section;
}

function reviewPanel(item, review, canFind, done) {
  const what = item.kind === "post" ? "post" : "article";
  const rows = review.suggestions.map((s, index) => {
    const id = `m${index}`;
    const keep = h("input", { type: "checkbox", checked: true, "aria-label": `Add ${s.name}` });
    const name = h("input", { type: "text", value: s.name, dir: "auto", maxlength: 300, "aria-label": "Name" });
    const category = categorySelect(s.category, `${id}-category`);
    const same = s.match ? h("input", { type: "checkbox", checked: true, id: `${id}-same` }) : null;
    const row = h("li", { class: "review-row" },
      h("div", { class: "review-main" }, keep, name, category),
      s.match ? h("label", { class: "review-match", for: `${id}-same` }, same,
        ` Same as ${s.match_name}`, s.match_note ? h("span", { class: "hint" }, ` (${s.match_note})`) : null) : null,
      s.evidence ? h("blockquote", { class: "review-evidence", dir: "auto" }, s.evidence) : null,
      s.url && s.url !== `https://${s.name}` ? h("p", { class: "hint" }, s.url) : null);
    keep.addEventListener("change", () => { row.classList.toggle("off", !keep.checked); count(); });
    return { s, row, keep, name, category, same };
  });
  const topicRows = review.topics.map((t) => {
    const keep = h("input", { type: "checkbox", checked: t.exists, "aria-label": `Add the topic ${t.name}` });
    keep.addEventListener("change", count);
    return { t, keep, row: h("li", { class: "review-row" }, h("label", { class: "review-main" }, keep, " ", t.name,
      t.exists ? null : h("span", { class: "badge" }, "new topic"))) };
  });
  const add = h("button", { class: "button button-primary", type: "button" });
  function count() {
    const n = rows.filter((r) => r.keep.checked).length + topicRows.filter((r) => r.keep.checked).length;
    add.textContent = n ? `Add ${n} to your graph` : "Save (add nothing)";
  }
  add.addEventListener("click", async () => {
    add.disabled = true;
    const body = {
      id: item.id,
      accept: rows.filter((r) => r.keep.checked).map((r) => ({
        name: r.name.value.trim(),
        category: r.category.value,
        evidence: r.s.evidence || "",
        url: r.s.url,
        match: r.same && r.same.checked ? r.s.match : null,
        found_as: r.s.name,
      })),
      dismiss: rows.filter((r) => !r.keep.checked).map((r) => r.s.name),
      topics: topicRows.filter((r) => r.keep.checked).map((r) => r.t.name),
    };
    try {
      const result = await api("/api/mentions/confirm", { method: "POST", body });
      toast(result.added.length || result.topics.length ? "Added to your graph" : "Saved");
      if (result.topics.length) {
        await refresh();
        return articleView(item.id);  // the topics shown at the top changed too
      }
      done();
    } catch (error) {
      add.disabled = false;
      toast(error.message);
    }
  });
  count();
  const grouped = byCategory(rows, (r) => r.s.category);
  return h("div", { class: "review", role: "group", "aria-label": `Found in this ${what}` },
    h("h3", {}, `Found in this ${what}`),
    h("p", { class: "hint" }, "Untick what doesn't belong, fix a name or its category, then add the rest. Nothing goes into your graph before you do."),
    grouped.map(([, plural, group]) => h("div", { class: "review-group" }, h("h4", {}, plural),
      h("ul", {}, group.map((r) => r.row)))),
    topicRows.length ? h("div", { class: "review-group" }, h("h4", {}, "Topics"), h("ul", {}, topicRows.map((r) => r.row))) : null,
    review.finder ? null : h("p", { class: "hint" }, canFind ? "" : "Only links were looked for: no model is connected."),
    h("div", { class: "editor-actions" }, add,
      h("button", { class: "button", type: "button", onclick: (event) => { event.currentTarget.closest(".review").remove(); } }, "Decide later")));
}

function mentionList(rows) {
  return pagedList(rows, (m) => h("li", {},
    h("a", { href: `#/article/${encodeURIComponent(m.id)}`, dir: "auto" }, m.title),
    h("span", { class: "hint" }, ` ${[m.kind === "post" ? "Post" : "Article", formatDate(m.published_on)].filter(Boolean).join(", ")}`),
    m.evidence ? h("blockquote", { class: "review-evidence", dir: "auto" }, m.evidence) : null),
  { pageSize: 20, listClass: "mention-list", what: "mentions" });
}

const GROUP_CHIPS = 24;

async function mentionsView(initial = {}) {
  const { entities, pending } = await api("/api/entities");
  const present = CATEGORIES.filter(([key]) => entities.some((e) => e.category === key));
  const list = h("div", {});
  const controls = listControls("Search names", [
    ["category", "Category", [["", "Every category"], ...present.map(([key, many]) => [key, many])]],
    ["sort", "Sort", [["", "Most mentioned"], ["name", "By name"]]],
  ], draw, initial);
  function draw({ query, category, sort }) {
    const shown = entities.filter((e) => (!category || e.category === category) && matches(query, e.name, ...e.aliases))
      .sort(sort === "name" ? (a, b) => a.name.localeCompare(b.name) : (a, b) => b.count - a.count || a.name.localeCompare(b.name));
    // A category shows its most mentioned names first; the rest open on request.
    const folded = !query && !category;
    fill(list, shown.length
      ? byCategory(shown, (e) => e.category).map(([key, many, group]) => {
        const chips = h("ul", { class: "mention-chips" });
        const chip = (e) => h("li", {}, h("a", { href: `#/entity/${encodeURIComponent(e.id)}`, dir: "auto" }, e.name,
          h("span", { class: "count" }, ` ${e.count}`)));
        const first = folded ? group.slice(0, GROUP_CHIPS) : group;
        chips.append(...first.map(chip));
        const rest = group.length - first.length;
        const more = rest > 0 ? h("button", { class: "link-button", type: "button", onclick: () => {
          chips.append(...group.slice(first.length).map(chip));
          more.remove();
        } }, `Show all ${group.length}`) : null;
        return h("section", { class: "mention-group", "data-category": key },
          h("h2", {}, `${many} (${group.length})`), chips, more);
      })
      : h("p", { class: "hint" }, entities.length ? "Nothing matches." : "Nothing yet. Open an article or post and choose Find people, organisations and more, or add a new one: postloom looks right after adding it."));
  }
  draw(controls.values);
  const filter = controls.node;
  setMain(h("section", { class: "page" },
    h("h1", {}, "Mentions"),
    h("p", { class: "lede" }, "The organisations, places, events, projects, datasets, methods and links your writing mentions, as you confirmed them. People are on the People page."),
    pending.length ? h("div", { class: "notice" },
      h("p", {}, h("strong", {}, `Waiting for your review (${pending.length})`)),
      pagedList(pending, (p) => h("li", {},
        h("a", { href: `#/article/${encodeURIComponent(p.id)}`, dir: "auto" }, p.title),
        ` ${plural(p.count, "suggestion")}`), { pageSize: 10, what: "to review" })) : null,
    entities.length > 8 ? filter : null,
    list));
}

async function entityView(id) {
  let e;
  try {
    e = await api(`/api/entity?id=${encodeURIComponent(id)}`);
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Not found"),
      notice("error", error.message), h("a", { href: "#/mentions" }, "Back to mentions")));
  }
  const { entities } = await api("/api/entities");
  const name = h("input", { id: "entity_name", value: e.name, maxlength: 300, dir: "auto" });
  const category = categorySelect(e.category, "entity_category");
  const url = h("input", { id: "entity_url", type: "url", value: e.url || "", maxlength: 2000, placeholder: "https://..." });
  const others = entities.filter((o) => o.id !== e.id)
    .sort((a, b) => (a.category === e.category ? 0 : 1) - (b.category === e.category ? 0 : 1) || a.name.localeCompare(b.name));
  const into = h("select", { id: "merge_into" }, h("option", { value: "" }, "Choose..."),
    others.map((o) => h("option", { value: o.id }, `${o.name} (${categoryName(o.category)})`)));
  const save = h("button", { class: "button button-primary", type: "submit" }, "Save");
  const form = h("form", { class: "editor", "aria-label": "Edit this entry", onsubmit: async (event) => {
    event.preventDefault();
    save.disabled = true;
    try {
      await api("/api/entity", { method: "PUT", body: { id: e.id, name: name.value.trim(), category: category.value, url: url.value.trim() || null } });
      toast("Saved");
      entityView(e.id);
    } catch (error) {
      save.disabled = false;
      toast(error.message);
    }
  } },
    h("div", { class: "field-row" }, field("entity_name", "Name", name), field("entity_category", "Category", category)),
    field("entity_url", "Link (optional)", url),
    h("div", { class: "editor-actions" }, save),
    h("p", { class: "hint" }, "Renaming keeps every link to it; the old name is kept as another name it's known by."));
  const merge = h("button", { class: "button", type: "button", onclick: async () => {
    if (!into.value) return toast("Choose an entry to merge into");
    merge.disabled = true;
    try {
      await api("/api/entity/merge", { method: "POST", body: { id: e.id, into: into.value } });
      toast("Merged");
      location.hash = `#/entity/${encodeURIComponent(into.value)}`;
    } catch (error) {
      merge.disabled = false;
      toast(error.message);
    }
  } }, "Merge");
  setMain(h("section", { class: "page" },
    h("p", { class: "eyebrow" }, categoryName(e.category)),
    h("h1", { dir: "auto" }, e.name),
    h("p", { class: "byline" }, `Mentioned in ${plural(e.mentions.length, "article or post", "articles and posts")}. `,
      webLink(e.url) ? h("a", { href: webLink(e.url), target: "_blank", rel: "noopener noreferrer" }, "Open link") : null),
    e.aliases.length ? h("p", { class: "hint" }, `Also known as: ${e.aliases.join(", ")}`) : null,
    h("div", { class: "person-section" }, h("h2", {}, "Where you mention it"),
      e.mentions.length ? mentionList(e.mentions) : h("p", { class: "hint" }, "Nowhere any more.")),
    h("div", { class: "person-section" }, h("h2", {}, "Edit"), form),
    others.length ? h("div", { class: "person-section" }, h("h2", {}, "Merge into another entry"),
      h("p", { class: "hint" }, "When two entries are the same thing, merge this one into the other. Its mentions move there and its names are kept."),
      h("div", { class: "inline-field" }, h("label", { class: "visually-hidden", for: "merge_into" }, "Merge into"), into, merge)) : null,
    h("div", { class: "person-section danger-zone" }, h("h2", {}, "Delete"),
      confirmBox("Delete", `Delete ${e.name} and every mention of it? Your articles and posts are not changed.`, "Delete", async () => {
        await api(`/api/entity?id=${encodeURIComponent(e.id)}`, { method: "DELETE" });
        toast("Deleted");
        location.hash = "#/mentions";
      }))));
  renderSidebar();
}

// ---------------------------------------------------------------------------- edit / delete an article
function articleActions(article) {
  const panel = h("div", { class: "article-edit" });
  const comments = article.discussion.length;
  const isPost = article.kind === "post";
  const what = isPost ? "this post" : `"${article.title}", its post`;
  const remove = confirmBox("Delete",
    `Delete ${what}${comments ? ` and ${plural(comments, "comment")}` : ""}? People you talked to are kept. This can't be undone.`,
    isPost ? "Delete post" : "Delete article", async () => {
      await api(`/api/${isPost ? "post" : "article"}?id=${encodeURIComponent(article.id)}`, { method: "DELETE" });
      state.chats.delete(article.id);
      await refresh();
      toast(isPost ? "Post deleted" : "Article deleted");
      location.hash = "#/";
    });
  const edit = h("button", { class: "button", type: "button", "aria-expanded": "false",
    onclick: () => {
      const open = panel.childElementCount > 0;
      edit.setAttribute("aria-expanded", String(!open));
      if (open) panel.replaceChildren();
      else (isPost ? postEditor : articleEditor)(article, panel, () => { panel.replaceChildren(); edit.setAttribute("aria-expanded", "false"); });
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

async function postEditor(post, panel, close) {
  fill(panel, h("p", { class: "hint" }, "Loading your topics…"));
  let topics;
  try {
    ({ topics } = await api("/api/topics"));
  } catch (error) {
    return fill(panel, notice("error", error.message));
  }
  const chosen = new Set(post.topics.map((t) => t.name));
  const date = h("input", { id: "edit_date", type: "date", value: post.published_on || "" });
  const url = h("input", { id: "edit_url", type: "url", value: post.url || "", maxlength: 2000, placeholder: "https://www.linkedin.com/posts/..." });
  const picker = h("fieldset", { class: "topic-picker" },
    h("legend", {}, "Topics"),
    topics.map((t) => h("label", { class: "chip" },
      h("input", { type: "checkbox", value: t.name, checked: chosen.has(t.name) }),
      h("span", { class: "swatch", vars: { "--thread": topicColor(t.name) } }), t.name)),
    h("p", { class: "hint" }, "Add, rename or remove topics in ", h("a", { href: "#/settings" }, "Settings"), "."));
  const status = h("p", { class: "hint", role: "status" });
  const save = h("button", { class: "button button-primary", type: "submit" }, "Save changes");
  const form = h("form", { class: "editor", "aria-label": "Edit post details",
    onsubmit: async (event) => {
      event.preventDefault();
      save.disabled = true;
      status.textContent = "Saving…";
      const body = {
        id: post.id,
        topics: [...picker.querySelectorAll("input:checked")].map((box) => box.value),
        published_on: date.value || null,
        url: url.value.trim() || null,
      };
      try {
        await api("/api/post", { method: "PUT", body });
        await refresh();
        toast("Post updated");
        articleView(post.id);
      } catch (error) {
        save.disabled = false;
        fill(status, notice("error", error.message));
      }
    } },
    picker,
    h("div", { class: "field-row" },
      field("edit_date", "Published", date),
      field("edit_url", "LinkedIn link", url)),
    h("div", { class: "editor-actions" }, save,
      h("button", { class: "button", type: "button", onclick: close }, "Cancel")),
    status,
    h("p", { class: "hint" }, "To change the post's text, edit its note in your vault; postloom reads the change."));
  fill(panel, form);
  picker.querySelector("input")?.focus();
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
  const others = state.articles.filter((a) => a.id !== article.id && a.kind !== "post");
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
    h("p", { class: "section-hint" }, "Your other articles on the same subject. Keep the suggestions that fit, or link one yourself."),
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
    : "Paste the comments from LinkedIn to see who engages with this, what they ask, and to draft your replies.";
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
    h("p", { class: "comment-text", dir: "auto" }, comment.text),
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
  const text = h("textarea", { id, dir: "auto", rows: Math.min(12, Math.max(4, Math.ceil(draft.text.length / 70))) });
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
  const textarea = h("textarea", { id: "comments-paste", rows: 10, required: true, dir: "auto",
    placeholder: "Paste the comment section here: names, headlines and messages, as LinkedIn shows them." });
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
      "On LinkedIn, open the post, click \u201cLoad more comments\u201d and every \u201cSee replies\u201d until all show. Then select from the first commenter's name down to the last message, copy and paste it here. Include your own replies; pasting again later adds only the new messages."),
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
          h("textarea", { rows: 3, dir: "auto", oninput: (e) => { d.text = e.target.value; } }, d.text)),
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
    spec.local ? ollamaSetup(urlInput, (model) => {
      for (const input of form.querySelectorAll("input[data-task]")) {
        if (!input.disabled) input.value = model;
      }
      form.requestSubmit();
    }) : spec.notes.map((note) => h("p", { class: "hint" }, note)),
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

// Ollama without a terminal: install, start, pick a model that fits, download it, use it.
function ollamaSetup(urlInput, useModel) {
  const panel = h("div", { class: "ollama-setup", role: "status", "aria-live": "polite" },
    h("p", { class: "hint" }, "Checking Ollama on this computer..."));
  let timer = null;
  const later = (ms) => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (panel.isConnected) check(); }, ms);
  };
  const gb = (bytes) => (bytes / 2 ** 30).toFixed(1);
  const step = (title, ...body) => fill(panel, h("h3", {}, title), ...body);
  const act = (label, run, primary = true) => {
    const button = h("button", { class: `button${primary ? " button-primary" : ""}`, type: "button", onclick: async () => {
      button.disabled = true;
      try {
        await run();
      } catch (error) {
        button.disabled = false;
        toast(error.message);
      }
    } }, label);
    return button;
  };

  async function check() {
    let o;
    try {
      o = await api(`/api/ollama?url=${encodeURIComponent(urlInput.value.trim())}`);
    } catch (error) {
      return fill(panel, notice("error", error.message));
    }
    const d = o.download;
    if (d && !d.done) {
      const percent = d.total ? Math.floor((100 * d.completed) / d.total) : 0;
      step(`Downloading ${d.model}`,
        h("progress", { max: 100, value: percent, "aria-label": `Download progress of ${d.model}` }),
        h("p", { class: "hint" }, d.total
          ? `${percent}%: ${gb(d.completed)} of ${gb(d.total)} GB. You can keep using postloom; the download continues.`
          : d.status || "Starting..."));
      return later(1000);
    }
    if (!o.installed) {
      return step("1. Install Ollama",
        h("p", {}, "Ollama runs AI models on your own computer, for free; nothing you write leaves it. Install it like any other app, then come back here."),
        h("div", { class: "actions" },
          h("a", { class: "button button-primary", href: o.download_page, target: "_blank", rel: "noopener noreferrer" }, "Download Ollama"),
          act("I've installed it", check, false)));
    }
    if (!o.running) {
      return step("2. Start Ollama",
        h("p", {}, "Ollama is installed but not running."),
        h("div", { class: "actions" },
          act("Start Ollama", async () => {
            await api("/api/ollama/start", { method: "POST", body: {} });
            fill(panel, h("p", { class: "hint" }, "Starting Ollama..."));
            later(1500);
          }),
          act("Check again", check, false)));
    }
    const failed = d && d.error ? notice("error", `${d.model}: ${d.error}`) : null;
    const memory = o.memory_gb ? `This computer has ${o.memory_gb} GB of memory. ` : "";
    const others = o.models.filter((m) => !o.suggestions.some((s) => s.installed && (m === s.name || m === `${s.name}:latest`)));
    step("3. Choose a model",
      h("p", { class: "hint" }, `${memory}Bigger models answer better but need more memory and are slower. You can change this any time.`),
      failed,
      h("ul", { class: "model-choices" }, o.suggestions.map((s) => h("li", { class: s.recommended ? "recommended" : null },
        h("div", {},
          h("strong", {}, `${s.label}: ${s.name}`),
          s.recommended ? h("span", { class: "badge free" }, "Fits this computer") : null,
          h("p", { class: "hint" }, `${s.why} ${s.installed ? "Downloaded." : `Download about ${s.size_gb} GB.`}`)),
        s.installed
          ? act("Use this model", async () => useModel(s.name), s.recommended)
          : act(`Download`, async () => {
              await api("/api/ollama/pull", { method: "POST", body: { base_url: urlInput.value.trim() || null, model: s.name } });
              later(300);
            }, s.recommended)))),
      others.length ? h("div", { class: "field" },
        h("p", { class: "hint" }, "Or use a model you already have:"),
        h("div", { class: "actions" }, others.map((m) => act(m, async () => useModel(m), false)))) : null);
  }
  urlInput.addEventListener("change", check);
  check();
  return panel;
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
    e.mode === "local" ? languageChoice(e) : null,
    e.needs_reindex ? notice("", "Your search index was built with a different model, so search by meaning can't use it yet.", rebuild) : null,
    !e.available && e.mode !== "off" ? notice("error", "Embeddings aren't available right now, so search uses keywords only.") : null);
}

function languageChoice(e) {
  const options = [
    ["english", "English", "The default. Best for English, about 70 MB."],
    ["multilingual", "Many languages", "50+ languages, including Persian, Arabic, German, Spanish, Chinese and Hindi. About 220 MB."],
  ];
  const current = e.local_model === e.local_models.multilingual ? "multilingual" : "english";
  return h("fieldset", { class: "choice-list language-choice" },
    h("legend", {}, "Language of your writing"),
    options.map(([value, label, hint]) => h("label", { class: "choice" },
      h("input", { type: "radio", name: "search-language", value, checked: current === value,
        onchange: async () => {
          try {
            await api("/api/settings", { method: "PUT", body: { local_embedding_model: e.local_models[value] } });
            toast("Saved. Rebuild the search index to use it.");
            settingsView();
          } catch (error) {
            toast(error.message);
          }
        } }),
      h("span", {}, h("strong", {}, label), h("span", { class: "hint" }, ` ${hint}`)))));
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

function personRow(p) {
  return h("li", {},
    h("a", { class: "person-row", href: `#/person/${encodeURIComponent(p.id)}` }, avatar(p.name),
      h("div", {}, h("h2", {}, p.name, p.profile_url ? null : h("span", { class: "badge" }, "no profile link")),
        p.headline ? h("p", {}, p.headline) : null),
      h("span", { class: "count" }, `${p.messages} ${p.messages === 1 ? "message" : "messages"}`,
        h("br"), p.messages ? `${p.articles} ${p.articles === 1 ? "article" : "articles"}` : `mentioned in ${p.mentioned}`)));
}

const PEOPLE_SORTS = {
  "": (a, b) => b.messages - a.messages || b.articles - a.articles || a.name.localeCompare(b.name),
  mentioned: (a, b) => b.mentioned - a.mentioned || b.messages - a.messages || a.name.localeCompare(b.name),
  name: (a, b) => a.name.localeCompare(b.name),
};
const PEOPLE_FILTERS = {
  "": () => true,
  commented: (p) => p.messages > 0,
  mentioned: (p) => p.mentioned > 0,
  nolink: (p) => !p.profile_url,
};

async function peopleView(initial = {}) {
  const { people } = await api("/api/people");
  const page = h("section", { class: "page" },
    h("h1", {}, "People"),
    h("p", { class: "lede" }, people.length
      ? "Everyone who has commented on your posts, most engaged first, and the people you mention."
      : "No one yet. Open an article and add its comments to see who engages with your writing."));
  if (people.length) {
    const results = h("div", {});
    const summary = h("p", { class: "hint", role: "status" });
    const controls = listControls("Search names and headlines", [
      ["show", "Show", [["", "Everyone"], ["commented", "Commented"], ["mentioned", "You mention"], ["nolink", "No profile link"]]],
      ["sort", "Sort", [["", "Most engaged"], ["mentioned", "Most mentioned"], ["name", "By name"]]],
    ], draw, initial);
    function draw({ query, show, sort }) {
      const shown = people.filter((p) => (PEOPLE_FILTERS[show] || PEOPLE_FILTERS[""])(p) && matches(query, p.name, p.headline))
        .sort(PEOPLE_SORTS[sort] || PEOPLE_SORTS[""]);
      summary.textContent = shown.length === people.length ? plural(people.length, "person", "people") : `${shown.length} of ${people.length}`;
      fill(results, shown.length ? pagedList(shown, personRow, { listClass: "people-list", what: "people" })
        : h("p", { class: "hint" }, "No one matches."));
    }
    draw(controls.values);
    page.append(controls.node, summary, results);
  }
  setMain(page);
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
      webLink(person.profile_url) ? h("a", { href: webLink(person.profile_url), target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn") : null),

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

    person.mentioned_in.length ? h("div", { class: "person-section" },
      h("h2", {}, "You mention them in"),
      mentionList(person.mentioned_in)) : null,

    person.conversations.length ? null : h("div", { class: "person-section" }, h("h2", {}, "Conversations"),
      h("p", { class: "hint" }, `${firstName} hasn't commented on anything you saved.`)),
    h("div", { class: "person-section" },
      person.conversations.length ? h("h2", {}, "Conversations") : null,
      pagedList(person.conversations, (c) => h("div", { class: "conversation" },
        h("h3", {}, h("a", { href: `#/article/${encodeURIComponent(c.article_id)}` }, c.article_title)),
        threadsOf(c.messages).map((thread) => h("ol", { class: "thread" },
          thread.map((m) => commentRow(m, c.messages))))),
      { pageSize: 10, tag: "div", what: "conversations" })),

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
  const input = h("textarea", { "aria-label": "Your question", placeholder: "Ask a question", rows: 1, dir: "auto" });
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
  if (message.role === "user") return h("div", { class: "message user", dir: "auto" }, message.text);
  if (message.role === "error") return h("div", { class: "message error", role: "alert" }, message.text);
  if (message.pending) return h("div", { class: "message assistant pending" }, message.text);
  const body = addCitations(htmlBlock("message assistant", markdown(message.text)));
  const sources = message.sources || [];
  const here = currentArticleId();
  if (sources.length) {
    body.append(h("div", { class: "sources" }, sources.map((s) =>
      h("details", { "data-n": s.number },
        h("summary", {}, h("strong", {}, `[${s.number}] `),
          s.article_id && s.article_id === here ? s.section : `${s.title}: ${s.section}`),
        h("p", { class: "source-text", dir: "auto" }, s.text)))));
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

const GRAPH_BUDGET = 160;
const GRAPH_NEAR = 60;
const GRAPH_LABELS = 40;
const GRAPH_PERIODS = [["", "All time"], ["365", "Last 12 months"], ["90", "Last 3 months"]];
const isItem = (n) => n.kind === "article" || n.kind === "post";

function graphKindName(n) {
  if (isEntity(n)) return categoryName(n.kind);
  return { topic: "Topic", series: "Series", article: "Article", post: "Post", person: "Person" }[n.kind] || n.kind;
}

function graphHref(n) {
  if (isItem(n)) return `#/article/${encodeURIComponent(n.id)}`;
  if (n.kind === "person") return `#/person/${encodeURIComponent(n.id)}`;
  if (isEntity(n)) return `#/entity/${encodeURIComponent(n.id)}`;
  if (n.kind === "topic") return `#/library?topic=${encodeURIComponent(n.label)}`;
  return null;
}

async function graphView(initial = {}) {
  let graph;
  try {
    graph = await api("/api/graph");
  } catch (error) {
    return setMain(h("section", { class: "page" }, h("h1", {}, "Graph"), notice("error", error.message)));
  }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const options = {
    people: initial.people !== "0", mentions: initial.mentions !== "0", suggested: initial.suggested !== "0",
    period: GRAPH_PERIODS.some(([v]) => v === initial.period) ? initial.period : "",
    focus: byId.has(initial.focus) ? initial.focus : null,
  };
  const canvas = h("div", { class: "graph-canvas" });
  const card = h("div", { class: "graph-card", hidden: true, role: "region", "aria-label": "Selected node" });
  const note = h("p", { class: "graph-note", role: "status" });
  const remember = () => {
    const params = new URLSearchParams();
    if (options.focus) params.set("focus", options.focus);
    if (options.period) params.set("period", options.period);
    for (const key of ["people", "mentions", "suggested"]) if (!options[key]) params.set(key, "0");
    history.replaceState(null, "", `#/graph${params.toString() ? `?${params}` : ""}`);
  };
  const toggle = (key, label) => h("label", { class: "check" },
    h("input", { type: "checkbox", checked: options[key], onchange: (e) => { options[key] = e.target.checked; draw(); } }), label);

  // Find a node by name: articles, topics, people and everything mentioned.
  const names = new Map();
  for (const n of graph.nodes) names.set(`${n.label} (${graphKindName(n)})`, n.id);
  const choices = h("datalist", { id: "graph-names" }, [...names.keys()].sort((a, b) => a.localeCompare(b)).map((v) => h("option", { value: v })));
  const finder = h("input", { type: "search", list: "graph-names", placeholder: "Focus on an article, topic, person...",
    "aria-label": "Focus on", value: options.focus ? `${byId.get(options.focus).label} (${graphKindName(byId.get(options.focus))})` : "" });
  finder.addEventListener("change", () => {
    const id = names.get(finder.value) || [...names.entries()].find(([k]) => k.toLowerCase().startsWith(finder.value.trim().toLowerCase()))?.[1];
    if (finder.value.trim() && id) setFocus(id);
    else if (!finder.value.trim()) setFocus(null);
  });
  const period = h("select", { "aria-label": "Period", onchange: () => { options.period = period.value; draw(); } },
    GRAPH_PERIODS.map(([v, text]) => h("option", { value: v, selected: v === options.period }, text)));
  const clear = h("button", { class: "button", type: "button", onclick: () => setFocus(null) }, "Clear focus");

  function setFocus(id) {
    options.focus = id;
    finder.value = id ? `${byId.get(id).label} (${graphKindName(byId.get(id))})` : "";
    draw();
  }

  function select(n) {
    if (!n) { card.hidden = true; return; }
    const href = graphHref(n);
    fill(card,
      h("p", { class: "eyebrow" }, graphKindName(n)),
      h("h2", { dir: "auto" }, n.label),
      h("p", { class: "hint" }, [nodeTitle(n).replace(`${n.label}: `, ""), n.date ? formatDate(n.date) : null].filter(Boolean).join(", ")),
      h("div", { class: "graph-card-actions" },
        href ? h("a", { class: "button button-primary", href }, "Open") : null,
        options.focus === n.id ? null : h("button", { class: "button", type: "button", onclick: () => setFocus(n.id) }, "Focus here"),
        h("button", { class: "icon-button", type: "button", "aria-label": "Close", onclick: () => select(null) }, icon("close"))));
    card.hidden = false;
  }

  function draw() {
    remember();
    const shown = selectGraph(graph, options);
    clear.hidden = !options.focus;
    const total = shown.total;
    const focusName = options.focus ? byId.get(options.focus).label : "";
    note.textContent = !shown.nodes.length ? ""
      : options.focus
        ? `${focusName} and ${shown.nodes.length < total ? `the ${shown.nodes.length - 1} closest of ${total - 1}` : `all ${total - 1}`} connections around it.`
        : shown.nodes.length < total
          ? `Showing the ${shown.nodes.length} most connected of ${total}. Focus on an article, topic or person, or choose a shorter period, to see the rest.`
          : `Showing all ${total}.`;
    select(options.focus ? byId.get(options.focus) : null);
    canvas.replaceChildren(graphSvg(shown, options.focus, select));
  }

  const articles = graph.nodes.filter(isItem);
  setMain(h("section", { class: "graph-page" },
    h("h1", {}, "Graph"),
    h("p", { class: "lede" }, articles.length
      ? "Your articles and posts, their topics and series, the people who discussed them and what you mention. Drag to move around, scroll to zoom, select a node to see it or focus on it."
      : "Add an article or a post and its topics, links and commenters will appear here."),
    h("div", { class: "graph-controls" },
      h("div", { class: "list-controls graph-find" }, finder, choices, period, clear),
      toggle("people", "People"), toggle("mentions", "Mentions"), toggle("suggested", "Suggested links"),
      h("ul", { class: "graph-legend", "aria-label": "Legend" },
        h("li", {}, h("span", { class: "key key-topic" }), "Topic"),
        h("li", {}, h("span", { class: "key key-article" }), "Article"),
        h("li", {}, h("span", { class: "key key-post" }), "Post"),
        h("li", {}, svgEl("svg", { class: "key-person", viewBox: "-11 -11 22 22", "aria-hidden": "true" }, personGlyph(10)), "Person"),
        h("li", {}, h("span", { class: "key key-entity" }), "Mentioned"),
        h("li", {}, h("span", { class: "key key-linked" }), "Linked"),
        h("li", {}, h("span", { class: "key key-suggested" }), "Suggested"))),
    note,
    h("div", { class: "graph-stage" }, canvas, card),
    suggestionList(graph)));
  draw();
}

// What the graph shows: never more than GRAPH_BUDGET nodes, so it stays readable and quick
// however large the library grows. Without a focus, the most connected nodes; with one,
// that node, its neighbours and then theirs.
function selectGraph(graph, o) {
  const cutoff = o.period ? Date.now() - Number(o.period) * 86400000 : null;
  let nodes = graph.nodes.filter((n) => (o.people || n.kind !== "person") && (o.mentions || !isEntity(n))
    && (!cutoff || !isItem(n) || (n.date && Date.parse(n.date) >= cutoff)));
  let ids = new Set(nodes.map((n) => n.id));
  let links = graph.links.filter((l) => ids.has(l.source) && ids.has(l.target)
    && (o.suggested || l.grade !== "asserted" || l.kind !== "related_to"));
  const near = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const l of links) { near.get(l.source).add(l.target); near.get(l.target).add(l.source); }
  // A topic, person or mention with nothing left to connect to (outside the period) goes.
  nodes = nodes.filter((n) => isItem(n) || near.get(n.id).size || n.id === o.focus);
  const degree = (n) => near.get(n.id).size;
  const rank = (list) => list.sort((a, b) => (b.kind === "topic") - (a.kind === "topic") || degree(b) - degree(a)
    || b.weight - a.weight || a.label.localeCompare(b.label));

  let chosen, total;
  if (o.focus && near.has(o.focus)) {
    // Its neighbours, then theirs while the picture stays small enough to read.
    const focus = graph.nodes.find((n) => n.id === o.focus);
    const ring1 = rank(nodes.filter((n) => near.get(o.focus).has(n.id) && n.id !== o.focus));
    const inner = new Set([o.focus, ...ring1.map((n) => n.id)]);
    const ring2 = rank(nodes.filter((n) => !inner.has(n.id) && [...near.get(n.id)].some((m) => inner.has(m))));
    chosen = [focus, ...ring1.slice(0, GRAPH_BUDGET - 1)];
    if (chosen.length < GRAPH_NEAR) chosen.push(...ring2.slice(0, GRAPH_NEAR - chosen.length));
    total = 1 + ring1.length + ring2.length;
  } else {
    total = nodes.length;
    chosen = nodes.length <= GRAPH_BUDGET ? nodes : rank([...nodes]).slice(0, GRAPH_BUDGET);
  }
  ids = new Set(chosen.map((n) => n.id));
  links = links.filter((l) => ids.has(l.source) && ids.has(l.target));
  // Names on the busiest nodes only; the others show theirs on hover or selection.
  const labelled = new Set([o.focus, ...rank([...chosen]).slice(0, GRAPH_LABELS).map((n) => n.id),
    ...chosen.filter((n) => n.kind === "topic" || n.kind === "series").map((n) => n.id)]);
  if (o.focus) for (const id of near.get(o.focus) || []) labelled.add(id);
  return { nodes: chosen, links, total, labelled: chosen.length <= GRAPH_LABELS * 2 ? null : labelled };
}

function suggestionList(graph) {
  const titles = new Map(graph.nodes.map((n) => [n.id, n.label]));
  const pending = graph.links.filter((l) => l.kind === "related_to" && l.grade === "asserted");
  if (!pending.length) return null;
  const decide = async (link, decision, button) => {
    button.disabled = true;
    try {
      await api("/api/links", { method: "POST", body: { article_id: link.source, other_id: link.target, decision } });
      await graphView(Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || "")));
    } catch (error) {
      button.disabled = false;
      toast(error.message);
    }
  };
  return h("section", { class: "link-review", "aria-label": "Suggested links" },
    h("h2", {}, `${pending.length} suggested ${pending.length === 1 ? "link" : "links"} to review`),
    h("p", { class: "hint" }, "Accepted links are added to both articles' notes in your vault. Dismissed ones are never suggested again."),
    pagedList(pending, (link) => h("li", { class: "related-item suggested" },
      h("div", {},
        h("a", { href: `#/article/${encodeURIComponent(link.source)}` }, titles.get(link.source)),
        h("span", { class: "pair-sep" }, " and "),
        h("a", { href: `#/article/${encodeURIComponent(link.target)}` }, titles.get(link.target)),
        h("p", { class: "hint" }, link.weight ? `${Math.round(link.weight * 100)}% similar` : "Suggested")),
      h("div", { class: "related-actions" },
        h("button", { class: "button", type: "button", onclick: (e) => decide(link, "accept", e.currentTarget) }, "Accept"),
        h("button", { class: "button", type: "button", onclick: (e) => decide(link, "reject", e.currentTarget) }, "Dismiss"))),
    { pageSize: 10, listClass: "related-list", what: "suggestions" }));
}

function graphSvg(shown, focus, onSelect) {
  const nodes = shown.nodes.map((n) => ({ ...n, r: nodeRadius(n) * (n.id === focus ? 1.3 : 1) }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = shown.links;
  if (!nodes.length) return h("p", { class: "hint graph-empty" }, "Nothing to show for this choice.");
  layout(nodes, links, byId, focus);

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
    const shape = n.kind === "person"
      ? personGlyph(n.r, { transform: `translate(${n.x} ${n.y})` })
      : svgEl("circle", { cx: n.x, cy: n.y, r: n.r, class: `node node-${isEntity(n) ? `entity node-${n.kind}` : n.kind}`,
          css: n.kind === "topic" ? { fill: topicColor(n.label) } : null });
    const quiet = shown.labelled && !shown.labelled.has(n.id) ? " quiet" : "";
    const label = svgEl("text", { x: n.x, y: n.y + n.r + 12, class: `label label-${n.kind}${quiet}` },
      clip(n.label, n.kind === "person" ? 22 : 30));
    const choose = () => {
      for (const g of svg.querySelectorAll(".graph-node.selected")) g.classList.remove("selected");
      group.classList.add("selected");
      onSelect(n);
    };
    const group = svgEl("g", { class: `graph-node${n.id === focus ? " selected focus" : ""}`, "data-id": n.id,
      tabindex: "0", role: "button", "aria-label": `${graphKindName(n)}: ${nodeTitle(n)}`,
      onclick: choose, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } },
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

const isEntity = (n) => n.id.startsWith("entity:");

function nodeRadius(n) {
  if (isEntity(n)) return 4 + Math.min(Math.sqrt(n.weight) * 1.5, 6);
  if (n.kind === "topic") return 10 + Math.min(Math.sqrt(n.weight) * 2.5, 12);
  if (n.kind === "series") return 8;
  if (n.kind === "article") return 7 + Math.min(Math.sqrt(n.weight), 5);
  if (n.kind === "post") return 5 + Math.min(Math.sqrt(n.weight), 5);
  return 7 + Math.min(Math.sqrt(n.weight) * 1.5, 5);
}

function nodeTitle(n) {
  if (isEntity(n)) return `${n.label} (${categoryName(n.kind)}): mentioned in ${plural(n.weight, "article or post", "articles and posts")}`;
  const count = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  if (n.kind === "topic") return `${n.label}: ${count(n.weight, "article or post", "articles and posts")}`;
  if (n.kind === "series") return `${n.label}: ${count(n.weight, "article", "articles")}`;
  if (n.kind === "article" || n.kind === "post") return n.weight ? `${n.label}: ${count(n.weight, "comment", "comments")}` : n.label;
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

function layout(nodes, links, byId, pinned = null) {
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
      if (n.id === pinned) { n.x = 0; n.y = 0; } // the focus stays in the middle
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
    await refresh();  // notes may have been edited meanwhile
    if (path.startsWith("#/article/")) {
      return await articleView(decodeURIComponent(path.slice(10)),
        { comment: params.get("comment"), reply: params.get("reply") === "1" });
    }
    if (path === "#/search") return await searchView(params.get("q") || "", params.get("ask") === "1");
    if (path === "#/add") return addView();
    if (path === "#/add/post") return addPostView();
    if (path === "#/settings") return await settingsView();
    const filters = Object.fromEntries(params);
    if (path === "#/library") return libraryView(filters);
    if (path === "#/people") return await peopleView(filters);
    if (path === "#/mentions") return await mentionsView(filters);
    if (path.startsWith("#/entity/")) return await entityView(decodeURIComponent(path.slice(9)));
    if (path === "#/graph") return await graphView(filters);
    if (path.startsWith("#/person/")) return await personView(decodeURIComponent(path.slice(9)));
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

// Text size: everything is sized in rem, so the root size scales the whole app.
const TEXT_SIZES = [["standard", "Standard text size", "0.85em"], ["large", "Large text size", "1em"], ["larger", "Larger text size", "1.15em"]];

function setTextSize(size) {
  document.documentElement.dataset.textSize = size;
  try {
    localStorage.setItem("postloom-text-size", size);
  } catch {
    // Not saved (private window); it still applies until the page closes.
  }
  renderTextSize();
}

function renderTextSize() {
  const current = document.documentElement.dataset.textSize || "standard";
  fill(document.getElementById("text-size"), h("span", { class: "text-size-label", "aria-hidden": "true" }, "Text"),
    TEXT_SIZES.map(([size, label, em]) => h("button", { type: "button", "aria-label": label, title: label,
      "aria-pressed": String(size === current), vars: { "--glyph": em }, onclick: () => setTextSize(size) }, "A")));
}
renderTextSize();

// Started from the Postloom icon, postloom has no window to close; this stops it.
const quitButton = document.getElementById("quit");
fill(quitButton, icon("power"), h("span", {}, "Quit postloom"));
quitButton.addEventListener("click", async () => {
  quitButton.disabled = true;
  try {
    await api("/api/quit", { method: "POST", body: {} });
  } catch (error) {
    quitButton.disabled = false;
    return toast(error.message);
  }
  document.body.replaceChildren(h("main", { class: "stopped" },
    h("h1", {}, "postloom has stopped"),
    h("p", {}, "Your data is saved. You can close this tab, and open postloom again from its icon.")));
});
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
