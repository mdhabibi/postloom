"""Request bodies (validated with Pydantic) and JSON views of use-case results."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from postloom.application.use_cases import (
    Answer,
    ArticleDetail,
    ArticleSummary,
    DiscussionPreview,
    DraftMessage,
    IndexResult,
    IngestArticleResult,
    SaveResult,
    SearchResults,
)

Json = dict[str, Any]


# -- requests ---------------------------------------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsUpdate(_Request):
    """Only the fields present in the request are changed."""

    gemini_api_key: str | None = Field(default=None, max_length=512)
    """A new key to save, or null/empty to remove the saved key."""
    owner_name: str | None = Field(default=None, max_length=200)
    """Your name as LinkedIn shows it, to recognise your own replies."""


class CommentsPreviewRequest(_Request):
    article_id: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=300_000)


class DraftMessageModel(_Request):
    author_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
    author_headline: str = Field(default="", max_length=500)
    is_own: bool = False
    posted_label: str = Field(default="", max_length=40)
    thread: int | None = Field(default=None, ge=0)
    reply_to: int | None = Field(default=None, ge=0)
    profile_url: str | None = Field(default=None, max_length=500)

    def to_draft(self) -> DraftMessage:
        return DraftMessage(
            author_name=self.author_name,
            text=self.text,
            author_headline=self.author_headline,
            is_own=self.is_own,
            posted_label=self.posted_label,
            thread=self.thread,
            reply_to=self.reply_to,
            profile_url=self.profile_url or None,
        )


class SaveCommentsRequest(_Request):
    article_id: str = Field(min_length=1, max_length=300)
    messages: list[DraftMessageModel] = Field(min_length=1, max_length=1000)


class IngestRequest(_Request):
    article_text: str = Field(min_length=1, max_length=400_000)
    post_text: str = Field(min_length=1, max_length=50_000)
    article_url: str | None = Field(default=None, max_length=2000)
    post_url: str | None = Field(default=None, max_length=2000)
    published_on: date | None = None


class HistoryMessage(_Request):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=20_000)


class AskRequest(_Request):
    question: str = Field(min_length=1, max_length=4000)
    article_id: str | None = Field(default=None, max_length=300)
    history: list[HistoryMessage] = Field(default_factory=list[HistoryMessage], max_length=40)


# -- responses --------------------------------------------------------------------
def article_summary(summary: ArticleSummary) -> Json:
    return {
        "id": summary.id,
        "title": summary.title,
        "summary": summary.summary,
        "published_on": summary.published_on.isoformat() if summary.published_on else None,
        "url": summary.url,
        "topics": [{"name": t.name, "grade": t.grade.value} for t in summary.topics],
        "series": summary.series,
        "series_part": summary.series_part,
    }


def article_detail(detail: ArticleDetail) -> Json:
    article = detail.article
    discussion = [
        {
            "id": c.id,
            "author_name": c.author_name,
            "author_headline": c.author_headline,
            "is_own": c.is_own,
            "text": c.text,
            "posted_label": c.posted_label,
            "thread": c.thread,
            "reply_to": c.reply_to,
            "reply_to_name": c.reply_to_name,
            "depth": c.depth,
        }
        for c in detail.discussion
    ]
    return {
        **article_summary(detail.summary),
        "body_markdown": article.body_markdown,
        "entities": list(article.entities),
        "hashtags": list(article.hashtags),
        "posts": [
            {
                "text": post.text,
                "url": post.url,
                "links": list(post.links),
                "hashtags": list(post.hashtags),
            }
            for post in detail.posts
        ],
        "discussion": discussion,
    }


def comments_preview(preview: DiscussionPreview) -> Json:
    return {
        "article_id": preview.article_id,
        "warnings": list(preview.warnings),
        "messages": [
            {
                "author_name": m.author_name,
                "text": m.text,
                "author_headline": m.author_headline,
                "is_own": m.is_own,
                "posted_label": m.posted_label,
                "thread": m.thread,
                "reply_to": m.reply_to,
                "profile_url": m.profile_url,
                "already_saved": m.already_saved,
                "known_person": m.known_person,
            }
            for m in preview.messages
        ],
    }


def comments_saved(result: SaveResult) -> Json:
    return {
        "added": result.added,
        "already_saved": result.already_saved,
        "new_people": result.new_people,
    }


def ingest_result(
    result: IngestArticleResult, index: IndexResult | None, index_error: str | None
) -> Json:
    indexed: Json | None = None
    if index is not None:
        indexed = {
            "chunks": index.chunks,
            "embedded": index.embedded,
            "reused": index.reused,
            "semantic": index.semantic,
        }
    return {
        "id": result.article.id,
        "title": result.article.title,
        "is_update": result.is_update,
        "topics": [t.name for t in result.topics],
        "series": result.article.series.name if result.article.series else None,
        "series_part": result.article.series_part,
        "entities": list(result.article.entities),
        "warnings": list(result.warnings),
        "note_path": str(result.note_path),
        "index": indexed,
        "index_error": index_error,
    }


def search_results(found: SearchResults) -> Json:
    return {
        "query": found.query,
        "methods": sorted(found.methods),
        "warnings": list(found.warnings),
        "results": [
            {
                "id": r.article_id,
                "title": r.title,
                "url": r.url,
                "passages": [
                    {
                        "heading": p.heading,
                        "excerpt": p.excerpt,
                        "matched_by": sorted(p.matched_by),
                        "similarity": p.similarity,
                    }
                    for p in r.passages
                ],
            }
            for r in found.results
        ],
    }


def answer(result: Answer) -> Json:
    return {
        "text": result.text,
        "grounded": result.grounded,
        "sources": [
            {
                "number": s.number,
                "article_id": s.article_id,
                "title": s.title,
                "section": s.section,
                "text": s.text,
            }
            for s in result.sources
        ],
    }
