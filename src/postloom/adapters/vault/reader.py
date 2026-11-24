"""Read the vault back: every note postloom wrote, parsed into domain entities.

The writer (``markdown_vault``) and this reader are inverses: writing a graph and reading
it back gives the same entities, which is what makes the index rebuildable. Notes are
also edited by people, so reading is forgiving about what a person plausibly changes
(text, a title, a topic link) and strict about what it can't interpret: a note that looks
like postloom's but can't be read is reported, never guessed at and never skipped
silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from postloom.adapters.vault.notes import (
    FOLDERS,
    TYPES,
    Meta,
    NoteError,
    body_after_heading,
    link_target,
    split_note,
)
from postloom.application.ports.vault import (
    VAULT_FORMAT,
    ArticleNote,
    NoteProblem,
    PostNote,
    VaultSnapshot,
)
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import OWNER, Comment
from postloom.domain.entities import Category, Entity
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId, NodeKind, node_id
from postloom.domain.media import Media, MediaKind, subtitle_text
from postloom.domain.people import Person, ProfileObservation, ProfileUrl
from postloom.domain.text import extract_hashtags, extract_urls

COMMENT_HEAD = re.compile(r"^(>+) \*\*.*\*\* ?.*%%(\{.*\})%%\s*$")
NOTES_HEADING = "## Notes"


def note_files(root: Path) -> Iterator[tuple[str, Path]]:
    """(folder, path) for every Markdown file in postloom's folders, in a stable order."""
    for folder in FOLDERS:
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.is_file() and not path.name.startswith("."):
                yield folder, path


def read_vault(root: Path, vault_format: int = VAULT_FORMAT) -> VaultSnapshot:
    reader = _Reader(root, legacy=vault_format < VAULT_FORMAT)
    return reader.read()


