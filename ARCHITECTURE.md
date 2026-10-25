# Architecture

This document records how postloom is built and why. When a decision changes, update the
decision log at the bottom rather than rewriting history.

## Goals that shape everything

1. **Trivial local install** for non-developers: one Python process, one data folder,
   no database server, no Docker requirement.
2. **Affordable**: cheap models for routine work, nothing re-computed that hasn't changed.
3. **Trustworthy graph**: every fact knows where it came from; the user's decisions win.
4. **Easy to extend**: new LLM providers, storage backends, importers and features are
   additions, not rewrites.

## Layers (clean / hexagonal architecture)

```
src/postloom/
  domain/        entities, value objects, rules       (standard library only)
  application/   use cases + ports (interfaces)        (depends on domain)
  adapters/      implementations of ports              (depends on application, domain)
  interfaces/    CLI, web API, UI                      (calls use cases via bootstrap)
  settings.py    environment + config.json -> Settings (provider, models, limits)
  bootstrap.py   composition root: wires adapters to ports
```

Dependencies only point inward. `tests/architecture/test_layers.py` fails the build if a
layer imports an outer one, or if the domain imports anything outside the standard library.
Settings and configuration are outer too: only interfaces and the composition root read
them, so use cases and adapters receive plain values.

| Port | Purpose | Adapters |
|---|---|---|
| `ContentExtractor` | pasted text -> structured content | any provider (see below), fakes |
| `ThreadParser` | pasted comment section -> messages | any provider, fakes |
| `GraphRepository` | queryable index of nodes and edges | in-memory, SQLite |
| `Vault` | Markdown source of truth | Obsidian-compatible folder |
| `Clock` | current time | system clock, fixed clock |
| `EmbeddingProvider` | text -> unit vectors | local (fastembed, default), any provider with embeddings, fakes |
| `ChatModel` | grounded answers, reply drafts | any provider, with fallback models, fakes |
| `UsageLedger` | tokens and cost per month, model and task | in-memory, SQLite |
| `SearchIndex` | keyword + vector retrieval over chunks, stored vectors per node | SQLite (FTS5 + in-memory cosine) |

Every adapter of a port must pass that port's contract tests (`tests/contract/`). Adding a
backend means adding its factory to the contract suite; nothing else changes.

Interfaces are only introduced where a second implementation is realistic. Abstracting
everything would make the project harder to contribute to.

## Data model

Node kinds: `topic`, `series`, `article`, `post`, `comment`, `person`.

| Edge | From -> to | Origin |
|---|---|---|
| `announces` | post -> article | structural (verified) |
| `belongs_to` | article -> topic | taxonomy (LLM, asserted) |
| `part_of` | article -> series | LLM, asserted |
| `commented_on` | comment -> post / article | structural |
| `replied_to` | comment -> comment | structural |
| `authored` | person -> comment | structural |
| `related_to` | article -> article | semantic similarity, asserted |
| `links_to` | article / post -> article | structural |

The schema is enforced in `domain/graph.py`: an edge connecting the wrong node kinds cannot
be constructed.

### Ids

Ids are stable and readable (`article:<slug>`, `person:<linkedin-slug>`), so re-ingesting the
same content updates it instead of duplicating it. Long slugs get a hash suffix so titles
that differ only at the end ("Part 1" / "Part 3") never collide.

People are identified by their normalized LinkedIn profile URL. A person pasted without a URL
gets a provisional id (`person:~jane-example`) that the UI asks the user to resolve.

### Provenance and history

Every edge carries `Provenance(origin, grade, producer, recorded_at, evidence)`:

- **verified**: parsed by a rule, or accepted by the user
- **asserted**: suggested by a model or heuristic, not reviewed
- **rejected**: declined by the user; kept so it is never suggested again

Nothing is deleted when the world changes. Edges and profile headlines are **superseded**:
retrieval uses current facts, while history stays queryable. A re-ingest only replaces the
model's own unreviewed claims; verified and rejected edges are never touched.

## Who does what: rules vs models

Deterministic rules handle everything they can, because they are free, instant and
repeatable: hashtags, links (including repairing `lnkd.in` links glued to text by
copy-paste), ids, the post -> article edge, "Part N" numbers.

