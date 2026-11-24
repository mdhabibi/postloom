"""Keep the index and the vault the same: export, sync and what to do on start.

The vault is the source of truth. Three situations follow from that:

- **Sync** (vault -> index): the notes changed outside postloom, or the index is new or
  was lost. Everything the notes say replaces what the index holds; the edge journal
  supplies where each link came from, so decisions and history survive. Then the notes
  are written back in their canonical form, so a hand-edited note and the index agree
  to the letter.
- **Export** (index -> vault): write every note from the index. Used after a sync, and
  to upgrade a vault written by an older postloom whose notes can't be read back.
- **Open**: on start, decide which of the two is needed, if any.

Sync never guesses. A note it can't read stops it (when there is an index to protect), and
notes that disappear from the graph are moved to the vault's trash, never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from postloom.application.errors import BudgetExceededError, ProviderError
from postloom.application.ports.clock import Clock
from postloom.application.ports.journal import EdgeJournal
from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.application.ports.search_index import SearchIndex
from postloom.application.ports.vault import (
    VAULT_FORMAT,
    NoteProblem,
    Vault,
    VaultChanges,
    VaultSnapshot,
)
from postloom.application.use_cases.index_content import IndexArticle
from postloom.application.use_cases.links import (
    Decision,
    accepted_related,
    decide_link,
    pair_key,
)
from postloom.application.use_cases.relations import (
    Item,
    current_topics,
    items_discussed_by,
    list_items,
    mentioned_in,
    post_of,
    set_series,
    set_topics,
    standalone_posts,
    write_discussion_note,
)
from postloom.domain.content import Article, Post
from postloom.domain.discussion import OWNER
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance

VAULT = "vault"
"""Producer name for facts read from notes the author edited by hand."""
STRUCTURAL_KINDS = frozenset(
    {EdgeKind.ANNOUNCES, EdgeKind.COMMENTED_ON, EdgeKind.REPLIED_TO, EdgeKind.AUTHORED}
)
"""Edges that follow from the notes themselves (a comment has an author and a post)."""

EdgeKey = tuple[NodeId, NodeId, EdgeKind]


@dataclass(frozen=True, slots=True)
class SyncReport:
    applied: bool
    """False when unreadable notes stopped the sync; the index is unchanged."""
    reason: str
    """"rebuilt" (the index was empty), "updated" (notes were edited), "upgraded" (notes
    rewritten in the current format), "restored" (notes rewritten from the index after
    they went missing) or "blocked"."""
    changed: int = 0
    """Notes added, edited or removed outside postloom."""
    articles: int = 0
    posts: int = 0
    """Posts that stand on their own (announcement posts come with their article)."""
    comments: int = 0
    people: int = 0
    topics: int = 0
    problems: tuple[NoteProblem, ...] = ()
    trashed: tuple[str, ...] = ()
    """Notes moved to the vault's trash because nothing in the graph matches them."""
    index_error: str | None = None
    """Set when articles were restored but couldn't be indexed for search."""


class ExportVault:
    """Write every note from the index, and move notes nothing matches to the trash."""

    def __init__(self, repository: GraphRepository, vault: Vault) -> None:
        self._repository = repository
        self._vault = vault

    def execute(self, protect: tuple[str, ...] = ()) -> list[str]:
        repo, vault = self._repository, self._vault
        keep: set[str] = set()
        for topic in repo.list_topics():
            vault.write_topic(topic)
            keep.add(topic.id)
        for article in repo.list_articles():
            keep.add(article.id)
            post = post_of(repo, article.id)
            if post is None:
                continue  # its post note was removed by hand: leave the article's note be
            topics = current_topics(repo, article.id)
            vault.write_article(article, post, topics, accepted_related(repo, article.id))
            keep.update((article.id, post.id))
            if repo.comments_on(post.id):
                write_discussion_note(repo, vault, article, post)
                keep.add(f"discussion:{post.key}")
        for post in standalone_posts(repo):
            vault.write_post(post, current_topics(repo, post.id))
            keep.add(post.id)
            if repo.comments_on(post.id):
                write_discussion_note(repo, vault, post, post)
                keep.add(f"discussion:{post.key}")
        for person in repo.list_people():
            vault.write_person(
                person, items_discussed_by(repo, person.id), mentioned_in(repo, person.id)
            )
            keep.add(person.id)
        for entity in repo.list_entities():
            vault.write_entity(entity, mentioned_in(repo, entity.id))
            keep.add(entity.id)
        return vault.prune(keep, protect)