class _Reader:
    def __init__(self, root: Path, *, legacy: bool) -> None:
        self._root = root
        self._legacy = legacy
        self._problems: list[NoteProblem] = []
        self._topics: dict[NodeId, Topic] = {}
        self._topic_by_file: dict[str, NodeId] = {}
        self._people: dict[NodeId, Person] = {}
        self._entities: dict[NodeId, Entity] = {}
        self._person_alias: dict[str, NodeId] = {}
        """The id written in a note -> the person's id now (it changes when someone adds
        a profile link to the note)."""

    def read(self) -> VaultSnapshot:
        notes: dict[str, list[tuple[Path, Meta, str]]] = {kind: [] for kind in TYPES}
        for _, path in note_files(self._root):
            try:
                parsed = split_note(path.read_text(encoding="utf-8"))
            except NoteError as error:
                self._problem(path, str(error))
                continue
            except (OSError, UnicodeDecodeError) as error:
                self._problem(path, f"the file can't be read ({error})")
                continue
            if parsed is None:
                continue  # no frontmatter: the user's own note
            meta, body = parsed
            kind = meta.get("type")
            if isinstance(kind, str) and kind in notes:
                notes[kind].append((path, meta, body))

        for path, meta, body in notes["topic"]:
            with self._reporting(path):
                self._topic(path, meta, body)
        for path, meta, body in notes["person"]:
            with self._reporting(path):
                self._person(path, meta, body)
        for path, meta, _ in notes["entity"]:
            with self._reporting(path):
                self._entity(meta)
        articles: list[ArticleNote] = []
        for path, meta, body in notes["article"]:
            with self._reporting(path):
                note = self._article(meta, body)
                articles.append(replace(note, path=path.relative_to(self._root).as_posix()))
        posts: list[PostNote] = []
        for path, meta, body in notes["post"]:
            with self._reporting(path):
                note = self._post(meta, body)
                posts.append(replace(note, path=path.relative_to(self._root).as_posix()))
        comments: list[Comment] = []
        for path, meta, body in notes["discussion"]:
            with self._reporting(path):
                comments.extend(self._discussion(meta, body))

        return VaultSnapshot(
            topics=tuple(self._topics.values()),
            articles=tuple(articles),
            posts=tuple(posts),
            comments=tuple(comments),
            people=tuple(self._people.values()),
            entities=tuple(self._entities.values()),
            problems=tuple(self._problems),
        )

    # -- plumbing -----------------------------------------------------------------
    @contextmanager
    def _reporting(self, path: Path) -> Generator[None, None, None]:
        """Turn a note that can't be read into a reported problem."""
        try:
            yield
        except (NoteError, DomainError) as error:
            self._problem(path, str(error))

    def _problem(self, path: Path, reason: str) -> None:
        self._problems.append(NoteProblem(path.relative_to(self._root).as_posix(), reason))

    # -- what the writing mentions ---------------------------------------------------
    def _entity(self, meta: Meta) -> None:
        category = _text(meta, "category")
        try:
            kind = Category(category)
        except ValueError as error:
            choices = ", ".join(c.value for c in Category)
            raise NoteError(f"`category` must be one of {choices}") from error
        entity = Entity(
            key=_key(meta, NodeKind.ENTITY),
            name=_text(meta, "name"),
            category=kind,
            url=_text(meta, "url") or None,
            aliases=tuple(_strings(meta, "aliases")),
        )
        self._entities[entity.id] = entity

    # -- topics -------------------------------------------------------------------
    def _topic(self, path: Path, meta: Meta, body: str) -> None:
        name = _text(meta, "name") or path.stem
        topic = Topic(name=name, description=body_after_heading(body))
        self._topics[topic.id] = topic
        self._topic_by_file[path.stem.casefold()] = topic.id

    def _topic_link(self, value: object) -> NodeId:
        target = link_target(value) or (value.strip() if isinstance(value, str) else "")
        if not target:
            raise NoteError(f"`topics` has an entry that isn't a topic link: {value!r}")
        name = target.rsplit("/", 1)[-1]
        known = self._topic_by_file.get(name.casefold())
        if known is not None:
            return known
        topic = Topic(name=name)  # a topic the author added by hand in the note
        self._topics.setdefault(topic.id, topic)
        self._topic_by_file[name.casefold()] = topic.id
        return topic.id

    # -- people -------------------------------------------------------------------
    def _person(self, path: Path, meta: Meta, body: str) -> None:
        name = _text(meta, "name") or path.stem
        linkedin = _text(meta, "linkedin")
        try:
            profile = ProfileUrl.parse(linkedin) if linkedin else None
        except DomainError as error:
            raise NoteError("`linkedin` isn't a LinkedIn profile link") from error
        person = Person(
            name=name,
            profile=profile,
            observations=self._observations(path, meta),
            notes=_section(body, NOTES_HEADING),
            tags=tuple(dict.fromkeys(_strings(meta, "tags"))),
        )
        written_id = _text(meta, "id")
        if profile is None and written_id and not written_id.startswith("person:~"):
            # The link was removed from the note; a person can't lose their identity.
            raise NoteError("the `linkedin` link is missing; restore it to keep this person")
        self._people[person.id] = person
        if written_id:
            self._person_alias[written_id] = person.id

    def _observations(self, path: Path, meta: Meta) -> tuple[ProfileObservation, ...]:
        raw: object = meta.get("headlines")
        if isinstance(raw, list):
            found: list[ProfileObservation] = []
            for item in cast(list[object], raw):
                if not isinstance(item, dict):
                    raise NoteError("`headlines` must be a list of {headline, from, until}")
                entry = cast(dict[str, Any], item)
                headline = str(entry.get("headline") or "").strip()
                if not headline:
                    continue
                found.append(
                    ProfileObservation(
                        headline=headline,
                        observed_at=_moment(entry.get("from"), "headlines.from"),
                        superseded_at=(
                            _moment(entry["until"], "headlines.until")
                            if entry.get("until")
                            else None
                        ),
                    )
                )
            return tuple(found)
        headline = _text(meta, "headline")
        if not headline:
            return ()
        seen = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(microsecond=0)
        return (ProfileObservation(headline, seen),)

    def _author(self, written: object, name: str) -> NodeId:
        """The person a comment's ``by`` refers to; unknown authors get a record."""
        if not isinstance(written, str) or not written.startswith("person:"):
            raise NoteError(f"a comment by {name!r} has no valid `by`")
        if written == OWNER:
            return OWNER
        current = self._person_alias.get(written)
        if current is not None:
            return current
        if NodeId(written) in self._people:
            return NodeId(written)
        key = written.partition(":")[2]
        person = Person(name) if key.startswith("~") else Person(name, ProfileUrl(key))
        self._people.setdefault(person.id, person)  # the person's note was deleted
        return person.id

    # -- articles and posts ---------------------------------------------------------
    def _article(self, meta: Meta, body: str) -> ArticleNote:
        key = _key(meta, NodeKind.ARTICLE)
        text = body_after_heading(body)
        summary = _text(meta, "summary")
        if self._legacy and "summary" not in meta:
            summary, text = _legacy_summary(text)
        series = _text(meta, "series")
        part: object = meta.get("series_part")
        article = Article(
            title=_text(meta, "title") or _heading(body) or key,
            body_markdown=text,
            summary=summary,
            url=_text(meta, "url") or None,
            published_on=_day(meta.get("published_on"), "published_on"),
            series=Series(series) if series else None,
            series_part=int(part) if isinstance(part, int) and series else None,
            hashtags=tuple(_strings(meta, "hashtags")),
            entities=tuple(_strings(meta, "entities")),
            key=key,
            media=self._media(meta),
        )
        topics = tuple(dict.fromkeys(self._topic_link(v) for v in _items(meta, "topics")))
        related: list[NodeId] = []
        for value in _items(meta, "related"):
            target = link_target(value)
            if target is None:
                raise NoteError(f"`related` has an entry that isn't a link: {value!r}")
            other = node_id(NodeKind.ARTICLE, target.rsplit("/", 1)[-1])
            if other != article.id and other not in related:
                related.append(other)
        return ArticleNote(article, topics, tuple(related))

    def _post(self, meta: Meta, body: str) -> PostNote:
        banner = _text(meta, "banner") or None
        text = body.strip("\n").rstrip()
        if banner and text.startswith(f"![[{banner}]]"):
            text = text.removeprefix(f"![[{banner}]]").strip("\n")
        has_lists = "hashtags" in meta or "links" in meta
        post = Post(
            key=_key(meta, NodeKind.POST),
            text=text,
            url=_text(meta, "url") or None,
            published_on=_day(meta.get("published_on"), "published_on"),
            hashtags=tuple(_strings(meta, "hashtags") if has_lists else extract_hashtags(text)),
            links=tuple(_strings(meta, "links") if has_lists else extract_urls(text)),
            banner_path=banner,
            media=self._media(meta),
        )
        target = link_target(meta.get("announces"))
        announces = node_id(NodeKind.ARTICLE, target.rsplit("/", 1)[-1]) if target else None
        topics = tuple(dict.fromkeys(self._topic_link(v) for v in _items(meta, "topics")))
        return PostNote(post, announces, () if announces else topics)

    def _media(self, meta: Meta) -> tuple[Media, ...]:
        found: list[Media] = []
        for i, entry in enumerate(_items(meta, "media"), start=1):
            if not isinstance(entry, dict):
                raise NoteError(f"`media` entry {i} must have a `file` and a `kind`")
            fields = {str(k): v for k, v in cast(dict[object, Any], entry).items()}
            try:
                kind = MediaKind(_text(fields, "kind"))
                subtitles = _text(fields, "subtitles") or None
                media = Media(
                    file=_text(fields, "file"),
                    kind=kind,
                    caption=_text(fields, "caption"),
                    description=_text(fields, "description"),
                    described_by=_text(fields, "described_by") or None,
                    subtitles=subtitles,
                    transcript=self._transcript(subtitles),
                )
            except (ValueError, DomainError) as error:
                raise NoteError(f"`media` entry {i} isn't valid: {error}") from error
            found.append(media)
        return tuple(found)

    def _transcript(self, subtitles: str | None) -> str:
        if not subtitles:
            return ""
        try:
            return subtitle_text((self._root / subtitles).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            return ""  # the file was moved or deleted: the video stays, without its words

    # -- discussions ----------------------------------------------------------------
    def _discussion(self, meta: Meta, body: str) -> list[Comment]:
        target = link_target(meta.get("post"))
        written = _text(meta, "id")
        if target:
            post = node_id(NodeKind.POST, target.rsplit("/", 1)[-1])
        elif written.startswith("discussion:"):
            post = node_id(NodeKind.POST, written.partition(":")[2])
        else:
            raise NoteError("the note doesn't say which post it belongs to (`post`)")

        blocks = _comment_blocks(body)
        if not blocks and int(meta.get("comments") or 0) > 0:
            raise NoteError(
                "its comments can't be read (written by an older postloom, or the hidden "
                "`%%{...}%%` markers were removed)"
            )
        drafts: list[tuple[dict[str, Any], Comment]] = []
        for order, (marker, text) in enumerate(blocks):
            name = str(marker.get("name") or "").strip()
            if not name:
                raise NoteError("a comment's marker has no `name`")
            comment = Comment(
                post=post,
                author=self._author(marker.get("by"), name),
                author_name=name,
                text=text,
                position=order,
                posted_label=str(marker.get("label") or ""),
            )
            drafts.append((marker, comment))

        # Markers name the message each one answers by number; resolve to ids, then
        # derive each message's thread: the top of its chain of replies.
        by_number = {m.get("n"): c.id for m, c in drafts if isinstance(m.get("n"), int)}
        answers: dict[NodeId, NodeId | None] = {}
        for marker, comment in drafts:
            target = by_number.get(marker.get("re")) if "re" in marker else None
            answers[comment.id] = target if target != comment.id else None

        def top_of(comment_id: NodeId) -> NodeId:
            seen: set[NodeId] = set()
            current = comment_id
            while (above := answers.get(current)) is not None and current not in seen:
                seen.add(current)
                current = above
            return current

        ordered = sorted(
            enumerate(drafts),
            key=lambda item: (
                number if isinstance(number := item[1][0].get("n"), int) else len(drafts),
                item[0],
            ),
        )
        comments: list[Comment] = []
        for _, (_, comment) in ordered:
            reply_to = answers[comment.id]
            thread = top_of(comment.id) if reply_to is not None else None
            comments.append(
                replace(comment, position=len(comments), thread=thread, reply_to=reply_to)
            )
        return comments


def _comment_blocks(body: str) -> list[tuple[dict[str, Any], str]]:
    """Each comment's marker and text, in the order they appear in the note."""
    lines = body.replace("\r\n", "\n").split("\n")
    blocks: list[tuple[dict[str, Any], str]] = []
    i = 0
    while i < len(lines):
        head = COMMENT_HEAD.match(lines[i])
        if head is None:
            i += 1
            continue
        prefix = head.group(1)
        try:
            loaded: object = json.loads(head.group(2))
        except ValueError as error:
            raise NoteError(f"a comment's hidden marker is damaged (line {i + 1})") from error
        if not isinstance(loaded, dict):
            raise NoteError(f"a comment's hidden marker is damaged (line {i + 1})")
        i += 1
        rows: list[str] = []
        while i < len(lines) and COMMENT_HEAD.match(lines[i]) is None:
            line = lines[i]
            if line == prefix:
                rows.append("")
            elif line.startswith(prefix + " "):
                rows.append(line[len(prefix) + 1 :])
            else:
                break
            i += 1
        text = "\n".join(rows).strip()
        if not text:
            raise NoteError(f"a comment has no text (line {i})")
        blocks.append((cast(dict[str, Any], loaded), text))
    return blocks


# -- field helpers ------------------------------------------------------------------
def _text(meta: Meta, key: str) -> str:
    value: object = meta.get(key)
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        raise NoteError(f"`{key}` must be text")
    return str(value).strip()


def _items(meta: Meta, key: str) -> list[object]:
    value: object = meta.get(key)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in cast(list[object], value) if v not in (None, "")]
    if isinstance(value, str):
        return [value]  # Obsidian turns a one-item list into plain text
    raise NoteError(f"`{key}` must be a list")


