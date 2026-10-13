# postloom

**A local-first knowledge graph and chat for your LinkedIn articles, posts, comments and the people behind them.**

You publish an article, announce it in a post, and a conversation starts in the comments.
A week later it's all buried in the feed. postloom keeps it: paste in your article and post,
and it becomes a connected note in your own graph, linked to its topics, its series, the
links and hashtags you used, and every comment and reply. Then you can chat with any article
and its discussion, see who engages with your work, and draft replies grounded in what you
actually wrote.

> **Status: alpha.** Adding articles, search and chat work end to end. Comments and the
> people behind them come next. See the [roadmap](#roadmap).

## Why postloom

- **Runs on your machine.** Your writing and the people you talk to stay on your computer.
  No account, no cloud, no telemetry.
- **Bring your own key.** Uses your own Gemini or Claude API key, or a local model through
  Ollama. Cheap models do the routine work; costs stay in cents.
- **Your files, not a database you can't read.** Everything lives in a plain Markdown folder
  that is also a valid [Obsidian](https://obsidian.md) vault, so you get Obsidian's graph view
  for free and are never locked in.
- **A graph you can trust.** Links parsed from your content are marked *verified*; links an AI
  suggests stay *asserted* until you accept them. Nothing you decided is ever overwritten,
  and history is kept instead of deleted.
- **Knows your audience.** Every commenter becomes a person in the graph, identified by their
  LinkedIn profile URL, with every article they've interacted with.

## Quick start

> Not on PyPI yet. Until the first release, install from source with [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mdhabibi/postloom.git
cd postloom
uv sync
uv run postloom start
```

`postloom start` opens the app in your browser. On first run:

1. Open **Settings** and paste a free Gemini API key from
   [aistudio.google.com](https://aistudio.google.com/apikey). It's saved only in your
   Postloom folder.
2. Click **Add article**, paste a LinkedIn article and the post that announced it.
   postloom restores the formatting, files it under your topics and indexes it.
3. Open the article to read it and ask questions about it, or use the search box to search
   and ask across everything you've written. Answers cite the sections they come from, and
   when nothing relevant exists postloom says so instead of guessing.

Your data lives in `~/Postloom` (change it with `--home` or `POSTLOOM_HOME`). The `vault`
folder inside is plain Markdown: open it in [Obsidian](https://obsidian.md) to browse your
articles as a graph.

### Command line

Everything the app does is also available from the terminal:

```bash
uv run postloom ingest article.txt post.txt --date 2026-10-12   # add an article
uv run postloom search "how do I know if my cache serves wrong answers" --explain
uv run postloom reindex                                         # after upgrading
```

### Settings

| Setting | Environment variable | Default |
|---|---|---|
| Data folder | `POSTLOOM_HOME` | `~/Postloom` |
| Gemini API key | `GEMINI_API_KEY` (wins over the saved key) | set in the app |
| Model for restoring articles | `POSTLOOM_EXTRACTION_MODEL` | `gemini-3.5-flash-lite` |
| Model for search | `POSTLOOM_EMBEDDING_MODEL` | `gemini-embedding-2` |
| Model for chat | `POSTLOOM_CHAT_MODEL` | `gemini-3.8-flash` |
| Minimum similarity for a meaning-based match | `POSTLOOM_MIN_SIMILARITY` | `0.66` |

## How it works

```
paste article + post (+ banner)
  -> extraction (cheap LLM): clean Markdown, title, summary, topics, entities, series
  -> rules: hashtags, links, ids, post->article edge, "Part N"
  -> vault/*.md (source of truth)  +  graph index (nodes, edges, provenance)

ask a question (optionally about one article or thread)
  -> hybrid search (keywords + embeddings) -> expand one hop through the graph
  -> answer with citations, or a reply draft you approve
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and the reasoning behind it.

## Roadmap

- [x] Domain model with provenance and superseded history
- [x] Ingest use case, Markdown/Obsidian vault, architecture tests
- [x] **Milestone 1 (MVP):** SQLite index, Gemini extraction and embeddings, hybrid
      search, local web app with paste-to-add, search and grounded chat
- [ ] **Milestone 2:** comments, replies and people; who-engaged-with-what views;
      reply drafting in your own voice
- [ ] **Milestone 3:** graph view, link suggestions to accept or reject, banner embeddings
- [ ] **Milestone 4:** one-command install (`pipx`/`uvx`), Docker image, first release

## Contributing

Contributions are welcome once the MVP lands. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy

postloom runs only on your computer and listens only on `127.0.0.1`, so nothing on your
network can reach it. It refuses requests that don't come from its own page, so other
websites you visit can't use it either. Once comments arrive, it will store names, headlines
and profile URLs of people who comment on your posts, locally and only for your own use. Every person can be exported or deleted in one step.
If you use a hosted model, the text you ingest is sent to that provider under their terms;
check them (free tiers may use your data for training) or use a local model.

postloom is not affiliated with or endorsed by LinkedIn.

## License

[Apache-2.0](LICENSE)
