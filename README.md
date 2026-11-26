<div align="center">

<img src="site/img/icon.svg" width="72" height="72" alt="">

# postloom

**Your LinkedIn, remembered.**

A private, local-first memory of your articles, posts, every comment under them and the
people who wrote them: search, chat, a knowledge graph and reply drafts, with any AI model
or none.

[![CI](https://github.com/mdhabibi/postloom/actions/workflows/ci.yml/badge.svg)](https://github.com/mdhabibi/postloom/actions/workflows/ci.yml)
[![Python 3.11 to 3.14](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776ab)](#install)
[![Mac, Windows, Linux](https://img.shields.io/badge/runs%20on-Mac%20%7C%20Windows%20%7C%20Linux-555)](#install)
[![License: FSL-1.1-ALv2](https://img.shields.io/badge/license-FSL--1.1--ALv2-blue)](LICENSE.md)

[**Website**](https://postloom-app.vercel.app/) · [**Tour**](https://postloom-app.vercel.app/tour) · [**Install**](#install) ·
[**User guide**](docs/guide.md) · [**What's new**](CHANGELOG.md)

</div>

You publish a post or an article, and a conversation starts in the comments. A week later
it's all buried in the feed. postloom keeps it: paste in your post or article, and it becomes
a connected note in your own graph, linked to its topics, its series, the links and hashtags
you used, and every comment and reply. Then you can chat with anything you wrote and its
discussion, see who engages with your work, and draft replies grounded in what you actually
wrote.

![postloom home: messages waiting for your reply, suggested links, this month's cost, your articles and most engaged people](site/img/home.png)

<p align="center">
  <img src="site/img/chat.png" width="49%" alt="A question about the library answered with numbered sources from the author's own posts and comments">
  <img src="site/img/graph.png" width="49%" alt="The graph focused on one person: the articles they discussed, their topics and the other people in those conversations">
</p>

*Screenshots use a fictional library: the author, the people and the numbers are invented.
`scripts/demo/screenshots.py` rebuilds it and retakes them.*

## Why postloom

- **Runs on your machine.** Your writing and the people you talk to stay on your computer.
  No account, no cloud, no telemetry.
- **Any model, your key.** Gemini, Claude, OpenAI, OpenRouter, any OpenAI-compatible
  server, or free local models with Ollama. Search runs on your computer for free. A usage
  page shows what every task costs, and an optional monthly budget caps it.
- **Your files, not a database you can't read.** Everything lives in a plain Markdown folder
  that is also a valid [Obsidian](https://obsidian.md) vault. It is the source of truth:
  edit a note and postloom reads the change; lose the index and postloom rebuilds itself
  from the folder. Backing up that one folder backs up everything.
- **A graph you can trust.** Links postloom reads from your own text are facts; links an AI
  suggests stay suggestions until you accept them. Nothing you decided is ever overwritten,
  and history is kept instead of deleted.
- **Answers you can check.** Chat answers only from your own articles, posts and comments,
  cites the passage behind every claim, and says "not found" instead of guessing.
- **Knows your audience.** Every commenter becomes a person in the graph, identified by their
  LinkedIn profile URL, with every article they've interacted with. Anyone can be removed
  completely when they ask.

## Install

Four steps, about two minutes. You don't need Python or anything else first, and nothing
needs an administrator password. After that, postloom is an app with its own icon.

### Mac

1. **Open Terminal.** Press <kbd>⌘</kbd> and <kbd>Space</kbd> together, type **Terminal**
   and press <kbd>Return</kbd>.
2. **Copy the install line** (the copy button is at the right of the box):

   ```bash
   curl -LsSf https://raw.githubusercontent.com/mdhabibi/postloom/main/install.sh | sh
   ```

3. **Paste it into Terminal and press Return.** Click in the Terminal window, press
   <kbd>⌘</kbd> <kbd>V</kbd>, then <kbd>Return</kbd>. Text scrolls by while postloom
   installs.
4. **Wait for postloom to open in your browser.** You can close Terminal then. Next time,
   open postloom from Launchpad or Applications, like any app.

### Windows

1. **Open PowerShell.** Click Start, type **PowerShell** and press <kbd>Enter</kbd>.
2. **Copy the install line:**

   ```powershell
   irm https://raw.githubusercontent.com/mdhabibi/postloom/main/install.ps1 | iex
   ```

3. **Paste it into PowerShell and press Enter.** Right-click inside the window (or press
   <kbd>Ctrl</kbd> <kbd>V</kbd>), then press <kbd>Enter</kbd>.
4. **Wait for postloom to open in your browser.** You can close PowerShell then. Next time,
   open postloom from the Start menu or the desktop icon.

### Linux

1. **Open a terminal** (<kbd>Ctrl</kbd> <kbd>Alt</kbd> <kbd>T</kbd> on most systems).
2. **Copy the install line:**

   ```bash
   curl -LsSf https://raw.githubusercontent.com/mdhabibi/postloom/main/install.sh | sh
   ```

3. **Paste it** with <kbd>Ctrl</kbd> <kbd>Shift</kbd> <kbd>V</kbd> and press <kbd>Enter</kbd>.
4. **Wait for postloom to open in your browser.** Next time, open it from your applications
   menu.

Stuck? [Tell us what you see](https://github.com/mdhabibi/postloom/issues/new/choose).

<details>
<summary><b>Update, quit or uninstall</b></summary>

- **Update:** do the same steps again. Your data is never touched.
- **Quit:** choose **Quit postloom** at the bottom of the sidebar.
- **Uninstall:** run the line for your computer the same way. Your data folder is kept;
  delete it yourself if you want.

  Mac or Linux:

  ```bash
  curl -LsSf https://raw.githubusercontent.com/mdhabibi/postloom/main/install.sh | sh -s -- --uninstall
  ```

  Windows:

  ```powershell
  $env:POSTLOOM_UNINSTALL = 1; irm https://raw.githubusercontent.com/mdhabibi/postloom/main/install.ps1 | iex
  ```

</details>

The installer uses [uv](https://docs.astral.sh/uv/), which downloads its own copy of Python
for postloom, so it never changes the Python on your computer. Everything else postloom
needs (its database, search engine and local search model) is inside it or downloaded on
first use: there is no database server to install.

**For developers:** `uvx postloom start` runs it from PyPI, `uv tool install postloom` keeps
it installed, and `uv sync && uv run postloom start` runs a clone.

## Getting started

postloom opens in your browser (dark by default; switch to light at the bottom of the
sidebar). Press <kbd>⌘K</kbd> or <kbd>Ctrl K</kbd> anywhere to search your
articles and people, ask a question, or jump to a page. On first run:

1. Open **Settings**, pick a model provider, paste your API key and click **Test
   connection**. Keys are saved only in your Postloom folder. No key? Choose **Ollama**:
   postloom walks you through installing it, suggests a model that fits your computer's
   memory and downloads it, all without a terminal.
2. Click **Add**. For an article, paste it and the post that announced it; postloom
   restores the formatting, files it under your topics and indexes it. For a post that
   stands on its own, choose **Post** and paste it (no model needed; with one, postloom
   also picks its topics).
3. Open the article to read it and ask questions about it, or use the search box to search
   and ask across everything you've written. Answers cite the sections they come from, and
   when nothing relevant exists postloom says so instead of guessing.

## Choosing a model

| Provider | Key | Good for |
|---|---|---|
| Google Gemini | [aistudio.google.com](https://aistudio.google.com/apikey) | A free tier to start with |
| Anthropic Claude | [console.anthropic.com](https://console.anthropic.com/settings/keys) | Reply drafts that sound like you |
| OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) | GPT models |
| OpenRouter | [openrouter.ai](https://openrouter.ai/keys) | One key for hundreds of models, exact cost per call |
| Ollama | none | Free and fully private; needs a capable computer |
| Other OpenAI-compatible | depends | LM Studio, Groq, Mistral, DeepSeek, Together, vLLM... |

Each task has its own model, with sensible defaults: a cheap model restores articles,
reads comments and answers questions, and a stronger one writes reply drafts. Change any
of them under **Models** in Settings.

**What it costs.** Rough figures at list prices on 2026-10-25 (the usage page shows your
real numbers):

| | Gemini (default models) | Claude (Haiku, Sonnet for replies) |
|---|---|---|
| Adding a 2,000-word article | ~$0.01 | ~$0.002 |
| A question about an article | ~$0.005 | under $0.001 |
| A reply draft | ~$0.006 | ~$0.02 |
| A month of daily articles, 5 questions and 2 replies a day | ~$1.40 | ~$1.40 |

Search, related-article suggestions, the graph and the people pages cost nothing: they
run on your computer. (On Intel Macs, where the local embedding runtime isn't available,
postloom uses your provider's embeddings for search instead, or keywords.) Nothing runs in
the background; a model is only called when you click something.

**Local models with Ollama.** Choose Ollama in Settings. postloom checks whether
[Ollama](https://ollama.com) is installed and running (and starts it for you), suggests a
model for your computer's memory (Qwen 3.5 in 4B, 9B or 27B), downloads it with a progress
bar and uses it for every task. Models you already pulled are offered too. Reading
comments and chat work well with mid-size models. Restoring long articles needs a capable
model (14B parameters or more, so 32 GB of memory helps) and can take several minutes.
postloom sizes Ollama's context for every request and refuses, with a clear message, texts
too long for the limit you set, instead of letting them be silently cut off.

## What you can do

- **Comments and replies:** paste a comment section; postloom works out who answered whom,
  and drafts replies in your voice from the article and the whole thread.
- **People:** everyone who engaged with you, across all your posts, with your private notes.
- **Mentions:** the people, organisations, events and links your writing names, confirmed
  by you before they enter your graph.
- **Images and videos:** found by your captions, by what a model sees in them and by
  subtitles.
- **Ask questions:** answers only from your own library, with sources you can open.
- **The graph:** articles, topics, series, people and mentions, focused on whatever you pick.
- **Export the graph:** RDF (Turtle, JSON-LD) with schema.org and PROV-O, Cypher for
  Neo4j, or GraphML for Gephi, with the provenance of every link
  ([how](#export-your-graph)).
- **Your vault:** plain Markdown you can open in Obsidian, edit, back up or move.
- **Command line:** everything the app does, scriptable.

The [user guide](docs/guide.md) explains each of them in detail, with every setting.

## Export your graph

Take your whole graph into the tools you already use: every article, post, comment,
person and mention, every link between them, and where each link came from (parsed from
your text, suggested by a model, or confirmed by you).

1. Open **Settings** and scroll to **Export your graph**.
2. Pick a format:

   | Format | Pick it for |
   |---|---|
   | **RDF (Turtle)** | A triple store (GraphDB, Apache Jena, Stardog) and SPARQL |
   | **RDF (JSON-LD)** | The same RDF as JSON, for your own code |
   | **Cypher for Neo4j** | Neo4j (or Memgraph) and Cypher queries |
   | **GraphML** | Gephi, yEd, Cytoscape, NetworkX or igraph |

3. Choose what goes in. **Include what was written** (on by default) adds article bodies,
   posts, comments and your notes on people; turn it off to share only the structure
   (names, titles, dates). **Include history** adds links that were replaced or that you
   dismissed, marked as not current.
4. Click **Export the graph**. The file lands in your downloads, named like
   `postloom-graph-2026-11-26.ttl`.

From the terminal: `postloom export turtle` (or `jsonld`, `cypher`, `graphml`), with
`--history`, `--no-text` and `-o <file>`.

<details>
<summary><b>Load it into Neo4j</b></summary>

With Neo4j running, load the script with `cypher-shell` (it comes with Neo4j):

```bash
cypher-shell -u neo4j -p <your password> -f postloom-graph-2026-11-26.cypher
```

Or open Neo4j Browser, turn on **Enable multi statement query editor** in its settings,
paste the file and run it. Loading the same file again changes nothing, and a newer export
updates what changed. Then try:

```cypher
MATCH (p:Person)-[:AUTHORED]->(:Comment)-[:COMMENTED_ON]->(:Post)-[:ANNOUNCES]->(a:Article)
RETURN p.name, count(DISTINCT a) AS articles ORDER BY articles DESC LIMIT 10;
```

Every node has the label `Postloom`, its kind (`Article`, `Post`, `Comment`, `Person`,
`Topic`, `Series`, `Entity`, `Media`) and a unique `id`. Relationships (`BELONGS_TO`,
`PART_OF`, `ANNOUNCES`, `COMMENTED_ON`, `REPLIED_TO`, `AUTHORED`, `RELATED_TO`, `LINKS_TO`,
`MENTIONS`) carry `origin`, `grade` (`verified`, `asserted` or `rejected`), `producer` and
`recorded_at`. With history, filter on `r.current = true` for today's graph.

</details>

<details>
<summary><b>Load it into a triple store and query it with SPARQL</b></summary>

- **GraphDB:** create a repository, then **Import → Upload RDF files**, choose the `.ttl`
  file and click **Import**. Query it under **SPARQL**.
- **Apache Jena:** `sparql --data postloom-graph-2026-11-26.ttl --query query.rq`
- **Python:** `rdflib.Graph().parse("postloom-graph-2026-11-26.ttl")`

Who comments most:

```sparql
PREFIX pl: <https://postloom-app.vercel.app/ns#>
PREFIX schema: <https://schema.org/>
SELECT ?name (COUNT(?comment) AS ?comments) WHERE {
  ?person pl:authored ?comment ; schema:name ?name .
} GROUP BY ?name ORDER BY DESC(?comments) LIMIT 10
```

Links a model made that you haven't confirmed yet, using the provenance records:

```sparql
PREFIX pl: <https://postloom-app.vercel.app/ns#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?from ?link ?to ?producer WHERE {
  ?record a pl:EdgeRecord ; pl:grade pl:Asserted ; pl:producer ?producer ;
          rdf:subject ?from ; rdf:predicate ?link ; rdf:object ?to .
  FILTER NOT EXISTS { ?record prov:invalidatedAtTime ?until }
}
```

Nodes use schema.org (`schema:Article`, `schema:Comment`, `schema:Person`...) and SKOS
for topics, and are named `urn:postloom:<id>`. Relations are `pl:` properties mapped to
schema.org and Dublin Core; the vocabulary is at
[postloom-app.vercel.app/ns](https://postloom-app.vercel.app/ns) and inside every export.
Each link is also a `pl:EdgeRecord` (an `rdf:Statement`) with its origin, grade, producer
and PROV-O times.

</details>

<details>
<summary><b>Open it in Gephi, yEd or NetworkX</b></summary>

- **Gephi:** **File → Open**, choose the `.graphml` file, keep **Directed** and click
  **OK**. Under **Appearance**, colour nodes by the `labels` attribute (partition) and size
  them by degree; run **ForceAtlas 2** under **Layout**.
- **yEd:** **File → Open**, then **Layout → Organic**.
- **NetworkX:** `networkx.read_graphml("postloom-graph-2026-11-26.graphml")`
- **Neo4j:** copy the file into Neo4j's `import` folder, then run
  `CALL apoc.import.graphml("file:///postloom-graph-2026-11-26.graphml", {readLabels: true})`
  (needs the APOC plugin and `apoc.import.file.enabled=true`).

</details>

The file holds the names and comments of the people in your library, so share it with the
same care as your vault. The [user guide](docs/guide.md#exporting-the-graph) has the full
data model.

## Privacy

postloom runs only on your computer and listens only on `127.0.0.1`, so nothing on your
network can reach it. It refuses requests that don't come from its own page, so other
websites you visit can't use it either. It stores the names, headlines and profile URLs of
people who comment on your posts, locally and only for your own use. If one of them asks
to be removed, **Delete this person** erases them from the app, its history, the search
index and your vault.

When you use a hosted model, the text a feature needs (the article you add, the comments
you paste, the passages behind an answer, an image you ask it to describe) is sent to that
provider under its terms. Check them: free tiers may use your data for training. Search
embeddings run on your computer by default, and with Ollama nothing leaves your computer
at all.

postloom is not affiliated with or endorsed by LinkedIn.

## Documentation

- [User guide](docs/guide.md): every feature and setting
- [Architecture](ARCHITECTURE.md): how postloom is built, and why
- [Changelog](CHANGELOG.md): what changed in each version
- [Contributing](CONTRIBUTING.md), [code of conduct](CODE_OF_CONDUCT.md) and
  [security policy](SECURITY.md)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Something missing?
[Suggest an idea](https://github.com/mdhabibi/postloom/issues/new?template=idea.yml).

## License

postloom is **fair source**, under the [Functional Source License 1.1](LICENSE.md)
(FSL-1.1-ALv2). You can read, run, modify and share the code for anything except offering
a competing commercial product or service. Using postloom for your own work, including
your business, is allowed. Each release becomes Apache-2.0 two years after it is
published. The postloom name and logo aren't covered by the license.
