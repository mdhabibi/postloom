"""IngestArticle: pasted article + announcement post -> vault note + graph nodes and edges.

Division of labour:
- The LLM (via ``ContentExtractor``) does what needs language understanding: restoring
  Markdown structure, the title, a summary, topics, entities and the series name.
- Deterministic rules do everything else: hashtags, links, ids, the post -> article edge,
  and the "Part N" number when the title states it.
- The use case guards the graph: topics outside the user's taxonomy are dropped, and edges
  the user already verified or rejected are never overwritten by a re-ingest.

Which article is this? Titles are not identities: the same article can come back with a
reworded title, and two articles can share one. So an added article is matched to an
existing one by its LinkedIn link when there is one, otherwise by its text, and only then
is it treated as new. Nothing is ever replaced on the strength of a title alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from postloom.application.errors import ApplicationError, NoTopicsConfiguredError
from postloom.application.ports.clock import Clock
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.application.use_cases.links import accepted_related
from postloom.application.use_cases.relations import current_topics, write_mentions
from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance
from postloom.domain.text import (
    canonical_url,
    containment,
    content_size,
    detect_series_part,
    extract_hashtags,
    extract_urls,
    looks_english,
    slugify,
    web_url,
)

PARSER = "parser"
MIN_COVERAGE = 0.85
"""Below this share of the pasted text's content, the restored article is flagged."""
SAME_TEXT = 0.5
"""At least this much shared text (see ``containment``) means a new version of the same
article. Versions of one article score above 0.9 and different articles, even parts of
one series, below 0.2, so the exact value matters little."""
DIFFERENT_TEXT = 0.2
"""Below this, two texts are different articles, whatever their link or title says."""
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
        *,
        english_only_search: bool = False,
    ) -> None:
        self._extractor = extractor
        self._repository = repository
        self._vault = vault
        self._clock = clock
        self._english_only_search = english_only_search
        """True when search by meaning runs on a model that only understands English."""

    def execute(self, command: IngestArticleCommand) -> IngestArticleResult:
        taxonomy = list(self._repository.list_topics())
        if not taxonomy:
            raise NoTopicsConfiguredError("No topics configured. Run setup first.")

        existing = list(self._repository.list_articles())
        same_link = _with_link(existing, command.article_url)
        if (
            same_link is not None
            and containment(command.article_text, same_link.body_markdown) < DIFFERENT_TEXT
        ):
            # Checked before the model is called, so a wrong link costs nothing.
            raise ApplicationError(
                f'That link already belongs to "{same_link.title}", and its text is '
                "different. Check the link, or delete that article first."
            )

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
        if self._english_only_search and not looks_english(command.article_text):
            warnings.append(
                "This article isn't in English, but search by meaning uses an English-only "
                "model. In Settings, set Search by meaning to Many languages for better "
                "results; keyword search works either way."
            )

        previous = same_link or _same_text(existing, command.article_text)
        article = _build_article(command, extracted)
        if previous is not None:
            article = replace(
                article,
                key=previous.slug,
                url=article.url or previous.url,
                published_on=article.published_on or previous.published_on,
            )
            if slugify(previous.title) != slugify(article.title):
                warnings.append(
                    f'Recognised as a new version of "{previous.title}" and updated it.'
                )
        else:
            key = _free_key(slugify(article.title), {a.slug for a in existing})
            if key != slugify(article.title):
                warnings.append(
                    "Another article has the same title, so this one was saved separately. "
                    "If it was meant to replace the other one, delete that article."
                )
            article = replace(article, key=key)

        old_post = self._repository.get_post(Post(Post.key_for_article(article), "-").id)
        post = Post(
            key=Post.key_for_article(article),
            text=command.post_text.strip(),
            url=web_url(command.post_url) or (old_post.url if old_post else None),
            published_on=command.published_on or (old_post.published_on if old_post else None),
            hashtags=tuple(extract_hashtags(command.post_text)),
            links=tuple(extract_urls(command.post_text)),
            banner_path=command.banner_path or (old_post.banner_path if old_post else None),
            media=old_post.media if old_post else (),
        )
        stored = self._repository.get_article(article.id)
        is_update = stored is not None
        if stored is not None:  # pasting it again keeps its images and videos
            article = replace(article, media=stored.media)

        if article.series is not None:
            self._repository.save_series(article.series)
        self._repository.save_article(article)
        self._repository.save_post(post)
        edges = self._sync_edges(article, post, topics)

        # The note lists the topics that are live now, not the model's latest opinion:
        # a topic the author rejected stays out even if the model proposes it again.
        topics = current_topics(self._repository, article.id)
        related = accepted_related(self._repository, article.id)
        note_path = self._vault.write_article(article, post, topics, related)
        if previous is not None and previous.title != article.title:
            write_mentions(self._repository, self._vault, article)
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

        return reconcile_edges(self._repository, (article.id, post.id), proposed, now)


def reconcile_edges(
    repository: GraphRepository,
    nodes: Sequence[NodeId],
    proposed: Sequence[Edge],
    now: datetime,
) -> list[Edge]:
    """Make the edges an ingest owns (announces, topics, series) from ``nodes`` match what
    was ``proposed``, and return the live ones.

    Only edges this use case owns are reconciled; semantic links, comments etc. are managed
    by their own use cases and must survive a re-ingest. What the model said last time but
    no longer says is retired; the user's own decisions (verified / rejected) are never
    touched by a re-ingest.
    """
    existing = {
        e.key: e for node in nodes for e in repository.edges_from(node) if e.kind in _OWNED_KINDS
    }
    proposed_keys = {e.key for e in proposed}
    live: list[Edge] = []
    for key, old in existing.items():
        if key in proposed_keys:
            continue
        if old.provenance.grade is Grade.ASSERTED:
            repository.supersede_edge(old.supersede(now))
        elif old.is_current:
            live.append(old)  # verified by the user: kept even if the model forgot it

    for edge in proposed:
        old = existing.get(edge.key)
        if old is not None and old.provenance.grade is not Grade.ASSERTED:
            if old.is_current:
                live.append(old)
            continue
        repository.save_edge(edge)
        live.append(edge)
    return live


def _with_link(articles: Sequence[Article], url: str | None) -> Article | None:
    if not url or not url.strip():
        return None
    wanted = canonical_url(url)
    return next((a for a in articles if a.url and canonical_url(a.url) == wanted), None)


def _same_text(articles: Sequence[Article], pasted: str) -> Article | None:
    """The stored article that shares the most text with ``pasted``, if it shares enough."""
    scored = [(containment(pasted, a.body_markdown), a) for a in articles]
    best = max(scored, key=lambda item: item[0], default=None)
    return best[1] if best is not None and best[0] >= SAME_TEXT else None


def _free_key(wanted: str, taken: set[str]) -> str:
    if wanted not in taken:
        return wanted
    return next(f"{wanted}-{n}" for n in range(2, len(taken) + 3) if f"{wanted}-{n}" not in taken)


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
        url=web_url(command.article_url),
        published_on=command.published_on,
        series=series,
        series_part=series_part if series is not None else None,
        hashtags=tuple(hashtags),
        entities=tuple(dict.fromkeys(e.strip() for e in extracted.entities if e.strip())),
    )
