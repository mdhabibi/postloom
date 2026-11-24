# Changelog

All notable changes to postloom. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change how
data is stored; postloom upgrades your data folder itself when it starts.

## [Unreleased]

### Added
- An **About postloom** page (bottom of the sidebar, and at the end of Settings): who made
  it, the version and what's new, the source code on GitHub, where to report a problem,
  the license in plain words and in full, what happens to your data, and the open
  projects postloom is built with. `postloom --version` names the author, license and
  repository too.

### Changed
- Clearer screens. Adding an article is two numbered steps, "The article" and "The post
  that shared it", each saying above its box exactly what to copy from LinkedIn and how,
  with an example; links and date are grouped under an optional Details box, and the
  button says what happens next. The post and comment forms explain the same way, and
  article sections say what they are for. In the sidebar, "Threads" is now "Topics" (as
  in Settings) and the list under it "Recent writing".
- Larger text throughout (16px interface, 19px reading), and a Text size control at the
  bottom of the sidebar (Standard, Large, Larger) that scales the whole app and is
  remembered.

### Fixed
- When Gemini's small model is overloaded ("high demand"), reading an article, a post,
  comments or mentions now switches to Gemini Flash instead of failing, as chat already
  did. The same applies through OpenRouter.
- Words written with LinkedIn "fancy text" converters (bold, italic, script, double-struck,
  monospace, small capitals, circled, fullwidth, struck-through) are found by search and
  chat, matched as hashtags and names, and read correctly by the model. Posts keep the
  letters exactly as written; the same post from another converter is recognised.
- An edited note could make postloom write a Markdown file outside the vault. Ids from
  notes are now validated and such a note is reported as unreadable.
- Commenters whose names are written in Persian, Arabic, Chinese, Cyrillic, Hindi and
  similar scripts all became one person. They now get ids of their own (Latin ids are
  unchanged).
- Keyword search and chat found nothing in Chinese, Japanese or Thai text.
- Right-to-left text (Persian, Arabic, Hebrew) was shown left to right.
- A `javascript:` link could be saved as an article's LinkedIn link; only web links are
  accepted now. Citation numbers inside a link no longer break it.
- Request bodies without a declared length weren't size-limited.

### Added
- A large library stays quick and tidy. With 500 articles, 1000 people and 5000 comments
  every screen opens in well under a second (the graph took over 5 seconds, lists over a
  second): screens are answered from an in-memory snapshot of the library that any change
  refreshes. A new **Library** page lists everything with search, kind, topic and sort;
  the sidebar keeps the busiest topics and newest writing; People and Mentions can be
  searched, filtered and sorted; long lists show 50 at a time; a person's conversations
  come 10 at a time.
- The graph shows at most 160 nodes, the most connected first, instead of everything at
  once. Click a node for a card with **Open** and **Focus here**; focus on any article,
  topic, person or mention by name to see its connections; narrow it to the last 3 or 12
  months. The focus and choices are kept in the address.
- Mentions: after adding a post or an article, postloom proposes the people,
  organisations, places, events, projects, datasets, methods and links it names, plus
  topics (including new ones). You review them with the sentence that names each, and
  only what you confirm enters the graph. Mentions show on the post, on the new
  Mentions page, on people's pages, in the graph and in chat; entries can be renamed,
  recategorised, merged, removed from a post or deleted. Names not in the text, and
  your own name, are never suggested. Each entry has a note in `vault/mentions/`.
- One-line installers for macOS, Linux and Windows. They need nothing installed first,
  add a Postloom icon (Launchpad, Start menu and desktop, applications menu), open the
  app, update when run again and uninstall without touching your data.
- `postloom open` (what the icon runs) starts postloom in the background and opens it;
  clicking the icon again opens the running one instead of starting a second copy.
  `postloom stop`, **Quit postloom** in the sidebar, and `postloom shortcut`.
- Settings → Ollama sets up local models without a terminal: install, start, a model
  suggested for your computer's memory, download with progress, use.
- Stand-alone posts: add a post that doesn't announce an article (Add → Post, or
  `postloom post post.txt`). It gets its own page, topics, comments, reply drafts, search,
  chat, a place in the graph and a note in `vault/posts/`. Posts can be added without a
  model; with one, postloom picks their topics. Adding a post again updates it, and a
  post already saved with its article is not added twice.
- Settings → Search by meaning → Language of your writing: English or Many languages.
  Adding an article that isn't in English while the English-only model is active shows a
  hint.

### Changed
- Reply drafts and chat treat comments as material, never as instructions to follow.

## [0.1.0] - 2026-11-16

The first release.

### Your library
- Paste a LinkedIn article and the post that announced it. postloom restores the
  formatting, files it under your topics, links its series and indexes it for search.
- Paste a post's comment section to save every conversation under it, with who answered
  whom. Review each message before it is saved; pasting again later adds only new ones.
- People: everyone who commented, their headline history, your private notes and every
  conversation you had with them. Add a profile link once to recognise them everywhere.
- Edit an article's title, summary, topics, series, date and link; delete an article;
  add, rename, merge and remove topics.
- Delete a person: erases their profile, notes and every message they wrote, everywhere,
  for data-removal requests.

### Asking and replying
- Search by meaning and by keyword across articles, posts and comments.
- Chat across the library, about one article, or about one person. Answers come only from
  your own content, cite their sources, and say "not found" without calling a model when
  nothing matches. People, topics and series named in a question are looked up in the
  graph. Answers that cite nothing are flagged.
- Reply drafts in your voice, from the article, the whole conversation and what you know
  about the person. postloom never posts anything.

### Your data
- Everything is plain Markdown in an Obsidian-compatible vault, and the vault is the source
  of truth: notes edited in Obsidian are read back, and a lost index is rebuilt from the
  folder, including which links you accepted or dismissed.
- Notes postloom can't read are named and nothing is guessed; stale notes are moved to a
  trash folder, never deleted; your own notes are never touched.
- Related-article suggestions you accept or dismiss, and a graph of articles, topics,
  series and people.

### Models and cost
- Bring your own key: Gemini, Claude, OpenAI, OpenRouter, any OpenAI-compatible server, or
  free local models with Ollama.
- Free local embeddings for search by default.
- A usage page per task and model, and an optional monthly budget that stops paid calls.
- `postloom doctor` makes one tiny real call per configured model and explains slow ones.

### Privacy
- Runs only on your computer and listens only on 127.0.0.1. API keys stay in your data
  folder and are never sent to the browser. No account, no telemetry.

[Unreleased]: https://github.com/mdhabibi/postloom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mdhabibi/postloom/releases/tag/v0.1.0
