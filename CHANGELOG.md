# Changelog

All notable changes to postloom. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change how
data is stored; postloom upgrades your data folder itself when it starts.

## [Unreleased]

### Fixed
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
