from datetime import date
from pathlib import Path
from typing import Any

import yaml

from postloom.adapters.vault.markdown_vault import MarkdownVault
from postloom.domain.content import Article, Post, Series, Topic


def read_note(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


ARTICLE = Article(
    title="Measuring What Matters - Part 3",
    body_markdown="## Metrics\n\nHit rate, precision, recall.",
    summary="How to measure a semantic cache.",
    url="https://www.linkedin.com/pulse/x",
    published_on=date(2026, 10, 12),
    series=Series("Semantic Caching for AI Agents"),
    series_part=3,
    hashtags=("RAG",),
    entities=("LangGraph",),
)
POST = Post(key=ARTICLE.slug, text="Read part 3 👇", banner_path="assets/part3.png")
TOPICS = [Topic("RAG"), Topic("AI Agents")]


def test_article_note_is_obsidian_friendly(tmp_path: Path) -> None:
    path = MarkdownVault(tmp_path).write_article(ARTICLE, POST, TOPICS)

    assert path == tmp_path / "articles" / "measuring-what-matters-part-3.md"
    meta, body = read_note(path)
    assert meta["id"] == "article:measuring-what-matters-part-3"
    assert meta["topics"] == ["[[RAG]]", "[[AI Agents]]"]
    assert meta["post"] == "[[posts/measuring-what-matters-part-3|Announcement post]]"
    assert meta["published_on"] == date(2026, 10, 12)
    assert meta["series_part"] == 3
    assert meta["summary"] == "How to measure a semantic cache."
    assert body.startswith("\n# Measuring What Matters - Part 3\n\n## Metrics")


def test_post_note_links_back_and_embeds_the_banner(tmp_path: Path) -> None:
    MarkdownVault(tmp_path).write_article(ARTICLE, POST, TOPICS)
    meta, body = read_note(tmp_path / "posts" / "measuring-what-matters-part-3.md")
    assert meta["announces"] == "[[articles/measuring-what-matters-part-3|" + ARTICLE.title + "]]"
    assert "![[assets/part3.png]]" in body
    assert "👇" in body


def test_empty_fields_are_left_out_of_frontmatter(tmp_path: Path) -> None:
    bare = Article(title="Bare", body_markdown="Text")
    path = MarkdownVault(tmp_path).write_article(bare, Post(key=bare.slug, text="t"), [])
    meta, _ = read_note(path)
    assert set(meta) == {"id", "type", "title", "post"}


def test_topic_notes_keep_human_names_so_wikilinks_resolve(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    assert vault.write_topic(Topic("AI Agents")).name == "AI Agents.md"
    assert vault.write_topic(Topic("CI/CD: Pipelines?")).name == "CI-CD- Pipelines-.md"


def test_rewrites_are_atomic_and_leave_no_temp_files(tmp_path: Path) -> None:
    vault = MarkdownVault(tmp_path)
    vault.write_article(ARTICLE, POST, TOPICS)
    vault.write_article(ARTICLE, POST, TOPICS[:1])
    leftovers = [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]
    assert leftovers == []
    meta, _ = read_note(tmp_path / "articles" / "measuring-what-matters-part-3.md")
    assert meta["topics"] == ["[[RAG]]"]
