"""The period a question is about: "in March", "last month", "since spring", "in 2026".

Read deterministically from the words of an English question, relative to today, so a
question about a time can be answered from what was published then. Anything this
doesn't recognise means "no period", and the whole library is searched as before.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS: dict[str, int] = {
    **{name.casefold(): n for n, name in enumerate(calendar.month_abbr) if name},
    **{name.casefold(): n for n, name in enumerate(calendar.month_name) if name},
    "sept": 9,
}
SEASONS = {"spring": (3, 5), "summer": (6, 8), "autumn": (9, 11), "fall": (9, 11)}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d\d"
_UNIT = {"day": 1, "week": 7, "month": 30, "year": 365}
_NUMBERS = {"couple of": 2, "few": 3} | {
    word: n
    for n, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        ]
    )
}


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date
    """Inclusive."""
    label: str
    """How to say it: "March 2026", "the last 3 months"."""

    def __contains__(self, day: date) -> bool:
        return self.start <= day <= self.end


def period_in(question: str, today: date) -> Period | None:
    """The time span the question asks about, or None."""
    text = question.casefold()
    for read in (_between, _relative, _since, _quarter, _season, _month, _year):
        found = read(text, today)
        if found is not None:
            return found
    return None


def _month_span(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _latest(month: int, today: date) -> int:
    """The year of the most recent such month: "in March" asked in May 2026 is March 2026,
    asked in January 2026 it is March 2025."""
    return today.year if month <= today.month else today.year - 1


def _month(text: str, today: date) -> Period | None:
    m = re.search(rf"\b(?:in|during|from|of|for)\s+({_MONTH})\.?(?:\s+({_YEAR}))?\b", text)
    if not m:
        m = re.search(rf"\b({_MONTH})\.?\s+({_YEAR})\b", text)
    if not m:
        return None
    month = MONTHS[m.group(1)]
    year = int(m.group(2)) if m.group(2) else _latest(month, today)
    start, end = _month_span(year, month)
    return Period(start, end, f"{calendar.month_name[month]} {year}")


def _year(text: str, today: date) -> Period | None:
    if re.search(r"\bthis year\b", text):
        return Period(date(today.year, 1, 1), today, f"{today.year}")
    if re.search(r"\blast year\b", text):
        y = today.year - 1
        return Period(date(y, 1, 1), date(y, 12, 31), f"{y}")
    m = re.search(rf"\b(?:in|during|of|for)\s+({_YEAR})\b", text)
    if not m:
        return None
    y = int(m.group(1))
    return Period(date(y, 1, 1), date(y, 12, 31), f"{y}")


def _relative(text: str, today: date) -> Period | None:
    if re.search(r"\bthis month\b", text):
        return Period(today.replace(day=1), today, "this month")
    if re.search(r"\blast month\b", text):
        first = today.replace(day=1)
        start, end = _month_span(
            (first - timedelta(days=1)).year, (first - timedelta(days=1)).month
        )
        return Period(start, end, calendar.month_name[start.month] + f" {start.year}")
    if re.search(r"\bthis week\b", text):
        return Period(today - timedelta(days=today.weekday()), today, "this week")
    if re.search(r"\blast week\b", text):
        monday = today - timedelta(days=today.weekday() + 7)
        return Period(monday, monday + timedelta(days=6), "last week")
    if re.search(r"\b(?:today)\b", text):
        return Period(today, today, "today")
    if re.search(r"\byesterday\b", text):
        day = today - timedelta(days=1)
        return Period(day, day, "yesterday")
    m = re.search(
        r"\b(?:in |over |during )?(?:the )?(?:last|past|previous)\s+(\d+|two|three|four|five|six|"
        r"seven|eight|nine|ten|eleven|twelve|few|couple of)?\s*(day|week|month|year)s?\b",
        text,
    )
    if not m:
        return None
    raw = m.group(1)
    count = 1 if raw is None else int(raw) if raw.isdigit() else _NUMBERS[raw]
    unit = m.group(2)
    start = today - timedelta(days=count * _UNIT[unit])
    label = f"the last {count} {unit}s" if count > 1 else f"the last {unit}"
    return Period(start, today, label)


def _since(text: str, today: date) -> Period | None:
    m = re.search(
        rf"\b(?:since|after)\s+({_MONTH}|{'|'.join(SEASONS)}|{_YEAR})\.?(?:\s+({_YEAR}))?\b", text
    )
    if not m:
        return None
    word = m.group(1)
    if re.fullmatch(_YEAR, word):
        start = date(int(word), 1, 1)
    elif word in SEASONS:
        first = SEASONS[word][0]
        start = date(int(m.group(2)) if m.group(2) else _latest(first, today), first, 1)
    else:
        month = MONTHS[word]
        start = date(int(m.group(2)) if m.group(2) else _latest(month, today), month, 1)
    if start > today:
        return None
    return Period(start, today, f"since {start:%B %Y}")


def _between(text: str, today: date) -> Period | None:
    m = re.search(
        rf"\bbetween\s+({_MONTH})\.?(?:\s+({_YEAR}))?\s+and\s+({_MONTH})\.?(?:\s+({_YEAR}))?\b",
        text,
    )
    if not m:
        return None
    m1, m2 = MONTHS[m.group(1)], MONTHS[m.group(3)]
    y2 = int(m.group(4)) if m.group(4) else _latest(m2, today)
    y1 = int(m.group(2)) if m.group(2) else (y2 if m1 <= m2 else y2 - 1)
    start, _ = _month_span(y1, m1)
    _, end = _month_span(y2, m2)
    return Period(start, end, f"{start:%B %Y} to {end:%B %Y}")


def _season(text: str, today: date) -> Period | None:
    # Only with a preposition or a year: "did accuracy fall" is not a season.
    m = re.search(
        rf"\b(?:in|during|this|last|over)\s+(?:the\s+)?(spring|summer|autumn|fall|winter)\b"
        rf"(?:\s+(?:of\s+)?({_YEAR}))?",
        text,
    ) or re.search(rf"\b(spring|summer|autumn|fall|winter)\s+({_YEAR})\b", text)
    if not m:
        return None
    season = m.group(1)
    if season == "winter":
        year = (
            int(m.group(2)) if m.group(2) else (today.year if today.month >= 12 else today.year - 1)
        )
        start = date(year, 12, 1)
        end = date(year + 1, 2, calendar.monthrange(year + 1, 2)[1])
        return Period(start, end, f"winter {year}/{year + 1}")
    first, last = SEASONS[season]
    if m.group(2):
        year = int(m.group(2))
    else:
        year = today.year if first <= today.month else today.year - 1
        if "last " + season in text and first <= today.month:
            year -= 1
    start, _ = _month_span(year, first)
    _, end = _month_span(year, last)
    return Period(start, end, f"{season} {year}")


def _quarter(text: str, today: date) -> Period | None:
    m = re.search(rf"\bq([1-4])(?:\s+({_YEAR}))?\b", text)
    if not m:
        return None
    q = int(m.group(1))
    year = int(m.group(2)) if m.group(2) else today.year
    start, _ = _month_span(year, 3 * q - 2)
    _, end = _month_span(year, 3 * q)
    return Period(start, end, f"Q{q} {year}")
