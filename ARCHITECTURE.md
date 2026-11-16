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

Ids are stable and readable (`article:<key>`, `person:<linkedin-slug>`). Long slugs get a
hash suffix so titles that differ only at the end ("Part 1" / "Part 3") never collide.

An article's key is the slug of the title it had when it was first saved, and never changes
after that: retitling an article keeps its id, its file name, its post and its comments.
A title is not an identity, so ingest decides which article it is looking at in this order:

1. the same LinkedIn link (compared without scheme, `www.`, query or fragment);
2. the same text: at least half of the shorter text's 4-word sequences appear in the other
   (`domain/text.containment`; versions of one article score above 0.9, different articles
   below 0.2);
3. otherwise it is new, and if its title is taken it gets a numbered key and a warning.

A link that belongs to an article with different text is refused before the model is
called, so a wrong link costs nothing.

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

There is one exception, and it is deliberate: **deleting an article or a person erases
them**, history included (`GraphRepository.erase_nodes`). A commenter can ask to be
removed, and "removed" must mean no trace in the index, its history, the search index, the
journal or the notes. A person's messages are taken out of their conversations with
`domain/discussion.without_authors`, which re-attaches replies to the nearest remaining
message so the conversation stays valid. Removing a topic is not an erasure: its links are
superseded and the node is removed, so the history remains.

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
- **Thinking is asked for, not left to defaults.** Each task has an effort: "low" for
  routine work, "high" for reply drafts. Gemini maps it to `thinkingLevel` ("low" /
  "medium"; never "minimal", which some models refuse); OpenAI-compatible reasoning models
  to `reasoning_effort`. Model defaults differ (Gemini 3.8 Flash thinks at "medium" when
  nothing is set) and change between releases, and thinking counts against the output
  limit, so leaving it unset made answers slower and could cut them short. A model that
  refuses the setting is learned from its 400 and asked without it.
- **Retries are logged** (logger `postloom.llm`): `postloom doctor` shows them next to each
  check and says whether a slow call was the provider being busy or the model itself.
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
  written atomically. It is a valid Obsidian vault, and everything postloom knows is in it.
- **Index (derived, rebuildable)**: one SQLite file (`<home>/index.db`), standard
  library only, shared by the graph repository and the search index. Nodes are JSON keyed
  by stable id; edges keep their history in the same table, with a partial unique index
  guaranteeing one live edge per (source, target, kind). Schema changes are numbered
  migrations tracked with `PRAGMA user_version`, so an existing `index.db` is upgraded on
  first open. File databases run in WAL mode. The usage ledger is a table in the same
  file; unlike the rest of the index it isn't rebuildable, which is acceptable for
  history that only feeds the usage page and the budget.

### The vault is read back

`adapters/vault/reader.py` is the inverse of the writer: writing a graph and reading it
back gives the same entities (`tests/unit/adapters/test_vault_reading.py`). What makes that
possible:

- **Notes are complete.** Frontmatter carries each entity's id and every field; an
  article's body is everything under its `# Title`; a person's notes are the text under
  `## Notes`, and their headline history is a property. In a discussion note each message
  is a quote block whose first line ends in an Obsidian comment, `%%{"n":2,"by":
  "person:jane-example","name":"Jane Example","re":1}%%`: who wrote it and which message it
  answers, the two things prose can't state reliably. Obsidian hides it when reading.
- **The edge journal** (`vault/.postloom/edges.jsonl`, port `EdgeJournal`). Notes say what
  is linked to what; they can't say that a link was suggested by a model, accepted by the
  author on a certain day, or dismissed. Every edge write is appended to the journal by
  `JournaledRepository`, a decorator around the repository, so no use case can forget it.
  It is plain JSON Lines: it travels with the vault and diffs cleanly.
- **Notes postloom didn't write are not its business.** A file without postloom's `type`
  and `id` properties is never read, overwritten or moved.

