"""Overview: what needs the author's attention, for the home dashboard.

"Waiting for a reply" means a message from someone else that none of the author's saved
replies answers. Reply targets are inferred deterministically when comments are pasted
(an @mention, or the previous speaker), so this matches what the author sees on LinkedIn
once their latest replies are pasted in.
"""

from __future__ import annotations

from dataclasses import dataclass

from postloom.application.ports.repository import GraphRepository
from postloom.application.use_cases.people import PeopleDirectory, PersonSummary
from postloom.application.use_cases.relations import Item, discussion_post, list_items
from postloom.domain.content import Post
from postloom.domain.discussion import Comment
from postloom.domain.graph import EdgeKind, NodeId
from postloom.domain.provenance import Grade

MAX_WAITING = 6
MAX_PEOPLE = 5


@dataclass(frozen=True, slots=True)
class WaitingMessage:
    comment_id: NodeId
    author: NodeId
    author_name: str
    text: str
    posted_label: str
    article_id: NodeId
    article_title: str


@dataclass(frozen=True, slots=True)
class OverviewData:
    articles: int
    posts: int
    """Stand-alone posts; posts that announce an article are not counted."""
    messages: int
    people: int
    waiting: tuple[WaitingMessage, ...]
    """The most recent unanswered messages, newest paste first."""
    waiting_total: int
    pending_links: int
    """Suggested related-article links nobody has reviewed yet."""
    top_people: tuple[PersonSummary, ...]


class Overview:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def execute(self) -> OverviewData:
        repo = self._repository
        articles = list_items(repo)
        waiting: list[WaitingMessage] = []
        messages = 0
        pending: set[tuple[NodeId, NodeId]] = set()
        for article in articles:
            comments = self._comments(article)
            answered = {c.reply_to for c in comments if c.is_own and c.reply_to}
            for comment in comments:
                messages += 1
                if comment.is_own:
                    continue
                if comment.id not in answered:
                    waiting.append(
                        WaitingMessage(
                            comment.id,
                            comment.author,
                            comment.author_name,
                            comment.text,
                            comment.posted_label,
                            article.id,
                            article.title,
                        )
                    )
            for edge in repo.edges_from(article.id):
                if (
                    edge.kind is EdgeKind.RELATED_TO
                    and edge.is_current
                    and edge.provenance.grade is Grade.ASSERTED
                ):
                    pending.add((edge.source, edge.target))
        waiting.reverse()  # later pastes and later positions first
        people = PeopleDirectory(repo).list_people()
        return OverviewData(
            articles=sum(1 for i in articles if not isinstance(i, Post)),
            posts=sum(1 for i in articles if isinstance(i, Post)),
            messages=messages,
            people=len(people),
            waiting=tuple(waiting[:MAX_WAITING]),
            waiting_total=len(waiting),
            pending_links=len(pending),
            top_people=tuple(people[:MAX_PEOPLE]),
        )

    def _comments(self, item: Item) -> list[Comment]:
        post = discussion_post(self._repository, item.id)
        if post is None:
            return []
        return sorted(self._repository.comments_on(post.id), key=lambda c: c.position)
