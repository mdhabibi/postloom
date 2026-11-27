"""Build the benchmark library: a year of articles, posts and comments, and the questions
whose right sources are known because we put the answers there.

The library is built through postloom's own use cases, as a user would build it, with
the test fakes standing in for the language model (restoring articles, reading comment
sections, choosing topics). Search uses the embedder you pass, so the same library can
be measured with the real local model or with the fast stand-in used in development.
"""

from __future__ import annotations

import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.ports.embeddings import EmbeddingProvider
from postloom.application.ports.thread_parser import ParsedMessage, ParsedThread
from postloom.application.use_cases import IngestArticleCommand, IngestPostCommand
from postloom.bootstrap import Container, build_container
from postloom.domain.graph import NodeId
from postloom.settings import Settings, save_settings
from scripts.eval.corpus import GENERIC_COMMENTS, OWNER, OWNER_LINE, PEOPLE, THEMES, Theme
from tests.fakes import (
    FakeChat,
    FakeExtractor,
    FakePostClassifier,
    FakeThreadParser,
    FixedClock,
    part3_extraction,
)

START = date(2025, 12, 1)
DAYS = 364
POSTS_PER_THEME = 8
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


@dataclass(frozen=True)
class Question:
    kind: str
    """fact, comment, when, broad or absent."""
    text: str
    gold: frozenset[str]
    """Ids of the articles and posts that hold the answer; empty when there is none."""


@dataclass
class Item:
    theme: Theme
    kind: str  # "article" or "post"
    day: date
    title: str
    body: str
    announcement: str = ""
    comments: list[ParsedMessage] = field(default_factory=list[ParsedMessage])
    facts: list[int] = field(default_factory=list[int])
    comment_facts: list[int] = field(default_factory=list[int])
    id: str = ""


def plan(seed: int = 7) -> list[Item]:
    """Every article and post, dated across a year, with the facts placed in them."""
    rng = random.Random(seed)
    articles = [(theme, n) for n in range(3) for theme in THEMES]
    items: list[Item] = []
    for i, (theme, n) in enumerate(articles):
        day = START + timedelta(days=int(i * DAYS / len(articles)) + 3)
        items.append(_article(theme, n, day, rng))
    posts = [(theme, n) for n in range(POSTS_PER_THEME) for theme in THEMES]
    for i, (theme, n) in enumerate(posts):
        day = START + timedelta(days=int(i * DAYS / len(posts)))
        items.append(_post(theme, n, day, rng))
    for item in items:
        _discuss(item, rng)
    return sorted(items, key=lambda it: it.day)


def _article(theme: Theme, n: int, day: date, rng: random.Random) -> Item:
    # Facts 0 and 1 go in the first article, 2 and 3 in the second and third.
    facts = {0: [0, 1], 1: [2], 2: [3]}[n]
    sections: list[str] = []
    headings = list(theme.headings)
    for s, heading in enumerate(headings[:3]):
        lines = rng.sample(theme.filler, 3)
        if s == 1 and n > 0:
            lines.insert(1, theme.near_misses[n - 1])
        placed = [f for f in facts if (facts.index(f) + 1) == s]
        for f in placed:
            lines.insert(rng.randrange(len(lines) + 1), theme.facts[f].text)
        sections.append(f"## {heading}\n\n" + " ".join(lines))
    title = theme.titles[n]
    body = "\n\n".join(sections)
    announcement = f"New article: {title}.\n\n{rng.choice(theme.filler)} Link in the comments."
    item = Item(theme, "article", day, title, body, announcement)
    item.facts = facts
    if n == 0:
        item.comment_facts = [0]
    return item


LEADS = (
    "Quick one.",
    "Something I learned this week.",
    "Small change, big effect.",
    "From our team retro.",
    "Worth sharing.",
    "A colleague asked me this today.",
    "A note to my future self.",
    "Friday lesson.",
)


def _post(theme: Theme, n: int, day: date, rng: random.Random) -> Item:
    opening = f"{LEADS[n]} {theme.posts[n % len(theme.posts)]}"
    lines = rng.sample(theme.filler, 2)
    item = Item(theme, "post", day, opening, "")
    if n == 2:
        lines.insert(1, theme.facts[4].text)
        item.facts = [4]
    if n == 6:
        lines.insert(1, theme.facts[5].text)
        item.facts = [5]
    if n == 4:
        lines.append(theme.near_misses[2])
    if n in (1, 3, 5):
        item.comment_facts = [{1: 1, 3: 2, 5: 3}[n]]
    item.body = f"{opening}\n\n" + " ".join(lines) + "\n\nWhat would you do?"
    return item


