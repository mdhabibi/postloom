# postloom user guide

Everything postloom can do, screen by screen. New here? Start with [Install](../README.md#install)
and [Getting started](../README.md#getting-started) in the README.

- [Comments and replies](#comments-and-replies)
- [Reply drafts](#reply-drafts)
- [People](#people)
- [Mentions: people, organisations and more](#mentions-people-organisations-and-more)
- [Images and videos](#images-and-videos)
- [Asking questions](#asking-questions)
- [Fixing and organising](#fixing-and-organising)
- [Related articles and the graph](#related-articles-and-the-graph)
- [A large library](#a-large-library)
- [Your vault](#your-vault)
- [Command line](#command-line)
- [Settings](#settings)
- [How it works](#how-it-works)

## Comments and replies

On an article's page, click **Add comments**, then paste the comment section of your
post. Open the post on LinkedIn, expand all comments and replies, select the whole
section and copy it. postloom splits it into messages and works out who is answering
whom, including long back-and-forths with one person. Before anything is saved you can
check each message, fix where a reply belongs, mark your own replies, and add people's
profile links so they're recognised next time. Pasting the same section again later only
adds the new messages. Set **Your name on LinkedIn** in Settings so your replies are
recognised automatically.

## Reply drafts

Every comment has a **Draft reply** button. postloom writes a reply in your voice from your
article, the whole conversation up to that message, what you know about the person
(their headline, your notes, your earlier exchanges on other articles) and a few of your
earlier replies as examples of your tone. Tell it how to change the next draft ("shorter",
"mention part 4") and click **Redraft**. postloom never posts anything: edit the draft,
copy it and reply on LinkedIn, then paste the comments again to save your real reply.

## People

**People** lists everyone who has commented on your posts, most engaged first. A person's
page shows their headline (and earlier ones), your private notes, and every conversation
you've had with them, grouped by article. Add someone's LinkedIn profile link once and
postloom merges their comments into one identity and recognises them on every future
post. Each person also gets a note in `vault/people/`, so they appear in Obsidian's graph.

A person's page has its own chat, limited to your notes about them and the conversations
you had: "What does Jane care about?", "Is there anything I haven't answered?".

**Delete this person**, at the bottom of their page, erases their profile, your notes and
every message they wrote, from postloom and from your vault. Use it when someone asks you
to remove their data. Conversations they took part in stay readable, and your own replies
stay as you wrote them.

## Mentions: people, organisations and more

When you add a post or an article, postloom looks for what it names: people,
organisations, places, events, projects and products, datasets, methods and links (links
need no model). It shows them as **Found in this post**, each with the sentence that names
it, and suggests topics, including new ones when none of yours fit. Untick what doesn't
belong, fix a name or category, and click **Add**: nothing goes into your graph before
you do. Names that aren't in your text are never suggested, and neither are you.

Confirmed mentions appear on the post, on **Mentions** (grouped by category, with what
still waits for review) and in the graph. A person you mention is the same person as the
one who comments, so their page shows both. Open any entry to rename it (the old name is
kept, so it's recognised next time), change its category, add a link, merge it into
another entry, or delete it. Chat uses them too: "Where did I mention Example Labs?",
"Which companies have I written about?", "Who did I thank?".

## Images and videos

Add the pictures, slides and videos you posted, when you add a post or an article or
later on its page (drop them on **Images and videos**). They are copied into your vault,
under `vault/media/`, so they travel with it and Obsidian shows them.

What makes them findable is words: write a caption saying what each one shows, and with a
model connected, **Describe with AI** has it look at an image and write down what it
shows and every word written in it (a chart's numbers, a slide's text). For a video, add
its subtitle file (`.vtt` or `.srt`, the one you uploaded to LinkedIn), and what is said in
it becomes searchable. Search then finds "the slide with the latency numbers", shows the
picture with the result, and chat can answer from it.

Describing an image costs a fraction of a cent with a hosted model. On Ollama it needs a
model that can see (gemma3, for example); postloom says so instead of letting a text-only
model guess. Images up to 25 MB and videos up to 1 GB are accepted.

## Asking questions

Press `Ctrl K` (or `/`) and ask. postloom answers only from your library and cites its
sources, so you can open the passage behind each claim:

- *"How do I know if my cache serves wrong answers?"* finds the passages by meaning.
- *"What did Jane ask me?"* looks Jane up and reads your conversations with her.
- *"Which articles are in the caching series?"* and *"How many articles have I written
  about RAG?"* are answered from the graph, not guessed from similar text.
- Follow-up questions keep their subject.

If nothing in your library matches, postloom says so without calling the model, so a
wrong question costs nothing. An answer that cites no source is marked as unverified.

## Fixing and organising

- **Edit details** on an article fixes its title, summary, topics, series, date and link.
  The article keeps its identity, comments and links when you retitle it. On a post it
  fixes the topics, date and link; edit the post's note to change its text.
- **Delete** removes an article with its post and comments, or a post with its comments.
- **Settings → Topics** adds, renames and removes topics. Renaming a topic to the name of
  another one merges them.
- Adding a post again updates it; it is recognised by its link or its text.
- Adding an article you already have updates it, even if its title changed. A different
  article that happens to have the same title is kept separately; nothing is replaced on
  the strength of a title.

## Related articles and the graph

When you add an article, postloom compares it by meaning with everything you've written
and suggests links to the closest ones. Each article page lists them under **Related
articles**: **Accept** keeps a link, **Dismiss** hides it for good, and you can link any
two articles by hand. Only links you accept are written to your vault (as `related:` in
the article note), so Obsidian's graph shows your decisions, not a model's guesses.

**Graph** (in the sidebar) shows your articles, topics, series and the people who
discussed them. Suggested links are dashed until you review them; the list under the
graph lets you go through them all at once. Hover a node to see its neighbours, click it
to see what it is and **Open** it or **Focus here**, drag to pan and scroll to zoom.

A large library would make one unreadable ball, so the graph shows at most 160 nodes at
a time: the most connected ones, or, once you focus on an article, topic, person or
anything you mention (type its name in **Focus on**), that node and its connections. The
period choice (last 3 or 12 months) narrows it further, and the address keeps the focus,
so you can bookmark it.

## A large library

Every list is built to stay tidy at hundreds of articles and thousands of people. The
sidebar keeps the busiest topics and your newest writing; **Library** has everything,
with search, kind, topic and sort. **People** and **Mentions** can be searched, filtered
and sorted, and long lists grow 50 at a time with **Show more**. Screens are answered from
a snapshot of the library kept in memory until something changes, so they open in a
fraction of a second.

## Your vault

Your data lives in `~/Postloom` (change it with `--home` or `POSTLOOM_HOME`). The `vault`
folder inside is plain Markdown: open it in [Obsidian](https://obsidian.md) to browse your
articles as a graph.

The vault is the source of truth, and `index.db` next to it is only a fast copy:

- **Edit notes freely.** Change an article's text or title, its `topics` or `related`
  links, a person's notes or tags, a mention's name, category or aliases (in
  `vault/mentions/`), or a comment. postloom notices the edit, shows a banner
  and reads it; topics and links you change in a note count as your decisions.
- **Lose the index, lose nothing.** Delete `index.db` (or move the vault to another
  computer) and postloom rebuilds everything on the next start, including which links
  you accepted or dismissed and when.
- **Nothing is guessed or destroyed.** A note postloom can't read (say, broken YAML) is
  named and your edits wait until it's fixed. Notes that no longer match anything are
  moved to `vault/.postloom/trash`, never deleted. Notes you create yourself are left
  alone.
- The hidden `vault/.postloom` folder holds `edges.jsonl`, a plain-text record of where
  each link came from. It travels with the vault.

To delete an article or a person, use the app: it removes every trace, which deleting a
single note can't.

## Command line

Everything the app does is also available from the terminal (in a clone of the repository,
put `uv run` in front):

```bash
postloom ingest article.txt post.txt --date 2026-10-12   # add an article
postloom post post.txt --url https://www.linkedin.com/posts/...  # add a stand-alone post
postloom search "how do I know if my cache serves wrong answers" --explain
postloom reindex                                         # after upgrading
postloom links --explain                                 # how similar your articles are
postloom usage                                           # this month's calls and cost
postloom sync                                            # read your vault again
postloom doctor                                          # check provider, models, search, vault
```

`doctor` makes one tiny real call with each model you configured (a fraction of a cent), so
a wrong model name or a key without credits shows up there and not while you add an article.

## Settings

Everything is set in the app. Environment variables win over saved settings, which is
handy for servers and scripts.

| Setting | Environment variable | Default |
|---|---|---|
| Data folder | `POSTLOOM_HOME` | `~/Postloom` |
| Provider | `POSTLOOM_PROVIDER` | chosen in the app |
| API key | `POSTLOOM_API_KEY`, or the provider's own (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`) | saved in the app |
| Server address (Ollama, custom) | `POSTLOOM_BASE_URL` | the provider's |
| Models per task | `POSTLOOM_EXTRACTION_MODEL`, `POSTLOOM_COMMENTS_MODEL`, `POSTLOOM_CHAT_MODEL`, `POSTLOOM_REPLY_MODEL` | the provider's defaults |
| Search embeddings | `POSTLOOM_EMBEDDINGS` (`local`, `provider` or `off`) | `local` |
| Language of your writing (local search model) | `POSTLOOM_LOCAL_EMBEDDING_MODEL` | English (`BAAI/bge-small-en-v1.5`); choose **Many languages** in Settings for `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Minimum similarity for a meaning-based match | `POSTLOOM_MIN_SIMILARITY` | calibrated per embedding model |
| Similarity needed to suggest a related article | `POSTLOOM_RELATED_SIMILARITY` | calibrated per embedding model |
| Monthly budget in US dollars | `POSTLOOM_MONTHLY_BUDGET` | none |
| Largest context for Ollama models | `POSTLOOM_OLLAMA_CONTEXT` | `32768` tokens |
| Your name on LinkedIn (recognises your replies) | `POSTLOOM_OWNER_NAME` | set in the app |

Prices for models postloom doesn't know can be added to `config.json` as
`"prices": {"model-id": [input, output]}` in dollars per million tokens.

## How it works

```
paste article + post (+ banner)
  -> extraction (cheap LLM): clean Markdown, title, summary, topics, entities, series
  -> rules: hashtags, links, ids, post->article edge, "Part N"
  -> vault/*.md (source of truth)  +  graph index (nodes, edges, provenance)

edit a note in Obsidian, or lose index.db
  -> postloom reads the vault back -> the index matches the notes again

ask a question (about everything, one article or one person)
  -> people, topics and series named in it are looked up in the graph
  -> hybrid search (keywords + embeddings) over articles, posts and comments
  -> answer with citations, "not found" without a model call, or a reply draft you approve
```

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the design and the reasoning behind it.