The model only does what needs language understanding: restoring Markdown structure,
title, summary, topics (constrained to the user's taxonomy), entities and series name.
Its output is validated by a Pydantic schema before it reaches the domain.

Topics come from a fixed, user-editable taxonomy. Free-form LLM topic creation is how
knowledge graphs turn into noise.

## Model providers

Model-backed ports are implemented once, provider-neutrally, on top of a small backend
protocol (`adapters/llm/base.py`):

```
use case -> port (ContentExtractor, ThreadParser, ChatModel, EmbeddingProvider)
         -> provider-neutral adapter (content.py, chat.py, embeddings.py)
         -> LlmGateway: budget check, call, usage record
         -> LlmBackend: Gemini | OpenAI-compatible | Anthropic | Ollama
         -> HttpApi: retries, backoff, provider-neutral errors -> HttpTransport (stdlib)
```

- **Prompts and schemas live in one place** (`prompts.py`) as plain JSON Schema. Each
  backend translates the schema to its dialect: Gemini's OpenAPI subset, a forced tool for
  Anthropic, `response_format` for OpenAI-compatible servers, `format` for Ollama.
- **Structured output is validated at the boundary** with the same Pydantic models for
  every provider. Malformed or invalid JSON gets exactly one repair attempt that tells the
  model what was wrong; cut-off answers are not retried.
- **OpenAI-compatible servers disagree on parameters** (reasoning models reject
  `temperature` and `max_tokens`, some lack JSON Schema output, some cap output tokens).
  Instead of a table of quirks, the backend reads the server's 400 message, drops or swaps
  the named parameter, retries, and remembers the fix per model. Context-window overflows
  are reported, not retried.
- **Ollama goes through its native API**, because only that accepts `num_ctx`; Ollama's
  small default context silently drops text. Each request gets a context sized for it, and
  texts that can't fit the user's limit are refused before anything is sent.
- **Providers are data** (`providers.py`): label, key URL, defaults per task, whether they
  offer embeddings, and a dated price table. Adding an OpenAI-compatible provider is one
  entry; a new protocol is one backend module plus an entry.

### Embeddings

Search embeddings run locally by default (fastembed on ONNX Runtime, `bge-small-en-v1.5`,
~70 MB downloaded once), so search, related links and the graph are free, private, work
offline and don't depend on the chat provider (Anthropic has no embedding API). Users can
switch to their provider's embeddings or turn them off. Each model's vectors live in their
own named vector space and are never compared with another's; when the configured space
has no vectors yet, the app offers to rebuild the index. Similarity cutoffs are calibrated
per embedding model, with an explicit setting winning. Gemini setups created before local
embeddings keep Gemini embeddings, so their index stays valid.

### Usage and budget

Every model call is recorded per month, provider, model and task (articles, comments,
chat, reply drafts, embeddings). Cost is the provider's own figure where it reports one
(OpenRouter), otherwise tokens times the price table, with the user's prices winning;
calls to models without a known price are counted and flagged, never guessed. The
optional monthly budget is checked before every paid call against what's already spent,
so the call that crosses it completes and the next one is refused with a clear message.
Models on the user's computer are free and never blocked.

## Storage

- **Vault (source of truth)**: Markdown with YAML frontmatter and `[[wikilinks]]`,
  written atomically. It is a valid Obsidian vault.
- **Index (derived, rebuildable)**: one SQLite file (`<home>/index.db`), standard
  library only, shared by the graph repository and the search index. Nodes are JSON keyed
  by stable id; edges keep their history in the same table, with a partial unique index
  guaranteeing one live edge per (source, target, kind). Schema changes are numbered
  migrations tracked with `PRAGMA user_version`, so an existing `index.db` is upgraded on
  first open. File databases run in WAL mode. The usage ledger is a table in the same
  file; unlike the rest of the index it isn't rebuildable, which is acceptable for
  history that only feeds the usage page and the budget.

## Retrieval

1. **Chunking** (`domain/chunking.py`): an article is split along its own `##`/`###`
   sections; long sections are split between paragraphs and code blocks are never cut.
   The summary is indexed as a chunk of its own.
2. **Embedding cache**: every chunk has a content hash. Re-indexing reuses stored vectors
   for unchanged chunks, so editing one section re-embeds only that section.
3. **Hybrid search**: BM25 over FTS5 (porter stemming, user input quoted so it can't
   break FTS syntax) plus cosine similarity over embeddings, fused with reciprocal rank
   fusion (k = 60) and grouped by article with its best passages. Without an API key, or
   when the provider is unreachable, search degrades to keywords with a warning.
4. *(Next)* graph expansion: a hit in Part 3 brings in its post, comments and series
   siblings as context for chat.

## Links between articles

`SuggestLinks` runs after every ingest and reindex. Each article is represented by the
normalized centroid of its stored section vectors (no new embedding calls), every pair is
scored by cosine similarity, and each article keeps its three closest neighbours above
`related_similarity` (default 0.75, stricter than the search cutoff because whole articles
in one field resemble each other more than a query resembles a passage). One `related_to`
edge is stored per pair, from the smaller id to the larger.

- New suggestions are `semantic` / `asserted`, with the similarity as weight and evidence.
- A suggestion that no longer passes the cutoff is superseded; verified and rejected links
  are never touched, so a dismissed pair is never suggested again.
- `ReviewLink` supersedes the old edge and records the decision as a new one (verified or
  rejected), or creates a `manual` link. Both article notes are then rewritten with the
  accepted links in their `related:` frontmatter; suggestions never reach the vault.

`postloom links --explain` prints every pair's similarity, for calibrating the cutoff on
a real library.

## Graph view

`GraphOverview` returns topics and series that have articles, all articles, and people,
with comments folded into derived `discussed` links (person -> article, weighted by
messages) so the picture shows who engages with what without one node per message. The
frontend lays it out with a small force simulation in plain JavaScript and draws SVG: no
graph library, and the same library always gets the same picture because starting
positions come from id hashes. Colours are applied through the CSSOM, never `style`
attributes, so the strict CSP stays intact.

## Chat (grounded answers)

`AskQuestion` only ever shows the model numbered sources from the user's own content:
the whole article and its post when asked about one article, or passages above the
similarity cutoff when asked across the library. If nothing passes the cutoff, it answers
"not found" without calling the model. Citations like `[2]` are parsed back
deterministically, so the UI only shows sources the answer actually used.

## Discussions

LinkedIn shows two visual levels (top-level comments, and replies flat underneath), and
says who answers whom only through @mentions and order. postloom stores the actual
conversation: every message has a `thread` (the top-level comment it sits under) and a
`reply_to` (the specific message it answers), so long back-and-forths become chains and
parallel conversations inside one thread stay apart.

1. **Parse** (`ThreadParser`, cheap model): the pasted section becomes messages with
   author, headline, age and text, with LinkedIn's interface noise removed.
2. **Infer** (`domain/discussion.py`, deterministic): an @mention answers that person's
   latest earlier message in the thread; otherwise the reply answers the previous message
   by someone else. Impossible indexes from the model are repaired, with a warning.
3. **Review**: the user sees every message and its reply target before saving, fixes
   anything, marks their own replies, and adds profile URLs.
4. **Save** (deterministic): comments are identified by post, author and text, so a
   section pasted again only adds new messages, and they attach to existing chains.
   People are matched by profile URL, then by name. Edges: `authored`, `commented_on`,
   `replied_to`. Each post's discussion is also written to `vault/discussions/` as nested
   blockquotes with `[[Person]]` links.

## People

A commenter pasted without a profile link gets a provisional id from their name
(`person:~jane-example`). Adding the link later merges them into their permanent id
(`person:jane-example`): comments are re-attributed, the old `authored` edges are
superseded (kept as history) and replaced with new ones, and the provisional record is
removed. If someone with that link already exists, the two records are combined
(headline history, notes and tags are all kept). Headline changes are superseded
observations, never overwritten.

## Reply drafts

`DraftReply` writes one reply to one message, as the author. The model sees the article
and its post (so claims match what was actually written), the thread up to the message
being answered (later messages are left out, and the target is marked), the commenter's
headline, the author's private notes and their earlier exchanges on other articles, and up
to five of the author's own replies from outside this thread as examples of tone only.
The prompt forbids invented results, links or promises and asks for plain LinkedIn text;
leftover quotes and Markdown bold are stripped deterministically. Reply drafts use their
own model setting (`reply_model`), so users can pick a stronger model for the one task
where quality is most visible, while routine parsing stays on the cheap one.

Drafts are never stored and never posted. The loop closes through the normal paste flow:
once the author has replied on LinkedIn, pasting the comments again saves the real reply.

## Web app

`postloom start` serves a Starlette app on `127.0.0.1` with a static, build-free frontend
(plain HTML/CSS/JS, system fonts, nothing loaded from the internet).

- **Localhost only**: the server binds to the loopback interface and refuses any Host
  header that isn't localhost, which blocks DNS-rebinding attacks.
- **CSRF**: every write needs an `X-Postloom: 1` header, which other websites can't add
  without a CORS preflight that postloom never approves.
- **CSP**: `default-src 'self'` with no inline scripts; the Markdown renderer escapes all
  input before adding the few tags it generates.
- **Secrets**: the API key is stored in `<home>/config.json` with 0600 permissions and is
  never sent to the browser. An environment variable overrides it.

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-10-13 | SQLite (+ sqlite-vec, FTS5) instead of Neo4j | A personal corpus is small; a JVM database server breaks the one-command install. |
| 2026-10-13 | No Microsoft GraphRAG | Expensive indexing built for unknown corpora; most of our edges are known structurally. |
| 2026-10-13 | Markdown vault as source of truth | User owns readable files, Obsidian for free, index rebuildable. |
| 2026-10-13 | CortexDB not adopted (for now) | Go library reached from Python via a separate gRPC server; would break single-process install. Its provenance grades and supersession ideas were adopted. |
| 2026-10-13 | Comments are pasted, not scraped | LinkedIn's terms prohibit scraping; individuals have no comments API. |
| 2026-10-13 | Gemini via REST on the standard library, not Google's SDK | Smaller install; one tiny `HttpTransport` seam makes adapters testable without network. |
| 2026-10-13 | Model names are settings (default `gemini-3.5-flash-lite`) | Google retires model versions often; users choose cost vs quality. |
| 2026-10-13 | Brute-force cosine in Python instead of sqlite-vec | ~0.1 s for 5,000 chunks; no native extension to install on every OS. Same port can take sqlite-vec later. |
| 2026-10-13 | Hybrid search with reciprocal rank fusion | Keywords catch names and exact terms, embeddings catch paraphrases; RRF needs no score calibration. |
| 2026-10-13 | Starlette instead of FastAPI | Fewer dependencies; thin JSON handlers don't need FastAPI's extras. |
| 2026-10-13 | Build-free vanilla JS frontend | Contributors need no Node toolchain; the app works offline. |
| 2026-10-13 | Comments: model parses, rules infer, user reviews, save is deterministic | Parsing pasted LinkedIn text is the one guess in the pipeline; the user confirms it before anything is stored. |
| 2026-10-13 | Dataclasses in the domain, Pydantic at the boundaries | Keeps the domain dependency-free; validates untrusted LLM output where it enters. |
| 2026-10-15 | Reply drafts are copied, never posted or stored | LinkedIn has no posting API for comments; the user stays the author, and the real reply enters the graph through the same paste and review flow. |
| 2026-10-15 | Related articles by centroid similarity of stored section vectors | Free (no new embedding calls) and good enough to rank a personal library; per-chunk matching can come later behind the same use case. |
| 2026-10-15 | Only accepted links are written to the vault | The vault is the user's record; suggestions live in the index until reviewed. |
| 2026-10-15 | Hand-written force layout and SVG for the graph view | A few hundred nodes need no library; keeps the frontend build-free and CSP-strict. |
| 2026-10-25 | Bring-your-own-key for any provider; no shared key or hosted proxy | An embedded key leaks from open source within days; a proxy would make postloom a hosted service holding everyone's data. |
| 2026-10-25 | One backend protocol, provider-neutral adapters, prompts and schemas in one place | A prompt fix applies to every provider; a new provider is one backend, not four adapters. |
| 2026-10-25 | Adapt to OpenAI-compatible servers from their 400 messages | Dozens of servers differ in small ways that change often; reacting to the server's own explanation stays correct where a quirk table goes stale. |
| 2026-10-25 | Local embeddings (fastembed) by default | Free, private and offline search for every provider, including those without embeddings. |
| 2026-10-25 | Metering in a gateway that every model call goes through | No call can skip the budget or the usage page, whatever adapter makes it. |