`SyncVault` (vault -> index) replaces the graph with what the notes say, in one
transaction, and takes each link's provenance from the journal. Then it applies what the
notes *declare*, using the same functions the app uses (`relations.set_topics`,
`set_series`, `links.decide_link`), so an edit in Obsidian and a click in the app follow
the same rules: a topic added to a note is a verified link by the author; a topic removed
is a rejection, so a re-ingest doesn't bring it back; a `related` entry added in either
note links the pair. Finally `ExportVault` writes every note in canonical form (a no-op
for notes that already are), so a hand-edited note and the index agree to the letter.

Sync never guesses:

- A note that looks like postloom's but can't be read **blocks** the sync while there is
  an index to protect; the index is left untouched and the note is named in the UI. With
  no index (a rebuild), readable notes are restored and unreadable ones are reported and
  left alone.
- Notes that no longer match anything (the post of an article whose note was deleted)
  are **moved to `.postloom/trash`**, never deleted.
- If every article note is gone while the index still has the articles, the vault was
  emptied by accident: the notes are written again from the index, not mirrored.
- A link that one note of a pair lists and the other doesn't is removed only if the note
  lacking it was just edited; otherwise the two notes merely disagree and the link stays.

Edits are noticed through `NoteStamps` (each note's mtime and size at the last sync, kept
in the index so that a new or restored index sees every note as changed). `OpenVault` runs
when the container is built: it upgrades a vault written by an older version from its
intact index, or syncs when notes changed. The web app also syncs before any request that
writes, so it never overwrites an edit it hasn't read.

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
4. **Posts and comments** are indexed too, under the post's node: the announcement text,
   then one chunk per comment thread, written as "Name (replying to Name): text". A match
   there is shown under the article it belongs to. Keeping the discussion out of the
   article's node means link suggestions still compare articles by what they are about.

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

`AskQuestion` only ever shows the model numbered sources from the user's own library, and
each kind of question gets the sources that can answer it:

- **One article**: the whole article, its post and every comment.
- **One person** (asked on their page): what postloom knows about them and every
  conversation they took part in.
- **The whole library**, most specific evidence first:
  1. *Named things.* People (by full name, or a first name only one person has), topics
     and series named in the question are looked up in the graph. "What did Jane ask?"
     gets Jane's facts and conversations; "which articles are in this series?" gets the
     list, in order. This is the graph doing what similarity search can't.
  2. *Passages* from articles, posts and comment threads: by meaning above the calibrated
     cutoff, and by keyword when the passage contains at least half of the question's
     distinctive words (`domain/text.significant_terms`). The second rule matters because
     any common word matches something, and "what" is not evidence. A follow-up is also
     searched together with the question before it.
  3. *An overview* of the library (articles with dates, topics, series and comment counts;
     the most active people), added when there is other evidence or when the question is
     about the library itself.

Guard rails are deterministic. If nothing qualifies, the answer is "not found" without
calling the model: no cost, and no confident answer built on unrelated text. Citations like
`[2]` are parsed back; numbers that match no source are removed from the text, the UI shows
only the sources that were used, and an answer that cites nothing is flagged as unverified.
The prompt forbids outside knowledge and tells the model to keep voices apart: what a
commenter wrote is their view, not the author's.

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
(plain HTML/CSS/JS, nothing loaded from the internet).

- **Design system**: colour, type and spacing are CSS custom properties with a dark theme
  (default) and a light one, switched by `data-theme` on `<html>`; `theme.js` applies the
  saved choice before first paint. Topic "dyes" are the only saturated colours, used for
  the threads beside articles and the woven bands. Fonts are bundled under the SIL Open
  Font License: Geist for the interface, Source Serif 4 for the author's own writing.
- **Command palette** (Cmd/Ctrl K, or `/`): articles, people, search, ask and navigation in
  one keyboard-first list, built as an accessible combobox.
