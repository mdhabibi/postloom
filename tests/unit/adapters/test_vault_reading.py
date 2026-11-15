"""The vault reads back what it wrote: that is what makes the index rebuildable."""

from datetime import UTC, date, datetime
from pathlib import Path

from postloom.adapters.vault.journal import FileEdgeJournal
from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.application.ports.vault import ArticleNote, PostNote
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import OWNER, Comment
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.people import Person, ProfileUrl
from postloom.domain.provenance import Grade, Origin, Provenance

T0 = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
T1 = datetime(2026, 2, 1, 18, 0, tzinfo=UTC)
RAG, AGENTS = Topic("RAG", "Retrieval-augmented generation."), Topic("AI Agents")
ARTICLE = Article(
    title='Measuring: what "matters" [part 3] | 2026',
    body_markdown="Intro line.\n\n## Metrics\n\n> A quote in the body\n\n```python\nx = 1\n```",
    summary="How to measure a cache: hit rate, précision 👇",
    url="https://www.linkedin.com/pulse/x",
    published_on=date(2026, 10, 12),
    series=Series("Semantic Caching"),
    series_part=3,
    hashtags=("RAG", "LLM"),
    entities=("LangGraph", "Redis"),
    key="measuring-what-matters-part-3",
)
OTHER = Article(title="Part 2", body_markdown="Body of part two.", key="part-2")
POST = Post(
    key=ARTICLE.slug,
    text="Read part 3 👇\n\nhttps://lnkd.in/euyuNU9y #RAG",
    url="https://www.linkedin.com/posts/x",
    published_on=date(2026, 10, 12),
    hashtags=("RAG",),
    links=("https://lnkd.in/euyuNU9y",),
    banner_path="assets/part3.png",
)
JANE = (
    Person(
        "Jane Example",
        ProfileUrl.parse("linkedin.com/in/jane-example"),
        notes="Met at PyCon.\n\n## Follow up\n\nAsk about caching.",
        tags=("speaker", "caching"),
    )
    .observe("Engineer at Acme", T0)
    .observe("Lead at Beta", T1)
)
SAM = Person("Sam Sample")


def discussion() -> list[Comment]:
    a = Comment(POST.id, JANE.id, "Jane Example", "Question?\n\nSecond paragraph.", 0, None, None)
    a = Comment(a.post, a.author, a.author_name, a.text, 0, posted_label="2d")
    b = Comment(POST.id, OWNER, "Alex Author", "> quoting you\nAnswer 100%%.", 1, a.id, a.id, "1d")
    c = Comment(POST.id, SAM.id, "Sam Sample", "Separate point.", 2)
    d = Comment(POST.id, JANE.id, "Jane Example", "Thanks!", 3, a.id, b.id)
    return [a, b, c, d]


def written(tmp_path: Path) -> MarkdownVault:
    vault = MarkdownVault(tmp_path)
    for topic in (RAG, AGENTS):
        vault.write_topic(topic)
    vault.write_article(ARTICLE, POST, [RAG, AGENTS], [OTHER])
    vault.write_article(OTHER, Post(key=OTHER.slug, text="Part two is out"), [RAG], [ARTICLE])
    vault.write_discussion(ARTICLE, POST, discussion(), {JANE.id: JANE, SAM.id: SAM})
    vault.write_person(JANE, [ARTICLE])
    vault.write_person(SAM, [ARTICLE])
    vault.mark_format()
    vault.mark_synced()
    return vault


def test_everything_written_is_read_back_unchanged(tmp_path: Path) -> None:
    snapshot = written(tmp_path).read()
    assert snapshot.problems == ()
    assert set(snapshot.topics) == {RAG, AGENTS}
    assert ArticleNote(ARTICLE, (RAG.id, AGENTS.id), (OTHER.id,)) in snapshot.articles
    assert PostNote(POST, ARTICLE.id) in snapshot.posts
    assert set(snapshot.people) == {JANE, SAM}
    assert sorted(snapshot.comments, key=lambda c: c.position) == discussion()


def test_a_second_vault_object_reads_the_same(tmp_path: Path) -> None:
    written(tmp_path)
    assert MarkdownVault(tmp_path).read() == MarkdownVault(tmp_path).read()


