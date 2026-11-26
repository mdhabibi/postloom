# Changelog

All notable changes to postloom. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change how
data is stored; postloom upgrades your data folder itself when it starts.

## [Unreleased]

### Changed
- The README is a shorter front page (what postloom is, install, getting started, models,
  privacy), and everything it can do, screen by screen, is in the new
  [user guide](docs/guide.md).
- The README opens centred with the logo, and installs in the same four steps per computer
  as the website; update and uninstall are folded away.
- The website moved to [postloom-app.vercel.app](https://postloom-app.vercel.app/),
  with security headers and caching (`site/vercel.json`); the GitHub Pages workflow is gone.

## [0.1.0] - unreleased

The first public release.

### Your library
- Paste a LinkedIn article and the post that shared it. postloom restores the formatting,
  files it under your topics, links its series and indexes it for search. Stand-alone
  posts get their own page too, with or without a model.
- Paste a post's comment section to save every conversation under it, with who answered
  whom. Review each message before it is saved; pasting again later adds only new ones.
- Mentions: postloom proposes the people, organisations, places, events, projects,
  datasets, methods and links a post or article names, with the sentence that names each,
  and new topics. Only what you confirm enters your graph; every entry can be renamed,
  recategorised, merged or deleted later.
- People: everyone who commented, their headline history, your private notes and every
  conversation you had with them, across all your posts.
- Images and videos: add the pictures, slides and videos you posted. They are found by
  your captions, by what a model sees in an image (including the text in it) and by a
  video's subtitles.
- A Library page with search, filters and sorting, and a graph you can focus on any
  article, topic, person or mention. Everything stays quick with hundreds of articles and
  thousands of people.
- Edit an article's title, summary, topics, series, date and link; delete articles and
  posts; add, rename, merge and remove topics.

### Asking and replying
- Search by meaning and by keyword across articles, posts, comments, images and videos,
  in many languages, including right-to-left scripts and text written with LinkedIn
  "fancy text" converters.
- Chat across the library, about one article or post, or about one person. Answers come
  only from your own content and cite their sources; answers that cite nothing are
  flagged. People, topics and series named in a question are looked up in the graph.
- Reply drafts in your voice, from the article, the whole conversation and what you know
  about the person. postloom never posts anything.

### Your data
- Everything is plain Markdown in an Obsidian-compatible vault, and the vault is the
  source of truth: notes edited in Obsidian are read back, and a lost index is rebuilt
  from the folder, including which links you accepted or dismissed.
- Notes postloom can't read are named and nothing is guessed; files it no longer needs go
  to a trash folder, never deleted; your own notes are never touched.
- Delete a person: erases their profile, notes and every message they wrote, everywhere,
  for data-removal requests.

### Models and cost
- Bring your own key: Gemini, Claude, OpenAI, OpenRouter, any OpenAI-compatible server,
  or free local models with Ollama, set up from Settings without a terminal.
- Free local embeddings for search, in English or many languages.
- A usage page per task and model, and an optional monthly budget that stops paid calls.
  When a provider's small model is overloaded, reading falls back to a larger one.
- `postloom doctor` makes one tiny real call per configured model and explains slow ones.

### Install and use
- One-line installers for macOS, Linux and Windows that need nothing installed first and
  no administrator rights. They add a Postloom icon, update when run again and uninstall
  without touching your data.
- Clear forms that say what to paste and where, a text size setting, light and dark
  themes, and an About page with the license and credits.

### Privacy
- Runs only on your computer and listens only on 127.0.0.1. API keys stay in your data
  folder and are never sent to the browser. No account, no telemetry.

[Unreleased]: https://github.com/mdhabibi/postloom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mdhabibi/postloom/releases/tag/v0.1.0