- **Home** is a dashboard fed by `GET /api/overview`: messages nobody answered yet,
  link suggestions to review, spend against the budget, recent articles and people.

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
| 2026-10-25 | Bring-your-own-key for any provider; no shared key or hosted proxy | A key embedded in published code leaks within days; a proxy would make postloom a hosted service holding everyone's data. |
| 2026-10-25 | One backend protocol, provider-neutral adapters, prompts and schemas in one place | A prompt fix applies to every provider; a new provider is one backend, not four adapters. |
| 2026-10-25 | Adapt to OpenAI-compatible servers from their 400 messages | Dozens of servers differ in small ways that change often; reacting to the server's own explanation stays correct where a quirk table goes stale. |
| 2026-10-25 | Local embeddings (fastembed) by default | Free, private and offline search for every provider, including those without embeddings. |
| 2026-10-25 | Metering in a gateway that every model call goes through | No call can skip the budget or the usage page, whatever adapter makes it. |
| 2026-10-25 | Fair source (FSL-1.1-ALv2) instead of Apache-2.0 | Readable, auditable code (essential for a tool holding API keys and LinkedIn data) without letting anyone resell it as a competing product; each version becomes Apache-2.0 after two years. |
| 2026-10-25 | Dark-first product UI with bundled fonts and a command palette | Modern tool conventions experts expect; bundling keeps the app offline and CSP-strict. |
| 2026-11-15 | The vault is read back; the index is rebuilt from it | "Source of truth" was a promise the code didn't keep: the vault was write-only. Now losing the index loses nothing, and notes can be edited in Obsidian. |
| 2026-11-15 | Edge provenance in a journal inside the vault, not in note frontmatter | Notes stay readable; decisions and history still survive a rebuild and travel with the vault. A repository decorator writes it, so no use case can forget. |
| 2026-11-15 | Sync blocks on unreadable notes and trashes instead of deleting | A sync that guesses can silently destroy an author's decisions or files. Stopping and naming the note is recoverable; guessing is not. |
| 2026-11-15 | Articles have a stable key; identity is link, then text, never title | Titles get reworded and reused. Matching on text (4-word shingles) is deterministic, free and runs before the model is called. |
| 2026-11-15 | Deleting an article or a person erases history too | The one exception to "supersede, never delete": erasure requests must leave no trace, including in the journal. |
| 2026-11-15 | Chat looks named people, topics and series up in the graph | Similarity search can't answer "what did Jane ask" or "what's in this series" reliably; a lookup can, and it costs nothing. |
| 2026-11-15 | Keyword matches count as chat evidence only above a coverage threshold | Every question shares common words with some passage; without the threshold the "not found without a model call" guarantee would be lost. |
| 2026-11-16 | Keys and profile names are validated in the domain; the vault refuses paths outside its folders | An edited note's `id` became a file name, so `post:../../x` wrote outside the vault. The invariant belongs where keys are made; the writer check is a second line. |
| 2026-11-16 | Slugs keep letters of non-Latin scripts; Latin results unchanged | Every Persian, Arabic, Chinese or Cyrillic name became "untitled", merging all such commenters into one person. Latin output was checked against the old function on 200,000 strings, so stored ids stay valid. |
| 2026-11-16 | Keyword search matches two-character pieces for scripts written without spaces | FTS5's tokenizer splits on spaces, so Chinese, Japanese and Thai text was one "word" and could not be found. Pieces are the standard dictionary-free approach. |
| 2026-11-16 | Comments are marked as material, not instructions, in prompts | Pasted comments are written by other people and reach the model; postloom has no tools, so the risk is a misleading draft, which this reduces. |
| 2026-11-15 | postloom sets each model's thinking level instead of using the default | A real `doctor` run showed Gemini 3.8 Flash taking 43-172s for a one-word answer at its default level; defaults vary per model and release, and thinking eats into the output limit. |
| 2026-11-15 | Requests borrow the wired container | Saving settings rewires the app; closing the old database under a running request made that request fail. |
