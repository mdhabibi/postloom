"""The vault reads back what it wrote: that is what makes the index rebuildable."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

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


STANDALONE = Post(
    key="hot-take",
    text="Hot take: «caching» beats bigger models 👇\n\n---\n\nکش کمک می‌کند. #RAG",
    url="https://www.linkedin.com/posts/y",
    published_on=date(2026, 11, 2),
    hashtags=("RAG",),
)


def test_a_stand_alone_post_and_its_discussion_are_read_back(tmp_path: Path) -> None:
    vault = written(tmp_path)
    vault.write_post(STANDALONE, [AGENTS])
    reply = Comment(STANDALONE.id, JANE.id, "Jane Example", "Agreed.", 0, posted_label="1h")
    vault.write_discussion(STANDALONE, STANDALONE, [reply], {JANE.id: JANE})
    vault.write_person(JANE, [ARTICLE, STANDALONE])
    vault.mark_synced()
    snapshot = MarkdownVault(tmp_path).read()
    assert snapshot.problems == ()
    assert PostNote(STANDALONE, None, (AGENTS.id,)) in snapshot.posts
    assert PostNote(POST, ARTICLE.id) in snapshot.posts  # announcements keep no topics
    assert reply in snapshot.comments

    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    vault.write_post(STANDALONE, [AGENTS])
    vault.write_discussion(STANDALONE, STANDALONE, [reply], {JANE.id: JANE})
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before

    vault.remove_post(STANDALONE)
    assert not list(tmp_path.rglob("hot-take.md"))


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


# -- what people plausibly do to a note --------------------------------------------------
def write(tmp_path: Path, relative: str, text: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_note_written_by_hand_in_postlooms_format_is_read(tmp_path: Path) -> None:
    write(
        tmp_path,
        "articles/by-hand.md",
        "---\r\nid: article:by-hand\r\ntype: article\r\ntitle: 2026\r\n"
        "published_on: '2026-03-04'\r\ntopics: '[[RAG]]'\r\nseries: Notes\r\n---\r\n\r\n"
        "# 2026\r\n\r\nWritten in another editor, with Windows line endings.\r\n",
    )
    write(
        tmp_path,
        "people/Pat Example.md",
        "---\nid: person:~pat-example\ntype: person\nname: Pat Example\n"
        "headline: Engineer\ntags: friend\n---\n\n# Pat Example\n",
    )
    snapshot = MarkdownVault(tmp_path).read()
    assert snapshot.problems == ()
    (note,) = snapshot.articles
    assert note.article.title == "2026"  # YAML read it as a number; it is still a title
    assert note.article.published_on == date(2026, 3, 4)
    assert note.article.body_markdown == "Written in another editor, with Windows line endings."
    assert note.topics == (Topic("RAG").id,)  # Obsidian stores a one-item list as text
    (pat,) = snapshot.people
    assert (pat.headline, pat.tags) == ("Engineer", ("friend",))


def test_each_kind_of_damage_is_reported_with_its_reason(tmp_path: Path) -> None:
    written(tmp_path)
    cases = {
        "articles/no-id.md": ("---\ntype: article\ntitle: T\n---\n\nBody\n", "`id` is missing"),
        "articles/bad-date.md": (
            "---\nid: article:bad-date\ntype: article\ntitle: T\npublished_on: soon\n---\n\nB\n",
            "isn't a date",
        ),
        "articles/empty.md": ("---\nid: article:empty\ntype: article\ntitle: T\n---\n\n", "empty"),
        "articles/open.md": ("---\nid: article:open\ntype: article\n\nBody\n", "never closes"),
        "articles/bad-topic.md": (
            "---\nid: article:bad-topic\ntype: article\ntitle: T\ntopics: 3\n---\n\nB\n",
            "must be a list",
        ),
        "people/bad-link.md": (
            "---\nid: person:x\ntype: person\nname: X\nlinkedin: not a link\n---\n",
            "`linkedin` isn't a LinkedIn profile link",
        ),
        "people/bad-history.md": (
            "---\nid: person:~y\ntype: person\nname: Y\nheadlines: [oops]\n---\n",
            "`headlines` must be a list",
        ),
        "discussions/no-post.md": ("---\ntype: discussion\ncomments: 0\n---\n", "which post"),
        "discussions/no-name.md": (
            "---\nid: discussion:x\ntype: discussion\n---\n\n"
            '> **Someone** %%{"n":0,"by":"person:~s"}%%\n> Hi\n',
            "no `name`",
        ),
        "discussions/no-text.md": (
            "---\nid: discussion:y\ntype: discussion\n---\n\n"
            '> **Sam** %%{"n":0,"by":"person:~sam","name":"Sam"}%%\n\n',
            "no text",
        ),
    }
    for relative, (text, _) in cases.items():
        write(tmp_path, relative, text)
    problems = {p.path: p.reason for p in MarkdownVault(tmp_path).read().problems}
    assert set(problems) == set(cases)
    for relative, (_, expected) in cases.items():
        assert expected in problems[relative], (relative, problems[relative])


def test_replies_survive_reordering_and_a_reply_to_nothing_becomes_a_comment(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        "discussions/x.md",
        "---\nid: discussion:x\ntype: discussion\n---\n\n"
        '>> **You** %%{"n":1,"by":"person:me","name":"Alex","re":0}%%\n>> Answer\n\n'
        '> **Sam** %%{"n":0,"by":"person:~sam","name":"Sam","label":"2d"}%%\n> Question\n\n'
        '> **Sam** %%{"n":2,"by":"person:~sam","name":"Sam","re":9}%%\n> Orphan\n',
    )
    snapshot = MarkdownVault(tmp_path).read()
    assert snapshot.problems == ()
    question, answer, orphan = sorted(snapshot.comments, key=lambda c: c.position)
    assert (question.text, question.posted_label, question.thread) == ("Question", "2d", None)
    assert (answer.reply_to, answer.thread, answer.is_own) == (question.id, question.id, True)
    assert (orphan.reply_to, orphan.thread) == (None, None)
    assert [p.name for p in snapshot.people] == ["Sam"]  # recreated from the comments


# -- notes can't steer postloom outside the vault --------------------------------------
def test_ids_that_would_point_outside_the_vault_are_refused(tmp_path: Path) -> None:
    written(tmp_path)
    write(
        tmp_path,
        "posts/evil.md",
        "---\nid: post:../../../escaped\ntype: post\n"
        f"announces: '[[articles/{ARTICLE.slug}]]'\n---\n\nText\n",
    )
    write(
        tmp_path,
        "articles/evil.md",
        "---\nid: article:../../escaped\ntype: article\ntitle: T\n---\n\n# T\n\nBody\n",
    )
    write(
        tmp_path,
        "discussions/evil.md",
        "---\nid: discussion:x\ntype: discussion\n---\n\n"
        '> **Eve** %%{"n":0,"by":"person:../../escaped","name":"Eve"}%%\n> Hi\n',
    )
    problems = {p.path: p.reason for p in MarkdownVault(tmp_path).read().problems}
    assert set(problems) == {"posts/evil.md", "articles/evil.md", "discussions/evil.md"}
    assert "isn't valid" in problems["posts/evil.md"]
    assert "invalid profile name" in problems["discussions/evil.md"]


def test_the_vault_never_writes_a_note_outside_its_folders(tmp_path: Path) -> None:
    from postloom.adapters.vault.markdown_vault import VaultPathError

    vault = MarkdownVault(tmp_path / "vault")
    with pytest.raises(VaultPathError):
        vault._write(tmp_path / "vault" / "posts" / ".." / ".." / "x.md", {}, "")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(VaultPathError):
        vault._remove(tmp_path / "vault" / "notes.md")  # pyright: ignore[reportPrivateUsage]
    assert list(tmp_path.rglob("*.md")) == []


def test_a_library_in_other_scripts_round_trips(tmp_path: Path) -> None:
    article = Article(title="حافظه نهان معنایی", body_markdown="متن مقاله.")
    article = Article(title=article.title, body_markdown=article.body_markdown, key=article.slug)
    post = Post(key=article.slug, text="مقاله جدید منتشر شد")
    topic = Topic("بازیابی")
    ali, maryam, wang = Person("علی رضایی"), Person("مریم احمدی"), Person("王伟")
    assert len({ali.id, maryam.id, wang.id}) == 3
    comments = [
        Comment(post.id, ali.id, ali.name, "سوال من این است", 0),
        Comment(post.id, maryam.id, maryam.name, "عالی بود", 1),
        Comment(post.id, wang.id, wang.name, "很好", 2),
    ]
    vault = MarkdownVault(tmp_path)
    vault.write_topic(topic)
    vault.write_article(article, post, [topic])
    vault.write_discussion(article, post, comments, {p.id: p for p in (ali, maryam, wang)})
    for person in (ali, maryam, wang):
        vault.write_person(person, [article])
    snapshot = MarkdownVault(tmp_path).read()
    assert snapshot.problems == ()
    assert snapshot.articles[0].article == article and snapshot.articles[0].topics == (topic.id,)
    assert {p.id for p in snapshot.people} == {ali.id, maryam.id, wang.id}
    assert sorted(snapshot.comments, key=lambda c: c.position) == comments
    assert (tmp_path / "articles" / f"{article.slug}.md").exists()


def test_entity_notes_are_read_back_and_edits_to_them_kept(tmp_path: Path) -> None:
    from postloom.domain.entities import Category, Entity

    vault = written(tmp_path)
    lab = Entity(
        "example-lab", "Example Lab", Category.ORGANISATION, "https://example.org", ("ExLab",)
    )
    path = vault.write_entity(lab, [ARTICLE, STANDALONE])
    vault.write_person(JANE, [ARTICLE], mentioned_in=[STANDALONE])
    vault.mark_synced()
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "mentions" / "example-lab.md"
    assert "category: organisation" in text and "*Organisation*" in text
    snapshot = MarkdownVault(tmp_path).read()
    assert snapshot.problems == ()
    assert snapshot.entities == (lab,)
    assert JANE in snapshot.people

    path.write_text(
        text.replace("name: Example Lab", "name: Example Research Lab").replace(
            "category: organisation", "category: project"
        ),
        encoding="utf-8",
    )
    (edited,) = MarkdownVault(tmp_path).read().entities
    assert (edited.id, edited.name, edited.category) == (lab.id, "Example Research Lab", "project")

    path.write_text(text.replace("category: organisation", "category: spaceship"), "utf-8")
    problem = MarkdownVault(tmp_path).read().problems[0]
    assert problem.path == "mentions/example-lab.md" and "category" in problem.reason
