"""Finding what a post names, and adding only what the author confirms.

The fixture is fictional, shaped like a real hackathon post: collaborators, people
thanked, organisations, an event, datasets, a model, methods and links.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError
from postloom.application.ports.extraction import FoundMention, FoundMentions
from postloom.application.use_cases import IngestPostCommand
from postloom.application.use_cases.mentions import Accepted, is_owner, mentions_of
from postloom.domain.entities import Category
from postloom.domain.errors import DomainError
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade
from tests import fancy
from tests.fakes import FakeMentionFinder
from tests.home_support import lose_index, open_home, state

OWNER = "Alex Author"
TEXT = (
    f"{fancy.bold('Can a small model find the T wave?')}\n\n"
    "WaveLens is our Example Hackathon 2026 project. We fine-tuned Tiny-TSLM with LoRA "
    "on the Sample ECG Database.\n\n"
    "Built with Dr. Alex Author and Dr. Robin Sample.\n\n"
    "Thanks to Kim Placeholder from Example Labs for the hackathon, and to Fictive Cloud "
    "for the compute.\n\n"
    "Code: https://github.com/example/wavelens\n"
    "Demo: https://lnkd.in/eAbCdEfG\n\n"
    "#ECG #TimeSeries"
)


def found(*mentions: tuple[str, str], topics: tuple[str, ...] = (), new: tuple[str, ...] = ()):
    return FakeMentionFinder(
        FoundMentions(
            mentions=tuple(FoundMention(name=n, category=c) for n, c in mentions),  # type: ignore[arg-type]
            topics=topics,
            new_topics=new,
        )
    )


GOOD = found(
    ("Dr. Robin Sample", "person"),
    ("Alex Author", "person"),
    ("Kim Placeholder", "person"),
    ("Example Labs", "organisation"),
    ("Fictive Cloud", "organisation"),
    ("Example Hackathon 2026", "event"),
    ("WaveLens", "project"),
    ("Tiny-TSLM", "project"),
    ("Sample ECG Database", "dataset"),
    ("LoRA", "method"),
    ("Imaginary University", "organisation"),  # not in the text: made up
    topics=("Machine Learning",),
    new=("Time Series", "Healthcare AI"),
)


def add_post(home: Path, finder: FakeMentionFinder = GOOD) -> NodeId:
    with open_home(home, mention_finder=finder) as c:
        c.seed_topics().execute(DEFAULT_TOPICS, only_when_empty=True)
        return c.ingest_post().execute(IngestPostCommand(TEXT)).post.id


def test_suggestions_are_checked_against_the_text(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        review = c.find_mentions().execute(post, OWNER)
    names = {(s.name, s.category) for s in review.suggestions}
    assert ("Robin Sample", "person") in names  # the title is dropped
    assert ("Imaginary University", "organisation") not in names  # not in the text
    assert all(s.name != "Alex Author" for s in review.suggestions)  # the author themselves
    links = [s for s in review.suggestions if s.category == "link"]
    assert [(s.name, s.url) for s in links] == [
        ("github.com/example/wavelens", "https://github.com/example/wavelens"),
        ("lnkd.in/eAbCdEfG", "https://lnkd.in/eAbCdEfG"),
    ]
    robin = next(s for s in review.suggestions if s.name == "Robin Sample")
    assert robin.evidence == "Built with Dr. Alex Author and Dr. Robin Sample."
    assert [(t.name, t.exists) for t in review.topics] == [
        ("Machine Learning", True),
        ("Time Series", False),
        ("Healthcare AI", False),
    ]
    with open_home(tmp_path) as c:
        assert c.repository.list_entities() == []  # nothing is added before confirming
        assert c.reviews.get(post) == review  # it waits for the user


def test_without_a_model_only_links_are_found(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        review = c.find_mentions().execute(post, OWNER)
    assert review.finder is None
    assert {s.category for s in review.suggestions} == {"link"}


def test_confirming_adds_only_what_was_chosen(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        result = c.confirm_mentions().execute(
            post,
            [
                Accepted(
                    "Robin Sample", "person", "Built with Dr. Alex Author and Dr. Robin Sample."
                ),
                Accepted("Example Labs", "organisation", "Thanks to Kim Placeholder..."),
                Accepted("Sample ECG DB", "dataset"),  # renamed by the user
                Accepted(
                    "github.com/example/wavelens",
                    "link",
                    url="https://github.com/example/wavelens",
                ),
            ],
            dismissed=["Fictive Cloud", "LoRA"],
            topics=["Time Series"],
        )
        mentioned = {(name, category) for _, name, category in mentions_of(c.repository, post)}
        edges = [e for e in c.repository.edges_from(post) if e.kind is EdgeKind.MENTIONS]
        topics = {t.name for t in c.browse().get_article(post).summary.topics}  # type: ignore[union-attr]
        review = c.reviews.get(post)
    assert mentioned == {
        ("Robin Sample", "person"),
        ("Example Labs", "organisation"),
        ("Sample ECG DB", "dataset"),
        ("github.com/example/wavelens", "link"),
    }
    assert all(e.provenance.grade is Grade.VERIFIED for e in edges)
    robin = next(e for e in edges if e.target.startswith("person:"))
    assert robin.provenance.evidence == "Built with Dr. Alex Author and Dr. Robin Sample."
    assert "Time Series" in topics and result.topics == ("Time Series",)
    assert review is not None
    left = {s.name for s in review.suggestions}
    assert "Fictive Cloud" not in left and "Robin Sample" not in left and "WaveLens" in left
    assert set(review.dismissed) == {"Fictive Cloud", "LoRA"}

    vault = tmp_path / "vault"
    lab = (vault / "mentions" / "example-labs.md").read_text("utf-8")
    assert "category: organisation" in lab and "posts/" in lab
    assert (vault / "topics" / "Time Series.md").is_file()
    assert "mentioned_in:" in (vault / "people" / "Robin Sample.md").read_text("utf-8")


def test_finding_again_leaves_out_what_was_decided(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        c.confirm_mentions().execute(
            post, [Accepted("Example Labs", "organisation")], dismissed=["Fictive Cloud"]
        )
        again = c.find_mentions().execute(post, OWNER)
    names = {s.name for s in again.suggestions}
    assert "Example Labs" not in names and "Fictive Cloud" not in names
    assert "WaveLens" in names


def test_a_person_who_commented_is_offered_as_the_same_person(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    finder = found(("Jane Example", "person"))
    text_with_jane = TEXT + "\n\nAnd thanks to Jane Example for the review."
    with open_home(tmp_path, mention_finder=finder) as c:
        second = c.ingest_post().execute(IngestPostCommand(text_with_jane)).post.id
        drafts = c.preview_comments().execute(post, "pasted", OWNER).messages
        c.save_comments().execute(post, drafts)
        jane = next(p for p in c.repository.list_people() if p.name == "Jane Example")
        review = c.find_mentions().execute(second, OWNER)
        (suggestion,) = [s for s in review.suggestions if s.category == "person"]
        assert suggestion.match == jane.id
        assert suggestion.match_note == "commented on 1 of your posts"
        c.confirm_mentions().execute(
            second, [Accepted("Jane Example", "person", match=suggestion.match)]
        )
        assert [p.name for p in c.repository.list_people()].count("Jane Example") == 1
        page = c.people().get_person(jane.id)
    assert page is not None


def test_an_entity_named_differently_later_joins_the_same_one(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        c.confirm_mentions().execute(post, [Accepted("Example Labs", "organisation")])
        other = (
            c.ingest_post()
            .execute(IngestPostCommand("A new post.\n\nWith ExLabs again. #ECG"))
            .post.id
        )
        lab = c.repository.list_entities()[0]
        c.confirm_mentions().execute(other, [Accepted("ExLabs", "organisation", match=lab.id)])
        (entity,) = c.repository.list_entities()
    assert entity.aliases == ("ExLabs",)
    assert {e.source for e in c_edges(tmp_path, entity.id)} == {post, other}


def c_edges(home: Path, target: NodeId) -> list[Edge]:
    with open_home(home) as c:
        return list(c.repository.edges_to(target))


def test_confirmed_mentions_survive_a_lost_index(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        c.confirm_mentions().execute(
            post,
            [
                Accepted("Robin Sample", "person", "Built with Dr. Robin Sample."),
                Accepted("Example Labs", "organisation"),
                Accepted("Example Hackathon 2026", "event"),
            ],
            topics=["Time Series"],
        )
        before = state(c)
        entities = sorted(c.repository.list_entities(), key=lambda e: e.key)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert state(c) == before
        assert sorted(c.repository.list_entities(), key=lambda e: e.key) == entities
        assert {n for _, n, _ in mentions_of(c.repository, post)} == {
            "Robin Sample",
            "Example Labs",
            "Example Hackathon 2026",
        }


def test_bad_choices_are_refused(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        with pytest.raises(ApplicationError, match="category"):
            c.confirm_mentions().execute(post, [Accepted("Thing", "spaceship")])
        with pytest.raises(ApplicationError, match="empty"):
            c.confirm_mentions().execute(post, [Accepted("Dr.", "person")])
        with pytest.raises(ApplicationError, match="Unknown"):
            c.find_mentions().execute(NodeId("post:nothing"), OWNER)


def test_the_owner_is_recognised_with_or_without_a_title() -> None:
    assert is_owner("Dr. Alex Author", OWNER)
    assert is_owner("alex  AUTHOR", OWNER)
    assert not is_owner("Alex Authorson", OWNER)
    assert not is_owner("Robin Sample", OWNER)
    assert not is_owner("Alex Author", None)
    assert Category("dataset") is Category.DATASET


# -- editing later -----------------------------------------------------------------------
def confirmed_post(home: Path) -> tuple[NodeId, NodeId]:
    post = add_post(home)
    with open_home(home, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        c.confirm_mentions().execute(
            post,
            [
                Accepted("Example Labs", "organisation", "Thanks to Example Labs."),
                Accepted("Example Hackathon 2026", "event"),
                Accepted("Robin Sample", "person"),
            ],
        )
        lab = next(e for e in c.repository.list_entities() if e.name == "Example Labs")
    return post, lab.id


def test_renaming_and_recategorising_keep_every_link(tmp_path: Path) -> None:
    post, lab = confirmed_post(tmp_path)
    with open_home(tmp_path) as c:
        entity = c.entities().update(
            lab, name="Example Research Labs", category="project", url="example.org"
        )
        detail = c.entities().get(lab)
        with pytest.raises(ApplicationError, match="category"):
            c.entities().update(lab, category="spaceship")
        with pytest.raises(DomainError):
            c.entities().update(lab, url="javascript:alert(1)")
    assert entity.id == lab and entity.aliases == ("Example Labs",)
    assert (entity.category, entity.url) == ("project", "https://example.org")
    assert [m.item.id for m in detail.mentions] == [post]
    assert detail.mentions[0].evidence == "Thanks to Example Labs."
    note = (tmp_path / "vault" / "mentions" / "example-labs.md").read_text("utf-8")
    assert "name: Example Research Labs" in note and "category: project" in note


def test_merging_moves_mentions_and_keeps_the_names(tmp_path: Path) -> None:
    post, lab = confirmed_post(tmp_path)
    with open_home(tmp_path) as c:
        hackathon = next(e for e in c.repository.list_entities() if e.category == "event")
        merged = c.entities().merge(hackathon.id, lab)
        assert c.repository.get_entity(hackathon.id) is None
        assert {n for _, n, _ in mentions_of(c.repository, post)} == {
            "Example Labs",
            "Robin Sample",
        }
        history = c.repository.edges_from(post, include_history=True)
        with pytest.raises(ApplicationError, match="different"):
            c.entities().merge(lab, lab)
    assert merged.aliases == ("Example Hackathon 2026",)
    assert any(e.target == hackathon.id and e.superseded_at for e in history)
    assert not (tmp_path / "vault" / "mentions" / "example-hackathon-2026.md").exists()


def test_removing_a_mention_keeps_it_from_coming_back(tmp_path: Path) -> None:
    post, lab = confirmed_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.entities().remove_mention(post, lab)
        assert "Example Labs" not in {n for _, n, _ in mentions_of(c.repository, post)}
        again = c.find_mentions().execute(post, OWNER)
        with pytest.raises(ApplicationError):
            c.entities().remove_mention(post, lab)
    assert "Example Labs" not in {s.name for s in again.suggestions}


def test_deleting_an_entity_erases_it(tmp_path: Path) -> None:
    _, lab = confirmed_post(tmp_path)
    with open_home(tmp_path) as c:
        c.entities().delete(lab)
        assert c.repository.get_entity(lab) is None
        assert all(lab not in (e.source, e.target) for e in c.repository.all_edges())
        assert [s.entity.name for s in c.entities().summaries()] == ["Example Hackathon 2026"]
    assert not (tmp_path / "vault" / "mentions" / "example-labs.md").exists()


def test_deleting_a_post_updates_what_it_mentioned(tmp_path: Path) -> None:
    post, lab = confirmed_post(tmp_path)
    with open_home(tmp_path) as c:
        c.delete_post().execute(post)
        assert c.entities().get(lab).mentions == ()
        assert c.entities().pending() == []
    note = (tmp_path / "vault" / "mentions" / "example-labs.md").read_text("utf-8")
    assert "posts/" not in note


def test_a_renamed_suggestion_keeps_the_name_it_was_found_as(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path, mention_finder=GOOD) as c:
        c.find_mentions().execute(post, OWNER)
        done = c.confirm_mentions().execute(
            post, [Accepted("Example Research Labs", "organisation", found_as="Example Labs")]
        )
        (lab,) = c.repository.list_entities()
    assert (lab.name, lab.aliases) == ("Example Research Labs", ("Example Labs",))
    assert done.review is not None
    assert "Example Labs" not in {s.name for s in done.review.suggestions}


# -- the graph and chat ----------------------------------------------------------------
def test_mentioned_things_are_in_the_graph(tmp_path: Path) -> None:
    post, lab = confirmed_post(tmp_path)
    with open_home(tmp_path) as c:
        graph = c.graph().execute()
    kinds = {n.id: n.kind for n in graph.nodes}
    assert kinds[lab] == "organisation"
    robin = next(n for n in graph.nodes if n.label == "Robin Sample")
    assert robin.kind == "person" and robin.weight == 1  # mentioned, never commented
    assert {(link.source, link.target) for link in graph.links if link.kind == "mentions"} >= {
        (post, lab),
        (post, robin.id),
    }


def test_chat_knows_what_is_mentioned_where(tmp_path: Path) -> None:
    from tests.fakes import FakeChat

    post, _ = confirmed_post(tmp_path)
    chat = FakeChat(reply="In your hackathon post [1].")
    with open_home(tmp_path, chat=chat) as c:
        answer = c.ask_question().execute("Where did I mention Example Labs?")
        cards = [s for s in answer.sources if s.kind == "mentions"]
        assert cards and cards[0].text.startswith("Organisation: Example Labs")
        assert '"Thanks to Example Labs."' in cards[0].text
        listed = c.ask_question().execute("Which companies have I written about?")
        group = next(s for s in listed.sources if s.kind == "mentions")
        assert group.text.startswith("Organisation entries you mention (1):")
        people = c.ask_question().execute("Who did I thank in my posts?")
        assert any("Robin Sample" in s.text for s in people.sources if s.kind == "mentions")
    assert post
