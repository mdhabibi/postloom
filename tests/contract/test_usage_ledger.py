"""The UsageLedger contract. Every usage ledger adapter must pass all of these."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from postloom.adapters.storage.database import SqliteDatabase
from postloom.adapters.storage.usage import InMemoryUsageLedger, SqliteUsageLedger
from postloom.application.ports.usage import Task, UsageLedger

pytestmark = pytest.mark.contract

FACTORIES: dict[str, Callable[[], UsageLedger]] = {
    "memory": InMemoryUsageLedger,
    "sqlite": lambda: SqliteUsageLedger(SqliteDatabase()),
}
adapters = pytest.mark.parametrize("make", FACTORIES.values(), ids=FACTORIES.keys())
OCT = datetime(2026, 10, 25, 12, tzinfo=UTC)
NOV = datetime(2026, 11, 1, 0, 5, tzinfo=UTC)


def record(
    ledger: UsageLedger, *, at: datetime = OCT, task: Task = Task.CHAT, cost: float | None = 0.01
) -> None:
    ledger.record(
        at=at, provider="p", model="m", task=task, input_tokens=100, output_tokens=10, cost_usd=cost
    )


@adapters
def test_calls_add_up_per_task(make: Callable[[], UsageLedger]) -> None:
    ledger = make()
    record(ledger)
    record(ledger)
    record(ledger, task=Task.EXTRACTION, cost=None)
    chat, extraction = sorted(ledger.month("2026-10"), key=lambda e: e.task.value)
    assert (chat.task, chat.calls, chat.input_tokens, chat.output_tokens) == (Task.CHAT, 2, 200, 20)
    assert chat.cost_usd == pytest.approx(0.02)
    assert (extraction.unpriced_calls, extraction.cost_usd) == (1, 0.0)


@adapters
def test_months_are_kept_apart(make: Callable[[], UsageLedger]) -> None:
    ledger = make()
    record(ledger)
    record(ledger, at=NOV)
    assert [e.calls for e in ledger.month("2026-10")] == [1]
    assert [e.calls for e in ledger.month("2026-11")] == [1]
    assert list(ledger.month("2026-12")) == []
