"""Request bodies (validated with Pydantic) and JSON views of use-case results."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from postloom.adapters.llm.providers import ProviderSpec
from postloom.application.use_cases import (
    Answer,
    ArticleDetail,
    ArticleSummary,
    CommentView,
    DiscussionPreview,
    DraftMessage,
    GraphData,
    IndexResult,
    IngestArticleResult,
    IngestPostResult,
    OverviewData,
    PersonDetail,
    PersonSummary,
    RelatedLink,
    ReplyDraft,
    SaveResult,
    SearchResults,
    SuggestResult,
    SyncReport,
    TopicUsage,
)
from postloom.application.use_cases.usage import UsageSummary
from postloom.domain.content import Post

Json = dict[str, Any]


# -- requests ---------------------------------------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsUpdate(_Request):
    """Only the fields present in the request are changed; null removes a saved value."""

    provider: str | None = Field(default=None, max_length=40)
    api_key: str | None = Field(default=None, max_length=1024)
    """Saved for the chosen provider (the one in this request, else the current one)."""
    base_url: str | None = Field(default=None, max_length=500)
    models: dict[str, str | None] | None = Field(default=None, max_length=10)
    embeddings: Literal["local", "provider", "off"] | None = None
    local_embedding_model: str | None = Field(default=None, max_length=200)
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=100_000)
    owner_name: str | None = Field(default=None, max_length=200)
    """Your name as LinkedIn shows it, to recognise your own replies."""
    ollama_context: int | None = Field(default=None, ge=8192, le=1_048_576)


class ConnectionTest(_Request):
    """Check a provider before saving: with the given key, or the saved one."""

    provider: str = Field(min_length=1, max_length=40)
    api_key: str | None = Field(default=None, max_length=1024)
    base_url: str | None = Field(default=None, max_length=500)


class OllamaPull(_Request):
    base_url: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=120)


class OllamaStart(_Request):
    pass


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


class PersonUpdate(_Request):
    """Only the fields present are changed."""

    id: str = Field(min_length=1, max_length=300)
    profile_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = Field(default=None, max_length=50)


class ArticleUpdate(_Request):
    """Only the fields that are sent change; null clears series, link or date."""

    id: str = Field(min_length=1, max_length=300)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=2000)
    topics: list[str] | None = Field(default=None, max_length=30)
    series: str | None = Field(default=None, max_length=200)
    series_part: int | None = Field(default=None, ge=1, le=999)
    url: str | None = Field(default=None, max_length=2000)
    published_on: date | None = None


class TopicCreate(_Request):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)


class TopicUpdate(_Request):
    id: str = Field(min_length=1, max_length=300)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)


class ReplyDraftRequest(_Request):
    comment_id: str = Field(min_length=1, max_length=300)
    guidance: str = Field(default="", max_length=1000)
    """Optional instruction, e.g. "shorter" or "mention part 4"."""


class LinkReviewRequest(_Request):
    article_id: str = Field(min_length=1, max_length=300)
    other_id: str = Field(min_length=1, max_length=300)
    decision: Literal["accept", "reject"]


class SaveCommentsRequest(_Request):
    article_id: str = Field(min_length=1, max_length=300)
    messages: list[DraftMessageModel] = Field(min_length=1, max_length=1000)


class IngestRequest(_Request):
    article_text: str = Field(min_length=1, max_length=400_000)
    post_text: str = Field(min_length=1, max_length=50_000)
    article_url: str | None = Field(default=None, max_length=2000)
    post_url: str | None = Field(default=None, max_length=2000)
    published_on: date | None = None


class PostIngestRequest(_Request):
    text: str = Field(min_length=1, max_length=50_000)
    url: str | None = Field(default=None, max_length=2000)
    published_on: date | None = None


class PostUpdate(_Request):
    """Only the fields that are sent change; null clears the link or date."""

    id: str = Field(min_length=1, max_length=300)
    topics: list[str] | None = Field(default=None, max_length=30)
    url: str | None = Field(default=None, max_length=2000)
    published_on: date | None = None


class HistoryMessage(_Request):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=20_000)


class AskRequest(_Request):
    question: str = Field(min_length=1, max_length=4000)
    article_id: str | None = Field(default=None, max_length=300)
    person_id: str | None = Field(default=None, max_length=300)
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
        "kind": summary.kind,
    }


def comment_view(c: CommentView) -> Json:
    return {
        "id": c.id,
        "author": c.author,
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


def person_summary(p: PersonSummary) -> Json:
    return {
        "id": p.id,
        "name": p.name,
        "headline": p.headline,
        "profile_url": p.profile_url,
        "messages": p.messages,
        "articles": p.articles,
    }


def person_detail(detail: PersonDetail) -> Json:
    return {
        **person_summary(detail.summary),
        "notes": detail.notes,
        "tags": list(detail.tags),
        "headlines": [
            {
                "headline": o.headline,
                "observed_at": o.observed_at.isoformat(),
                "current": o.is_current,
            }
            for o in detail.observations
        ],
        "conversations": [
            {
                "article_id": c.article_id,
                "article_title": c.article_title,
                "messages": [comment_view(m) for m in c.messages],
            }
            for c in detail.conversations
        ],
    }


def topic_usage(usage: TopicUsage) -> Json:
    return {
        "id": usage.topic.id,
        "name": usage.topic.name,
        "description": usage.topic.description,
        "articles": usage.articles,
    }


def sync_report(report: SyncReport | None) -> Json | None:
    if report is None:
        return None
    return {
        "applied": report.applied,
        "reason": report.reason,
        "changed": report.changed,
        "articles": report.articles,
        "comments": report.comments,
        "people": report.people,
        "topics": report.topics,
        "problems": [{"path": p.path, "reason": p.reason} for p in report.problems],
        "trashed": list(report.trashed),
        "index_error": report.index_error,
    }


def related_link(link: RelatedLink) -> Json:
    return {
        "id": link.article_id,
        "title": link.title,
        "grade": link.grade.value,
        "origin": link.origin.value,
        "similarity": link.similarity,
    }


def graph_data(graph: GraphData) -> Json:
    return {
        "nodes": [
            {"id": n.id, "kind": n.kind, "label": n.label, "weight": n.weight} for n in graph.nodes
        ],
        "links": [
            {
                "source": link.source,
                "target": link.target,
                "kind": link.kind,
                "grade": link.grade.value,
                "weight": link.weight,
            }
            for link in graph.links
        ],
    }


def suggest_result(result: SuggestResult) -> Json:
    return {
        "added": result.added,
        "updated": result.updated,
        "retired": result.retired,
        "semantic": result.semantic,
    }


def article_detail(detail: ArticleDetail) -> Json:
    item = detail.article
    discussion = [comment_view(c) for c in detail.discussion]
    if isinstance(item, Post):
        body, entities = item.text, []
    else:
        body, entities = item.body_markdown, list(item.entities)
    return {
        **article_summary(detail.summary),
        "body_markdown": body,
        "entities": entities,
        "hashtags": list(item.hashtags),
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
        "related": [related_link(link) for link in detail.related],
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


def reply_draft(draft: ReplyDraft) -> Json:
    return {
        "comment_id": draft.comment_id,
        "replying_to": draft.replying_to,
        "text": draft.text,
        "already_answered": draft.already_answered,
        "model": draft.model,
    }


def overview(data: OverviewData) -> Json:
    return {
        "articles": data.articles,
        "posts": data.posts,
        "messages": data.messages,
        "people": data.people,
        "waiting_total": data.waiting_total,
        "pending_links": data.pending_links,
        "waiting": [
            {
                "comment_id": w.comment_id,
                "author": w.author,
                "author_name": w.author_name,
                "text": w.text,
                "posted_label": w.posted_label,
                "article_id": w.article_id,
                "article_title": w.article_title,
            }
            for w in data.waiting
        ],
        "top_people": [person_summary(p) for p in data.top_people],
    }


def provider_spec(spec: ProviderSpec) -> Json:
    return {
        "id": spec.id,
        "label": spec.label,
        "description": spec.description,
        "key": spec.key,
        "key_url": spec.key_url,
        "key_envs": list(spec.key_envs),
        "base_url": spec.base_url,
        "base_url_editable": spec.base_url_editable,
        "local": spec.local,
        "offers_embeddings": spec.offers_embeddings,
        "notes": list(spec.notes),
        "models": {
            "extraction": spec.models.extraction,
            "comments": spec.models.comments,
            "chat": spec.models.chat,
            "reply": spec.models.reply,
            "embedding": spec.models.embedding,
        },
    }


def usage_summary(summary: UsageSummary) -> Json:
    return {
        "month": summary.month,
        "cost_usd": round(summary.cost_usd, 6),
        "calls": summary.calls,
        "unpriced_calls": summary.unpriced_calls,
        "budget_usd": summary.budget_usd,
        "remaining_usd": summary.remaining_usd,
        "by_task": [
            {
                "task": t.task.value,
                "calls": t.calls,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cost_usd": round(t.cost_usd, 6),
                "unpriced_calls": t.unpriced_calls,
            }
            for t in summary.by_task
        ],
        "by_model": [
            {
                "provider": e.provider,
                "model": e.model,
                "task": e.task.value,
                "calls": e.calls,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "cost_usd": round(e.cost_usd, 6),
                "unpriced_calls": e.unpriced_calls,
            }
            for e in summary.entries
        ],
    }


def ingest_result(
    result: IngestArticleResult,
    index: IndexResult | None,
    index_error: str | None,
    suggested: int = 0,
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
        "suggested_links": suggested,
    }


def post_ingest_result(
    result: IngestPostResult, index: IndexResult | None, index_error: str | None
) -> Json:
    return {
        "id": result.post.id,
        "title": result.post.title,
        "is_update": result.is_update,
        "topics": [t.name for t in result.topics],
        "warnings": list(result.warnings),
        "note_path": str(result.note_path),
        "index": None if index is None else {"chunks": index.chunks, "semantic": index.semantic},
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
                        "kind": p.kind,
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
        "uncited": result.uncited,
        "sources": [
            {
                "number": s.number,
                "article_id": s.article_id,
                "person_id": s.person_id,
                "kind": s.kind,
                "title": s.title,
                "section": s.section,
                "text": s.text,
            }
            for s in result.sources
        ],
    }
