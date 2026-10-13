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
  bootstrap.py   composition root: wires adapters to ports
```

Dependencies only point inward. `tests/architecture/test_layers.py` fails the build if a
layer imports an outer one, or if the domain imports anything outside the standard library.

| Port | Purpose | Adapters |
|---|---|---|
| `ContentExtractor` | pasted text -> structured content | Gemini (REST, stdlib HTTP), fakes |
| `GraphRepository` | queryable index of nodes and edges | in-memory, SQLite |
| `Vault` | Markdown source of truth | Obsidian-compatible folder |
| `Clock` | current time | system clock, fixed clock |
| `EmbeddingProvider` | text -> unit vectors | Gemini Embedding 2 (768 dims), fakes |
| `SearchIndex` | keyword + vector retrieval over chunks | SQLite (FTS5 + in-memory cosine) |
| `ChatModel` *(M1)* | answers and reply drafts | Gemini, Claude, Ollama |

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

## Storage

- **Vault (source of truth)**: Markdown with YAML frontmatter and `[[wikilinks]]`,
  written atomically. It is a valid Obsidian vault.
- **Index (derived, rebuildable)**: one SQLite file (`<home>/index.db`), standard
  library only, shared by the graph repository and the search index. Nodes are JSON keyed
  by stable id; edges keep their history in the same table, with a partial unique index
  guaranteeing one live edge per (source, target, kind). Schema changes are numbered
  migrations tracked with `PRAGMA user_version`, so an existing `index.db` is upgraded on
  first open. File databases run in WAL mode.

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
| 2026-10-13 | Dataclasses in the domain, Pydantic at the boundaries | Keeps the domain dependency-free; validates untrusted LLM output where it enters. |
