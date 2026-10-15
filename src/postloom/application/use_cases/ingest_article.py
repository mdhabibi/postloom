"""IngestArticle: pasted article + announcement post -> vault note + graph nodes and edges.

Division of labour:
- The LLM (via ``ContentExtractor``) does what needs language understanding: restoring
  Markdown structure, the title, a summary, topics, entities and the series name.
- Deterministic rules do everything else: hashtags, links, ids, the post -> article edge,
  and the "Part N" number when the title states it.
- The use case guards the graph: topics outside the user's taxonomy are dropped, and edges
  the user already verified or rejected are never overwritten by a re-ingest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from postloom.application.errors import NoTopicsConfiguredError
from postloom.application.ports.clock import Clock
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.links import accepted_related
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, EdgeKind
from postloom.domain.provenance import Grade, Origin, Provenance
from postloom.domain.text import (
    content_size,
    detect_series_part,
    extract_hashtags,
    extract_urls,
)

PARSER = "parser"
MIN_COVERAGE = 0.85
"""Below this share of the pasted text's content, the restored article is flagged."""
_OWNED_KINDS = frozenset({EdgeKind.ANNOUNCES, EdgeKind.BELONGS_TO, EdgeKind.PART_OF})


@dataclass(frozen=True, slots=True)
class IngestArticleCommand:
    article_text: str
    post_text: str
    article_url: str | None = None
    post_url: str | None = None
    published_on: date | None = None
    banner_path: str | None = None


@dataclass(frozen=True, slots=True)
class IngestArticleResult:
    article: Article
    post: Post
    topics: tuple[Topic, ...]
    edges: tuple[Edge, ...]
    """Live edges written or kept by this ingest."""
    note_path: Path
    is_update: bool
    warnings: tuple[str, ...] = ()


class IngestArticle:
    def __init__(
        self,
        extractor: ContentExtractor,
        repository: GraphRepository,
        vault: Vault,
        clock: Clock,
    ) -> None:
        self._extractor = extractor
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def execute(self, command: IngestArticleCommand) -> IngestArticleResult:
        taxonomy = list(self._repository.list_topics())
        if not taxonomy:
            raise NoTopicsConfiguredError("No topics configured. Run setup first.")

        extracted = self._extractor.extract(
            ExtractionRequest(
                article_text=command.article_text,
                post_text=command.post_text,
                allowed_topics=tuple(t.name for t in taxonomy),
            )
        )
        warnings: list[str] = []
        topics = _match_topics(extracted.topics, taxonomy, warnings)
        _check_coverage(command.article_text, extracted, warnings)

        article = _build_article(command, extracted)
        post = Post(
            key=Post.key_for_article(article),
            text=command.post_text.strip(),
            url=command.post_url,
            published_on=command.published_on,
            hashtags=tuple(extract_hashtags(command.post_text)),
            links=tuple(extract_urls(command.post_text)),
            banner_path=command.banner_path,
        )
        is_update = self._repository.get_article(article.id) is not None

        if article.series is not None:
            self._repository.save_series(article.series)
        self._repository.save_article(article)
        self._repository.save_post(post)
        edges = self._sync_edges(article, post, topics)

        related = accepted_related(self._repository, article.id)
        note_path = self._vault.write_article(article, post, topics, related)
        return IngestArticleResult(
            article=article,
            post=post,
            topics=tuple(topics),
            edges=tuple(edges),
            note_path=note_path,
            is_update=is_update,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------ edges
    def _sync_edges(self, article: Article, post: Post, topics: Sequence[Topic]) -> list[Edge]:
        now = self._clock.now()
        structural = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, PARSER, now)
        llm = Provenance(Origin.TAXONOMY, Grade.ASSERTED, self._extractor.name, now)

        proposed = [Edge(post.id, article.id, EdgeKind.ANNOUNCES, structural)]
        proposed += [Edge(article.id, t.id, EdgeKind.BELONGS_TO, llm) for t in topics]
        if article.series is not None:
            proposed.append(Edge(article.id, article.series.id, EdgeKind.PART_OF, llm))

        # Only edges this use case owns are reconciled; semantic links, comments etc.
        # are managed by their own use cases and must survive a re-ingest.
        existing = {
            e.key: e
            for node in (article.id, post.id)
            for e in self._repository.edges_from(node)
            if e.kind in _OWNED_KINDS
        }
        proposed_keys = {e.key for e in proposed}

        # Retire what the model said last time but no longer says. The user's own
        # decisions (verified / rejected) are never touched by a re-ingest.
        live: list[Edge] = []
        for key, old in existing.items():
            if key in proposed_keys:
                continue
            if old.provenance.grade is Grade.ASSERTED:
                self._repository.supersede_edge(old.supersede(now))
            elif old.is_current:
                live.append(old)  # verified by the user: kept even if the model forgot it

        for edge in proposed:
            old = existing.get(edge.key)
            if old is not None and old.provenance.grade is not Grade.ASSERTED:
                if old.is_current:
                    live.append(old)
                continue
            self._repository.save_edge(edge)
            live.append(edge)
        return live


def _match_topics(
    names: Sequence[str], taxonomy: Sequence[Topic], warnings: list[str]
) -> list[Topic]:
    by_name = {t.name.casefold(): t for t in taxonomy}
    matched: list[Topic] = []
    for name in names:
        topic = by_name.get(name.strip().casefold())
        if topic is None:
            warnings.append(f"Ignored topic outside your taxonomy: {name!r}")
        elif topic not in matched:
            matched.append(topic)
    if not matched:
        warnings.append("No topic assigned; the article is unlinked until you add one.")
    return matched


def _check_coverage(raw: str, extracted: ExtractedContent, warnings: list[str]) -> None:
    """Flag extractions that look shortened: restoring formatting must not drop content."""
    pasted = content_size(raw)
    kept = content_size(extracted.title) + content_size(extracted.body_markdown)
    if pasted and kept / pasted < MIN_COVERAGE:
        warnings.append(
            f"The restored article keeps only {kept / pasted:.0%} of the pasted text. "
            "Compare it with the original before relying on it."
        )


def _build_article(command: IngestArticleCommand, extracted: ExtractedContent) -> Article:
    series_part = detect_series_part(extracted.title) or extracted.series_part
    series = Series(extracted.series_name.strip()) if extracted.series_name else None
    hashtags = extract_hashtags(command.article_text + "\n" + command.post_text)
    return Article(
        title=extracted.title.strip(),
        body_markdown=extracted.body_markdown.strip(),
        summary=extracted.summary.strip(),
        url=command.article_url,
        published_on=command.published_on,
        series=series,
        series_part=series_part if series is not None else None,
        hashtags=tuple(hashtags),
        entities=tuple(dict.fromkeys(e.strip() for e in extracted.entities if e.strip())),
    )
