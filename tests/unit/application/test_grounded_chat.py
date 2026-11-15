"""Chat answers from the library's graph and text, and says so when it has nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from postloom.application.errors import ApplicationError
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.use_cases.ask_question import NOT_FOUND
from postloom.domain.graph import NodeId
from tests.fakes import FakeChat
from tests.home_support import AGENTS, CACHING, JANE, library, open_home

STRICT = 0.99
"""A similarity cutoff nothing reaches, to show what keywords and the graph find alone."""


def kinds(chat: FakeChat) -> list[str]:
    """The heading line of every source the model was shown."""
    prompt = chat.last_prompt
    return [line for line in prompt.splitlines() if line.startswith("[")]


# -- named things come from the graph -----------------------------------------------------
def test_a_question_naming_a_person_gets_their_facts_and_conversations(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="She asked how to choose the threshold [2] and is a caching contact [1].")
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("What did Jane ask me?")
    assert answer.grounded and not answer.uncited
    card, conversation = answer.sources
    assert (card.kind, card.person_id, card.article_id) == ("person", JANE, None)
    assert "Your private notes about them: Met at PyCon." in card.text
    assert "Senior ML Engineer at Acme Analytics" in card.text
    assert "Activity: 2 messages on 1 articles" in card.text
    assert (conversation.kind, conversation.article_id) == ("comments", CACHING)
    assert "Jane Example: How do you choose the distance threshold" in conversation.text
    assert "You (replying to Jane Example): @Jane Example I start from" in conversation.text
    assert "John Sample" not in chat.last_prompt.split("Your library | Overview")[0]


def test_topics_and_series_named_in_a_question_are_listed_from_the_graph(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="One article [1]; the series has one part [2].")
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("Which articles about AI Agents are in Shipping agents?")
    topic, series = answer.sources
    assert (topic.kind, series.kind) == ("topic", "series")
    assert "Articles in this topic (3):" in topic.text
    assert '- "Agents in production" (undated; series: Shipping agents)' in topic.text
    assert series.text.startswith("Series: Shipping agents (1 articles)")


def test_questions_about_the_library_are_answered_from_an_overview(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="Three [1].")
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("How many articles have I written?")
    (overview,) = answer.sources
    assert overview.kind == "library"
    assert overview.text.startswith("The library has 3 articles, 5 comments and 2 people")
    assert "1 comments have no reply" in overview.text  # John's
    assert '- "Caching basics" (undated); topics: RAG, AI Agents; comments: 5' in overview.text
    assert "- Jane Example, Senior ML Engineer at Acme Analytics: 2 messages" in overview.text


# -- and nothing is made up ----------------------------------------------------------------
def test_an_unrelated_question_is_not_sent_to_the_model(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("What is the capital of France?")
    assert (answer.text, answer.grounded, answer.sources) == (NOT_FOUND, False, ())
    assert chat.calls == []


def test_common_words_alone_are_not_evidence(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        # "an", "to" and "introduction" all occur in the library; the subject does not.
        answer = c.ask_question().execute("Give me an introduction to quantum chemistry")
    assert not answer.grounded and chat.calls == []


def test_citations_that_match_no_source_are_removed_and_flagged(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="It is definitely covered [7], trust me [12].")
    with open_home(tmp_path, chat=chat) as c:
        answer = c.ask_question().execute("caching0 caching1 caching2")
    assert answer.text == "It is definitely covered, trust me."
    assert answer.sources == () and answer.uncited


# -- passages: comments, exact words, follow-ups ------------------------------------------
def test_what_people_wrote_in_comments_can_be_found(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="John asked for it [1].")
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("Did anyone ask about cache invalidation?")
        found = c.search().execute("love a part on invalidation")
    (source, *_) = answer.sources
    assert (source.kind, source.article_id) == ("comments", CACHING)
    assert source.section == "Comments: thread started by John Sample"
    assert source.text.startswith("John Sample: Great series.")
    best = found.results[0]
    assert best.article_id == CACHING and best.passages[0].kind == "comments"


def test_posts_are_searched_too(tmp_path: Path) -> None:
    library(tmp_path)
    with open_home(tmp_path) as c:
        found = c.search().execute("New article Agents in production")
    assert found.results[0].article_id == AGENTS
    assert "post" in {p.kind for p in found.results[0].passages}


def test_exact_words_are_found_even_below_the_similarity_cutoff(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        answer = c.ask_question().execute("caching41 caching42")
    assert answer.grounded and answer.sources[0].article_id == CACHING


def test_a_follow_up_is_searched_together_with_the_question_before_it(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    history = [
        ChatMessage(Role.USER, "What do I say about caching41 caching42?"),
        ChatMessage(Role.ASSISTANT, "You list them [1]."),
    ]
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        alone = c.ask_question().execute("Can you expand on that?")
        assert not alone.grounded  # nothing to go on without the conversation
        answer = c.ask_question().execute("Can you expand on that?", history=history)
    assert answer.grounded and answer.sources[0].article_id == CACHING
    assert [m.role for m in chat.calls[-1][1]] == [Role.USER, Role.ASSISTANT, Role.USER]


# -- one person ------------------------------------------------------------------------------
def test_questions_on_a_persons_page_see_only_that_person(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat(reply="Thresholds [2].")
    with open_home(tmp_path, chat=chat) as c:
        answer = c.ask_question().execute("What does she care about?", person_id=JANE)
        shown = kinds(chat)
        assert shown == [
            "[1] Jane Example | What you know about them",
            "[2] Caching basics | Conversation with Jane Example",
        ]
        assert answer.sources[0].section == "Conversation with Jane Example"
        with pytest.raises(ApplicationError, match="Unknown person"):
            c.ask_question().execute("Who?", person_id=NodeId("person:nobody"))


def test_a_deleted_persons_words_can_no_longer_be_found(tmp_path: Path) -> None:
    library(tmp_path)
    chat = FakeChat()
    with open_home(tmp_path, chat=chat, min_similarity=STRICT) as c:
        assert c.search().execute("distance threshold").results
        c.delete_person().execute(JANE)
        assert c.search().execute("distance threshold").results == ()
        answer = c.ask_question().execute("What did Jane ask about the distance threshold?")
    assert "Jane" not in chat.last_prompt.split("Question:")[0] if chat.calls else True
    assert not any(s.kind == "person" for s in answer.sources)
