"""What postloom costs: prices, the monthly budget and the usage report.

Costs are recorded when a call is made: the provider's own figure when it reports one
(OpenRouter does), otherwise tokens times the price table. Changing a price later doesn't
rewrite history; it applies to new calls.

The budget is checked before every paid call against what was already spent this month,
so the call that crosses the limit still completes and the next one is refused. A single
call costs at most a few cents, so the overshoot is bounded and the rule stays simple.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from postloom.application.errors import BudgetExceededError
from postloom.application.ports.clock import Clock
from postloom.application.ports.usage import Task, UsageEntry, UsageLedger, month_of


@dataclass(frozen=True, slots=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / 1_000_000


class PriceBook:
    """Known prices by model id; the user's overrides win over the built-in table."""

    def __init__(
        self, defaults: Mapping[str, Price], overrides: Mapping[str, Price] | None = None
    ) -> None:
        self._prices = {**defaults, **(overrides or {})}

    def price(self, model: str) -> Price | None:
        return self._prices.get(model)

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        price = self.price(model)
        return price.cost(input_tokens, output_tokens) if price else None


class BudgetPolicy:
    def __init__(self, ledger: UsageLedger, clock: Clock, monthly_limit_usd: float | None) -> None:
        if monthly_limit_usd is not None and monthly_limit_usd < 0:
            raise ValueError("The monthly budget can't be negative.")
        self._ledger = ledger
        self._clock = clock
        self.limit = monthly_limit_usd

    def spent(self) -> float:
        return sum(e.cost_usd for e in self._ledger.month(month_of(self._clock.now())))

    def check(self) -> None:
        """Raise if this month's paid usage already reached the limit."""
        if self.limit is None:
            return
        spent = self.spent()
        if spent >= self.limit:
            raise BudgetExceededError(
                f"You've reached your monthly budget of ${self.limit:.2f} "
                f"(${spent:.2f} spent this month), so postloom paused paid model calls. "
                "Raise or remove the budget in Settings to continue."
            )


@dataclass(frozen=True, slots=True)
class TaskUsage:
    task: Task
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    unpriced_calls: int


@dataclass(frozen=True, slots=True)
class UsageSummary:
    month: str
    entries: tuple[UsageEntry, ...]
    by_task: tuple[TaskUsage, ...]
    cost_usd: float
    calls: int
    unpriced_calls: int
    budget_usd: float | None

    @property
    def remaining_usd(self) -> float | None:
        return None if self.budget_usd is None else max(self.budget_usd - self.cost_usd, 0.0)


class UsageReport:
    def __init__(self, ledger: UsageLedger, clock: Clock, budget_usd: float | None) -> None:
        self._ledger = ledger
        self._clock = clock
        self._budget = budget_usd

    def execute(self, month: str | None = None) -> UsageSummary:
        month = month or month_of(self._clock.now())
        entries = tuple(self._ledger.month(month))
        by_task: dict[Task, list[UsageEntry]] = {}
        for entry in entries:
            by_task.setdefault(entry.task, []).append(entry)
        tasks = tuple(
            TaskUsage(
                task,
                sum(e.calls for e in rows),
                sum(e.input_tokens for e in rows),
                sum(e.output_tokens for e in rows),
                sum(e.cost_usd for e in rows),
                sum(e.unpriced_calls for e in rows),
            )
            for task in Task
            if (rows := by_task.get(task))
        )
        return UsageSummary(
            month=month,
            entries=entries,
            by_task=tasks,
            cost_usd=sum(e.cost_usd for e in entries),
            calls=sum(e.calls for e in entries),
            unpriced_calls=sum(e.unpriced_calls for e in entries),
            budget_usd=self._budget,
        )
