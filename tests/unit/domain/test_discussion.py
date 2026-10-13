import pytest

from postloom.domain.discussion import (
    OWNER,
    Comment,
    Message,
    comment_key,
    conversation_depth,
    infer_reply_targets,
)
from postloom.domain.errors import EmptyContentError
from postloom.domain.graph import NodeId

POST = NodeId("post:semantic-caching-part-3")


def test_same_comment_pasted_again_gets_the_same_identity() -> None:
    first = comment_key(POST, "Jane Example", "Great  post!\nThanks")
    again = comment_key(POST, "Jane Example", "great post! thanks")
    other_post = comment_key(NodeId("post:other"), "Jane Example", "Great post! Thanks")
    other_author = comment_key(POST, "John Sample", "Great post! Thanks")
    assert first == again
    assert len({first, other_post, other_author}) == 3
    assert first.startswith("jane-example-")


def test_owner_comments_are_own() -> None:
    mine = Comment(POST, OWNER, "Alex Author", "Thanks!", position=1)
    theirs = Comment(POST, NodeId("person:~jane-example"), "Jane Example", "Hi", position=0)
    assert mine.is_own and not theirs.is_own


def test_empty_comments_are_rejected() -> None:
    with pytest.raises(EmptyContentError):
        Comment(POST, OWNER, "Alex", "   ", position=0)


def thread(*rows: tuple[str, str]) -> list[Message]:
    """First row is the top-level comment; the rest are replies under it."""
    return [
        Message(author, text, thread=None if i == 0 else 0) for i, (author, text) in enumerate(rows)
    ]


def test_a_back_and_forth_becomes_a_chain() -> None:
    inferred = infer_reply_targets(
        thread(
            ("Jane Example", "How do you set the threshold?"),
            ("Alex Author", "Start from validation data."),
            ("Jane Example", "And when traffic drifts?"),
            ("Alex Author", "Re-calibrate weekly."),
        )
    )
    assert [m.reply_to for m in inferred] == [None, 0, 1, 2]


def test_mentions_pick_the_person_being_answered() -> None:
    inferred = infer_reply_targets(
        thread(
            ("Jane Example", "Great breakdown."),
            ("John Sample", "Agree, but what about drift?"),
            ("Alex Author", "@Jane Example thank you!"),
            ("Alex Author", "@John good point: re-calibrate weekly."),
        )
    )
    assert [m.reply_to for m in inferred] == [None, 0, 0, 1]


def test_first_name_mentions_need_a_word_boundary() -> None:
    inferred = infer_reply_targets(
        thread(
            ("Ann Lee", "Question one"),
            ("Bob Stone", "Question two"),
            ("Alex Author", "@Annabel is not Ann"),
        )
    )
    # "@Annabel" must not match "Ann"; falls back to the previous other speaker (Bob).
    assert inferred[2].reply_to == 1


def test_explicit_reply_targets_are_kept() -> None:
    messages = thread(("Jane", "a"), ("Alex", "b"), ("Jane", "c"))
    messages[2] = Message("Jane", "c", thread=0, reply_to=0)
    assert infer_reply_targets(messages)[2].reply_to == 0


def test_threads_do_not_leak_into_each_other() -> None:
    messages = [
        Message("Jane", "First thread", thread=None),
        Message("John", "Second thread", thread=None),
        Message("Alex", "@John answer to second", thread=1),
        Message("Alex", "answer to first", thread=0),
    ]
    assert [m.reply_to for m in infer_reply_targets(messages)] == [None, None, 1, 0]


def test_depth_follows_the_reply_chain() -> None:
    top = Comment(POST, NodeId("person:~jane"), "Jane", "q", position=0)
    reply = Comment(POST, OWNER, "Alex", "a", position=1, thread=top.id, reply_to=top.id)
    follow = Comment(
        POST, NodeId("person:~jane"), "Jane", "q2", 2, thread=top.id, reply_to=reply.id
    )
    by_id = {c.id: c for c in (top, reply, follow)}
    assert [conversation_depth(c, by_id) for c in (top, reply, follow)] == [0, 1, 2]