class SyncVault:
    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        journal: EdgeJournal,
        index: SearchIndex,
        index_article: IndexArticle,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._journal = journal
        self._index = index
        self._index_article = index_article
        self._clock = clock

    def execute(self) -> SyncReport:
        repo, vault = self._repository, self._vault
        changes = vault.changes()
        before = {i.id: i for i in list_items(repo)}
        had_data = bool(before or repo.list_people())
        snapshot = vault.read()
        if snapshot.problems and had_data:
            return SyncReport(False, "blocked", changed=changes.count, problems=snapshot.problems)
        if before and not snapshot.articles and not snapshot.posts:
            # Every note is gone while the index still has the library: a folder emptied
            # by accident or a sync tool, not an author deleting their library. Put the
            # notes back; deleting is done in the app, one item at a time.
            trashed = ExportVault(repo, vault).execute()
            vault.mark_format()
            vault.mark_synced()
            return SyncReport(
                True,
                "restored",
                changed=changes.count,
                articles=len(repo.list_articles()),
                posts=len(standalone_posts(repo)),
                people=len(repo.list_people()),
                topics=len(repo.list_topics()),
                trashed=tuple(trashed),
            )

        now = self._clock.now()
        contents = self._contents(snapshot, had_data, now)
        repo.replace_graph(contents)
        self._apply_declared(snapshot, changes, had_data, now)
        self._journal.rewrite(repo.all_edges())  # one line per edge again, no replays

        after = {i.id: i for i in list_items(repo)}
        index_error = self._reindex(before, after)
        protect = tuple(p.path for p in snapshot.problems)
        trashed = ExportVault(repo, vault).execute(protect)
        vault.mark_format()
        vault.mark_synced()
        return SyncReport(
            True,
            "updated" if had_data else "rebuilt",
            changed=changes.count,
            articles=len(contents.articles),
            posts=sum(1 for i in after.values() if isinstance(i, Post)),
            comments=len(contents.comments),
            people=len(contents.people),
            topics=len(contents.topics),
            problems=snapshot.problems,
            trashed=tuple(trashed),
            index_error=index_error,
        )

    # -- nodes and the edges that follow from them -----------------------------------
    def _contents(self, snapshot: VaultSnapshot, had_data: bool, now: datetime) -> GraphContents:
        articles = {n.article.id: n.article for n in snapshot.articles}
        # Announcement posts whose article is still there, and posts that stand alone.
        posts = {
            n.post.id: n for n in snapshot.posts if n.announces is None or n.announces in articles
        }
        comments = [c for c in snapshot.comments if c.post in posts]
        series = {a.series.id: a.series for a in articles.values() if a.series is not None}
        nodes: set[NodeId] = {
            OWNER,
            *articles,
            *posts,
            *series,
            *(t.id for t in snapshot.topics),
            *(c.id for c in comments),
            *(p.id for p in snapshot.people),
            *(e.id for e in snapshot.entities),
        }

        fact = Provenance(Origin.STRUCTURAL, Grade.VERIFIED, VAULT, now)
        wanted: dict[EdgeKey, Edge] = {}
        for note in posts.values():
            if note.announces is not None:
                _want(wanted, Edge(note.post.id, note.announces, EdgeKind.ANNOUNCES, fact))
        for comment in comments:
            _want(wanted, Edge(comment.author, comment.id, EdgeKind.AUTHORED, fact))
            _want(wanted, Edge(comment.id, comment.post, EdgeKind.COMMENTED_ON, fact))
            if comment.reply_to is not None:
                _want(wanted, Edge(comment.id, comment.reply_to, EdgeKind.REPLIED_TO, fact))

        recorded = list(self._journal.read())
        if not recorded and had_data:
            recorded = list(self._repository.all_edges())  # the journal file was lost
        live, history = _replay(recorded)
        edges = list(history)
        for key, edge in live.items():
            if edge.kind in STRUCTURAL_KINDS:
                # Keep what was recorded (and when) for facts the notes still state.
                edges.append(edge if wanted.pop(key, None) is not None else edge.supersede(now))
            elif edge.source in nodes and edge.target in nodes:
                edges.append(edge)
            else:
                edges.append(edge.supersede(now))  # one end no longer exists
        edges.extend(wanted.values())

        return GraphContents(
            topics=snapshot.topics,
            series=tuple(series.values()),
            articles=tuple(sorted(articles.values(), key=_article_order)),
            posts=tuple(n.post for n in posts.values()),
            comments=tuple(comments),
            people=snapshot.people,
            entities=snapshot.entities,
            edges=tuple(edges),
        )

    # -- what the notes declare about topics, series and related articles -------------
    def _apply_declared(
        self, snapshot: VaultSnapshot, changes: VaultChanges, had_data: bool, now: datetime
    ) -> None:
        repo = self._repository
        known = {n.article.id for n in snapshot.articles}
        declared: dict[tuple[NodeId, NodeId], set[NodeId]] = {}
        """Pair of articles -> which of the two notes lists the other as related."""
        for post in snapshot.posts:
            if post.announces is None:
                set_topics(repo, post.post.id, post.topics, now, producer=VAULT, confirm=False)
        for note in snapshot.articles:
            set_topics(repo, note.article.id, note.topics, now, producer=VAULT, confirm=False)
            set_series(repo, note.article, now, producer=VAULT)
            for other in note.related:
                if other in known:
                    declared.setdefault(pair_key(note.article.id, other), set()).add(
                        note.article.id
                    )

        accepted = {pair_key(a, other.id) for a in known for other in accepted_related(repo, a)}
        edited = {
            n.article.id for n in snapshot.articles if n.path in (*changes.modified, *changes.added)
        }
        for pair in declared.keys() | accepted:
            sides = declared.get(pair, set())
            if pair not in accepted:
                decide_link(repo, pair[0], pair[1], Decision.ACCEPT, now, VAULT)
            elif not sides or (
                # Removed from one note only: a decision if that note was just edited,
                # otherwise the two notes merely disagree and the link is kept.
                had_data and len(sides) == 1 and (set(pair) - sides) <= edited
            ):
                decide_link(repo, pair[0], pair[1], Decision.REJECT, now, VAULT)

    # -- search index ------------------------------------------------------------------
    def _reindex(self, before: dict[NodeId, Item], after: dict[NodeId, Item]) -> str | None:
        for gone, item in before.items():
            if gone in after:
                continue
            self._index.remove(gone)
            if isinstance(item, Article):  # and the announcement post's discussion
                self._index.remove(NodeId(f"post:{Post.key_for_article(item)}"))
        return reindex_all(self._index_article, list(after))