def _discuss(item: Item, rng: random.Random) -> None:
    """Comments under the item, from people who follow its theme, with replies."""
    crowd = [name for name, (_, themes) in PEOPLE.items() if item.theme.key in themes]
    count = rng.randint(4, 10)
    messages: list[ParsedMessage] = []
    facts = [item.theme.comment_facts[c] for c in item.comment_facts]
    texts: list[tuple[str, str]] = [(f.person, f.text) for f in facts]
    while len(texts) < count:
        who = rng.choice(crowd)
        what = rng.choice(item.theme.comments if rng.random() < 0.7 else GENERIC_COMMENTS)
        texts.append((who, what))
    rng.shuffle(texts)
    for who, what in texts:
        top = len(messages)
        messages.append(
            ParsedMessage(
                author_name=who,
                author_headline=PEOPLE[who][0],
                text=what,
                posted_label=f"{rng.randint(1, 9)}w",
            )
        )
        if rng.random() < 0.35:
            first = who.split()[0]
            reply = rng.choice(
                (f"Thanks, {first}!", f"Good point, {first}.", f"Agreed, {first}. More soon.")
            )
            messages.append(
                ParsedMessage(
                    author_name=OWNER,
                    author_headline=OWNER_LINE,
                    is_post_author=True,
                    text=reply,
                    posted_label="1w",
                    thread=top,
                    reply_to=top,
                )
            )
    item.comments = messages


def questions(items: list[Item]) -> list[Question]:
    """Questions with known answers, asked in other words than the text uses."""
    out: list[Question] = []
    for theme in THEMES:
        mine = [it for it in items if it.theme is theme]
        for f, fact in enumerate(theme.facts):
            holder = next(it for it in mine if f in it.facts)
            out.append(Question("fact", fact.question, frozenset({holder.id})))
        for c, said in enumerate(theme.comment_facts):
            holder = next(it for it in mine if c in it.comment_facts)
            out.append(Question("comment", said.question, frozenset({holder.id})))
        # The month of its second article: everything on the theme from that month.
        when = next(it for it in mine if it.kind == "article" and it.title == theme.titles[1]).day
        same_month = {
            it.id for it in mine if (it.day.year, it.day.month) == (when.year, when.month)
        }
        month = f"{MONTHS[when.month - 1]} {when.year}"
        out.append(
            Question(
                "when", f"What did I write about {theme.phrase} in {month}?", frozenset(same_month)
            )
        )
        out.append(
            Question(
                "broad",
                f"What have people said in the comments about {theme.phrase}?",
                frozenset(it.id for it in mine if it.comments),
            )
        )
    from scripts.eval.corpus import UNANSWERABLE

    out += [Question("absent", q, frozenset()) for q in UNANSWERABLE]
    return out


def build(home: Path, embedder: EmbeddingProvider, seed: int = 7) -> list[Question]:
    """Build the library in ``home`` and return the questions about it."""
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    save_settings(home, owner_name=OWNER)
    clock = FixedClock()
    items = plan(seed)

    def open_home(**fakes: object) -> Container:
        return build_container(
            Settings.load(home),
            embedder=embedder,
            chat=FakeChat(),
            clock=clock,
            **fakes,  # type: ignore[arg-type]
        )

    with open_home() as c:
        c.seed_topics().execute(DEFAULT_TOPICS)

    for item in items:
        thread = ParsedThread(messages=tuple(item.comments))
        pasted = "\n\n".join(f"{m.author_name}\n{m.text}" for m in item.comments)
        if item.kind == "article":
            extraction = part3_extraction(
                title=item.title,
                body_markdown=item.body,
                summary=f"{item.title}: notes on {item.theme.phrase}.",
                topics=item.theme.topics,
                entities=(),
                series_name=None,
                series_part=None,
            )
            with open_home(
                extractor=FakeExtractor(extraction), thread_parser=FakeThreadParser(thread)
            ) as c:
                added = c.ingest_article().execute(
                    IngestArticleCommand(
                        f"{item.title}\n\n{item.body}", item.announcement, published_on=item.day
                    )
                )
                item.id = added.article.id
                c.index_article().execute(added.article.id)
                drafts = c.preview_comments().execute(NodeId(item.id), pasted, OWNER)
                c.save_comments().execute(NodeId(item.id), drafts.messages)
        else:
            with open_home(
                post_classifier=FakePostClassifier(item.theme.topics),
                thread_parser=FakeThreadParser(thread),
            ) as c:
                post = (
                    c.ingest_post()
                    .execute(IngestPostCommand(item.body, published_on=item.day))
                    .post
                )
                item.id = post.id
                drafts = c.preview_comments().execute(post.id, pasted, OWNER)
                c.save_comments().execute(post.id, drafts.messages)
        clock.advance(hours=1)
    return questions(items)
