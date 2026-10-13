# postloom

**A local-first knowledge graph and chat for your LinkedIn articles, posts, comments and the people behind them.**

You publish an article, announce it in a post, and a conversation starts in the comments.
A week later it's all buried in the feed. postloom keeps it: paste in your article and post,
and it becomes a connected note in your own graph, linked to its topics, its series, the
links and hashtags you used, and every comment and reply. Then you can chat with any article
and its discussion, see who engages with your work, and draft replies grounded in what you
actually wrote.

> **Status: pre-alpha.** The domain model and ingest pipeline are in place; the web app,
> SQLite index and LLM adapters are being built. See the [roadmap](#roadmap).

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

> Not on PyPI yet. Until the first release, install from source.

```bash
git clone https://github.com/mdhabibi/postloom.git
cd postloom
uv sync            # https://docs.astral.sh/uv/
uv run postloom init
```

`init` creates your vault at `~/Postloom/vault` (override with `--home` or `POSTLOOM_HOME`)
with a starter set of topics. Open that folder in Obsidian to browse it.

### Add an article (command line, until the web app lands)

1. Create a free Gemini API key at [aistudio.google.com](https://aistudio.google.com).
2. Paste your article into one text file and its announcement post into another
   (on macOS: copy the article, then `pbpaste > article.txt`; same for `post.txt`).
3. Run:

```bash
export GEMINI_API_KEY=your-key-here
uv run postloom ingest article.txt post.txt --url https://www.linkedin.com/pulse/... --date 2026-10-12
```

postloom restores the article's formatting, picks topics from your list, detects the
series, and writes `articles/<slug>.md` and `posts/<slug>.md` into your vault. If the
restored article looks shorter than what you pasted, it tells you.

Ingest also indexes the article for search. Then search by keywords or in your own words:

```bash
uv run postloom search "how do I know if my cache serves wrong answers"
```

Search combines keyword matching with meaning-based matching (Gemini embeddings), and shows
the best-matching sections of each article. Run `uv run postloom reindex` after upgrading
postloom or changing the embedding model.

To use different Gemini models, set `POSTLOOM_EXTRACTION_MODEL` (default:
`gemini-3.5-flash-lite`) or `POSTLOOM_EMBEDDING_MODEL` (default: `gemini-embedding-2`).

Once released, installation will be a single command:

```bash
pipx install postloom   # or: uvx postloom start
postloom start          # opens the app in your browser
```

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
- [ ] **Milestone 1 (MVP):** SQLite index (FTS5 + sqlite-vec), Gemini extraction and
      embeddings, local web app with paste-to-ingest and chat scoped to an article
- [ ] **Milestone 2:** comments, replies and people; who-engaged-with-what views;
      reply drafting in your own voice
- [ ] **Milestone 3:** graph view, link suggestions to accept or reject, banner embeddings
- [ ] **Milestone 4:** one-command install (`pipx`/`uvx`), Docker image, first release

## Contributing

Contributions are welcome once the MVP lands. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy

postloom stores names, headlines and profile URLs of people who comment on your posts,
locally and only for your own use. Every person can be exported or deleted in one step.
If you use a hosted model, the text you ingest is sent to that provider under their terms;
check them (free tiers may use your data for training) or use a local model.

postloom is not affiliated with or endorsed by LinkedIn.

## License

[Apache-2.0](LICENSE)
