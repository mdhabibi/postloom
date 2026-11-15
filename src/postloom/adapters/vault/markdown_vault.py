"""Markdown vault: the user's source of truth, readable and editable in Obsidian.

Layout::

    <root>/
      articles/<key>.md       article body + metadata, links to its post and topics
      posts/<key>.md          the announcement post, links back to its article
      topics/<Topic Name>.md  one note per topic, so [[RAG]] resolves in Obsidian
      discussions/<key>.md    every comment thread under a post, as conversations
      people/<Name>.md        one note per commenter, so [[Jane Example]] resolves
      .postloom/              hidden from Obsidian: edges.jsonl (where each link came
                              from), vault.json (note format), trash/

Notes carry YAML frontmatter (Obsidian "properties") and ``[[wikilinks]]``, so the folder
works as an Obsidian vault with a graph view, with no plugins required.

Everything postloom knows is in this folder, and ``reader.read_vault`` reads it back, so
the SQLite index can always be rebuilt from it. Notes without postloom's properties are
the user's own and are never read, overwritten or removed.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from postloom.adapters.vault.notes import (
    DATA_DIR,
    TYPES,
    Meta,
    NoteError,
    atomic_write,
    render_note,
    safe_name,
    split_note,
    wikilink,
)
from postloom.adapters.vault.reader import NOTES_HEADING, note_files, read_vault
from postloom.application.ports.vault import (
    VAULT_FORMAT,
    NoteStamps,
    Stamp,
    VaultChanges,
    VaultSnapshot,
)
from postloom.domain.content import Article, Post, Topic
from postloom.domain.discussion import Comment, conversation_depth, conversation_order
from postloom.domain.graph import NodeId
from postloom.domain.people import Person

FORMAT_FILE = "vault.json"
TRASH_DIR = "trash"


class MemoryNoteStamps:
    """Stamps kept in memory: for tests and for a vault without an index next to it."""

    def __init__(self) -> None:
        self._stamps: dict[str, Stamp] = {}

    def all(self) -> dict[str, Stamp]:
        return dict(self._stamps)

    def put(self, path: str, stamp: Stamp) -> None:
        self._stamps[path] = stamp

    def remove(self, path: str) -> None:
        self._stamps.pop(path, None)

    def replace_all(self, stamps: Mapping[str, Stamp]) -> None:
        self._stamps = dict(stamps)


class MarkdownVault:
    def __init__(self, root: Path, stamps: NoteStamps | None = None) -> None:
        self.root = root
        self._stamps: NoteStamps = stamps if stamps is not None else MemoryNoteStamps()
        self._lock = threading.RLock()
        self._person_paths: dict[NodeId, Path] | None = None
        """Which note belongs to which person; filled from the notes on first use."""

    # ------------------------------------------------------------------ writing
    def write_article(
        self,
        article: Article,
        post: Post,
        topics: Sequence[Topic],
        related: Sequence[Article] = (),
    ) -> Path:
        article_path = self._article_path(article)
        article_link = wikilink(f"articles/{article.slug}", article.title)
        post_link = wikilink(f"posts/{post.key}", "Announcement post")

        article_meta: Meta = {
            "id": article.id,
            "type": "article",
            "title": article.title,
            "url": article.url,
            "published_on": article.published_on,
            "series": article.series.name if article.series else None,
            "series_part": article.series_part,
            "topics": [wikilink(_topic_filename(t)) for t in topics],
            "related": [wikilink(f"articles/{r.slug}", r.title) for r in related],
            "post": post_link,
            "hashtags": list(article.hashtags),
            "entities": list(article.entities),
            "summary": article.summary,
        }
        self._write(article_path, article_meta, f"# {article.title}\n\n{article.body_markdown}")

        post_meta: Meta = {
            "id": post.id,
            "type": "post",
            "url": post.url,
            "published_on": post.published_on,
            "announces": article_link,
            "hashtags": list(post.hashtags),
            "links": list(post.links),
            "banner": post.banner_path,
        }
        post_body = post.text
        if post.banner_path:
            post_body = f"![[{post.banner_path}]]\n\n{post.text}"
        self._write(self._post_path(post), post_meta, post_body)
        return article_path

    def write_discussion(
        self,
        article: Article,
        post: Post,
        comments: Sequence[Comment],
        people: Mapping[NodeId, Person],
    ) -> Path:
        path = self._discussion_path(post.key)
        if not comments:
            self._remove(path)
            return path
        with self._lock:
            links = {
                c.author: self._person_link(people.get(c.author), c.author_name)
                for c in comments
                if not c.is_own
            }
        meta: Meta = {
            "id": f"discussion:{post.key}",
            "type": "discussion",
            "article": wikilink(f"articles/{article.slug}", article.title),
            "post": wikilink(f"posts/{post.key}", "Announcement post"),
            "comments": len(comments),
            "people": sorted(set(links.values())),
        }
        by_id = {c.id: c for c in comments}
        numbers = {c.id: n for n, c in enumerate(sorted(comments, key=lambda c: c.position))}
        lines = [f"# Discussion: {article.title}"]
        for comment in conversation_order(comments):
            if comment.reply_to is None or comment.reply_to not in by_id:
                lines += ["", f"## Thread started by {comment.author_name}", ""]
            quote = ">" * (conversation_depth(comment, by_id) + 1)
            who = "You" if comment.is_own else links[comment.author]
            person = people.get(comment.author)
            headline = person.headline if person is not None else None
            label = ", ".join(x for x in (headline, comment.posted_label) if x)
            shown = f"{quote} **{who}**" + (f" ({label})" if label else "")
            lines.append(f"{shown} {_marker(comment, numbers)}")
            lines += [f"{quote} {row}" if row else quote for row in comment.text.splitlines()]
            lines.append("")
        self._write(path, meta, "\n".join(lines))
        return path

    def write_person(self, person: Person, articles: Sequence[Article]) -> Path:
        with self._lock:
            previous = self._people().get(person.id)
            path = self._person_path(person)
        if previous is not None and previous != path:
            self._remove(previous)  # renamed: the note follows the name
        meta: Meta = {
            "id": person.id,
            "type": "person",
            "name": person.name,
            "linkedin": person.profile.url if person.profile else None,
            "headline": person.headline,
            "tags": list(person.tags),
            "articles": [wikilink(f"articles/{a.slug}", a.title) for a in articles],
            "headlines": [
                {
                    "headline": o.headline,
                    "from": o.observed_at.isoformat(),
                    "until": o.superseded_at.isoformat() if o.superseded_at else None,
                }
                for o in person.observations
            ],
        }
        lines = [f"# {person.name}"]
        if person.headline:
            lines += ["", person.headline]
        history = [o for o in person.observations if o.superseded_at is not None]
        if history:
            lines += ["", "## Earlier headlines", ""]
            lines += [f"- {o.headline} (until {o.superseded_at:%Y-%m-%d})" for o in history]
        if person.notes:
            lines += ["", NOTES_HEADING, "", person.notes]
        self._write(path, meta, "\n".join(lines))
        return path

    def write_topic(self, topic: Topic) -> Path:
        path = self._topic_path(topic)
        meta: Meta = {"id": topic.id, "type": "topic", "name": topic.name}
        self._write(path, meta, f"# {topic.name}\n\n{topic.description}".rstrip())
        return path

    # ----------------------------------------------------------------- removing
    def remove_article(self, article: Article, post: Post | None) -> None:
        self._remove(self._article_path(article))
        if post is not None:
            self._remove(self._post_path(post))
            self._remove(self._discussion_path(post.key))

    def remove_person(self, person: Person) -> None:
        with self._lock:
            path = self._people().pop(person.id, None)
        if path is not None:
            self._remove(path)

    def remove_topic(self, topic: Topic) -> None:
        self._remove(self._topic_path(topic))

    def prune(self, keep: Collection[str], protect: Collection[str] = ()) -> list[str]:
        trash = self.root / DATA_DIR / TRASH_DIR / time.strftime("%Y%m%d-%H%M%S")
        moved: list[str] = []
        for _, path in note_files(self.root):
            relative = self._relative(path)
            note_id = _id_of(path)
            if note_id is None or note_id in keep or relative in protect:
                continue
            target = trash / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
            self._stamps.remove(relative)
            moved.append(relative)
        if moved:
            with self._lock:
                self._person_paths = None
        return moved

    # ------------------------------------------------------------------ reading
    def read(self) -> VaultSnapshot:
        with self._lock:
            self._person_paths = None  # the notes may have changed outside postloom
        return read_vault(self.root, self.format)

    def changes(self) -> VaultChanges:
        known = self._stamps.all()
        current = self._scan()
        return VaultChanges(
            added=tuple(sorted(p for p in current if p not in known)),
            modified=tuple(sorted(p for p, s in current.items() if p in known and known[p] != s)),
            removed=tuple(sorted(p for p in known if p not in current)),
        )

    def mark_synced(self) -> None:
        self._stamps.replace_all(self._scan())

    @property
    def format(self) -> int:
        marker = self.root / DATA_DIR / FORMAT_FILE
        try:
            data: object = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # No marker: a vault from before formats were recorded, or a brand-new one.
            return 1 if any(True for _ in note_files(self.root)) else 0
        version: object = cast(dict[str, object], data).get("format") if data else None
        return version if isinstance(version, int) else 1

    def mark_format(self) -> None:
        marker = self.root / DATA_DIR / FORMAT_FILE
        atomic_write(marker, json.dumps({"format": VAULT_FORMAT}) + "\n")

    # ------------------------------------------------------------------ helpers
    def _article_path(self, article: Article) -> Path:
        return self.root / "articles" / f"{article.slug}.md"

    def _post_path(self, post: Post) -> Path:
        return self.root / "posts" / f"{post.key}.md"

    def _discussion_path(self, post_key: str) -> Path:
        return self.root / "discussions" / f"{post_key}.md"

    def _topic_path(self, topic: Topic) -> Path:
        return self.root / "topics" / f"{_topic_filename(topic)}.md"

    def _people(self) -> dict[NodeId, Path]:
        if self._person_paths is None:
            found: dict[NodeId, Path] = {}
            directory = self.root / "people"
            for path in sorted(directory.glob("*.md")) if directory.is_dir() else ():
                meta = _meta_of(path)
                written = meta.get("id") if meta is not None else None
                if isinstance(written, str) and written.startswith("person:"):
                    found.setdefault(NodeId(written), path)
            self._person_paths = found
        return self._person_paths

    def _person_path(self, person: Person) -> Path:
        """The person's note: named after them, unless someone else has that name.

        Two people can share a name, and file names are case-insensitive on macOS and
        Windows, so the second one gets their identity in brackets after the name.
        """
        paths = self._people()
        base = safe_name(person.name, "person")
        unique = f"{base} ({person.id.partition(':')[2]})"
        current = paths.get(person.id)
        if current is not None and current.stem in (base, unique):
            return current
        directory = self.root / "people"
        taken = {p.name.casefold() for owner, p in paths.items() if owner != person.id}
        name = f"{base}.md"
        if name.casefold() in taken or _is_someone_elses(directory / name, person.id):
            name = f"{unique}.md"
        paths[person.id] = directory / name
        return paths[person.id]

    def _person_link(self, person: Person | None, name: str) -> str:
        if person is None:
            return wikilink(safe_name(name, "person"))
        return wikilink(self._person_path(person).stem, name)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _write(self, path: Path, meta: Meta, body: str) -> None:
        text = render_note(meta, body)
        try:
            unchanged = path.read_text(encoding="utf-8") == text
        except (OSError, UnicodeDecodeError):
            unchanged = False
        if not unchanged:
            atomic_write(path, text)
        self._stamps.put(self._relative(path), _stamp(path))

    def _remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        self._stamps.remove(self._relative(path))

    def _scan(self) -> dict[str, Stamp]:
        return {self._relative(path): _stamp(path) for _, path in note_files(self.root)}


def _stamp(path: Path) -> Stamp:
    status = path.stat()
    return (status.st_mtime_ns, status.st_size)


def _meta_of(path: Path) -> Meta | None:
    try:
        parsed = split_note(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, NoteError):
        return None
    return parsed[0] if parsed is not None else None


def _id_of(path: Path) -> str | None:
    """The ``id`` of a note postloom wrote; None for anyone else's note."""
    meta = _meta_of(path)
    if meta is None or meta.get("type") not in TYPES:
        return None
    written = meta.get("id")
    return written if isinstance(written, str) else None


def _is_someone_elses(path: Path, person: NodeId) -> bool:
    """True when a file already has this name and it isn't this person's note."""
    if not path.exists():
        return False
    meta = _meta_of(path)
    return meta is None or meta.get("id") != person


def _topic_filename(topic: Topic) -> str:
    """Keep the human name (so ``[[AI Agents]]`` resolves) but strip unsafe characters."""
    return safe_name(topic.name, "topic")


def _marker(comment: Comment, numbers: Mapping[NodeId, int]) -> str:
    """What the note can't show in prose, hidden in an Obsidian comment (``%%...%%``):
    the message's place in the pasted order, who wrote it, and which message it answers."""
    data: dict[str, Any] = {"n": numbers[comment.id], "by": comment.author}
    data["name"] = comment.author_name
    if comment.posted_label:
        data["label"] = comment.posted_label
    if comment.reply_to is not None and comment.reply_to in numbers:
        data["re"] = numbers[comment.reply_to]
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"%%{encoded.replace('%', chr(92) + 'u0025')}%%"