def _strings(meta: Meta, key: str) -> list[str]:
    return [str(v).strip() for v in _items(meta, key) if str(v).strip()]


def _key(meta: Meta, kind: NodeKind) -> str:
    written = _text(meta, "id")
    prefix = f"{kind.value}:"
    if not written.startswith(prefix) or not written.removeprefix(prefix):
        raise NoteError(f"`id` is missing or doesn't start with `{prefix}`")
    return written.removeprefix(prefix)


def _day(value: object, key: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as error:
        raise NoteError(f"`{key}` isn't a date (use YYYY-MM-DD)") from error


def _moment(value: object, key: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip())
        except ValueError as error:
            raise NoteError(f"`{key}` isn't a date and time") from error
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _heading(body: str) -> str:
    first = body.strip("\n").partition("\n")[0]
    return first.removeprefix("# ").strip() if first.startswith("# ") else ""


def _section(body: str, heading: str) -> str:
    """The text under a ``## heading``, up to the end of the note."""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == heading:
            return "\n".join(lines[index + 1 :]).strip()
    return ""


def _legacy_summary(text: str) -> tuple[str, str]:
    """Format 1 wrote the summary as a quote under the title instead of a property."""
    if not text.startswith("> "):
        return "", text
    first, _, rest = text.partition("\n\n")
    if "\n" in first or not rest.strip():
        return "", text
    return first.removeprefix("> ").strip(), rest.strip("\n")
