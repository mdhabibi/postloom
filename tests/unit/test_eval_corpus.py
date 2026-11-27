"""The retrieval benchmark's library: every answer is placed exactly once."""

from collections import Counter

from scripts.eval.corpus import PEOPLE, THEMES
from scripts.eval.library import plan

from postloom.application.use_cases.posts import SAME_TEXT
from postloom.domain.text import containment


def test_every_fact_is_in_exactly_one_item() -> None:
    items = plan()
    for theme in THEMES:
        mine = [it for it in items if it.theme is theme]
        for f, fact in enumerate(theme.facts):
            holders = [it for it in mine if f in it.facts]
            assert len(holders) == 1, fact.text
            assert fact.text in holders[0].body
            assert sum(fact.text in it.body for it in items) == 1
        for c, said in enumerate(theme.comment_facts):
            holders = [it for it in mine if c in it.comment_facts]
            assert len(holders) == 1, said.text
            assert [m.author_name for m in holders[0].comments if m.text == said.text] == [
                said.person
            ]


def test_the_year_has_thirty_articles_and_eighty_distinct_posts() -> None:
    items = plan()
    kinds = Counter(it.kind for it in items)
    assert kinds == {"article": 30, "post": 80}
    assert len({it.body for it in items if it.kind == "post"}) == 80
    assert all(it.comments for it in items)


def test_no_post_looks_like_an_edit_of_another() -> None:
    """postloom treats a post that mostly repeats an earlier one as an edit of it."""
    texts = [it.body if it.kind == "post" else it.announcement for it in plan()]
    worst = max(containment(a, b) for i, a in enumerate(texts) for b in texts[:i])
    assert worst < SAME_TEXT


def test_commenters_are_the_invented_people() -> None:
    names = {m.author_name for it in plan() for m in it.comments}
    assert names <= {*PEOPLE, "Alex Morgan"}