def test_writing_what_was_read_changes_no_file(tmp_path: Path) -> None:
    vault = written(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    vault.write_article(ARTICLE, POST, [RAG, AGENTS], [OTHER])
    vault.write_discussion(ARTICLE, POST, discussion(), {JANE.id: JANE, SAM.id: SAM})
    vault.write_person(JANE, [ARTICLE])
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before
    assert not vault.changes()


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_edits_made_in_obsidian_are_read(tmp_path: Path) -> None:
    vault = written(tmp_path)
    article = tmp_path / "articles" / f"{ARTICLE.slug}.md"
    edit(article, "Intro line.", "A better intro line.")
    edit(article, "- '[[AI Agents]]'", "- '[[Kubernetes]]'")
    edit(tmp_path / "people" / "Jane Example.md", "Met at PyCon.", "Met at EuroPython.")
    edit(tmp_path / "discussions" / f"{POST.key}.md", "> Thanks!", "> Thanks a lot!")

    changes = vault.changes()
    assert len(changes.modified) == 3 and not changes.added and not changes.removed
    snapshot = vault.read()
    assert snapshot.problems == ()
    note = next(n for n in snapshot.articles if n.article.id == ARTICLE.id)
    assert note.article.body_markdown.startswith("A better intro line.")
    assert note.topics == (RAG.id, Topic("Kubernetes").id)
    assert Topic("Kubernetes") in snapshot.topics  # a topic added by hand is created
    jane = next(p for p in snapshot.people if p.id == JANE.id)
    assert jane.notes.startswith("Met at EuroPython.")
    assert "Thanks a lot!" in {c.text for c in snapshot.comments}


def test_retitling_an_article_in_its_note_keeps_its_identity(tmp_path: Path) -> None:
    vault = written(tmp_path)
    edit(tmp_path / "articles" / "part-2.md", "title: Part 2", "title: The second part")
    note = next(n for n in vault.read().articles if n.article.id == OTHER.id)
    assert note.article.title == "The second part"


def test_adding_a_profile_link_in_a_note_moves_the_persons_comments(tmp_path: Path) -> None:
    vault = written(tmp_path)
    edit(
        tmp_path / "people" / "Sam Sample.md",
        "name: Sam Sample",
        "name: Sam Sample\nlinkedin: https://www.linkedin.com/in/sam-sample-42",
    )
    snapshot = vault.read()
    sam = Person("Sam Sample", ProfileUrl("sam-sample-42"))
    assert sam.id in {p.id for p in snapshot.people} and SAM.id not in {
        p.id for p in snapshot.people
    }
    assert [c.author for c in snapshot.comments if c.author_name == "Sam Sample"] == [sam.id]


def test_a_deleted_person_note_does_not_lose_the_person(tmp_path: Path) -> None:
    vault = written(tmp_path)
    (tmp_path / "people" / "Sam Sample.md").unlink()
    assert vault.changes().removed == ("people/Sam Sample.md",)
    snapshot = vault.read()
    assert SAM.id in {p.id for p in snapshot.people}  # still the author of a comment


def test_the_users_own_notes_are_ignored_and_never_removed(tmp_path: Path) -> None:
    vault = written(tmp_path)
    mine = tmp_path / "articles" / "draft ideas.md"
    mine.write_text("# Ideas\n\nNo properties here.\n", encoding="utf-8")
    tagged = tmp_path / "people" / "Reading list.md"
    tagged.write_text("---\ntags: [reading]\n---\n\nBooks.\n", encoding="utf-8")
    snapshot = vault.read()
    assert snapshot.problems == ()
    assert len(snapshot.articles) == 2
    assert vault.prune(keep=[]) != []
    assert mine.exists() and tagged.exists()


def test_broken_notes_are_reported_not_guessed(tmp_path: Path) -> None:
    vault = written(tmp_path)
    edit(tmp_path / "articles" / "part-2.md", "title: Part 2", "title: [Part 2")
    edit(tmp_path / "discussions" / f"{POST.key}.md", '"n":0', '"n":')
    edit(tmp_path / "people" / "Jane Example.md", "linkedin:", "previously:")
    problems = {p.path: p.reason for p in vault.read().problems}
    assert set(problems) == {
        "articles/part-2.md",
        f"discussions/{POST.key}.md",
        "people/Jane Example.md",
    }
    assert "YAML" in problems["articles/part-2.md"]
    assert "marker" in problems[f"discussions/{POST.key}.md"]
    assert "linkedin" in problems["people/Jane Example.md"]


def test_two_people_with_one_name_get_separate_notes(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    first = Person("Jane Example", ProfileUrl("jane-example-1"))
    second = Person("jane example", ProfileUrl("jane-example-2"))  # same name on macOS/Windows
    paths = [vault.write_person(first, []), vault.write_person(second, [])]
    assert [p.name for p in paths] == ["Jane Example.md", "jane example (jane-example-2).md"]
    assert vault.write_person(second, []) == paths[1]  # stable when written again
    assert MarkdownVault(tmp_path).write_person(first, []) == paths[0]  # and after a restart
    assert {p.id for p in vault.read().people} == {first.id, second.id}

    comment = Comment(POST.id, second.id, "jane example", "Hi", 0)
    vault.write_discussion(ARTICLE, POST, [comment], {second.id: second})
    text = (tmp_path / "discussions" / f"{POST.key}.md").read_text(encoding="utf-8")
    assert "[[jane example (jane-example-2)|jane example]]" in text


def test_a_persons_note_never_overwrites_the_users_own_note(tmp_path: Path) -> None:
    (tmp_path / "people").mkdir()
    mine = tmp_path / "people" / "Jane Example.md"
    mine.write_text("My own page about Jane.\n", encoding="utf-8")
    path = MarkdownVault(tmp_path).write_person(JANE, [])
    assert path.name == "Jane Example (jane-example).md"
    assert mine.read_text(encoding="utf-8") == "My own page about Jane.\n"


def test_renaming_a_person_moves_their_note(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    old = vault.write_person(SAM, [])
    renamed = Person("Samuel Sample", ProfileUrl("sam"))
    vault.remove_person(SAM)
    new = vault.write_person(renamed, [])
    assert not old.exists() and new.name == "Samuel Sample.md"


def test_file_names_are_safe_on_windows(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    assert vault.write_person(Person("CON"), []).name == "_CON.md"
    assert vault.write_person(Person("Dr. Who ..."), []).name == "Dr. Who.md"
    assert vault.write_topic(Topic("x" * 300)).name == "x" * 120 + ".md"


def test_pruning_moves_stale_notes_to_the_trash(tmp_path: Path) -> None:
    vault = written(tmp_path)
    moved = vault.prune({ARTICLE.id, POST.id}, protect=["people/Sam Sample.md"])
    assert "articles/part-2.md" in moved and "people/Sam Sample.md" not in moved
    assert (tmp_path / "articles" / f"{ARTICLE.slug}.md").exists()
    assert (tmp_path / "people" / "Sam Sample.md").exists()
    trashed = list((tmp_path / ".postloom" / "trash").rglob("part-2.md"))
    assert len(trashed) == 2  # the article and its post: moved, not destroyed


def test_removing_an_article_removes_its_post_and_discussion(tmp_path: Path) -> None:
    vault = written(tmp_path)
    vault.remove_article(ARTICLE, POST)
    assert not list(tmp_path.rglob(f"{ARTICLE.slug}.md"))
    assert not vault.changes()


def test_a_discussion_without_comments_is_removed(tmp_path: Path) -> None:
    vault = written(tmp_path)
    path = vault.write_discussion(ARTICLE, POST, [], {})
    assert not path.exists()


def test_changes_are_noticed_until_marked_synced(tmp_path: Path) -> None:
    vault = written(tmp_path)
    assert not vault.changes()
    new = tmp_path / "topics" / "MLOps.md"
    new.write_text("---\nid: topic:mlops\ntype: topic\nname: MLOps\n---\n\n# MLOps\n", "utf-8")
    assert vault.changes().added == ("topics/MLOps.md",)
    assert Topic("MLOps") in vault.read().topics
    vault.mark_synced()
    assert not vault.changes()


def test_format_is_recorded(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    assert vault.format == 0  # nothing written yet
    vault.write_topic(RAG)
    assert vault.format == 1  # notes but no marker: written before formats existed
    vault.mark_format()
    assert vault.format == 2


def test_format_1_notes_keep_their_summary(tmp_path: Path) -> None:
    (tmp_path / "articles").mkdir()
    (tmp_path / "articles" / "old.md").write_text(
        "---\nid: article:old\ntype: article\ntitle: Old\n---\n\n# Old\n\n"
        "> The summary.\n\nThe body.\n",
        encoding="utf-8",
    )
    (note,) = MarkdownVault(tmp_path).read().articles
    assert (note.article.summary, note.article.body_markdown) == ("The summary.", "The body.")


# -- the edge journal -----------------------------------------------------------------
def test_journal_round_trips_edges_in_order(tmp_path: Path) -> None:
    journal = FileEdgeJournal(tmp_path)
    assert list(journal.read()) == []
    suggested = Edge(
        ARTICLE.id,
        OTHER.id,
        EdgeKind.RELATED_TO,
        Provenance(Origin.SEMANTIC, Grade.ASSERTED, "similarity", T0, "meaning similarity 0.812"),
        weight=0.812,
    )
    topic = Edge(
        ARTICLE.id,
        RAG.id,
        EdgeKind.BELONGS_TO,
        Provenance(Origin.TAXONOMY, Grade.ASSERTED, "m", T0),
    )
    for edge in (suggested, topic, suggested.supersede(T1), suggested.verify(T1)):
        journal.append(edge)
    assert list(FileEdgeJournal(tmp_path).read()) == [
        suggested,
        topic,
        suggested.supersede(T1),
        suggested.verify(T1),
    ]
    journal.rewrite([topic])
    assert list(journal.read()) == [topic]


def test_journal_skips_torn_and_foreign_lines(tmp_path: Path) -> None:
    journal = FileEdgeJournal(tmp_path)
    edge = Edge(
        ARTICLE.id,
        RAG.id,
        EdgeKind.BELONGS_TO,
        Provenance(Origin.TAXONOMY, Grade.ASSERTED, "m", T0),
    )
    journal.append(edge)
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write('\n{"source": "article:x", "tar')  # the app stopped mid-write
        handle.write('\n{"source":"topic:a","target":"topic:b","kind":"belongs_to"}\n[1, 2]\n')
    assert list(journal.read()) == [edge]
    assert NodeId("article:x") not in {e.source for e in journal.read()}
