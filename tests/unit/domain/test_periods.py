from datetime import date

import pytest

from postloom.domain.periods import period_in

TODAY = date(2026, 11, 28)


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("What did I write about caching in March 2026?", date(2026, 3, 1), date(2026, 3, 31)),
        ("What did I post in March?", date(2026, 3, 1), date(2026, 3, 31)),
        ("What did I post in December?", date(2025, 12, 1), date(2025, 12, 31)),
        ("Anything from Sept 2025?", date(2025, 9, 1), date(2025, 9, 30)),
        ("What did people say last month?", date(2026, 10, 1), date(2026, 10, 31)),
        ("What did I write this month?", date(2026, 11, 1), date(2026, 11, 28)),
        ("Comments in the last 3 months", date(2026, 8, 30), date(2026, 11, 28)),
        ("Posts from the past two weeks", date(2026, 11, 14), date(2026, 11, 28)),
        ("What have I said about agents since May?", date(2026, 5, 1), date(2026, 11, 28)),
        ("What changed since spring?", date(2026, 3, 1), date(2026, 11, 28)),
        ("Articles between May and July", date(2026, 5, 1), date(2026, 7, 31)),
        ("Between November and February 2026", date(2025, 11, 1), date(2026, 2, 28)),
        ("What did I write in summer 2026?", date(2026, 6, 1), date(2026, 8, 31)),
        ("What did I write in the winter?", date(2025, 12, 1), date(2026, 2, 28)),
        ("Posts in Q2 2026", date(2026, 4, 1), date(2026, 6, 30)),
        ("Everything I wrote in 2025", date(2025, 1, 1), date(2025, 12, 31)),
        ("What did I write this year?", date(2026, 1, 1), date(2026, 11, 28)),
    ],
)
def test_periods(question: str, start: date, end: date) -> None:
    period = period_in(question, TODAY)
    assert period is not None
    assert (period.start, period.end) == (start, end)


@pytest.mark.parametrize(
    "question",
    [
        "What did I write about semantic caching?",
        "Did accuracy fall after the change?",
        "What may I have missed in the comments?",
        "Who asked about the spring framework?",
        "What did Lena say about the March of progress?",
    ],
)
def test_no_period(question: str) -> None:
    assert period_in(question, TODAY) is None


def test_a_period_names_itself_and_holds_its_days() -> None:
    period = period_in("in March 2026", TODAY)
    assert period is not None
    assert period.label == "March 2026"
    assert date(2026, 3, 31) in period
    assert date(2026, 4, 1) not in period
