"""Request bodies (validated with Pydantic) and JSON views of use-case results."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from postloom.application.use_cases import (
    Answer,
    ArticleDetail,
    ArticleSummary,
    IndexResult,
    IngestArticleResult,
    SearchResults,
)

Json = dict[str, Any]


# -- requests ---------------------------------------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsUpdate(_Request):
    gemini_api_key: str | None = Field(default=None, max_length=512)
    """A new key to save, or null/empty to remove the saved key."""


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