def reindex_all(index_article: IndexArticle, items: list[NodeId]) -> str | None:
    """Index every article and post with its discussion again; unchanged text reuses its
    vectors, so this costs little. Returns why search by meaning is incomplete, if it is."""
    error: str | None = None
    for item_id in items:
        try:
            index_article.execute(item_id)
        except (ProviderError, BudgetExceededError) as failure:
            error = str(failure)  # keyword search still works; a reindex fills the rest
    return error


class OpenVault:
    """On start: bring the index and the vault in line, whichever is behind."""

    def __init__(
        self,
        repository: GraphRepository,
        vault: Vault,
        journal: EdgeJournal,
        sync: SyncVault,
        index_article: IndexArticle,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._journal = journal
        self._sync = sync
        self._index_article = index_article

    def execute(self) -> SyncReport | None:
        """What was done, or None when the index and the vault already agreed."""
        repo, vault = self._repository, self._vault
        has_index = bool(repo.list_articles() or repo.list_people() or repo.list_topics())
        if vault.format < VAULT_FORMAT and has_index:
            # Written by an older postloom (or brand new): its notes can't be read back,
            # but the index is intact, so write every note again from it.
            for article in repo.list_articles():
                if not article.key:  # saved before articles had a stable key: pin it now
                    repo.save_article(replace(article, key=article.slug))
            self._journal.rewrite(repo.all_edges())
            trashed = ExportVault(repo, vault).execute()
            vault.mark_format()
            vault.mark_synced()
            # Older versions didn't index posts and comments for search.
            articles = [i.id for i in list_items(repo)]
            return SyncReport(
                True,
                "upgraded",
                articles=len(articles),
                people=len(repo.list_people()),
                topics=len(repo.list_topics()),
                trashed=tuple(trashed),
                index_error=reindex_all(self._index_article, articles),
            )
        if not vault.changes():
            if vault.format < VAULT_FORMAT:
                vault.mark_format()  # an empty vault: nothing to convert
            return None
        return self._sync.execute()


def _want(wanted: dict[EdgeKey, Edge], edge: Edge) -> None:
    wanted[edge.key] = edge


def _replay(recorded: list[Edge]) -> tuple[dict[EdgeKey, Edge], list[Edge]]:
    """The journal's lines as the live edge per key, plus history, in recorded order."""
    live: dict[EdgeKey, Edge] = {}
    history: list[Edge] = []
    for edge in recorded:
        if edge.superseded_at is None:
            live[edge.key] = edge
        else:
            live.pop(edge.key, None)
            history.append(edge)
    return live, history


def _article_order(article: Article) -> tuple[str, str]:
    return (article.published_on.isoformat() if article.published_on else "", article.slug)
