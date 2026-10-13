"""Markdown vault: the user's source of truth, readable and editable in Obsidian.

Layout::

    <root>/
      articles/<slug>.md      article body + metadata, links to its post and topics
      posts/<slug>.md         the announcement post, links back to its article
      topics/<Topic Name>.md  one note per topic, so [[RAG]] resolves in Obsidian

Notes carry YAML frontmatter (Obsidian "properties") and ``[[wikilinks]]``, so the folder
works as an Obsidian vault with a graph view, with no plugins required. The SQLite index is
derived from these files and can always be rebuilt from them.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from postloom.domain.content import Article, Post, Topic

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')


class MarkdownVault:
    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------ public
    def write_article(self, article: Article, post: Post, topics: Sequence[Topic]) -> Path:
        article_path = self.root / "articles" / f"{article.slug}.md"
        post_path = self.root / "posts" / f"{post.key}.md"
        article_link = _wikilink(f"articles/{article.slug}", article.title)
        post_link = _wikilink(f"posts/{post.key}", "Announcement post")

        article_meta: dict[str, Any] = {
            "id": article.id,
            "type": "article",
            "title": article.title,
            "url": article.url,
            "published_on": article.published_on,
            "series": article.series.name if article.series else None,
            "series_part": article.series_part,
            "topics": [_wikilink(_topic_filename(t)) for t in topics],
            "post": post_link,
            "hashtags": list(article.hashtags),
            "entities": list(article.entities),
        }
        article_body = [f"# {article.title}", ""]
        if article.summary:
            article_body += [f"> {article.summary}", ""]
        article_body.append(article.body_markdown)
        _write_note(article_path, article_meta, "\n".join(article_body))

        post_meta: dict[str, Any] = {
            "id": post.id,
            "type": "post",
            "url": post.url,
            "published_on": post.published_on,
            "announces": article_link,
            "hashtags": list(post.hashtags),
            "links": list(post.links),
            "banner": post.banner_path,
        }
        post_body = [post.text]
        if post.banner_path:
            post_body = [f"![[{post.banner_path}]]", "", *post_body]
        _write_note(post_path, post_meta, "\n".join(post_body))
        return article_path

    def write_topic(self, topic: Topic) -> Path:
        path = self.root / "topics" / f"{_topic_filename(topic)}.md"
        meta: dict[str, Any] = {"id": topic.id, "type": "topic", "name": topic.name}
        body = f"# {topic.name}\n\n{topic.description}".rstrip()
        _write_note(path, meta, body)
        return path


# ---------------------------------------------------------------------- helpers
def _topic_filename(topic: Topic) -> str:
    """Keep the human name (so ``[[AI Agents]]`` resolves) but strip unsafe characters."""
    return _UNSAFE_FILENAME.sub("-", topic.name).strip() or "topic"


def _wikilink(target: str, alias: str | None = None) -> str:
    return f"[[{target}|{alias}]]" if alias else f"[[{target}]]"


def _write_note(path: Path, meta: dict[str, Any], body: str) -> None:
    clean = {k: v for k, v in meta.items() if v not in (None, [], "")}
    front = yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, width=1000)
    _atomic_write(path, f"---\n{front}---\n\n{body.rstrip()}\n")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
